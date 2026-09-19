# ruff: noqa: F811
import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text

from app.db.models import (
    AcquisitionSelection,
    AuditEvent,
    DownloadAttempt,
    DownloadCapacity,
    DownloadInspection,
    Integration,
    Operation,
    RecoveryFinding,
    RestoreCheckpoint,
    User,
)
from app.domain import recovery_observers as observers
from app.domain import recovery_reconciliation as reconciliation
from app.domain import recovery_scans as scans
from app.jobs.queue import recovery_queue
from app.jobs.retry import ShelfRetry
from app.security import encrypt_secrets
from tests.contracts.test_audiobookshelf import ABSFixture
from tests.integration.test_acquisition import catalog  # noqa: F401
from tests.integration.test_acquisition_selections import selection_route  # noqa: F401
from tests.integration.test_download_attempts import selected  # noqa: F401
from tests.integration.test_download_attempts import start as start_download
from tests.integration.test_recovery_scan_workflow import begin, pause, report
from tests.unit.test_recovery_census_adapter import CensusServer, transfer

pytestmark = pytest.mark.integration


@pytest.fixture
async def observed(client, admin, database, selected, monkeypatch):
    response = await start_download(client, selected)
    assert response.status_code == 202
    attempt_id = UUID(response.json()["id"])
    async with database() as db, db.begin():
        selection = await db.get(AcquisitionSelection, UUID(selected["id"]))
        frozen = selection.frozen
        for backend in await db.scalars(
            select(Integration).where(Integration.kind == "audiobookshelf")
        ):
            backend.encrypted_secrets = encrypt_secrets({"token": "private-abs-token"})
    server = CensusServer(
        [
            transfer(
                hash=frozen["descriptor"]["infohash_v1"],
                save_path=frozen["downloader"]["save_path"],
                tags="book-search:" + str(attempt_id),
                category=frozen["downloader"]["category"],
                state="downloading",
                progress=0.25,
                amount_left=9,
                total_size=frozen["descriptor"]["torrent_bytes"],
            )
        ]
    )
    server.file_rows[frozen["descriptor"]["infohash_v1"]] = [
        {
            "index": i,
            "name": file["path"],
            "size": file["size_bytes"],
            "progress": 0.25,
            "priority": 1,
        }
        for i, file in enumerate(frozen["descriptor"]["files"])
    ]
    monkeypatch.setattr(observers, "QbitClient", server.client)
    monkeypatch.setattr(reconciliation, "QbitClient", server.client)
    monkeypatch.setattr(
        observers,
        "Audiobookshelf",
        lambda endpoint, token: ABSFixture({}).client("http://abs.test/abs", "private-abs-token"),
    )
    checkpoint_id = await pause(database, admin)
    identifier = await begin(client)
    await scans.run(UUID(identifier))
    result = await report(client, identifier, domain="downloads")
    finding = next(row for row in result["items"] if row["state"] == "matched")
    return {
        "scan_id": identifier,
        "finding_id": finding["id"],
        "attempt_id": attempt_id,
        "server": server,
        "frozen": frozen,
        "checkpoint_id": checkpoint_id,
    }


async def preview(client, observed, key=None, **changes):
    return await client.post(
        "/api/recovery/reconciliations",
        headers={"Idempotency-Key": key or str(uuid4())},
        json={"scan_id": observed["scan_id"], "finding_ids": [observed["finding_id"]], **changes},
    )


async def accept(client, plan, key=None):
    return await client.post(
        f"/api/recovery/reconciliations/{plan['id']}/accept",
        headers={"Idempotency-Key": key or str(uuid4())},
        json={"revision": plan["revision"]},
    )


async def review(client, identifier):
    response = await client.get("/api/recovery/reconciliations/" + identifier)
    assert response.status_code == 200, response.text
    return response.json()


