import asyncio
from uuid import UUID

import pytest

from app.config import get_settings
from app.db.models import ImportEntry, ImportRun, User, Version, Work
from app.importing import cancellation, execution
from app.jobs.queue import get_queue
from tests.integration.test_import_destinations import route as destination_route  # noqa: F401
from tests.integration.test_import_execution import ready_route, start  # noqa: F401
from tests.integration.test_import_inspections import submit
from tests.media_fixtures import epub

pytestmark = pytest.mark.integration


async def cancel(client, run, entry=None):
    return await client.post(
        f"/api/organization/imports/{run['id']}/entries/{(entry or run['entries'][0])['id']}/cancel"
    )


async def state(client, run):
    return (await client.get(f"/api/organization/imports/{run['id']}")).json()["entries"][0]


async def test_queued_cancellation_is_idempotent_and_releases_only_after_worker_check(
    client,
    admin,
    database,
    ready_route,  # noqa: F811
):
    route = ready_route
    run = (await start(client, route)).json()
    assert run["entries"][0]["can_cancel"]
    responses = await asyncio.gather(*(cancel(client, run) for _ in range(3)))
    assert all(row.status_code == 202 for row in responses)
    async with database() as db:
        entry = await db.get(ImportEntry, UUID(run["entries"][0]["id"]))
        assert entry.state == "cancelling" and entry.reserved
    repeated = (await start(client, route, "while-cancelling")).json()
    assert repeated["entries"][0]["state"] == "held"
    await get_queue().run_worker_async(wait=False, concurrency=1)
    stopped = await state(client, run)
    assert stopped["state"] == "cancelled" and not stopped["can_retry"]
    assert not list(route["target"].rglob("*.epub"))
    assert not list(get_settings().import_staging_root.glob("item-*"))
    assert (await cancel(client, run)).status_code == 202
    retry = await client.post(
        f"/api/organization/imports/{run['id']}/entries/{stopped['id']}/retry"
    )
    assert retry.status_code == 409
    assert (await start(client, route)).json()["id"] == run["id"]
    replacement = (await start(client, route, "after-cancellation")).json()
    assert replacement["entries"][0]["state"] == "queued"
    await get_queue().run_worker_async(wait=False, concurrency=1)
    assert (await state(client, replacement))["state"] == "confirmed"


async def test_cancel_during_preparation_fences_final_rename(client, admin, database, ready_route):  # noqa: F811
    route = ready_route
    run = (await start(client, route)).json()
    loop = asyncio.get_running_loop()

    def checkpoint(phase):
        if phase == "prepared":
            response = asyncio.run_coroutine_threadsafe(cancel(client, run), loop).result()
            assert response.status_code == 202

    await execution.execute(UUID(run["entries"][0]["operation_id"]), checkpoint=checkpoint)
    assert not list(route["target"].rglob("*.epub"))
    await get_queue().run_worker_async(wait=False, concurrency=1)
    assert (await state(client, run))["state"] == "cancelled"
    assert not list(get_settings().import_staging_root.glob("item-*"))
    assert (route["source"] / "pack/book.epub").stat().st_nlink == 1


async def test_cancel_after_unacknowledged_publication_preserves_and_confirms(
    client,
    admin,
    database,
    ready_route,  # noqa: F811
):
    run = (await start(client, ready_route)).json()

    def crash(phase):
        if phase == "published-before-database":
            raise RuntimeError("Fixture crash")

    with pytest.raises(RuntimeError):
        await execution.execute(UUID(run["entries"][0]["operation_id"]), checkpoint=crash)
    media = next(ready_route["target"].rglob("*.epub"))
    original = media.read_bytes(), media.stat().st_ino
    assert (await cancel(client, run)).status_code == 202
    await get_queue().run_worker_async(wait=False, concurrency=1)
    assert (await state(client, run))["state"] == "confirmed"
    assert (media.read_bytes(), media.stat().st_ino) == original
    assert (await cancel(client, run)).status_code == 409


