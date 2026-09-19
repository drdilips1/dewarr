from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select, update

from app.db.models import (
    AcquisitionIntent,
    AssetContains,
    Integration,
    Library,
    LibraryAsset,
    LibraryGrant,
    Operation,
    Work,
)
from tests.integration.test_discovery import add_owned, login_member

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 19, tzinfo=UTC)


async def add(db, title, days=0, **values):
    work = Work(title=title, authors=["Library writer"])
    db.add(work)
    await db.flush()
    library = await add_owned(db, work)
    asset = await db.scalar(select(LibraryAsset).where(LibraryAsset.library_id == library.id))
    asset.created_at = NOW - timedelta(days=days)
    for key, value in values.items():
        setattr(asset, key, value)
    return work, library, asset


async def shelf(client, **params):
    response = await client.get("/api/discovery/library", params=params)
    assert response.status_code == 200, response.text
    assert "no-store" in response.headers["cache-control"]
    return response.json()


async def test_library_additions_use_observed_copy_dates_not_catalog_or_last_sync(
    client, admin, database, monkeypatch
):
    async def forbidden(*args, **kwargs):
        raise AssertionError("Library discovery must not contact metadata providers")

    monkeypatch.setattr("app.api.discovery.provider_call", forbidden)
    async with database() as db, db.begin():
        older, _, old_asset = await add(db, "Older copy", days=5)
        newer, _, new_asset = await add(db, "Newer copy", days=1, state="stale")
        newer.created_at = NOW - timedelta(days=100)
        old_asset.last_seen_at = NOW
        new_asset.last_seen_at = NOW - timedelta(days=1)
        db.add(Work(title="Newest catalog only", authors=[]))
        ids = [str(newer.id), str(older.id)]
    result = await shelf(client)
    assert [item["work"]["id"] for item in result["items"]] == ids
    assert datetime.fromisoformat(result["items"][0]["observed_at"]) == NOW - timedelta(days=1)
    assert result["items"][0]["work"]["availability"]["stale"]
    assert all(item["work"]["availability"]["owned"] for item in result["items"])
    async with database() as db, db.begin():
        await db.execute(update(LibraryAsset).values(last_seen_at=NOW + timedelta(days=1)))
    assert (await shelf(client)) == result
    async with database() as db:
        for model in (Operation, AcquisitionIntent):
            assert await db.scalar(select(func.count()).select_from(model)) == 0
        assert await db.scalar(select(func.count()).select_from(Work)) == 3


async def test_canonical_books_group_versions_and_filter_before_paging(client, admin, database):
    async with database() as db, db.begin():
        root, _, _ = await add(db, "Canonical book", days=10)
        alias, _, audio = await add(db, "Alternate title", days=1, medium="audio")
        alias.redirect_to = root.id
        extra, _, _ = await add(db, "Other ebook", days=5)
        ids = [str(root.id), str(extra.id)]
    first = await shelf(client, limit=1)
    second = await shelf(client, limit=1, page=2)
    assert [first["items"][0]["work"]["id"], second["items"][0]["work"]["id"]] == ids
    assert first["has_more"] and not second["has_more"]
    assert first["items"][0]["work"]["availability"]["ebook"]
    assert first["items"][0]["work"]["availability"]["audio"]
    ebook = await shelf(client, medium="ebook", limit=1)
    assert ebook["items"][0]["work"]["id"] == ids[1]
    audio = await shelf(client, medium="audio")
    assert len(audio["items"]) == 1 and audio["items"][0]["work"]["id"] == ids[0]
    assert (await shelf(client, page=3, limit=1))["items"] == []


@pytest.mark.parametrize("role", ["member", "viewer"])
async def test_library_grants_and_unavailable_connections_filter_before_paging(
    client, admin, database, role
):
    async with database() as db, db.begin():
        visible, library, _ = await add(db, "Allowed old book", days=10)
        await add(db, "Private recent book")
        visible_id, library_id, integration_id = visible.id, library.id, library.integration_id
    owner = await login_member(client, role)
    assert (await shelf(client))["items"] == []
    async with database() as db, db.begin():
        db.add(LibraryGrant(user_id=owner, library_id=library_id))
    result = await shelf(client, limit=1)
    assert [item["work"]["id"] for item in result["items"]] == [str(visible_id)]
    assert not result["has_more"] and "Private recent book" not in str(result)
    async with database() as db, db.begin():
        await db.execute(update(Library).where(Library.id == library_id).values(accessible=False))
    assert (await shelf(client))["items"] == []
    async with database() as db, db.begin():
        await db.execute(update(Library).where(Library.id == library_id).values(accessible=True))
        await db.execute(
            update(Integration).where(Integration.id == integration_id).values(enabled=False)
        )
    assert (await shelf(client))["items"] == []
    async with database() as db, db.begin():
        await db.execute(
            update(Integration).where(Integration.id == integration_id).values(enabled=True)
        )
        await db.execute(delete(LibraryGrant))
    assert (await shelf(client))["items"] == []


@pytest.mark.parametrize(
    "state", ["missing-suspected", "missing-confirmed", "scope-unavailable", "moved"]
)
async def test_unavailable_assets_never_create_additions(client, admin, database, state):
    async with database() as db, db.begin():
        await add(db, "Unavailable", state=state)
    assert (await shelf(client))["items"] == []


async def test_verified_collections_count_children_without_companions_or_unverified_matches(
    client, admin, database
):
    async with database() as db, db.begin():
        first, _, asset = await add(db, "Collection child one", containment={"kind": "reviewed"})
        second = Work(title="Collection child two", authors=[])
        unverified = Work(title="Unverified child", authors=[])
        db.add_all([second, unverified])
        await db.flush()
        db.add_all(
            [
                AssetContains(asset_id=asset.id, work_id=second.id, verified=True),
                AssetContains(asset_id=asset.id, work_id=unverified.id, verified=False),
            ]
        )
        await add(db, "Companion only", full_content=False)
        ids = [str(first.id), str(second.id)]
    result = await shelf(client)
    assert [item["work"]["id"] for item in result["items"]] == ids
    assert all(item["work"]["availability"]["in_collection"] for item in result["items"])


@pytest.mark.parametrize("params", [{"medium": "video"}, {"page": 0}, {"page": 101}, {"limit": 25}])
async def test_invalid_filters(client, admin, params):
    assert (await client.get("/api/discovery/library", params=params)).status_code == 422


async def test_anonymous_cannot_browse_library(client):
    assert (await client.get("/api/discovery/library")).status_code == 401


async def test_hidden_newer_copy_cannot_change_visible_order_or_observation_date(
    client, admin, database
):
    async with database() as db, db.begin():
        old, first_library, _ = await add(db, "Old allowed copy", days=10)
        new, second_library, _ = await add(db, "New allowed copy", days=5)
        hidden, _, _ = await add(db, "Hidden latest copy", days=0, medium="audio")
        hidden.redirect_to = old.id
        libraries = [first_library.id, second_library.id]
        ids = [str(new.id), str(old.id)]
    owner = await login_member(client)
    async with database() as db, db.begin():
        db.add_all([LibraryGrant(user_id=owner, library_id=value) for value in libraries])
    result = await shelf(client)
    assert [item["work"]["id"] for item in result["items"]] == ids
    assert datetime.fromisoformat(result["items"][1]["observed_at"]) == NOW - timedelta(days=10)
    assert not result["items"][1]["work"]["availability"]["audio"]
    assert (await shelf(client, medium="audio"))["items"] == []