async def test_review_records_existing_transfer_once_without_dispatch_or_import(
    client, admin, database, observed
):
    response = await preview(client, observed, "review-matching-transfer")
    assert response.status_code == 201, response.text
    plan = response.json()
    assert (await preview(client, observed, "review-matching-transfer")).json() == plan
    assert plan["status"] == "prepared" and plan["items"][0]["saved_external_may_exist"] is False
    assert "connection_signature" not in str(plan) and "credentials" not in str(plan)
    async with database() as db:
        assert not (await db.get(DownloadAttempt, observed["attempt_id"])).external_may_exist
    accepted = await accept(client, plan, "accept-reviewed-transfer")
    assert accepted.status_code == 202, accepted.text
    assert (await accept(client, plan, "accept-reviewed-transfer")).json() == accepted.json()
    assert (await accept(client, plan)).status_code == 409
    # No second scan can race the approved action.
    assert (
        await client.post("/api/recovery/scans", headers={"Idempotency-Key": "scan-during-review"})
    ).status_code == 409
    queue = recovery_queue()
    async with queue.open_async():
        await queue.run_worker_async(wait=False, concurrency=1)
    outcome = await review(client, plan["id"])
    assert outcome["status"] == "completed", outcome
    calls = list(observed["server"].calls)
    await reconciliation.run(UUID(plan["id"]))
    assert calls == observed["server"].calls
    async with database() as db:
        attempt = await db.get(DownloadAttempt, observed["attempt_id"])
        assert attempt.external_may_exist and attempt.state == "downloading"
        assert attempt.observation["association_verified"]
        assert attempt.next_check_at is None and attempt.inspection_id is None
        assert await db.scalar(select(func.count()).select_from(DownloadInspection)) == 0
        reserve = await db.get(DownloadCapacity, attempt.id)
        assert reserve.slot_active and reserve.submitted_at
        assert (await db.get(RestoreCheckpoint, observed["checkpoint_id"])).active
        assert (
            await db.scalar(
                text("SELECT status::text FROM book_queue.procrastinate_jobs WHERE id=:id"),
                {"id": (await db.get(Operation, attempt.operation_id)).job_id},
            )
            == "todo"
        )
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "recovery.download.reconciled")
            )
            == 1
        )
    assert all(method == "GET" or path.endswith("auth/login") for method, path in calls)
    assert (await client.get("/api/recovery")).json()["resume_available"] is False
    assert (await client.get("/api/lists")).status_code == 423
    # Applying evidence invalidates old previews, even when the original report remains readable.
    assert (await preview(client, observed)).status_code == 409


@pytest.mark.parametrize("change", ["routing", "missing", "identity", "configuration", "operator"])
async def test_changed_external_or_local_evidence_holds_all_updates(
    client, admin, database, observed, change
):
    plan = (await preview(client, observed)).json()
    assert (await accept(client, plan)).status_code == 202
    server = observed["server"]
    if change == "routing":
        server.rows[0]["save_path"] = "/different"
    elif change == "missing":
        server.rows.clear()
    elif change == "identity":
        server.rows[0]["tags"] = "unrelated"
    elif change == "configuration":
        async with database() as db, db.begin():
            (await db.get(User, UUID(admin["id"]))).display_name = "Changed after acceptance"
    else:
        async with database() as db, db.begin():
            (await db.get(User, UUID(admin["id"]))).active = False
    await reconciliation.run(UUID(plan["id"]))
    async with database() as db:
        assert (await db.get(Operation, UUID(plan["id"]))).status == "held"
        attempt = await db.get(DownloadAttempt, observed["attempt_id"])
        assert attempt.state == "queued" and not attempt.external_may_exist
        assert (await db.get(DownloadCapacity, attempt.id)).submitted_at is None


async def test_selection_and_current_scan_are_bound_to_exact_review(
    client, admin, database, observed
):
    assert (
        await preview(client, observed, finding_ids=[observed["finding_id"]] * 2)
    ).status_code == 422
    assert (await preview(client, observed, finding_ids=[str(uuid4())])).status_code == 409
    async with database() as db, db.begin():
        finding = await db.get(RecoveryFinding, UUID(observed["finding_id"]))
        finding.state = "untracked"
    assert (await preview(client, observed)).status_code == 409
    async with database() as db, db.begin():
        (await db.get(RecoveryFinding, UUID(observed["finding_id"]))).state = "matched"
    plan = (await preview(client, observed)).json()
    response = await client.post(
        f"/api/recovery/reconciliations/{plan['id']}/accept",
        headers={"Idempotency-Key": "wrong-revision"},
        json={"revision": "0" * 64},
    )
    assert response.status_code == 409
    fresh = await begin(client)
    await scans.run(UUID(fresh))
    assert (await accept(client, plan)).status_code == 409


