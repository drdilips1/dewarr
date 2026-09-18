import asyncio
import hashlib
from uuid import UUID

import pytest

from app.db.models import ImportEntry, Work
from app.importing import execution
from app.importing.cover_image import normalize
from app.jobs.queue import get_queue
from tests.cover_fixture import COVER_URL, CoverServiceFixture
from tests.integration.test_import_destinations import route as destination_route  # noqa: F401
from tests.integration.test_import_execution import ready_route, start  # noqa: F401
from tests.media_fixtures import cover_bytes

pytestmark = pytest.mark.integration


@pytest.fixture
async def cover_route(client, admin, database, ready_route, monkeypatch):  # noqa: F811
    route = ready_route
    selected = route["plan"]["document"]["groups"][0]
    async with database() as db, db.begin():
        (await db.get(Work, UUID(selected["work_id"]))).cover_url = COVER_URL
    inspection = (
        await client.get(f"/api/organization/inspections/{route['plan']['inspection_id']}")
    ).json()
    naming = (await client.get("/api/organization/settings")).json()
    body = {
        "inspection_revision": inspection["snapshot"]["revision"],
        "profile_revision": naming["revision"],
        "selections": [
            {
                "group_key": inspection["snapshot"]["groups"][0]["key"],
                "work_id": selected["work_id"],
                "version_id": selected["version_id"],
                "full_content": True,
            }
        ],
    }
    response = await client.post(
        f"/api/organization/inspections/{inspection['id']}/plans", json=body
    )
    assert response.status_code == 201, response.text
    route["plan"], route["plan_id"] = response.json(), response.json()["id"]
    route["freeze_body"] = body
    service = CoverServiceFixture()
    monkeypatch.setattr(execution, "fetch_cover", service.fetch)
    route["cover_service"] = service
    return route


async def entry(client, run):
    return (await client.get(f"/api/organization/imports/{run['id']}")).json()["entries"][0]


async def test_selected_cover_is_frozen_exported_and_confirmed(
    client, admin, database, cover_route
):
    route = cover_route
    selected = route["plan"]["document"]["groups"][0]
    async with database() as db, db.begin():
        (
            await db.get(Work, UUID(selected["work_id"]))
        ).cover_url = "https://assets.hardcover.app/later.png"
    run = (await start(client, route)).json()
    await get_queue().run_worker_async(wait=False, concurrency=1)
    current = await entry(client, run)
    assert current["state"] == "confirmed", current
    assert current["cover_export"]["backend_selected"] and current["cover_export"]["unchanged"]
    generated = next(route["target"].rglob("cover.jpg"))
    assert generated.stat().st_nlink == 1
    assert hashlib.sha256(generated.read_bytes()).hexdigest() == current["cover_export"]["sha256"]
    assert route["cover_service"].calls == [COVER_URL]
    assert not list(route["source"].rglob("*.jpg"))


async def test_unavailable_artwork_warns_without_blocking_media(client, admin, cover_route):
    cover_route["cover_service"].fail = True
    run = (await start(client, cover_route)).json()
    await get_queue().run_worker_async(wait=False, concurrency=1)
    current = await entry(client, run)
    assert current["state"] == "confirmed", current
    assert current["cover_export"]["state"] == "unavailable"
    assert "No cover exported" in current["cover_export"]["message"]
    assert not list(cover_route["target"].rglob("*.jpg"))


async def test_cover_preparation_survives_publication_crash_without_refetch(
    client, admin, cover_route
):
    run = (await start(client, cover_route)).json()
    operation = UUID(run["entries"][0]["operation_id"])

    def crash(phase):
        if phase == "published-before-database":
            raise RuntimeError("Synthetic acknowledgement crash")

    with pytest.raises(RuntimeError):
        await execution.execute(operation, checkpoint=crash)
    generated = next(cover_route["target"].rglob("cover.jpg"))
    original = generated.read_bytes()
    cover_route["cover_service"].content = cover_bytes(color="red")
    await execution.execute(operation)
    current = await entry(client, run)
    assert current["state"] == "confirmed", current
    assert generated.read_bytes() == original and len(cover_route["cover_service"].calls) == 1


async def test_external_artwork_change_is_preserved_during_detection_retry(
    client, admin, cover_route
):
    route = cover_route
    route["scan_backend"].detect = False
    run = (await start(client, route)).json()
    await get_queue().run_worker_async(wait=False, concurrency=1)
    current = await entry(client, run)
    assert current["state"] == "awaiting-library"
    cover = next(route["target"].rglob("cover.jpg"))
    changed = normalize(cover_bytes(color="gold"))
    cover.write_bytes(changed)
    route["scan_backend"].detect = True
    await execution.execute(UUID(current["operation_id"]))
    current = await entry(client, run)
    assert current["state"] == "confirmed"
    assert not current["cover_export"]["unchanged"]
    assert cover.read_bytes() == changed and len(route["cover_service"].calls) == 1


async def test_superseded_cover_fetch_cannot_replace_newer_prepared_artwork(
    client, admin, cover_route, monkeypatch
):
    started, release = asyncio.Event(), asyncio.Event()
    calls = 0
    newer = normalize(cover_bytes(color="blue"))

    async def fetch(url):
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            await release.wait()
            return normalize(cover_bytes(color="red"))
        return newer

    monkeypatch.setattr(execution, "fetch_cover", fetch)
    run = (await start(client, cover_route)).json()
    operation = UUID(run["entries"][0]["operation_id"])
    old = asyncio.create_task(execution.execute(operation))
    try:
        await asyncio.wait_for(started.wait(), 5)
        await execution.execute(operation)
    finally:
        release.set()
    await old
    assert (await entry(client, run))["state"] == "confirmed"
    assert next(cover_route["target"].rglob("cover.jpg")).read_bytes() == newer


async def test_plan_can_explicitly_omit_selected_covers(client, admin, cover_route):
    route = cover_route
    response = await client.post(
        f"/api/organization/inspections/{route['plan']['inspection_id']}/plans",
        json={**route["freeze_body"], "include_covers": False},
    )
    assert response.status_code == 201, response.text
    assert not response.json()["document"]["cover_sources"]
    assert response.json()["revision"] != route["plan"]["revision"]
    route["plan"], route["plan_id"] = response.json(), response.json()["id"]
    run = (await start(client, route)).json()
    await get_queue().run_worker_async(wait=False, concurrency=1)
    assert (await entry(client, run))["state"] == "confirmed"
    assert not route["cover_service"].calls and not list(route["target"].rglob("cover.jpg"))


async def test_cover_history_prevents_lossy_downgrade(client, admin, database, cover_route):
    from app.db.session import get_engine
    from tests.integration.test_correction_migration import migrate

    run = (await start(client, cover_route)).json()
    await get_queue().run_worker_async(wait=False, concurrency=1)
    await get_engine().dispose()
    try:
        result = await migrate("downgrade", "0012_groupings")
        assert result.returncode != 0 and "Cover export history" in result.stderr
        async with database() as db:
            assert (await db.get(ImportEntry, UUID(run["entries"][0]["id"]))).cover_export
    finally:
        assert (await migrate("upgrade", "head")).returncode == 0
        await get_engine().dispose()
