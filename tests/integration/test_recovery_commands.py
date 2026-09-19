# ruff: noqa: F401, F811
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text

from app.db.models import (
    AcquisitionIntent,
    AcquisitionReason,
    AcquisitionReservation,
    AcquisitionTarget,
    AuditEvent,
    ListAcquisitionBook,
    ListAcquisitionPolicy,
    Operation,
    RestoreCheckpoint,
    User,
)
from app.domain import (
    list_automation,
    list_policies,
    list_requests,
    series_acquisition,
    series_requests,
)
from app.domain import recovery_commands as recovery
from app.domain import recovery_scans as scans
from app.jobs.queue import recovery_queue
from tests.integration.test_acquisition import catalog
from tests.integration.test_acquisition_selections import selection_route
from tests.integration.test_automatic_dispatch import authorized
from tests.integration.test_automatic_pack_selection import series_pack
from tests.integration.test_automatic_selection import source
from tests.integration.test_list_policies import activate, add, policy_fixture
from tests.integration.test_list_policies import preview as policy_preview
from tests.integration.test_list_requests import preview as list_preview
from tests.integration.test_list_requests import shelf
from tests.integration.test_list_requests import submit as list_submit
from tests.integration.test_recovery_scan_workflow import begin, pause, report
from tests.integration.test_series_acquisition import accept as accept_series
from tests.integration.test_series_acquisition import ready as series_ready

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def unavailable_external_fixtures(monkeypatch):
    # These existing request fixtures contain synthetic backend credentials.
    # Retiring local authority must work without asserting external state.
    from app.adapters.contracts import AdapterError, FailureKind
    from app.domain import recovery_observers

    async def unavailable(*args):
        raise AdapterError(FailureKind.PERMISSION, "External fixture is unavailable")

    monkeypatch.setattr(recovery_observers, "inventory", unavailable)
    monkeypatch.setattr(recovery_observers, "downloads", unavailable)


async def observe(client, identifiers=None):
    scan = await begin(client)
    await scans.run(UUID(scan))
    data = await report(client, scan, domain="review")
    assert data["scan"]["state"] == "completed", data
    findings = [
        r["id"]
        for r in data["items"]
        if r["state"] == "command-ready"
        and (identifiers is None or UUID(r["entity_id"]) in identifiers)
    ]
    assert findings, data
    return {"scan_id": scan, "finding_ids": findings}