async def test_expiry_and_changed_findings_prevent_approval(client, admin, database, observed):
    plan = (await preview(client, observed)).json()
    async with database() as db, db.begin():
        operation = await db.get(Operation, UUID(plan["id"]))
        operation.payload = {
            **operation.payload,
            "expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        }
    assert (await accept(client, plan)).status_code == 409
    fresh = (await preview(client, observed)).json()
    async with database() as db, db.begin():
        finding = await db.get(RecoveryFinding, UUID(observed["finding_id"]))
        finding.evidence = {**finding.evidence, "modified": True}
    assert (await accept(client, fresh)).status_code == 409


@pytest.mark.parametrize("field", ["integration_id", "states"])
async def test_malformed_saved_evidence_requires_fresh_observation(
    client, admin, database, observed, field
):
    async with database() as db, db.begin():
        finding = await db.get(RecoveryFinding, UUID(observed["finding_id"]))
        finding.evidence = {**finding.evidence, field: "malformed-saved-evidence"}
    response = await preview(client, observed)
    assert response.status_code == 409
    assert response.json()["detail"] == "Observation evidence is invalid; run fresh checks"
    async with database() as db:
        assert not (await db.get(DownloadAttempt, observed["attempt_id"])).external_may_exist


async def test_concurrent_redelivery_and_expired_lease_recheck_without_duplicate_effects(
    client, admin, database, observed, monkeypatch
):
    plan = (await preview(client, observed)).json()
    assert (await accept(client, plan)).status_code == 202
    real = reconciliation.fresh_transfers
    entered, release = asyncio.Event(), asyncio.Event()

    async def blocked(*args):
        entered.set()
        await release.wait()
        return await real(*args)

    monkeypatch.setattr(reconciliation, "fresh_transfers", blocked)
    first = asyncio.create_task(reconciliation.run(UUID(plan["id"])))
    await entered.wait()
    try:
        with pytest.raises(ShelfRetry):
            await reconciliation.run(UUID(plan["id"]))
    finally:
        release.set()
        await first
    assert (await review(client, plan["id"]))["status"] == "completed"


async def test_transaction_failure_rolls_back_transfer_and_capacity(
    client, admin, database, observed
):
    plan = (await preview(client, observed)).json()
    assert (await accept(client, plan)).status_code == 202
    # An in-transaction failure after the record update must roll everything back.
    original = reconciliation.record_transfer

    async def fail_after_record(*args):
        await original(*args)
        raise RuntimeError("synthetic failure after local writes")

    from unittest.mock import patch

    with patch.object(reconciliation, "record_transfer", fail_after_record):
        await reconciliation.run(UUID(plan["id"]))
    assert (await review(client, plan["id"]))["status"] == "held"
    async with database() as db:
        attempt = await db.get(DownloadAttempt, observed["attempt_id"])
        assert not attempt.external_may_exist and attempt.state == "queued"
        assert (await db.get(DownloadCapacity, attempt.id)).submitted_at is None
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "recovery.download.reconciled")
            )
            == 0
        )


async def test_transfer_can_finish_after_preview_without_starting_import(
    client, admin, database, observed
):
    plan = (await preview(client, observed)).json()
    assert (await accept(client, plan)).status_code == 202
    server = observed["server"]
    server.rows[0].update(state="stalledUP", progress=1, amount_left=0)
    for file in next(iter(server.file_rows.values())):
        file["progress"] = 1
    await reconciliation.run(UUID(plan["id"]))
    result = await review(client, plan["id"])
    assert result["status"] == "completed" and result["results"][0]["state"] == "complete", result
    async with database() as db:
        attempt = await db.get(DownloadAttempt, observed["attempt_id"])
        assert attempt.state == "complete" and attempt.external_may_exist
        assert attempt.inspection_id is None and attempt.next_check_at is None
        assert not (await db.get(DownloadCapacity, attempt.id)).slot_active
        assert await db.scalar(select(func.count()).select_from(DownloadInspection)) == 0
        assert (
            await db.scalar(
                text(
                    "SELECT count(*) FROM book_queue.procrastinate_jobs WHERE task_name IN "
                    "('organization.inspect', 'organization.automatic', 'acquisition.fulfillment')"
                )
            )
            == 0
        )


async def test_lost_worker_lease_rechecks_and_applies_once(client, admin, database, observed):
    plan = (await preview(client, observed)).json()
    assert (await accept(client, plan)).status_code == 202
    async with database() as db, db.begin():
        operation = await db.get(Operation, UUID(plan["id"]))
        operation.status = "running"
        operation.payload = {
            **operation.payload,
            "run_token": str(uuid4()),
            "lease_until": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        }
    await reconciliation.run(UUID(plan["id"]))
    await reconciliation.run(UUID(plan["id"]))
    assert (await review(client, plan["id"]))["status"] == "completed"
    async with database() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "recovery.download.reconciled")
            )
            == 1
        )


async def test_context_change_during_remote_read_prevents_apply(
    client, admin, database, observed, monkeypatch
):
    plan = (await preview(client, observed)).json()
    assert (await accept(client, plan)).status_code == 202
    original = reconciliation.fresh_transfers

    async def change_after_read(*args):
        result = await original(*args)
        async with database() as db, db.begin():
            (await db.get(User, UUID(admin["id"]))).display_name = "Changed during verification"
        return result

    monkeypatch.setattr(reconciliation, "fresh_transfers", change_after_read)
    await reconciliation.run(UUID(plan["id"]))
    assert (await review(client, plan["id"]))["status"] == "held"
    async with database() as db:
        assert not (await db.get(DownloadAttempt, observed["attempt_id"])).external_may_exist


