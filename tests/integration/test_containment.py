import asyncio
import copy
from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.db.models import IdentityChange, LibraryAsset, LibraryGrant, User, Version
from app.security import hash_password
from tests.contracts.test_audiobookshelf import ABSFixture, book, connect, sync
from tests.integration.test_acquisition import body
from tests.integration.test_identity_corrections import history

pytestmark = pytest.mark.integration


async def setup(client, medium="audio"):
    connection = await connect(client)
    fixture = ABSFixture(
        {"one": book("one", audio=medium == "audio", ebook="epub" if medium == "ebook" else None)}
    )
    await sync(client, connection, fixture, "containment-initial-sync")
    asset = (await client.get("/api/library/assets")).json()["items"][0]
    works = [asset["work_ids"][0]]
    works.append(
        (await client.post("/api/catalog/works", json={"title": "Second Harbor"})).json()["id"]
    )
    return connection, fixture, asset, works


async def review(client, asset, works):
    return await client.put(
        f"/api/library/assets/{asset['id']}/contents",
        json={
            "work_ids": works,
            "expected_revision": asset["match_revision"],
            "complete_books_confirmed": True,
        },
    )


async def current(client):
    response = await client.get("/api/library/assets")
    assert response.status_code == 200
    return response.json()["items"][0]


@pytest.mark.parametrize("medium", ["ebook", "audio"])
async def test_reviewed_omnibus_counts_complete_books_but_never_separate_copies(
    client, admin, database, medium
):
    connection, fixture, asset, works = await setup(client, medium)
    async with database() as db:
        versions = await db.scalar(select(func.count()).select_from(Version))
    response = await review(client, asset, works)
    assert response.status_code == 204, response.text
    reviewed = await current(client)
    assert reviewed["collection"] and reviewed["version_id"] is None
    assert reviewed["open_url"] == asset["open_url"]
    assert set(reviewed["work_ids"]) == set(works)
    assert len(reviewed["contents"]) == 2 and all(b["verified"] for b in reviewed["contents"])
    for work in works:
        result = (await client.get(f"/api/catalog/works/{work}")).json()
        assert result["availability"]["owned"] and result["availability"]["in_collection"]
        for options, expected in [
            ({}, "satisfied"),
            ({"standalone": True}, "wanted"),
            ({"language": "en"}, "wanted"),
        ]:
            response = await client.post(
                "/api/requests/preview", json=body({"work": work}, medium, **options)
            )
            assert response.status_code == 200, response.text
            assert response.json()["targets"][0]["state"] == expected
    if medium == "audio":
        response = await client.post(
            "/api/requests/preview",
            json=body({"work": works[0]}, "audio", required_narrators=["Jordan Lee"]),
        )
        assert response.json()["targets"][0]["state"] == "wanted"
    await sync(client, connection, fixture, "containment-stable-resync")
    assert (await current(client))["match_revision"] == reviewed["match_revision"]
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(LibraryAsset)) == 1
        assert await db.scalar(select(func.count()).select_from(Version)) == versions
    change = (await history(client, asset=asset["id"]))[0]
    assert change["can_undo"]
    assert (await client.post(f"/api/identity/changes/{change['id']}/undo")).status_code == 204
    restored = await current(client)
    assert not restored["collection"] and restored["version_id"] == asset["version_id"]
    assert restored["work_ids"] == asset["work_ids"]


@pytest.mark.parametrize("change", ["narrator", "bytes", "file", "missing"])
async def test_changed_item_invalidates_coverage_until_explicit_reverification(
    client, admin, change
):
    connection, fixture, asset, works = await setup(client)
    assert (await review(client, asset, works)).status_code == 204
    reviewed = await current(client)
    original = copy.deepcopy(fixture.items["one"])
    item = fixture.items["one"]
    if change == "narrator":
        item["media"]["metadata"]["narrators"] = ["New Reader"]
    elif change == "bytes":
        item["media"]["audioFiles"][0]["metadata"]["mtimeMs"] += 1
    elif change == "file":
        item["media"]["audioFiles"][0]["ino"] = "replacement-inode"
    else:
        item["isMissing"] = True
    await sync(client, connection, fixture, "containment-changed-item")
    changed = await current(client)
    assert changed["collection"] and changed["match_status"] == "needs-review"
    assert not changed["full_content"] and not any(b["verified"] for b in changed["contents"])
    for work in works:
        assert not (await client.get(f"/api/catalog/works/{work}")).json()["availability"]["owned"]
        preview = await client.post("/api/requests/preview", json=body({"work": work}, "audio"))
        assert preview.status_code == 200, preview.text
        assert preview.json()["targets"][0]["state"] == "awaiting-inventory"
        standalone = await client.post(
            "/api/requests/preview", json=body({"work": work}, "audio", standalone=True)
        )
        assert standalone.json()["targets"][0]["state"] == "wanted"
    assert (await review(client, reviewed, works)).status_code == 409
    correction = (await history(client, asset=asset["id"]))[0]
    assert not correction["can_undo"]
    assert (await client.post(f"/api/identity/changes/{correction['id']}/undo")).status_code == 409
    fixture.items["one"] = original
    await sync(client, connection, fixture, "containment-original-returned")
    assert not (await current(client))["full_content"]
    assert (await review(client, await current(client), works)).status_code == 204
    assert (await current(client))["full_content"]


