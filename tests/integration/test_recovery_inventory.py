import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text

from app.db.models import (
    AssetContains,
    AuditEvent,
    InventoryRun,
    Library,
    LibraryAsset,
    LibraryGrant,
    Operation,
    ProviderObject,
    RestoreCheckpoint,
    User,
    Work,
)
from app.domain import availability
from app.domain import recovery_inventory as recovery
from app.domain import recovery_observers as observers
from app.domain import recovery_reconciliation as reviews
from app.domain import recovery_scans as scans
from app.domain.acquisition import RequestSpec, assess
from app.jobs.queue import recovery_queue
from app.jobs.retry import ShelfRetry
from tests.contracts.test_audiobookshelf import ABSFixture, book, connect, sync
from tests.integration.test_recovery_scan_workflow import begin, pause, report

pytestmark = pytest.mark.integration


@pytest.fixture
async def inventory_ready(client, admin, database, monkeypatch):
    deleted, kept = book("deleted"), book("kept", ebook="epub")
    deleted["media"]["metadata"]["title"] = "Removed after the backup"
    fixture = ABSFixture({"deleted": deleted, "kept": kept})
    integration_id = UUID(await connect(client))
    await sync(client, str(integration_id), fixture, "inventory-before-backup")
    async with database() as db, db.begin():
        assets = {
            row.external_id + ":" + row.medium: row
            for row in await db.scalars(select(LibraryAsset))
        }
        ids = {key: row.id for key, row in assets.items()}
        work_ids = {
            key: await db.scalar(
                select(AssetContains.work_id).where(AssetContains.asset_id == row.id)
            )
            for key, row in assets.items()
        }
        for link in await db.scalars(select(ProviderObject)):
            link.manual_lock = True
        library_id = assets["kept:audio"].library_id
        member = User(
            username="inventory-reader",
            display_name="Inventory reader",
            password_hash="not-a-login-hash",
            role="member",
        )
        db.add(member)
        await db.flush()
        db.add(LibraryGrant(user_id=member.id, library_id=library_id))
        member_id = member.id
    fixture.items.pop("deleted")
    new = book("new", audio=False, ebook="epub")
    new["media"]["metadata"]["title"] = "Added after the backup"
    fixture.items["new"] = new
    monkeypatch.setattr(observers, "Audiobookshelf", fixture.client)
    monkeypatch.setattr(recovery, "Audiobookshelf", fixture.client)
    checkpoint_id = await pause(database, admin)
    scan_id = await begin(client)
    await scans.run(UUID(scan_id))
    data = await report(client, scan_id, domain="library")
    finding = next(row for row in data["items"] if row["state"] == "inventory-ready")
    return {
        "fixture": fixture,
        "scan_id": scan_id,
        "finding_id": finding["id"],
        "integration_id": integration_id,
        "assets": ids,
        "work_ids": work_ids,
        "library_id": library_id,
        "member_id": member_id,
        "checkpoint_id": checkpoint_id,
    }