async def test_cancellation_receipt_survives_database_acknowledgement_crash(
    client,
    admin,
    database,
    ready_route,  # noqa: F811
):
    run = (await start(client, ready_route)).json()
    await cancel(client, run)

    def crash(phase):
        if phase == "cancel-before-database":
            raise RuntimeError("Fixture crash")

    with pytest.raises(RuntimeError):
        await cancellation.execute(UUID(run["entries"][0]["operation_id"]), checkpoint=crash)
    async with database() as db:
        entry = await db.get(ImportEntry, UUID(run["entries"][0]["id"]))
        assert entry.state == "cancelling" and entry.reserved
    await get_queue().run_worker_async(wait=False, concurrency=1)
    assert (await state(client, run))["state"] == "cancelled"
    assert not list(ready_route["target"].rglob("*.epub"))


async def test_cancellation_holds_changed_roots_and_can_be_retried_after_repair(
    client,
    admin,
    database,
    ready_route,  # noqa: F811
):
    run = (await start(client, ready_route)).json()
    await cancel(client, run)
    settings = get_settings()
    original = settings.import_staging_root
    settings.import_staging_root = original / "changed"
    try:
        await get_queue().run_worker_async(wait=False, concurrency=1)
        held = await state(client, run)
        assert held["state"] == "cancel-held" and held["can_cancel"] and not held["can_retry"]
        async with database() as db:
            assert (await db.get(ImportEntry, UUID(held["id"]))).reserved
    finally:
        settings.import_staging_root = original
    assert (await cancel(client, run)).status_code == 202
    await get_queue().run_worker_async(wait=False, concurrency=1)
    assert (await state(client, run))["state"] == "cancelled"


async def test_cancellation_rechecks_actor_and_is_owner_scoped(
    client,
    admin,
    database,
    ready_route,  # noqa: F811
):
    run = (await start(client, ready_route)).json()
    await cancel(client, run)
    async with database() as db, db.begin():
        user = await db.get(User, UUID(admin["id"]))
        user.active = False
    await get_queue().run_worker_async(wait=False, concurrency=1)
    async with database() as db, db.begin():
        entry = await db.get(ImportEntry, UUID(run["entries"][0]["id"]))
        assert entry.state == "cancel-held" and entry.reserved
        user = await db.get(User, UUID(admin["id"]))
        user.active = True
        other = User(
            username="other-canceller",
            display_name="Other",
            password_hash=user.password_hash,
            role="admin",
        )
        db.add(other)
        await db.flush()
        (await db.get(ImportRun, UUID(run["id"]))).owner_id = other.id
    assert (await cancel(client, run)).status_code == 404


async def test_same_inspected_group_cannot_be_reserved_as_another_version(
    client,
    admin,
    database,
    ready_route,  # noqa: F811
):
    route = ready_route
    run = (await start(client, route)).json()
    inspection_id = route["plan"]["inspection_id"]
    inspection = (await client.get(f"/api/organization/inspections/{inspection_id}")).json()
    async with database() as db, db.begin():
        original = await db.get(Version, UUID(run["entries"][0]["version_id"]))
        other = Version(work_id=original.work_id, medium="ebook", title="Alternate edition")
        db.add(other)
        await db.flush()
        version_id, work_id = str(other.id), str(other.work_id)
    naming = (await client.get("/api/organization/settings")).json()
    plan = await client.post(
        f"/api/organization/inspections/{inspection_id}/plans",
        json={
            "inspection_revision": inspection["snapshot"]["revision"],
            "profile_revision": naming["revision"],
            "selections": [
                {
                    "group_key": inspection["snapshot"]["groups"][0]["key"],
                    "work_id": work_id,
                    "version_id": version_id,
                    "full_content": True,
                }
            ],
        },
    )
    assert plan.status_code == 201, plan.text
    another = (
        await start(
            client,
            {**route, "plan": plan.json(), "plan_id": plan.json()["id"]},
            "other-version-plan",
        )
    ).json()
    assert (
        another["entries"][0]["state"] == "held"
        and "files already belong" in another["entries"][0]["message"]
    )