async def preview(client, body, key=None):
    response = await client.post(
        "/api/recovery/command-reconciliations",
        headers={"Idempotency-Key": key or str(uuid4())},
        json=body,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def accept(client, plan, key=None):
    return await client.post(
        f"/api/recovery/command-reconciliations/{plan['id']}/accept",
        headers={"Idempotency-Key": key or str(uuid4())},
        json={"revision": plan["revision"]},
    )


async def outcome(client, plan):
    return (await client.get(f"/api/recovery/command-reconciliations/{plan['id']}")).json()


async def wanted_snapshot(database):
    async with database() as db:
        result = {}
        for model in (
            AcquisitionIntent,
            AcquisitionReason,
            AcquisitionReservation,
            AcquisitionTarget,
        ):
            result[model.__tablename__] = [
                {c.name: deepcopy(getattr(row, c.name)) for c in model.__table__.columns}
                for row in await db.scalars(select(model).order_by(model.id))
            ]
        return result


@pytest.mark.parametrize("queued", [False, True])
async def test_list_batch_retirement_preserves_existing_wanted_and_forbids_replay(
    client, admin, database, shelf, catalog, queued
):
    completed = await list_preview(client, shelf, [catalog["work"]])
    await list_submit(client, shelf, completed)
    await list_requests.run(UUID(completed["id"]))
    batch = await list_preview(client, shelf, [catalog["work"]])
    if queued:
        await list_submit(client, shelf, batch)
    async with database() as db, db.begin():
        intent = await db.scalar(select(AcquisitionIntent))
        db.add(
            AcquisitionReason(intent_id=intent.id, kind="manual", reference="independent-manual")
        )
        if queued:
            (await db.scalar(select(AcquisitionReservation))).state = "committed"
    before = await wanted_snapshot(database)
    assert before["acquisition_reservations"]
    checkpoint = await pause(database, admin)
    body = await observe(client)
    plan = await preview(client, body, "same-retirement-preview")
    assert len(plan["items"]) == 1 and plan["items"][0]["entity_id"] == batch["id"]
    assert await preview(client, body, "same-retirement-preview") == plan
    assert (await accept(client, plan, "same-retirement-accept")).status_code == 202
    assert (await accept(client, plan, "same-retirement-accept")).status_code == 202
    queue = recovery_queue()
    async with queue.open_async():
        await queue.run_worker_async(wait=False, concurrency=1)
    result = await outcome(client, plan)
    assert result["status"] == "completed", result
    assert await wanted_snapshot(database) == before
    async with database() as db:
        retired = await db.get(Operation, UUID(batch["id"]))
        assert retired.status == "cancelled" and retired.payload["recovery_retirement"]
        assert (await db.get(Operation, UUID(completed["id"]))).status == "completed"
        assert (await db.get(RestoreCheckpoint, checkpoint)).active
        user = await db.get(User, UUID(admin["id"]))
        with pytest.raises(HTTPException, match="Recovery retired"):
            await list_requests.start(db, user, retired)
    await list_requests.run(UUID(batch["id"]))
    await recovery.run(UUID(plan["id"]))
    assert await wanted_snapshot(database) == before
    assert (await client.get("/api/recovery")).json()["latest_command_reconciliation"] == result


@pytest.mark.parametrize("completed", [False, True])
async def test_series_commands_and_controllers_preserve_accepted_receipts_and_reasons(
    client, admin, database, series_ready, completed
):
    parent_id = series_ready["parent"]
    controller_id = await accept_series(client, database, series_ready) if completed else None
    async with database() as db:
        parent_before = deepcopy((await db.get(Operation, parent_id)).payload)
        if controller_id:
            controller = await db.get(Operation, controller_id)
            proof = series_acquisition.proof(controller)
    before = await wanted_snapshot(database)
    await pause(database, admin)
    plan = await preview(client, await observe(client))
    assert any(item["entity_id"] == str(controller_id or parent_id) for item in plan["items"])
    assert (await accept(client, plan)).status_code == 202
    await recovery.run(UUID(plan["id"]))
    assert (await outcome(client, plan))["status"] == "completed"
    assert await wanted_snapshot(database) == before
    async with database() as db:
        parent = await db.get(Operation, parent_id)
        user = await db.get(User, UUID(admin["id"]))
        if completed:
            assert parent.status == "completed" and parent.payload == parent_before
            controller = await db.get(Operation, controller_id)
            assert not controller.payload["enabled"] and controller.status == "held"
            assert controller.payload["revision"] == 2 and controller.payload["next_at"] is None
            assert all(book["next_at"] is None for book in controller.payload["books"].values())
            with pytest.raises(HTTPException, match="Recovery retired"):
                await series_acquisition.retry(db, user, parent)
            with pytest.raises(HTTPException):
                await series_acquisition.require_authority(
                    db, user.id, proof, intent_id=UUID(parent.payload["receipt"][0]["request_id"])
                )
        else:
            assert parent.status == "cancelled"
            with pytest.raises(HTTPException, match="Recovery retired"):
                await series_requests.start(db, user, parent)
    await series_acquisition.run(controller_id) if controller_id else await series_requests.run(
        parent_id
    )
    assert await wanted_snapshot(database) == before


async def test_policy_pause_and_stale_activation_preview_need_new_owner_review(
    client, admin, database, policy_fixture
):
    f = policy_fixture
    await add(client, f)
    initial = await policy_preview(client, f)
    policy = await activate(client, f, initial)
    stale = await policy_preview(client, f, expected_revision=policy["revision"])
    await list_automation.schedule()
    async with database() as db:
        original_policy = await db.get(ListAcquisitionPolicy, UUID(policy["id"]))
        tick_id, old_due = original_policy.operation_id, original_policy.next_check_at
        jobs = list(
            await db.scalars(text("SELECT id FROM book_queue.procrastinate_jobs ORDER BY id"))
        )
    before = await wanted_snapshot(database)
    await pause(database, admin)
    plan = await preview(client, await observe(client))
    assert {item["action"] for item in plan["items"]} == {"retire-command", "pause-policy"}
    assert (await accept(client, plan)).status_code == 202
    await recovery.run(UUID(plan["id"]))
    assert (await outcome(client, plan))["status"] == "completed"
    async with database() as db, db.begin():
        row = await db.get(ListAcquisitionPolicy, UUID(policy["id"]))
        assert (
            not row.active
            and row.revision == policy["revision"] + 1
            and row.next_check_at == old_due
        )
        assert all(
            book.next_check_at is None for book in await db.scalars(select(ListAcquisitionBook))
        )
        user = await db.get(User, UUID(admin["id"]))
        retired = await db.get(Operation, UUID(stale["id"]))
        with pytest.raises(HTTPException, match="Recovery retired"):
            await list_policies.activate(db, user, retired)
        # Even deliberate later reactivation cannot make this old tick executable.
        row.active = True
        remaining = list(
            await db.scalars(text("SELECT id FROM book_queue.procrastinate_jobs ORDER BY id"))
        )
        assert set(jobs).issubset(remaining)
    if tick_id:
        await list_automation.run(tick_id)
        async with database() as db:
            assert (await db.get(Operation, tick_id)).status == "cancelled"
    assert await wanted_snapshot(database) == before and not f["calls"]


@pytest.mark.parametrize("change", ["command", "identity", "actor"])
async def test_changed_context_cannot_retire_a_reviewed_batch(
    client, admin, database, shelf, catalog, change
):
    saved = await list_preview(client, shelf, [catalog["work"]])
    await pause(database, admin)
    plan = await preview(client, await observe(client))
    assert (await accept(client, plan)).status_code == 202
    async with database() as db, db.begin():
        if change == "command":
            row = await db.get(Operation, UUID(saved["id"]))
            row.payload = {**row.payload, "new_decision": True}
        elif change == "actor":
            (await db.get(User, UUID(admin["id"]))).active = False
        else:
            # A changed library/request context must invalidate even a local-only decision.
            from app.db.models import Work

            (await db.get(Work, catalog["work"])).title = "Changed book identity"
    await recovery.run(UUID(plan["id"]))
    async with database() as db:
        assert (await db.get(Operation, UUID(plan["id"]))).status == "held"
        assert (await db.get(Operation, UUID(saved["id"]))).status == "preview"


async def test_batch_rollback_restores_every_command_and_audit(
    client, admin, database, shelf, catalog, monkeypatch
):
    first = await list_preview(client, shelf, [catalog["work"]])
    second = await list_preview(client, shelf, [catalog["work"]])
    await pause(database, admin)
    plan = await preview(client, await observe(client))
    assert len(plan["items"]) == 2
    assert (await accept(client, plan)).status_code == 202
    original = recovery.record_retirement
    count = 0

    async def fail(*args):
        nonlocal count
        result = await original(*args)
        count += 1
        if count == 2:
            raise RuntimeError("Second write failed")
        return result

    monkeypatch.setattr(recovery, "record_retirement", fail)
    await recovery.run(UUID(plan["id"]))
    assert (await outcome(client, plan))["status"] == "held"
    async with database() as db:
        for saved in (first, second):
            row = await db.get(Operation, UUID(saved["id"]))
            assert row.status == "preview" and "recovery_retirement" not in row.payload
        assert not await db.scalar(
            select(AuditEvent.id).where(AuditEvent.action == "recovery.command.retired")
        )


async def test_command_review_requires_exact_revision_and_excludes_other_actions(
    client, admin, database, shelf, catalog
):
    await list_preview(client, shelf, [catalog["work"]])
    await pause(database, admin)
    body = await observe(client)
    plan = await preview(client, body)
    path = f"/api/recovery/command-reconciliations/{plan['id']}/accept"
    assert (
        await client.post(
            path, headers={"Idempotency-Key": "wrong-command-revision"}, json={"revision": "0" * 64}
        )
    ).status_code == 409
    assert (
        await client.post(
            path,
            headers={"Idempotency-Key": "wrong-command-csrf", "X-CSRF-Token": "bad"},
            json={"revision": plan["revision"]},
        )
    ).status_code == 403
    assert (
        await client.get(f"/api/recovery/outbound-reconciliations/{plan['id']}")
    ).status_code == 404
    assert (await accept(client, plan)).status_code == 202
    assert (
        await client.post(
            "/api/recovery/scans", headers={"Idempotency-Key": "scan-during-retirement"}
        )
    ).status_code == 409
    await recovery.run(UUID(plan["id"]))
    assert (
        await client.post(
            "/api/recovery/command-reconciliations",
            headers={"Idempotency-Key": "stale-command-plan"},
            json=body,
        )
    ).status_code == 409


async def test_unselected_preview_remains_evidence_without_retirement(
    client, admin, database, shelf, catalog
):
    first = await list_preview(client, shelf, [catalog["work"]])
    second = await list_preview(client, shelf, [catalog["work"]])
    await pause(database, admin)
    plan = await preview(client, await observe(client, {UUID(first["id"])}))
    assert (await accept(client, plan)).status_code == 202
    await recovery.run(UUID(plan["id"]))
    async with database() as db:
        assert (await db.get(Operation, UUID(first["id"]))).status == "cancelled"
        other = await db.get(Operation, UUID(second["id"]))
        assert other.status == "preview" and "recovery_retirement" not in other.payload


async def test_waiting_old_list_worker_rechecks_retirement_after_acquiring_policy_lock(
    client, admin, database, policy_fixture, monkeypatch
):
    import asyncio

    f = policy_fixture
    policy = await activate(client, f, await policy_preview(client, f))
    await add(client, f)
    await list_automation.schedule()
    async with database() as db:
        tick_id = (await db.get(ListAcquisitionPolicy, UUID(policy["id"]))).operation_id
    assert tick_id
    before = await wanted_snapshot(database)
    started, released = asyncio.Event(), asyncio.Event()
    original = list_automation.owner_context

    async def delayed(*args):
        started.set()
        await released.wait()
        return await original(*args)

    monkeypatch.setattr(list_automation, "owner_context", delayed)
    old_worker = asyncio.create_task(list_automation.run(tick_id))
    try:
        await asyncio.wait_for(started.wait(), 5)
        await pause(database, admin)
        plan = await preview(client, await observe(client, {tick_id}))
        assert (await accept(client, plan)).status_code == 202
        await recovery.run(UUID(plan["id"]))
        assert (await outcome(client, plan))["status"] == "completed"
    finally:
        released.set()
        await asyncio.wait_for(old_worker, 5)
    async with database() as db:
        assert (await db.get(Operation, tick_id)).status == "cancelled"
        assert not list(await db.scalars(select(ListAcquisitionBook)))
        assert (await db.get(ListAcquisitionPolicy, UUID(policy["id"]))).active
    assert await wanted_snapshot(database) == before