async def preview(client, ready, key=None):
    response = await client.post(
        "/api/recovery/inventory-reconciliations",
        headers={"Idempotency-Key": key or str(uuid4())},
        json={"scan_id": ready["scan_id"], "finding_ids": [ready["finding_id"]]},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def accept(client, plan, key=None):
    return await client.post(
        f"/api/recovery/inventory-reconciliations/{plan['id']}/accept",
        headers={"Idempotency-Key": key or str(uuid4())},
        json={"revision": plan["revision"]},
    )


async def outcome(client, plan):
    result = await client.get("/api/recovery/inventory-reconciliations/" + plan["id"])
    assert result.status_code == 200, result.text
    return result.json()


async def test_reviewed_inventory_refresh_removes_false_ownership_without_remote_writes(
    client, admin, database, inventory_ready
):
    ready = inventory_ready
    plan = await preview(client, ready, "same-inventory-review")
    assert await preview(client, ready, "same-inventory-review") == plan
    assert plan["items"][0]["summary"]["missing_media"] == 1
    assert "inventory_digest" not in str(plan) and "connection_signature" not in str(plan)
    async with database() as db:
        assert (await db.get(LibraryAsset, ready["assets"]["deleted:audio"])).state == "present"
        old_grants = list(
            (await db.execute(select(LibraryGrant.user_id, LibraryGrant.library_id))).all()
        )
        queued = list(
            await db.scalars(
                text(
                    "SELECT id FROM book_queue.procrastinate_jobs WHERE status='todo' "
                    "AND task_name NOT LIKE 'recovery.%'"
                )
            )
        )
    accepted = await accept(client, plan, "same-inventory-accept")
    assert accepted.status_code == 202, accepted.text
    assert (await accept(client, plan, "same-inventory-accept")).json() == accepted.json()
    assert (
        await client.post(
            "/api/recovery/scans", headers={"Idempotency-Key": "during-inventory-review"}
        )
    ).status_code == 409
    queue = recovery_queue()
    async with queue.open_async():
        await queue.run_worker_async(wait=False, concurrency=1)
    result = await outcome(client, plan)
    assert result["status"] == "completed", result
    calls = list(ready["fixture"].calls)
    await recovery.run(UUID(plan["id"]))
    assert calls == ready["fixture"].calls
    assert not any("scan" in call or "update" in call for call in calls)
    async with database() as db:
        lost = await db.get(LibraryAsset, ready["assets"]["deleted:audio"])
        assert lost.state == "missing-suspected" and lost.missing_since
        assert (await db.get(LibraryAsset, ready["assets"]["kept:audio"])).state == "present"
        assert (await db.get(LibraryAsset, ready["assets"]["kept:ebook"])).state == "present"
        added = await db.scalar(select(LibraryAsset).where(LibraryAsset.external_id == "new"))
        assert added.state == "present" and added.full_content and added.medium == "ebook"
        assert (
            list((await db.execute(select(LibraryGrant.user_id, LibraryGrant.library_id))).all())
            == old_grants
        )
        assert all(
            row.manual_lock
            for row in await db.scalars(
                select(ProviderObject).where(ProviderObject.external_id == "kept")
            )
        )
        assert (await db.get(RestoreCheckpoint, ready["checkpoint_id"])).active
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "recovery.inventory.reconciled")
            )
            == 1
        )
        for identifier in queued:
            assert (
                await db.scalar(
                    text("SELECT status::text FROM book_queue.procrastinate_jobs WHERE id=:id"),
                    {"id": identifier},
                )
                == "todo"
            )
        user = await db.get(User, ready["member_id"])
        values = await availability.availability_for(db, user, list(ready["work_ids"].values()))
        assert not values[ready["work_ids"]["deleted:audio"]].owned
        assert values[ready["work_ids"]["kept:audio"]].owned
        missing_request = await assess(
            db, user, ready["work_ids"]["deleted:audio"], RequestSpec(mode="audio")
        )
        assert missing_request[0]["state"] == "awaiting-inventory"
    assert (await client.get("/api/lists")).status_code == 423
    assert (await client.get("/api/recovery")).json()["latest_inventory_reconciliation"][
        "status"
    ] == "completed"


@pytest.mark.parametrize(
    "change", ["item", "permission", "page-failure", "local-match", "local-grant", "operator"]
)
async def test_changed_review_holds_without_publishing_partial_inventory(
    client, admin, database, inventory_ready, change
):
    ready = inventory_ready
    plan = await preview(client, ready)
    assert (await accept(client, plan)).status_code == 202
    if change == "item":
        ready["fixture"].items["new"]["media"]["metadata"]["title"] = "Changed after review"
    elif change == "permission":
        ready["fixture"].scope = ["changed"]
    elif change == "page-failure":
        ready["fixture"].fail_batch = True
    else:
        async with database() as db, db.begin():
            if change == "operator":
                (await db.get(User, UUID(admin["id"]))).active = False
            elif change == "local-grant":
                await db.delete(
                    await db.get(LibraryGrant, (ready["member_id"], ready["library_id"]))
                )
            else:
                (await db.get(Work, ready["work_ids"]["kept:audio"])).title = "Manual correction"
    await recovery.run(UUID(plan["id"]))
    async with database() as db:
        assert (await db.get(Operation, UUID(plan["id"]))).status == "held"
        assert (await db.get(LibraryAsset, ready["assets"]["deleted:audio"])).state == "present"
        assert not await db.scalar(select(LibraryAsset).where(LibraryAsset.external_id == "new"))
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "recovery.inventory.reconciled")
            )
            == 0
        )


async def test_lost_library_access_is_not_deleted_media(client, admin, database, inventory_ready):
    ready = inventory_ready
    ready["fixture"].hide_libraries = True
    ready["scan_id"] = await begin(client)
    await scans.run(UUID(ready["scan_id"]))
    rows = await report(client, ready["scan_id"], domain="library")
    ready["finding_id"] = next(
        row["id"] for row in rows["items"] if row["state"] == "inventory-ready"
    )
    plan = await preview(client, ready)
    assert plan["items"][0]["summary"]["unavailable_libraries"] == 1
    assert (await accept(client, plan)).status_code == 202
    await recovery.run(UUID(plan["id"]))
    assert (await outcome(client, plan))["status"] == "completed"
    async with database() as db:
        assert not (await db.get(Library, ready["library_id"])).accessible
        assert all(
            asset.state == "scope-unavailable" for asset in await db.scalars(select(LibraryAsset))
        )
        assert await db.get(LibraryGrant, (ready["member_id"], ready["library_id"]))


