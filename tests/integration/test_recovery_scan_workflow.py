# ruff: noqa: F811
import asyncio
import subprocess
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text

from app.adapters.audiobookshelf import parse_item
from app.db.models import (
    AcquisitionSelection,
    DownloadAttempt,
    Integration,
    Library,
    LibraryAsset,
    Operation,
    RecoveryFinding,
    RecoveryScan,
    RestoreCheckpoint,
    User,
)
from app.domain import recovery_observers as observers
from app.domain import recovery_scans as scans
from app.jobs.queue import recovery_queue
from app.jobs.retry import ShelfRetry
from app.security import encrypt_secrets
from tests.contracts.test_audiobookshelf import ABSFixture, book
from tests.integration.test_acquisition import catalog  # noqa: F401
from tests.integration.test_acquisition_selections import selection_route  # noqa: F401
from tests.integration.test_download_attempts import selected  # noqa: F401
from tests.integration.test_download_attempts import start as start_download
from tests.unit.test_recovery_census_adapter import CensusServer, transfer

pytestmark = pytest.mark.integration


async def pause(database, admin):
    async with database() as db, db.begin():
        checkpoint = RestoreCheckpoint(
            operator_id=UUID(admin["id"]), backup_id=uuid4(), active=True, snapshot={}
        )
        db.add(checkpoint)
        await db.flush()
        return checkpoint.id


async def begin(client, key=None):
    result = await client.post(
        "/api/recovery/scans", headers={"Idempotency-Key": key or str(uuid4())}
    )
    assert result.status_code == 202, result.text
    return result.json()["id"]


