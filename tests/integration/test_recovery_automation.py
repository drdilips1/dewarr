# ruff: noqa: F401, F811
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text

from app.adapters.contracts import AdapterError, FailureKind
from app.db.models import (
    AuditEvent,
    AutomaticImportPolicy,
    BookList,
    ImportDestination,
    ListEntry,
    ListObservation,
    ListSubscription,
    ListWritebackLease,
    ListWritebackPolicy,
    Operation,
    RestoreCheckpoint,
    Work,
)
from app.domain import list_subscriptions, recovery_outbound, recovery_scans
from app.domain import recovery_automation as automation
from app.domain import recovery_commands as commands
from app.domain import recovery_observers as observers
from app.jobs.queue import recovery_queue
from app.security import encrypt_secrets
from tests.integration.test_import_destinations import route, start_probe
from tests.integration.test_recovery_commands import accept, outcome, preview
from tests.integration.test_recovery_scan_workflow import begin, pause, report

pytestmark = pytest.mark.integration


@pytest.fixture
async def settings(client, admin, database, route, monkeypatch):
    async def unavailable(*args):
        raise AdapterError(FailureKind.PERMISSION, "External fixture is unavailable")

    for name in ("inventory", "downloads", "shelf"):
        monkeypatch.setattr(observers, name, unavailable)
    monkeypatch.setattr(recovery_outbound, "observe", unavailable)
    now = datetime.now(UTC)
    async with database() as db, db.begin():
        owner = UUID(admin["id"])
        book_list = BookList(owner_id=owner, name="Saved automation list")
        db.add(book_list)
        await db.flush()
        subscription = ListSubscription(
            list_id=book_list.id,
            enabled=True,
            generation=4,
            encrypted_config=encrypt_secrets(
                {"feed_url": "https://www.goodreads.com/review/list_rss/1"}
            ),
            state="running",
            run_token=uuid4(),
            lease_until=now + timedelta(minutes=2),
            next_sync_at=now,
            baseline_at=now,
            last_success_at=now,
        )
        policy = AutomaticImportPolicy(
            destination_id=UUID(route["destination"]["id"]),
            approved_by=owner,
            enabled=True,
            generation=7,
            configuration={"preserved": "original-route"},
        )
        db.add_all([subscription, policy])
        await db.flush()
        pending = Operation(
            owner_id=owner,
            kind="lists.writeback",
            idempotency_key="saved-uncertain-write",
            status="attention",
            payload={"pending_attempt": {"sent_at": now.isoformat()}, "unchanged": "evidence"},
        )
        sync = Operation(
            owner_id=owner,
            kind="lists.sync",
            idempotency_key="saved-subscription-worker",
            status="running",
            payload={"subscription_id": str(subscription.id), "generation": 4},
        )
        db.add_all([pending, sync])
        await db.flush()
        subscription.operation_id = sync.id
        writeback = ListWritebackPolicy(
            list_id=book_list.id,
            subscription_id=subscription.id,
            generation=5,
            enabled=True,
            account_generation=2,
            remote_owner_id=7,
            external_list_id=9,
            confirmed_at=now,
            sequence=3,
        )
        lease = ListWritebackLease(
            target="hardcover:7:9",
            operation_id=pending.id,
            token=uuid4(),
            lease_until=now + timedelta(minutes=1),
        )
        work = await db.scalar(select(Work).limit(1))
        db.add_all(
            [
                writeback,
                lease,
                ListEntry(list_id=book_list.id, work_id=work.id),
                ListObservation(
                    subscription_id=subscription.id,
                    external_id="42",
                    snapshot={"title": "Saved title"},
                    work_id=work.id,
                    excluded=True,
                    last_seen_at=now,
                ),
            ]
        )
        return {
            "import-policy": policy.id,
            "subscription": subscription.id,
            "writeback-policy": book_list.id,
            "pending": pending.id,
            "sync": sync.id,
            "route": route,
            "list_id": book_list.id,
        }


async def observe(client, categories=None):
    scan = await begin(client)
    await recovery_scans.run(UUID(scan))
    data = await report(client, scan, domain="review")
    assert data["scan"]["state"] == "completed", data
    ids = []
    for finding in data["items"]:
        if finding["state"] != "automation-ready":
            continue
        evidence = (await client.get(f"/api/recovery/scans/{scan}/findings/{finding['id']}")).json()
        if categories is None or evidence["evidence"]["entity_type"] in categories:
            ids.append(finding["id"])
    assert ids, data
    return {"scan_id": scan, "finding_ids": ids}