async def test_inventory_apply_failure_rolls_back_catalog_assets_and_receipt(
    client, admin, database, inventory_ready, monkeypatch
):
    ready = inventory_ready
    plan = await preview(client, ready)
    assert (await accept(client, plan)).status_code == 202
    original = recovery.apply_inventory

    async def fail(*args):
        await original(*args)
        raise RuntimeError("synthetic failure after inventory writes")

    monkeypatch.setattr(recovery, "apply_inventory", fail)
    await recovery.run(UUID(plan["id"]))
    assert (await outcome(client, plan))["status"] == "held"
    async with database() as db:
        assert (await db.get(LibraryAsset, ready["assets"]["deleted:audio"])).state == "present"
        assert not await db.scalar(select(LibraryAsset).where(LibraryAsset.external_id == "new"))
        assert not await db.scalar(select(Work).where(Work.title == "Added after the backup"))
        assert not await db.scalar(
            select(InventoryRun).where(InventoryRun.operation_id == UUID(plan["id"]))
        )


async def test_inventory_redelivery_and_lost_lease_do_not_repeat_publication(
    client, admin, database, inventory_ready, monkeypatch
):
    plan = await preview(client, inventory_ready)
    assert (await accept(client, plan)).status_code == 202
    original = recovery.fresh_inventory
    entered, release = asyncio.Event(), asyncio.Event()

    async def wait(*args):
        entered.set()
        await release.wait()
        return await original(*args)

    monkeypatch.setattr(recovery, "fresh_inventory", wait)
    first = asyncio.create_task(recovery.run(UUID(plan["id"])))
    await entered.wait()
    try:
        with pytest.raises(ShelfRetry):
            await recovery.run(UUID(plan["id"]))
    finally:
        release.set()
        await first
    assert (await outcome(client, plan))["status"] == "completed"


async def test_inventory_expired_plan_and_wrong_route_are_rejected(
    client, admin, database, inventory_ready
):
    plan = await preview(client, inventory_ready)
    assert (await client.get("/api/recovery/reconciliations/" + plan["id"])).status_code == 404
    bad = await client.post(
        f"/api/recovery/inventory-reconciliations/{plan['id']}/accept",
        headers={"Idempotency-Key": "no-csrf-inventory", "X-CSRF-Token": "bad"},
        json={"revision": plan["revision"]},
    )
    assert bad.status_code == 403
    async with database() as db, db.begin():
        operation = await db.get(Operation, UUID(plan["id"]))
        payload = dict(operation.payload)
        payload["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        payload["revision"] = reviews.digest(
            {
                key: payload[key]
                for key in ("checkpoint_id", "command", "context_digest", "expires_at", "items")
            }
        )
        operation.payload = payload
        plan["revision"] = payload["revision"]
    assert (await accept(client, plan)).status_code == 409


async def fresh_plan(client, ready):
    ready = dict(ready)
    ready["scan_id"] = await begin(client)
    await scans.run(UUID(ready["scan_id"]))
    rows = await report(client, ready["scan_id"], domain="library")
    ready["finding_id"] = next(
        row["id"] for row in rows["items"] if row["state"] == "inventory-ready"
    )
    return await preview(client, ready)


async def test_moved_items_use_new_library_without_expanding_member_grants(
    client, admin, database, inventory_ready
):
    import httpx

    ready = inventory_ready
    fixture = ready["fixture"]
    fixture.items["kept"]["libraryId"] = "library-two"
    original = fixture.handle

    async def moved(request):
        path = request.url.path
        if path == "/abs/api/libraries":
            return httpx.Response(
                200,
                json={
                    "libraries": [
                        {"id": "library-one", "name": "Original library", "mediaType": "book"},
                        {"id": "library-two", "name": "New private library", "mediaType": "book"},
                    ]
                },
            )
        if path in {"/abs/api/libraries/library-one/items", "/abs/api/libraries/library-two/items"}:
            library_id = path.split("/")[-2]
            values = [item for item in fixture.items.values() if item["libraryId"] == library_id]
            return httpx.Response(
                200,
                json={
                    "total": len(values),
                    "results": [
                        {key: item[key] for key in ("id", "updatedAt", "isMissing", "isInvalid")}
                        for item in values
                    ],
                },
            )
        return await original(request)

    fixture.handle = moved
    plan = await fresh_plan(client, ready)
    assert plan["items"][0]["summary"]["new_libraries"] == 1
    assert (await accept(client, plan)).status_code == 202
    await recovery.run(UUID(plan["id"]))
    assert (await outcome(client, plan))["status"] == "completed"
    async with database() as db:
        destination = await db.scalar(select(Library).where(Library.external_id == "library-two"))
        assert destination.accessible
        assert not await db.scalar(
            select(LibraryGrant).where(LibraryGrant.library_id == destination.id)
        )
        assert (await db.get(LibraryAsset, ready["assets"]["kept:audio"])).state == "moved"
        assert (await db.get(LibraryAsset, ready["assets"]["kept:ebook"])).state == "moved"
        assets = list(
            await db.scalars(select(LibraryAsset).where(LibraryAsset.library_id == destination.id))
        )
        assert len(assets) == 2 and all(asset.state == "present" for asset in assets)
        work_id = ready["work_ids"]["kept:audio"]
        member = await db.get(User, ready["member_id"])
        actor = await db.get(User, UUID(admin["id"]))
        assert not (await availability.availability_for(db, member, [work_id]))[work_id].owned
        assert (await availability.availability_for(db, actor, [work_id]))[work_id].owned