async def report(client, identifier, **params):
    response = await client.get("/api/recovery/scans/" + identifier, params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def test_recovery_worker_cannot_run_ordinary_jobs_and_commands_are_idempotent(
    client, admin, database
):
    probe = await client.post(
        "/api/system/probe", headers={"Idempotency-Key": "preserved-normal-job"}
    )
    await pause(database, admin)
    identifier = await begin(client, "same-observation-command")
    assert await begin(client, "same-observation-command") == identifier
    assert (
        await client.post("/api/recovery/scans", headers={"Idempotency-Key": "different-command"})
    ).status_code == 409
    queue = recovery_queue()
    assert set(queue.tasks) == {
        "recovery.scan",
        "recovery.reconcile",
        "recovery.inventory",
        "recovery.publication",
        "recovery.lists",
    }
    async with queue.open_async():
        await queue.run_worker_async(wait=False, concurrency=1)
    result = await report(client, identifier)
    assert result["scan"]["state"] == "completed", result
    assert result["items"][-1]["state"] == "needs-review"
    assert result["scan"]["summary"]["resume_available"] is False
    async with database() as db:
        assert (await db.get(Operation, UUID(probe.json()["id"]))).status == "queued"
        assert await db.scalar(select(func.count()).select_from(RecoveryScan)) == 1
    assert (await client.get("/api/lists")).status_code == 423
    assert (
        await client.post(
            "/api/recovery/scans",
            headers={"X-CSRF-Token": "bad", "Idempotency-Key": "csrf-command"},
        )
    ).status_code == 403


async def test_census_finds_transfer_ahead_of_backup_and_untracked_transfer_without_submission(
    client, admin, database, selected, monkeypatch
):
    attempt_response = await start_download(client, selected)
    assert attempt_response.status_code == 202, attempt_response.text
    attempt_id = UUID(attempt_response.json()["id"])
    async with database() as db:
        selection = await db.get(AcquisitionSelection, UUID(selected["id"]))
        frozen = selection.frozen
        known_hash = frozen["descriptor"]["infohash_v1"]
    rows = [
        transfer(
            hash=known_hash,
            save_path=frozen["downloader"]["save_path"],
            tags="book-search:" + str(attempt_id),
            category=frozen["downloader"]["category"],
        ),
        transfer(999, tags="book-search:" + str(uuid4())),
    ]
    server = CensusServer(rows)
    monkeypatch.setattr(observers, "QbitClient", server.client)
    monkeypatch.setattr(
        observers,
        "Audiobookshelf",
        lambda endpoint, token: ABSFixture({}).client("http://abs.test/abs", "private-abs-token"),
    )
    async with database() as db, db.begin():
        for backend in await db.scalars(
            select(Integration).where(Integration.kind == "audiobookshelf")
        ):
            backend.encrypted_secrets = encrypt_secrets({"token": "private-abs-token"})
    await pause(database, admin)
    identifier = await begin(client)
    await scans.run(UUID(identifier))
    result = await report(client, identifier, domain="downloads")
    assert result["scan"]["state"] == "completed", result
    assert {r["state"] for r in result["items"]} >= {"matched", "untracked", "observed"}, result
    async with database() as db:
        attempt = await db.get(DownloadAttempt, attempt_id)
        assert attempt.state == "queued" and not attempt.external_may_exist
        assert await db.scalar(select(func.count()).select_from(DownloadAttempt)) == 1
    assert all(method == "GET" or path.endswith("auth/login") for method, path in server.calls)


async def test_abs_missing_and_new_items_do_not_rewrite_restored_owned_records(
    client, admin, database, monkeypatch
):
    old = parse_item(book("deleted"))
    fixture = ABSFixture({"new": book("new")})
    monkeypatch.setattr(observers, "Audiobookshelf", fixture.client)
    async with database() as db, db.begin():
        integration = Integration(
            kind="audiobookshelf",
            name="Saved ABS",
            base_url="http://abs.test/abs",
            encrypted_secrets=encrypt_secrets({"token": "private-abs-token"}),
        )
        db.add(integration)
        await db.flush()
        library = Library(
            integration_id=integration.id, external_id="library-one", name="Saved audio"
        )
        db.add(library)
        await db.flush()
        asset = LibraryAsset(
            library_id=library.id,
            external_id="deleted",
            medium="audio",
            title=old.title,
            state="present",
            full_content=True,
            metadata_snapshot=old.model_dump(mode="json"),
            files=[file.model_dump() for file in old.audio],
        )
        db.add(asset)
        await db.flush()
        asset_id = asset.id
    await pause(database, admin)
    identifier = await begin(client)
    await scans.run(UUID(identifier))
    result = await report(client, identifier, domain="library")
    assert result["scan"]["state"] == "completed", result
    assert {row["state"] for row in result["items"]} >= {"missing", "untracked"}, result
    async with database() as db:
        asset = await db.get(LibraryAsset, asset_id)
        assert asset.state == "present" and asset.full_content
    assert not any("scan" in call or "update" in call for call in fixture.calls)


async def test_changed_context_holds_report_and_old_checkpoint_cannot_be_read(
    client, admin, database, monkeypatch
):
    checkpoint = await pause(database, admin)

    async def collect(inputs, writer):
        await writer.add("downloads", "observed", "Before change", "Read-only observation")
        async with database() as db, db.begin():
            (await db.get(User, UUID(admin["id"]))).display_name = "Changed during scan"

    monkeypatch.setattr(observers, "collect", collect)
    identifier = await begin(client)
    await scans.run(UUID(identifier))
    result = await report(client, identifier)
    assert result["scan"]["state"] == "held"
    assert "changed" in result["scan"]["message"]
    async with database() as db, db.begin():
        (await db.get(RestoreCheckpoint, checkpoint)).active = False
        db.add(
            RestoreCheckpoint(
                operator_id=UUID(admin["id"]), backup_id=uuid4(), active=True, snapshot={}
            )
        )
    assert (await client.get("/api/recovery/scans/" + identifier)).status_code == 404


async def test_findings_are_paged_and_scan_redelivery_does_not_repeat_observations(
    client, admin, database, monkeypatch
):
    await pause(database, admin)
    calls = []

    async def collect(inputs, writer):
        calls.append(1)
        for i in range(56):
            await writer.add(
                "files",
                "untracked",
                f"Journal {i}",
                "Untracked evidence",
                evidence={"file_details": ["large-synthetic-detail" * 1000], "source": "unchanged"},
            )

    monkeypatch.setattr(observers, "collect", collect)
    identifier = await begin(client)
    await scans.run(UUID(identifier))
    await scans.run(UUID(identifier))
    first = await report(client, identifier, domain="files")
    second = await report(client, identifier, domain="files", offset=50)
    assert first["total"] == 56 and len(first["items"]) == 50 and first["next_offset"] == 50
    assert len(second["items"]) == 6 and second["next_offset"] is None
    assert len(str(first)) < 40000
    assert all(
        "file_details" not in row["evidence"] and row["has_evidence"] for row in first["items"]
    )
    detail = await client.get(
        f"/api/recovery/scans/{identifier}/findings/{first['items'][0]['id']}"
    )
    assert detail.status_code == 200 and "file_details" in detail.json()["evidence"]
    assert (
        await client.get(f"/api/recovery/scans/{uuid4()}/findings/{first['items'][0]['id']}")
    ).status_code == 404
    assert calls == [1]


async def test_concurrent_delivery_and_lost_worker_lease_preserve_one_report(
    client, admin, database, monkeypatch
):
    await pause(database, admin)
    entered, release = asyncio.Event(), asyncio.Event()

    async def collect(inputs, writer):
        entered.set()
        await release.wait()
        await writer.add("review", "observed", "Only once", "Observed")

    monkeypatch.setattr(observers, "collect", collect)
    identifier = await begin(client)
    task = asyncio.create_task(scans.run(UUID(identifier)))
    await entered.wait()
    try:
        with pytest.raises(ShelfRetry):
            await scans.run(UUID(identifier))
    finally:
        release.set()
        await task
    async with database() as db, db.begin():
        scan = await db.get(RecoveryScan, UUID(identifier))
        scan.state, scan.run_token = "running", uuid4()
        scan.lease_until = datetime.now(UTC) - timedelta(minutes=1)
    await scans.run(UUID(identifier))
    async with database() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(RecoveryFinding)
                .where(RecoveryFinding.scan_id == UUID(identifier))
            )
            == 1
        )