async def preserved(database, settings):
    async with database() as db:
        result = {}
        for model in (ListEntry, ListObservation, ListWritebackLease):
            result[model.__tablename__] = [
                {c.name: deepcopy(getattr(r, c.name)) for c in model.__table__.columns}
                for r in await db.scalars(select(model))
            ]
        pending = await db.get(Operation, settings["pending"])
        result["pending"] = (pending.status, deepcopy(pending.payload))
        policy = await db.get(AutomaticImportPolicy, settings["import-policy"])
        result["route"] = (policy.approved_by, deepcopy(policy.configuration))
        result["source"] = (settings["route"]["source"] / "pack/book.epub").read_bytes()
        return result


@pytest.mark.parametrize("category", ["import-policy", "subscription", "writeback-policy"])
async def test_selected_automation_pause_is_scoped_atomic_and_preserves_evidence(
    client, admin, database, settings, category
):
    before = await preserved(database, settings)
    checkpoint = await pause(database, admin)
    plan = await preview(client, await observe(client, {category}))
    assert len(plan["items"]) == 1 and plan["items"][0]["entity_type"] == category
    assert (await accept(client, plan, key="accept-automation-once")).status_code == 202
    queue = recovery_queue()
    async with queue.open_async():
        await queue.run_worker_async(wait=False, concurrency=1)
    result = await outcome(client, plan)
    assert result["status"] == "completed", result
    assert (await accept(client, plan, key="accept-automation-once")).status_code == 202
    await commands.run(UUID(plan["id"]))
    async with database() as db:
        for kind, model in automation.MODELS.items():
            row = await db.get(model, settings[kind])
            assert row.enabled == (kind != category)
            assert row.generation == {"import-policy": 7, "subscription": 4, "writeback-policy": 5}[
                kind
            ] + int(kind == category)
            if category == kind == "subscription":
                assert (
                    row.run_token is row.lease_until is row.next_sync_at is row.operation_id is None
                )
                assert row.baseline_at and row.last_success_at
        assert (await db.get(RestoreCheckpoint, checkpoint)).active
        events = list(
            await db.scalars(
                select(AuditEvent).where(AuditEvent.action == "recovery.automation.paused")
            )
        )
        assert len(events) == 1 and events[0].detail["entity_type"] == category
    assert await preserved(database, settings) == before
    assert (await client.get("/api/lists")).status_code == 423
    if category == "subscription":
        async with database() as db:
            jobs = await db.scalar(text("SELECT count(*) FROM book_queue.procrastinate_jobs"))
        await list_subscriptions.schedule()
        async with database() as db:
            assert (
                await db.scalar(text("SELECT count(*) FROM book_queue.procrastinate_jobs")) == jobs
            )
    elif category == "import-policy":
        from types import SimpleNamespace

        from app.importing.automatic import check_policy

        async with database() as db:
            with pytest.raises(HTTPException, match="approval changed"):
                await check_policy(
                    db,
                    SimpleNamespace(
                        policy_id=settings[category],
                        policy_generation=7,
                    ),
                )


async def test_automation_batch_rolls_back_all_selected_policies_on_failure(
    client, admin, database, settings, monkeypatch
):
    before = await preserved(database, settings)
    await pause(database, admin)
    plan = await preview(client, await observe(client))
    assert len(plan["items"]) == 3
    assert (await accept(client, plan)).status_code == 202
    original = automation.pause
    calls = 0

    async def fail(*args):
        nonlocal calls
        result = await original(*args)
        calls += 1
        if calls == 2:
            raise RuntimeError("Second policy update failed")
        return result

    monkeypatch.setattr(automation, "pause", fail)
    await commands.run(UUID(plan["id"]))
    assert (await outcome(client, plan))["status"] == "held"
    async with database() as db:
        assert all(
            [
                (await db.get(model, settings[kind])).enabled
                for kind, model in automation.MODELS.items()
            ]
        )
        assert not await db.scalar(
            select(AuditEvent.id).where(AuditEvent.action == "recovery.automation.paused")
        )
    assert await preserved(database, settings) == before


@pytest.mark.parametrize("change", ["configuration", "approval", "subscription", "owner"])
async def test_automation_review_rechecks_current_context(
    client, admin, database, settings, change
):
    from app.db.models import User

    await pause(database, admin)
    plan = await preview(client, await observe(client))
    assert (await accept(client, plan)).status_code == 202
    async with database() as db, db.begin():
        if change == "configuration":
            (await db.get(AutomaticImportPolicy, settings["import-policy"])).configuration = {
                "changed": True
            }
        elif change == "approval":
            (await db.get(AutomaticImportPolicy, settings["import-policy"])).generation += 1
        elif change == "subscription":
            (
                await db.get(ListSubscription, settings["subscription"])
            ).encrypted_config = encrypt_secrets({"changed": True})
        else:
            (await db.get(User, UUID(admin["id"]))).role = "member"
    await commands.run(UUID(plan["id"]))
    async with database() as db:
        assert (await db.get(Operation, UUID(plan["id"]))).status == "held"
        assert all(
            [
                (await db.get(model, settings[kind])).enabled
                for kind, model in automation.MODELS.items()
            ]
        )