async def test_recovery_preserves_suppression_and_holds_changed_recording(
    client, admin, database, inventory_ready
):
    ready = inventory_ready
    async with database() as db, db.begin():
        (await db.get(LibraryAsset, ready["assets"]["kept:ebook"])).state = "intentionally-removed"
    ready["fixture"].items["kept"]["media"]["metadata"]["narrators"] = ["Different narrator"]
    plan = await fresh_plan(client, ready)
    assert (await accept(client, plan)).status_code == 202
    await recovery.run(UUID(plan["id"]))
    assert (await outcome(client, plan))["status"] == "completed"
    async with database() as db:
        assert (
            await db.get(LibraryAsset, ready["assets"]["kept:ebook"])
        ).state == "intentionally-removed"
        audio = await db.get(LibraryAsset, ready["assets"]["kept:audio"])
        assert not audio.full_content and audio.match_status == "needs-review"
        assert not await db.scalar(
            select(AssetContains).where(
                AssetContains.asset_id == audio.id, AssetContains.verified.is_(True)
            )
        )


async def test_saved_inventory_lease_and_staged_run_are_fenced(
    client, admin, database, inventory_ready
):
    from app.db.models import Integration
    from app.domain.inventory import LeaseLost, fence

    ready = inventory_ready
    old_token = uuid4()
    async with database() as db, db.begin():
        integration = await db.get(Integration, ready["integration_id"])
        generation = integration.credential_generation
        integration.lease_token = old_token
        integration.lease_until = datetime.now(UTC) + timedelta(minutes=2)
        operation = Operation(
            owner_id=UUID(admin["id"]),
            kind="library.sync",
            idempotency_key="saved-interrupted-inventory",
            integration_id=integration.id,
            status="running",
        )
        db.add(operation)
        await db.flush()
        run = InventoryRun(
            integration_id=integration.id,
            operation_id=operation.id,
            credential_generation=generation,
        )
        db.add(run)
        await db.flush()
        run_id = run.id
    plan = await fresh_plan(client, ready)
    assert (await accept(client, plan)).status_code == 202
    await recovery.run(UUID(plan["id"]))
    assert (await outcome(client, plan))["status"] == "completed"
    async with database() as db:
        assert (await db.get(InventoryRun, run_id)).status == "interrupted"
        with pytest.raises(LeaseLost):
            await fence(db, ready["integration_id"], old_token, generation)


@pytest.mark.parametrize("changed", [False, True])
async def test_inventory_recovery_revalidates_reviewed_collection_coverage(
    client, admin, database, monkeypatch, changed
):
    from tests.integration.test_containment import review as review_collection
    from tests.integration.test_containment import setup

    _, fixture, asset, works = await setup(client)
    assert (await review_collection(client, asset, works)).status_code == 204
    if changed:
        fixture.items["one"]["media"]["audioFiles"][0]["ino"] = "different-inode"
    monkeypatch.setattr(observers, "Audiobookshelf", fixture.client)
    monkeypatch.setattr(recovery, "Audiobookshelf", fixture.client)
    await pause(database, admin)
    plan = await fresh_plan(client, {})
    assert (await accept(client, plan)).status_code == 202
    await recovery.run(UUID(plan["id"]))
    assert (await outcome(client, plan))["status"] == "completed"
    async with database() as db:
        record = await db.get(LibraryAsset, UUID(asset["id"]))
        assert record.containment["valid"] is not changed
        assert record.full_content is not changed
        rows = list(
            await db.scalars(select(AssetContains).where(AssetContains.asset_id == record.id))
        )
        assert len(rows) == 2 and all(row.verified is not changed for row in rows)
        actor = await db.get(User, UUID(admin["id"]))
        states = await availability.availability_for(db, actor, [UUID(work) for work in works])
        assert all(value.owned is not changed for value in states.values())