async def test_worker_failure_allows_new_explicit_scan(client, admin, database):
    await pause(database, admin)
    first = await begin(client)
    async with database() as db, db.begin():
        scan = await db.get(RecoveryScan, UUID(first))
        operation = await db.get(Operation, scan.operation_id)
        await db.execute(
            text("UPDATE book_queue.procrastinate_jobs SET status='failed' WHERE id=:id"),
            {"id": operation.job_id},
        )
    second = await begin(client)
    assert first != second
    assert (await report(client, first))["scan"]["state"] == "held"


async def test_observation_migration_roundtrip_and_history_preservation(client, admin, database):
    async def migrate(*arguments):
        return await asyncio.to_thread(
            subprocess.run,
            ["uv", "run", "alembic", *arguments],
            capture_output=True,
            timeout=20,
        )

    # An empty schema can roundtrip, but no populated evidence can be discarded.
    down = await migrate("downgrade", "0041_restore_checkpoints")
    assert down.returncode == 0, down.stderr.decode()
    up = await migrate("upgrade", "head")
    assert up.returncode == 0, up.stderr.decode()
    await pause(database, admin)
    identifier = await begin(client)
    await scans.run(UUID(identifier))
    rejected = await migrate("downgrade", "0041_restore_checkpoints")
    assert rejected.returncode != 0
    assert b"Recovery scan history requires a pre-upgrade backup" in rejected.stderr
    result = await report(client, identifier)
    assert result["scan"]["state"] == "completed"
    assert result["items"][-1]["state"] == "needs-review"
    async with database() as db:
        assert await db.scalar(text("SELECT version_num FROM alembic_version")) == (
            "0042_recovery_scans"
        )