async def test_ordinary_match_replaces_contents_and_undo_restores_collection(client, admin):
    connection, fixture, asset, works = await setup(client)
    assert (await review(client, asset, works)).status_code == 204
    reviewed = await current(client)
    response = await client.post(
        f"/api/library/assets/{asset['id']}/match",
        json={"work_id": works[0], "expected_revision": reviewed["match_revision"]},
    )
    assert response.status_code == 204, response.text
    assert not (await current(client))["collection"]
    change = (await history(client, asset=asset["id"]))[0]
    assert (await client.post(f"/api/identity/changes/{change['id']}/undo")).status_code == 204
    await sync(client, connection, fixture, "containment-restored-collection")
    assert (await current(client))["collection"] and (await current(client))["full_content"]


async def test_contents_require_explicit_confirmation_distinct_books_and_current_revision(
    client, admin
):
    _, _, asset, works = await setup(client)
    assert (await review(client, asset, [works[0], works[0]])).status_code == 422
    response = await client.put(
        f"/api/library/assets/{asset['id']}/contents",
        json={
            "work_ids": works,
            "expected_revision": asset["match_revision"],
            "complete_books_confirmed": False,
        },
    )
    assert response.status_code == 422
    assert (await review(client, asset, works)).status_code == 204
    assert (await review(client, asset, works)).status_code == 409


async def test_collection_is_private_to_library_grants_and_only_admin_can_change_it(
    client, admin, database
):
    _, _, asset, works = await setup(client)
    assert (await review(client, asset, works)).status_code == 204
    async with database() as db, db.begin():
        user = User(
            username="reader",
            display_name="Reader",
            password_hash=hash_password("reader-password-long"),
            role="member",
        )
        db.add(user)
        await db.flush()
        user_id = user.id
    login = await client.post(
        "/api/auth/login", json={"username": "reader", "password": "reader-password-long"}
    )
    client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
    assert (await client.get("/api/library/assets")).json()["items"] == []
    assert (await review(client, asset, works)).status_code == 403

    async with database() as db, db.begin():
        db.add(LibraryGrant(user_id=user_id, library_id=UUID(asset["library_id"])))
    visible = await current(client)
    assert len(visible["contents"]) == 2 and not visible["match_revision"]
    assert (await review(client, asset, works)).status_code == 403


async def test_concurrent_reviews_have_one_winner_and_one_journal_entry(client, admin, database):
    _, _, asset, works = await setup(client)
    responses = await asyncio.gather(review(client, asset, works), review(client, asset, works))
    assert sorted(response.status_code for response in responses) == [204, 409]
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(IdentityChange)) == 1


async def test_undo_cannot_restore_collection_over_changed_files(client, admin):
    connection, fixture, asset, works = await setup(client)
    assert (await review(client, asset, works)).status_code == 204
    reviewed = await current(client)
    assert (
        await client.post(
            f"/api/library/assets/{asset['id']}/match",
            json={"work_id": works[0], "expected_revision": reviewed["match_revision"]},
        )
    ).status_code == 204
    correction = (await history(client, asset=asset["id"]))[0]
    fixture.items["one"]["media"]["audioFiles"][0]["metadata"]["mtimeMs"] += 1
    await sync(client, connection, fixture, "containment-undo-changed-files")
    assert (await client.post(f"/api/identity/changes/{correction['id']}/undo")).status_code == 409