async def test_checkpoint_change_hides_saved_review(client, admin, database, observed):
    plan = (await preview(client, observed)).json()
    async with database() as db, db.begin():
        (await db.get(RestoreCheckpoint, observed["checkpoint_id"])).active = False
        db.add(
            RestoreCheckpoint(
                operator_id=UUID(admin["id"]), backup_id=uuid4(), active=True, snapshot={}
            )
        )
    assert (await client.get("/api/recovery/reconciliations/" + plan["id"])).status_code == 404
    assert (await accept(client, plan)).status_code == 404


async def test_csrf_and_wrong_command_keys_cannot_apply_review(client, admin, database, observed):
    plan = (await preview(client, observed, "prepared-review-key")).json()
    wrong_key = await accept(client, plan, "prepared-review-key")
    assert wrong_key.status_code == 409
    response = await client.post(
        f"/api/recovery/reconciliations/{plan['id']}/accept",
        headers={"Idempotency-Key": "forged-acceptance", "X-CSRF-Token": "invalid"},
        json={"revision": plan["revision"]},
    )
    assert response.status_code == 403
    async with database() as db:
        assert (await db.get(Operation, UUID(plan["id"]))).status == "prepared"
        assert not (await db.get(DownloadAttempt, observed["attempt_id"])).external_may_exist


async def test_failed_queue_attempt_cannot_apply_after_a_new_scan_starts(
    client, admin, database, observed, monkeypatch
):
    plan = (await preview(client, observed)).json()
    assert (await accept(client, plan)).status_code == 202
    original = reconciliation.fresh_transfers
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed(*args):
        result = await original(*args)
        entered.set()
        await release.wait()
        return result

    monkeypatch.setattr(reconciliation, "fresh_transfers", delayed)
    task = asyncio.create_task(reconciliation.run(UUID(plan["id"])))
    await entered.wait()
    try:
        async with database() as db, db.begin():
            operation = await db.get(Operation, UUID(plan["id"]))
            await db.execute(
                text("UPDATE book_queue.procrastinate_jobs SET status='failed' WHERE id=:id"),
                {"id": operation.job_id},
            )
        assert await begin(client)
    finally:
        release.set()
        await task
    async with database() as db:
        operation = await db.get(Operation, UUID(plan["id"]))
        assert operation.status == "held" and operation.payload["run_token"] is None
        assert not (await db.get(DownloadAttempt, observed["attempt_id"])).external_may_exist


async def test_another_attempts_identity_claim_cannot_be_taken_over(
    client, admin, database, observed
):
    from app.db.models import DownloadIdentityClaim

    async with database() as db, db.begin():
        original = await db.get(DownloadAttempt, observed["attempt_id"])
        selection = await db.get(AcquisitionSelection, original.selection_id)
        old_selection = AcquisitionSelection(
            **{
                column.name: getattr(selection, column.name)
                for column in AcquisitionSelection.__table__.columns
                if column.name not in {"id", "created_at", "command_key", "state"}
            },
            command_key="older-cancelled-selection",
            state="cancelled",
        )
        operation = Operation(
            owner_id=original.owner_id,
            kind="acquisition.download",
            idempotency_key="older-cancelled-attempt",
            status="completed",
        )
        db.add_all([old_selection, operation])
        await db.flush()
        other = DownloadAttempt(
            owner_id=original.owner_id,
            selection_id=old_selection.id,
            operation_id=operation.id,
            endpoint_key=original.endpoint_key,
            state="cancelled",
        )
        db.add(other)
        await db.flush()
        claim = await db.scalar(
            select(DownloadIdentityClaim).where(DownloadIdentityClaim.attempt_id == original.id)
        )
        claim.active = False
        await db.flush()
        db.add(
            DownloadIdentityClaim(
                attempt_id=other.id,
                endpoint_key=claim.endpoint_key,
                torrent_hash=claim.torrent_hash,
                active=True,
            )
        )
        other_id = other.id
    identifier = await begin(client)
    await scans.run(UUID(identifier))
    result = await report(client, identifier, domain="downloads")
    finding = next(row for row in result["items"] if row["state"] == "matched")
    updated = {**observed, "scan_id": identifier, "finding_id": finding["id"]}
    plan = (await preview(client, updated)).json()
    assert (await accept(client, plan)).status_code == 202
    await reconciliation.run(UUID(plan["id"]))
    outcome = await review(client, plan["id"])
    assert outcome["status"] == "held" and "Another saved attempt" in outcome["message"]
    async with database() as db:
        active = await db.scalar(
            select(DownloadIdentityClaim).where(DownloadIdentityClaim.active.is_(True))
        )
        assert active.attempt_id == other_id
        assert not (await db.get(DownloadAttempt, observed["attempt_id"])).external_may_exist