async def test_unresolved_collection_can_be_replanned_beside_confirmed_sibling(
    client,
    admin,
    database,
    ready_route,  # noqa: F811
):
    route = ready_route
    epub(route["source"] / "pack/book2.epub", title="Second Harbor")
    async with database() as db, db.begin():
        work = Work(title="Second Harbor", authors=["Alex Morgan"])
        db.add(work)
        await db.flush()
        version = Version(work_id=work.id, medium="ebook", title=work.title)
        db.add(version)
        await db.flush()
        second_ids = str(work.id), str(version.id)
    response = await submit(client, key="cancel-replan-pack")
    await get_queue().run_worker_async(wait=False, concurrency=1)
    inspection = (await client.get(f"/api/organization/inspections/{response.json()['id']}")).json()
    path = f"/api/organization/inspections/{inspection['id']}"
    naming = (await client.get("/api/organization/settings")).json()
    first = route["plan"]["document"]["groups"][0]
    selections = []
    for group in inspection["snapshot"]["groups"]:
        second = group["files"][0]["path"] == "book2.epub"
        selections.append(
            {
                "group_key": group["key"],
                "work_id": second_ids[0] if second else first["work_id"],
                "version_id": second_ids[1] if second else first["version_id"],
                "full_content": not second,
            }
        )
    body = {
        "inspection_revision": inspection["snapshot"]["revision"],
        "profile_revision": naming["revision"],
        "selections": selections,
    }
    plan = (await client.post(path + "/plans", json=body)).json()
    run = (await start(client, {**route, "plan": plan, "plan_id": plan["id"]})).json()
    await get_queue().run_worker_async(wait=False, concurrency=1)
    entries = (await client.get(f"/api/organization/imports/{run['id']}")).json()["entries"]
    held = next(entry for entry in entries if entry["state"] == "held")
    assert (await cancel(client, run, held)).json()["entries"]
    media = next(route["target"].rglob("*.epub"))
    inode = media.stat().st_ino
    grouping = (await client.get(path + "/grouping")).json()
    keep = [
        group for group in grouping["content"]["groups"] if group["files"][0]["path"] == "book.epub"
    ]
    changed = await client.put(
        path + "/grouping",
        json={
            "inspection_revision": inspection["snapshot"]["revision"],
            "expected_revision": grouping["revision"],
            "groups": [
                {
                    "files": [
                        {key: file[key] for key in ("path", "disc", "track")}
                        for file in group["files"]
                    ]
                }
                for group in keep
            ],
            "excluded": [{"path": "book2.epub", "reason": "Review second book separately"}],
        },
    )
    assert changed.status_code == 200, changed.text
    reset = await client.put(
        path + "/grouping",
        json={
            "inspection_revision": inspection["snapshot"]["revision"],
            "expected_revision": changed.json()["revision"],
            "action": "reset",
        },
    )
    assert reset.status_code == 200, reset.text
    second_selection = next(
        selection for selection in selections if selection["version_id"] == second_ids[1]
    )
    new_plan = await client.post(
        path + "/plans",
        json={
            **body,
            "grouping_revision": reset.json()["revision"],
            "selections": [{**second_selection, "full_content": True}],
        },
    )
    assert new_plan.status_code == 201, new_plan.text
    rerun = (
        await start(
            client,
            {**route, "plan": new_plan.json(), "plan_id": new_plan.json()["id"]},
            "replanned-second-book",
        )
    ).json()
    await get_queue().run_worker_async(wait=False, concurrency=1)
    assert (await state(client, rerun))["state"] == "confirmed"
    assert len(list(route["target"].rglob("*.epub"))) == 2 and media.stat().st_ino == inode


async def test_cancellation_history_blocks_lossy_downgrade(client, admin, database, ready_route):  # noqa: F811
    from app.db.session import get_engine
    from tests.integration.test_correction_migration import migrate

    run = (await start(client, ready_route)).json()
    await cancel(client, run)
    await get_queue().run_worker_async(wait=False, concurrency=1)
    await get_engine().dispose()
    try:
        result = await migrate("downgrade", "0013_import_covers")
        assert result.returncode != 0 and "cancellation history" in result.stderr
    finally:
        assert (await migrate("upgrade", "head")).returncode == 0
        await get_engine().dispose()
