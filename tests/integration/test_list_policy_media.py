# ruff: noqa: F401, F811
"""Media policy decisions use approved routes and the real shared acquisition workers."""

from uuid import UUID

import pytest
from sqlalchemy import select

from app.adapters.mam import ReleasePage
from app.config import get_settings
from app.db.models import (
    AcquisitionTarget,
    ImportDestination,
    LibraryAsset,
    ListAcquisitionBook,
)
from app.domain import book_sources
from app.importing.destinations import destination_configuration
from app.importing.naming import fingerprint
from tests.integration.test_list_policies import (
    activate,
    add,
    authorized,
    catalog,
    policy_fixture,
    preview,
    selection_route,
    source,
    tick,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def media_routes(client, database, policy_fixture, catalog, tmp_path, monkeypatch):
    f = policy_fixture
    settings = get_settings()
    ebook_root = tmp_path / "ebooks"
    ebook_root.mkdir()
    monkeypatch.setattr(
        settings, "import_destinations", {**settings.import_destinations, "ebooks": ebook_root}
    )
    async with database() as db, db.begin():
        audio = await db.get(
            ImportDestination, UUID(f["config"]["routes"]["audio"]["destination_id"])
        )
        ebook = ImportDestination(
            root_key="ebooks", library_id=catalog["library"], medium="ebook", backend_path="/ebooks"
        )
        db.add(ebook)
        await db.flush()
        probe = dict(audio.probe)
        routes = {}
        # Contract fixture only; native scanner and real file-route probes have
        # separate qualification. Adding a watched root invalidates both revisions.
        for destination in [ebook, audio]:
            revision = fingerprint(await destination_configuration(db, destination))
            destination.probe = {**probe, "configuration_revision": revision}
            routes[destination.medium] = {
                "destination_id": str(destination.id),
                "destination_revision": revision,
            }
    for medium, route in routes.items():
        response = await client.put(
            f"/api/organization/destinations/{route['destination_id']}/automatic-import",
            json={
                "enabled": True,
                "expected_generation": 0 if medium == "ebook" else 1,
                "destination_revision": route["destination_revision"],
            },
        )
        assert response.status_code == 200 and response.json()["ready"], response.text
    f["config"]["routes"] = routes
    return f


@pytest.mark.parametrize("mode", ["both", "either"])
async def test_owned_ebook_keeps_work_owned_and_only_both_requests_missing_audio(
    client, database, catalog, media_routes, mode
):
    f = media_routes
    f["config"]["specification"] = {
        "mode": mode,
        **({"preferred_medium": "audio"} if mode == "either" else {}),
    }
    await add(client, f)
    plan = await preview(client, f, include_work_ids=[f["work"]])
    assert plan["records"][0]["targets"][0]["state"] == "satisfied"
    saved = await activate(client, f, plan)
    for _ in range(3):
        await tick(database, saved, force_books=True)
    assert f["source"]["qbit"].calls.count("submit") == (1 if mode == "both" else 0)
    page = (await client.get(f"/api/catalog/works/{f['work']}")).json()
    assert page["availability"]["owned"] and page["availability"]["ebook"]
    async with database() as db:
        book = await db.scalar(select(ListAcquisitionBook))
        targets = list(
            await db.scalars(
                select(AcquisitionTarget).where(AcquisitionTarget.intent_id == book.intent_id)
            )
        )
        if mode == "both":
            assert {t.slot: t.state for t in targets} == {"ebook": "satisfied", "audio": "wanted"}
            assert book.state == "pending"
        else:
            assert book.state == "available" and f["calls"] == []


async def test_either_falls_back_to_other_medium_without_restarting_the_empty_search(
    client, database, catalog, media_routes, monkeypatch
):
    f = media_routes
    f["config"]["specification"] = {"mode": "either", "preferred_medium": "ebook"}
    # Remove the fixture's independent audio request so the initial preference
    # has no compatible pending transfer to reuse before trying ebook sources.
    intent_id = f["source"]["body"]["intent_id"]
    existing = (await client.get(f"/api/requests/{intent_id}")).json()
    for reason in existing["reasons"]:
        response = await client.delete(f"/api/requests/{intent_id}/reasons/{reason['id']}")
        assert response.status_code == 200, response.text
    async with database() as db, db.begin():
        (await db.get(LibraryAsset, catalog["asset"])).state = "missing"
    calls = []

    async def search(owner, action, value, **kwargs):
        calls.append(value.medium)
        return ReleasePage(
            items=[] if value.medium == "ebook" else [f["source"]["release"]],
            offset=0,
            limit=50,
            total=0 if value.medium == "ebook" else 1,
            has_more=False,
        ), 1

    monkeypatch.setattr(book_sources, "source_call", search)
    await add(client, f)
    saved = await activate(client, f, await preview(client, f, include_work_ids=[f["work"]]))
    for _ in range(7):
        await tick(database, saved, force_books=True)
    assert calls == ["ebook", "audio"]
    assert f["source"]["qbit"].calls.count("submit") == 1
    async with database() as db:
        book = await db.scalar(select(ListAcquisitionBook))
        assert book.state == "pending"
        assert set(book.progress["either"]["tried"]) == {"ebook"}
