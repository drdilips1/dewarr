from copy import deepcopy
from uuid import UUID

import pytest
from sqlalchemy import select

from app.adapters.audiobookshelf import parse_item
from app.db.models import Library, LibraryAsset, Version
from app.domain.inventory import apply_item
from app.jobs.queue import get_queue
from tests.integration.test_import_destinations import route as destination_route  # noqa: F401
from tests.integration.test_import_destinations import start_probe
from tests.integration.test_import_execution import ready_route, start  # noqa: F401
from tests.integration.test_import_inspections import submit
from tests.media_fixtures import pdf

pytestmark = pytest.mark.integration


@pytest.fixture
async def format_route(client, admin, ready_route):  # noqa: F811
    route = ready_route
    pdf(route["source"] / "pack/book.pdf")
    inspection = (await submit(client, key="formats-inspection")).json()
    await get_queue().run_worker_async(wait=False, concurrency=1)
    inspection = (await client.get(f"/api/organization/inspections/{inspection['id']}")).json()
    grouping = (
        await client.get(f"/api/organization/inspections/{inspection['id']}/grouping")
    ).json()
    body = {
        "inspection_revision": inspection["snapshot"]["revision"],
        "expected_revision": grouping["revision"],
        "groups": [{"files": [{"path": "book.epub"}, {"path": "book.pdf"}]}],
        "excluded": [],
    }
    rejected = await client.put(
        f"/api/organization/inspections/{inspection['id']}/grouping", json=body
    )
    assert rejected.status_code == 422 and "same complete edition" in rejected.text
    body["groups"][0]["same_edition"] = True
    response = await client.put(
        f"/api/organization/inspections/{inspection['id']}/grouping", json=body
    )
    assert response.status_code == 200, response.text
    grouped = response.json()
    assert (
        len(grouped["content"]["groups"]) == 1 and grouped["content"]["groups"][0]["same_edition"]
    )
    old = route["plan"]["document"]["groups"][0]
    settings = (await client.get("/api/organization/settings")).json()
    response = await client.post(
        f"/api/organization/inspections/{inspection['id']}/plans",
        json={
            "inspection_revision": inspection["snapshot"]["revision"],
            "grouping_revision": grouped["revision"],
            "profile_revision": settings["revision"],
            "selections": [
                {
                    "group_key": grouped["content"]["groups"][0]["key"],
                    "work_id": old["work_id"],
                    "version_id": old["version_id"],
                    "full_content": True,
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    route["plan"] = response.json()
    route["plan_id"] = route["plan"]["id"]
    await start_probe(client, route, key="formats-destination")
    await get_queue().run_worker_async(wait=False, concurrency=1)
    started = await start(client, route, key="formats-import")
    assert started.status_code == 202, started.text
    await get_queue().run_worker_async(wait=False, concurrency=1)
    run = (await client.get(f"/api/organization/imports/{started.json()['id']}")).json()
    assert run["entries"][0]["state"] == "confirmed", run
    route["asset_id"] = UUID(run["entries"][0]["asset_id"])
    return route


async def refresh(database, route, item):
    async with database() as db, db.begin():
        library = await db.get(Library, UUID(route["library_id"]))
        await apply_item(db, library, item, library.generation, library.integration_id, {item.id})


async def formats(database, route):
    async with database() as db:
        asset = await db.get(LibraryAsset, route["asset_id"])
        assert asset.full_content
        assert len((await db.scalars(select(Version))).all()) == 1
        return sorted(file["format"] for file in asset.files)


async def test_reviewed_formats_survive_refresh_and_primary_change(
    client, admin, database, format_route
):
    route = format_route
    assert await formats(database, route) == ["epub", "pdf"]
    raw = deepcopy(next(iter(route["scan_backend"].items.values())))
    await refresh(database, route, parse_item(raw))
    assert await formats(database, route) == ["epub", "pdf"]
    secondary = next(file for file in raw["libraryFiles"] if file["metadata"]["ext"] == ".pdf")
    for file in raw["libraryFiles"]:
        file["isSupplementary"] = file is not secondary
    raw["media"]["ebookFile"] = {**secondary, "ebookFormat": "pdf"}
    await refresh(database, route, parse_item(raw))
    assert await formats(database, route) == ["epub", "pdf"]
    repeated = await start(client, route, key="formats-second-import")
    assert repeated.json()["entries"][0]["state"] == "skipped"


@pytest.mark.parametrize("change", ["modified", "inode", "size", "missing"])
async def test_changed_alternate_format_loses_verification_without_losing_owned_book(
    client,
    admin,
    database,
    format_route,
    change,
):
    route = format_route
    raw = deepcopy(next(iter(route["scan_backend"].items.values())))
    secondary = next(file for file in raw["libraryFiles"] if file["metadata"]["ext"] == ".pdf")
    if change == "modified":
        secondary["metadata"]["mtimeMs"] += 1
    elif change == "inode":
        secondary["ino"] = "replacement-inode"
    elif change == "size":
        secondary["metadata"]["size"] += 1
    else:
        raw["libraryFiles"].remove(secondary)
    await refresh(database, route, parse_item(raw))
    assert await formats(database, route) == ["epub"]
    # Seeing the original path again does not silently renew a lost assertion.
    original = deepcopy(next(iter(route["scan_backend"].items.values())))
    await refresh(database, route, parse_item(original))
    assert await formats(database, route) == ["epub"]
