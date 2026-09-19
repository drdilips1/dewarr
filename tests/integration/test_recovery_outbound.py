# ruff: noqa: F811
import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text

from app.adapters.contracts import AdapterError, FailureKind
from app.db.models import (
    AuditEvent,
    CatalogAccount,
    ListSubscription,
    ListWritebackLease,
    ListWritebackPolicy,
    Operation,
    RestoreCheckpoint,
    User,
)
from app.domain import list_writeback as writes
from app.domain import recovery_outbound as recovery
from app.domain import recovery_scans as scans
from app.jobs.queue import recovery_queue
from app.jobs.retry import ShelfRetry
from tests.integration.test_hardcover_subscriptions import (  # noqa: F401
    finish,
    service,
    shelf,
    start,
)
from tests.integration.test_list_curation import edit
from tests.integration.test_list_writeback import enable, latest, new_book, remote  # noqa: F401
from tests.integration.test_recovery_scan_workflow import begin, pause, report

pytestmark = pytest.mark.integration


@pytest.fixture
async def ready(client, admin, database, shelf, remote):
    await finish(await start(client, shelf))
    await enable(client, shelf)
    work = await new_book(client, database, admin)
    assert (await edit(client, shelf, "add", [work], "saved-outbound-add")).status_code == 200
    saved = await latest(database)
    return {"saved_id": saved.id, "list_id": UUID(shelf)}


async def observe(client):
    scan_id = await begin(client)
    await scans.run(UUID(scan_id))
    data = await report(client, scan_id, domain="lists")
    assert data["scan"]["state"] == "completed", data
    findings = [r["id"] for r in data["items"] if r["state"] == "outbound-ready"]
    assert findings, data
    return {"scan_id": scan_id, "finding_ids": findings}


