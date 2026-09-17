from uuid import UUID

import httpx
import pytest
from sqlalchemy import select

from app.db.models import (
    AssetContains,
    Integration,
    Library,
    LibraryAsset,
    LibraryGrant,
    User,
    Work,
)
from app.domain.availability import availability_for

pytestmark = pytest.mark.integration


async def test_catalog_is_not_ownership_and_lists_are_idempotent(client, admin, database):
    work = (
        await client.post(
            "/api/catalog/works",
            json={
                "title": "The Synthetic Archive",
                "authors": ["Example Author"],
            },
        )
    ).json()
    assert work["availability"]["owned"] is False
    search = (await client.get("/api/catalog/works", params={"q": "example"})).json()
    assert search["total"] == 1
    created = (await client.post("/api/lists", json={"name": "Weekend reads"})).json()
    path = f"/api/lists/{created['id']}"
    for _ in range(2):
        assert (
            await client.post(path + "/entries", json={"work_id": work["id"]})
        ).status_code == 204
    detail = (await client.get(path)).json()
    assert detail["count"] == 1
    assert detail["items"][0]["id"] == work["id"]
    assert (await client.put(path + "/order", json={"work_ids": []})).status_code == 422
    assert (await client.delete(path)).status_code == 204
    async with database() as db:
        assert await db.get(Work, UUID(work["id"])) is not None


async def test_private_lists_do_not_leak_to_other_accounts(client, admin):
    first_list = (await client.post("/api/lists", json={"name": "Private reading"})).json()
    await client.post(
        "/api/auth/users",
        json={
            "username": "reader",
            "display_name": "Reader",
            "role": "member",
            "password": "a long reader password",
        },
    )
    from app.main import create_app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()),
        base_url="http://testserver",
        headers={"Origin": "http://testserver"},
    ) as other:
        signed = await other.post(
            "/api/auth/login",
            json={
                "username": "reader",
                "password": "a long reader password",
            },
        )
        other.headers["X-CSRF-Token"] = signed.json()["csrf_token"]
        assert (await other.get("/api/lists")).json() == []
        path = f"/api/lists/{first_list['id']}"
        assert (await other.get(path)).status_code == 404
        assert (await other.delete(path)).status_code == 404
        await client.patch(path, json={"name": "Private reading", "shared": True})
        assert (await other.get(path)).status_code == 200
        assert (await other.delete(path)).status_code == 404
        await client.patch(path, json={"name": "Private reading", "shared": False})
        assert (await other.get(path)).status_code == 404


async def test_ownership_requires_complete_verified_accessible_assets(client, admin, database):
    async with database() as db:
        user = User(
            username="reader", display_name="Reader", password_hash="not-a-login", role="member"
        )
        work = Work(title="A Test Work")
        source = Integration(
            kind="abs", name="Test ABS", base_url="http://abs.test", encrypted_secrets="test"
        )
        db.add_all([user, work, source])
        await db.flush()
        library = Library(integration_id=source.id, external_id="lib1", name="Private books")
        db.add(library)
        await db.flush()
        ebook = LibraryAsset(
            library_id=library.id,
            external_id="item1",
            medium="ebook",
            state="present",
            full_content=True,
        )
        db.add(ebook)
        await db.flush()
        coverage = AssetContains(asset_id=ebook.id, work_id=work.id, verified=True)
        db.add(coverage)
        await db.flush()
        assert not (await availability_for(db, user, [work.id]))[work.id].owned
        db.add(LibraryGrant(user_id=user.id, library_id=library.id))
        await db.flush()
        state = (await availability_for(db, user, [work.id]))[work.id]
        assert state.owned and state.ebook and not state.audio
        ebook.full_content = False
        await db.flush()
        assert not (await availability_for(db, user, [work.id]))[work.id].owned
        ebook.full_content = True
        coverage.verified = False
        await db.flush()
        assert not (await availability_for(db, user, [work.id]))[work.id].owned
        coverage.verified = True
        ebook.state = "stale"
        await db.flush()
        assert (await availability_for(db, user, [work.id]))[work.id].stale
        ebook.state = "missing-confirmed"
        await db.flush()
        assert not (await availability_for(db, user, [work.id]))[work.id].owned


async def test_validation_does_not_echo_password(client):
    response = await client.post(
        "/api/auth/login",
        json={
            "username": "reader",
            "password": "shortsecret",
        },
    )
    assert response.status_code == 422
    assert "shortsecret" not in response.text


async def test_search_literal_percent_and_pagination(client, admin, database):
    async with database() as db:
        db.add_all([Work(title="100% Complete"), Work(title="Another Book")])
        await db.commit()
    result = (await client.get("/api/catalog/works", params={"q": "%"})).json()
    assert result["total"] == 1
    assert result["items"][0]["title"] == "100% Complete"
    result = (await client.get("/api/catalog/works", params={"limit": 1, "offset": 1})).json()
    assert result["total"] == 2
    assert result["items"][0]["title"] == "Another Book"
    async with database() as db:
        assert len((await db.scalars(select(Work))).all()) == 2