async def preview(client, body, key=None):
    response = await client.post(
        "/api/recovery/outbound-reconciliations",
        headers={"Idempotency-Key": key or str(uuid4())},
        json=body,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def accept(client, plan, key=None):
    return await client.post(
        f"/api/recovery/outbound-reconciliations/{plan['id']}/accept",
        headers={"Idempotency-Key": key or str(uuid4())},
        json={"revision": plan["revision"]},
    )


async def outcome(client, plan):
    return (await client.get(f"/api/recovery/outbound-reconciliations/{plan['id']}")).json()


@pytest.mark.parametrize("applied", [False, True])
@pytest.mark.parametrize("sent", [False, True])
async def test_uncertain_add_or_backup_before_marker_never_replays(
    client, admin, database, ready, remote, service, applied, sent
):
    remote.apply, remote.lose_response = applied, True
    if sent:
        with pytest.raises(ShelfRetry):
            await writes.run(ready["saved_id"])
    elif applied:
        service.items.append({**service.items[0], "entry_id": 8, "external_id": "44"})
    checkpoint = await pause(database, admin)
    remote_before = deepcopy(service.items)
    async with database() as db:
        original = deepcopy((await db.get(Operation, ready["saved_id"])).payload)
        jobs = list(
            await db.scalars(
                text(
                    "SELECT id FROM book_queue.procrastinate_jobs "
                    "WHERE task_name NOT LIKE 'recovery.%' ORDER BY id"
                )
            )
        )
    body = await observe(client)
    plan = await preview(client, body, "outbound-plan-once")
    assert await preview(client, body, "outbound-plan-once") == plan
    expected = "desired-observed" if applied else "uncertain" if sent else "difference-held"
    assert plan["items"][0]["outcome"] == expected
    assert (await accept(client, plan, "outbound-accept-once")).status_code == 202
    assert (await accept(client, plan, "outbound-accept-once")).status_code == 202
    queue = recovery_queue()
    async with queue.open_async():
        await queue.run_worker_async(wait=False, concurrency=1)
    result = await outcome(client, plan)
    assert result["status"] == "completed", result
    async with database() as db:
        saved = await db.get(Operation, ready["saved_id"])
        assert saved.status == ("completed" if applied else "attention")
        assert saved.payload["pending_attempt"] == (
            None if applied else original["pending_attempt"]
        )
        assert saved.payload["attempts"] == original["attempts"]
        assert (
            saved.payload["recovery_receipt"]["before"]["pending_attempt"]
            == original["pending_attempt"]
        )
        assert saved.payload["reconcile_only"]
        policy = await db.get(ListWritebackPolicy, ready["list_id"])
        assert not policy.enabled and policy.generation == 2 and policy.confirmed_at is None
        assert (await db.get(RestoreCheckpoint, checkpoint)).active
        assert jobs == list(
            await db.scalars(
                text(
                    "SELECT id FROM book_queue.procrastinate_jobs "
                    "WHERE task_name NOT LIKE 'recovery.%' ORDER BY id"
                )
            )
        )
    reads, sends = remote.reads, deepcopy(remote.calls)
    await recovery.run(UUID(plan["id"]))
    await writes.run(ready["saved_id"])
    assert remote.reads == reads and remote.calls == sends and service.items == remote_before
    assert (await client.get("/api/recovery")).json()["latest_outbound_reconciliation"] == result
    assert (await client.get("/api/lists")).status_code == 423


@pytest.mark.parametrize("remaining", [False, True])
@pytest.mark.parametrize("exact_removed", [False, True])
async def test_removal_uses_exact_membership_not_just_same_book(
    client, admin, database, ready, service, remote, exact_removed, remaining
):
    async with database() as db, db.begin():
        saved = await db.get(Operation, ready["saved_id"])
        saved.payload = {
            **saved.payload,
            "base": {
                "owner_id": 7,
                "list_id": 9,
                "book_id": 42,
                "memberships": [{"id": 1, "list_id": 9, "book_id": 42, "edition_id": None}],
            },
            "book_id": 42,
            "desired": False,
            "pending_attempt": {"action": "remove", "entry_id": 1, "sent_at": "saved"},
        }
        lease = ListWritebackLease(
            target=writes.target(saved.payload),
            operation_id=saved.id,
            token=uuid4(),
            lease_until=datetime.now(UTC) + timedelta(minutes=2),
        )
        db.add(lease)
        old_token, lease_key = lease.token, lease.target
    service.items = [r for r in service.items if not exact_removed or r["entry_id"] != 1]
    if remaining:
        service.items.append(
            {**service.items[0], "entry_id": 5, "external_id": "42", "edition_id": "71"}
        )
    await pause(database, admin)
    plan = await preview(client, await observe(client))
    expected = (
        ("attempt-observed" if remaining else "desired-observed") if exact_removed else "uncertain"
    )
    assert plan["items"][0]["outcome"] == expected
    assert (await accept(client, plan)).status_code == 202
    await recovery.run(UUID(plan["id"]))
    assert (await outcome(client, plan))["status"] == "completed"
    async with database() as db:
        saved = await db.get(Operation, ready["saved_id"])
        assert saved.status == ("completed" if exact_removed and not remaining else "attention")
        assert bool(saved.payload["pending_attempt"]) == (not exact_removed)
        lease = await db.get(ListWritebackLease, lease_key)
        assert lease.token != old_token and lease.lease_until <= datetime.now(UTC)
    assert remote.calls == []


@pytest.mark.parametrize("change", ["remote", "account", "owner", "command", "lease"])
async def test_changes_after_acceptance_hold_without_touching_original_intent(
    client, admin, database, ready, service, remote, change
):
    await pause(database, admin)
    plan = await preview(client, await observe(client))
    assert (await accept(client, plan)).status_code == 202
    if change == "remote":
        service.items.append({**service.items[0], "entry_id": 8, "external_id": "44"})
    else:
        async with database() as db, db.begin():
            if change == "account":
                (await db.get(CatalogAccount, UUID(admin["id"]))).generation += 1
            elif change == "owner":
                (await db.get(User, UUID(admin["id"]))).active = False
            elif change == "command":
                saved = await db.get(Operation, ready["saved_id"])
                saved.payload = {**saved.payload, "sequence": 99}
            else:
                saved = await db.get(Operation, ready["saved_id"])
                db.add(
                    ListWritebackLease(
                        target=writes.target(saved.payload),
                        operation_id=saved.id,
                        token=uuid4(),
                        lease_until=datetime.now(UTC),
                    )
                )
    await recovery.run(UUID(plan["id"]))
    async with database() as db:
        assert (await db.get(Operation, UUID(plan["id"]))).status == "held"
        assert (await db.get(Operation, ready["saved_id"])).status == "queued"
        assert (await db.get(ListWritebackPolicy, ready["list_id"])).enabled
    assert remote.calls == []


async def test_remote_or_local_changes_during_read_cannot_publish(
    client, admin, database, ready, remote
):
    await pause(database, admin)
    plan = await preview(client, await observe(client))
    assert (await accept(client, plan)).status_code == 202

    async def change():
        async with database() as db, db.begin():
            (await db.get(ListWritebackPolicy, ready["list_id"])).generation += 1

    remote.before_read = change
    await recovery.run(UUID(plan["id"]))
    assert (await outcome(client, plan))["status"] == "held"
    async with database() as db:
        assert (await db.get(Operation, ready["saved_id"])).status == "queued"


async def test_multi_command_rollback_preserves_attempts_and_policy(
    client, admin, database, ready, monkeypatch
):
    async with database() as db, db.begin():
        saved = await db.get(Operation, ready["saved_id"])
        second = Operation(
            owner_id=saved.owner_id,
            kind=saved.kind,
            status="attention",
            idempotency_key="second-outbound",
            payload=deepcopy(saved.payload),
        )
        db.add(second)
        await db.flush()
        second_id = second.id
    await pause(database, admin)
    plan = await preview(client, await observe(client))
    assert len(plan["items"]) == 2
    assert (await accept(client, plan)).status_code == 202
    original, calls = recovery.record_outcome, []

    async def fail(*args):
        value = await original(*args)
        calls.append(value)
        if len(calls) == 2:
            raise RuntimeError("Injected second application failure")
        return value

    monkeypatch.setattr(recovery, "record_outcome", fail)
    await recovery.run(UUID(plan["id"]))
    assert (await outcome(client, plan))["status"] == "held"
    async with database() as db:
        for identifier in (ready["saved_id"], second_id):
            assert "recovery_receipt" not in (await db.get(Operation, identifier)).payload
        assert (await db.get(ListWritebackPolicy, ready["list_id"])).generation == 1
        assert not await db.scalar(
            select(AuditEvent.id).where(AuditEvent.action == "recovery.outbound.reconciled")
        )


@pytest.mark.parametrize("detached", [False, True])
async def test_rotated_credentials_and_detached_subscription_read_original_target(
    client, admin, database, ready, remote, detached
):
    async with database() as db, db.begin():
        (await db.get(CatalogAccount, UUID(admin["id"]))).generation += 1
        row = await db.scalar(
            select(ListSubscription).where(ListSubscription.list_id == ready["list_id"])
        )
        if detached:
            await db.delete(row)
        else:
            row.enabled = False
    await pause(database, admin)
    plan = await preview(client, await observe(client))
    assert (await accept(client, plan)).status_code == 202
    await recovery.run(UUID(plan["id"]))
    assert (await outcome(client, plan))["status"] == "completed"
    assert remote.calls == []


async def test_failed_or_wrong_owner_read_never_authorizes_resolution(
    client, admin, database, ready, remote
):
    remote.error = AdapterError(FailureKind.PERMISSION, "The original list is inaccessible")
    await pause(database, admin)
    scan_id = await begin(client)
    await scans.run(UUID(scan_id))
    data = await report(client, scan_id, domain="lists")
    assert not any(r["state"] == "outbound-ready" for r in data["items"])
    assert any(
        r["state"] == "blocked" and r["entity_id"] == str(ready["saved_id"]) for r in data["items"]
    )


async def test_operator_revision_csrf_and_recovery_serialization(client, admin, database, ready):
    await pause(database, admin)
    body = await observe(client)
    plan = await preview(client, body)
    path = f"/api/recovery/outbound-reconciliations/{plan['id']}/accept"
    assert (
        await client.post(
            path, headers={"Idempotency-Key": "wrong-revision"}, json={"revision": "0" * 64}
        )
    ).status_code == 409
    assert (
        await client.post(
            path,
            headers={"Idempotency-Key": "wrong-csrf", "X-CSRF-Token": "bad"},
            json={"revision": plan["revision"]},
        )
    ).status_code == 403
    assert (await client.get(f"/api/recovery/list-reconciliations/{plan['id']}")).status_code == 404
    assert (await accept(client, plan)).status_code == 202
    assert (
        await client.post("/api/recovery/scans", headers={"Idempotency-Key": "during-outbound"})
    ).status_code == 409
    await recovery.run(UUID(plan["id"]))
    assert (
        await client.post(
            "/api/recovery/outbound-reconciliations",
            headers={"Idempotency-Key": "stale-outbound"},
            json=body,
        )
    ).status_code == 409


async def test_inflight_ordinary_worker_loses_lease_after_review_without_sending(
    client, admin, database, ready, remote
):
    started, release = asyncio.Event(), asyncio.Event()
    blocked = False

    async def before():
        nonlocal blocked
        if not blocked:
            blocked = True
            started.set()
            await release.wait()

    remote.before_read = before
    old_worker = asyncio.create_task(writes.run(ready["saved_id"]))
    try:
        await asyncio.wait_for(started.wait(), 5)
        await pause(database, admin)
        plan = await preview(client, await observe(client))
        assert (await accept(client, plan)).status_code == 202
        await recovery.run(UUID(plan["id"]))
        assert (await outcome(client, plan))["status"] == "completed"
    finally:
        release.set()
        await asyncio.wait_for(old_worker, 5)
    assert remote.calls == []
    async with database() as db:
        saved = await db.get(Operation, ready["saved_id"])
        assert saved.status == "attention" and saved.payload["attempts"] == 0


@pytest.mark.parametrize(
    "malformed", ["base-target", "empty-attempt", "unknown-row", "wrong-action"]
)
async def test_corrupt_history_does_not_claim_an_effect(
    client, admin, database, ready, remote, malformed
):
    async with database() as db, db.begin():
        saved = await db.get(Operation, ready["saved_id"])
        p = deepcopy(saved.payload)
        if malformed == "base-target":
            p["base"]["book_id"] = 555
        elif malformed == "empty-attempt":
            p["pending_attempt"] = {}
        elif malformed == "wrong-action":
            p["pending_attempt"] = {"action": "remove", "entry_id": 1}
        else:
            p["desired"] = False
            p["pending_attempt"] = {"action": "remove", "entry_id": 999}
        saved.payload = p
    await pause(database, admin)
    scan_id = await begin(client)
    await scans.run(UUID(scan_id))
    data = await report(client, scan_id, domain="lists")
    assert not any(r["state"] == "outbound-ready" for r in data["items"])
    assert any(
        r["entity_id"] == str(ready["saved_id"]) and r["state"] == "needs-review"
        for r in data["items"]
    )
    assert remote.reads == 0 and remote.calls == []


async def test_remote_owner_must_match_original_even_when_new_account_owns_the_list(
    client, admin, database, ready, remote, monkeypatch
):
    original = remote.observe

    async def changed(*args):
        value = await original(*args)
        return value.model_copy(update={"owner_id": 8})

    monkeypatch.setattr(writes, "fetch_membership", changed)
    await pause(database, admin)
    scan_id = await begin(client)
    await scans.run(UUID(scan_id))
    data = await report(client, scan_id, domain="lists")
    assert not any(r["state"] == "outbound-ready" for r in data["items"])
    assert any(
        r["entity_id"] == str(ready["saved_id"]) and r["state"] == "blocked" for r in data["items"]
    )
