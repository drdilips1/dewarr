from contextlib import aclosing
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.adapters import goodreads_profile
from app.adapters.catalog_providers import Hardcover
from app.adapters.goodreads import FeedResult
from app.adapters.hardcover_lists import ListPage
from app.db.models import BookList, GoodreadsAccount, ListSubscription, Operation
from app.domain import list_subscriptions
from tests.integration.test_list_subscriptions import member

pytestmark = pytest.mark.integration


@pytest.fixture
async def discovery(monkeypatch):
    async def discover(config):
        return {
            **config,
            "name": "Reader",
            "warning": None,
            "shelves": [
                {"external_id": "to-read", "name": "Want to read", "count": 1},
                {"external_id": "fantasy", "name": "Fantasy", "count": 0},
            ],
        }

    monkeypatch.setattr(goodreads_profile, "discover", discover)


async def connect(client):
    response = await client.put(
        "/api/reading-accounts/goodreads",
        json={
            "profile": "https://www.goodreads.com/review/list_rss/123?key=private-secret&shelf=to-read"
        },
    )
    assert response.status_code == 200, response.text
    assert "private-secret" not in response.text
    return response.json()


async def test_connect_follow_refresh_pause_and_account_isolation(
    client, database, admin, discovery, monkeypatch
):
    assert (await client.get("/api/reading-accounts/goodreads")).json() is None
    account = await connect(client)
    assert account["user_id"] == "123" and len(account["shelves"]) == 2
    async with database() as db:
        assert (
            "private-secret"
            not in (await db.get(GoodreadsAccount, UUID(admin["id"]))).encrypted_config
        )
    invalid = await client.post(
        "/api/reading-accounts/follow", json={"provider": "goodreads", "external_id": "unknown"}
    )
    assert invalid.status_code == 422
    body = {"provider": "goodreads", "external_id": "to-read"}
    response = await client.post("/api/reading-accounts/follow", json=body)
    assert response.status_code == 200, response.text
    list_id = response.json()["list_id"]
    again = await client.post("/api/reading-accounts/follow", json=body)
    assert again.json() == {"list_id": list_id, "reused": True}
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(BookList)) == 1
        operation = await db.scalar(select(Operation).where(Operation.kind == "lists.sync"))
        assert operation.status == "queued"
    calls = []

    async def fetch(url, **kwargs):
        calls.append(url)
        return FeedResult([{"external_id": "42", "title": "Book", "authors": []}])

    monkeypatch.setattr(list_subscriptions, "fetch_feed", fetch)
    await list_subscriptions.run(operation.id)
    row = (await client.get("/api/reading-accounts/subscriptions")).json()[0]
    assert row["subscription"]["interval_minutes"] == 60
    assert row["subscription"]["observed_count"] == 1
    assert "key=private-secret" in calls[0]
    due = datetime.fromisoformat(row["subscription"]["next_sync_at"])
    assert (
        datetime.now(UTC) + timedelta(minutes=59) < due < datetime.now(UTC) + timedelta(minutes=64)
    )
    paused = await client.put(
        f"/api/lists/{list_id}/subscription",
        json={
            "enabled": False,
            "expected_generation": row["subscription"]["generation"],
            "interval_minutes": 60,
        },
    )
    assert paused.status_code == 200
    await list_subscriptions.schedule()
    assert (await client.get(f"/api/lists/{list_id}")).json()["count"] == 1
    row = (await client.get("/api/reading-accounts/subscriptions")).json()[0]
    assert not row["subscription"]["enabled"] and row["subscription"]["next_sync_at"] is None
    # A separate member cannot see the linked profile or its imported list.
    async with aclosing(await member(database)) as other:
        assert (await other.get("/api/reading-accounts/goodreads")).json() is None
        assert (await other.get("/api/reading-accounts/subscriptions")).json() == []
    assert (await client.post("/api/reading-accounts/goodreads/discover")).status_code == 200


async def test_failed_discovery_preserves_connection(client, admin, discovery, monkeypatch):
    from app.adapters.contracts import AdapterError, FailureKind

    await connect(client)

    async def fail(config):
        raise AdapterError(FailureKind.AUTHENTICATION, "Feed unavailable")

    monkeypatch.setattr(goodreads_profile, "discover", fail)
    response = await client.put("/api/reading-accounts/goodreads", json={"profile": "456"})
    assert response.status_code == 409
    assert (await client.get("/api/reading-accounts/goodreads")).json()["user_id"] == "123"


async def test_hardcover_private_list_uses_saved_token_and_reuses_subscription(
    client, database, admin, monkeypatch
):
    response = await client.put(
        "/api/metadata/account", json={"token": "saved-token", "enabled": True}
    )
    assert response.status_code == 200

    async def page(self, external_id, cursor=0):
        return ListPage({"name": "Private favorites", "external_id": external_id}, [], 0)

    monkeypatch.setattr(Hardcover, "list_page", page)
    body = {"provider": "hardcover", "external_id": "42"}
    response = await client.post("/api/reading-accounts/follow", json=body)
    assert response.status_code == 200, response.text
    assert not response.json()["reused"]
    response = await client.post("/api/reading-accounts/follow", json=body)
    assert response.status_code == 200 and response.json()["reused"]
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(ListSubscription)) == 1
    row = (await client.get("/api/reading-accounts/subscriptions")).json()[0]
    assert row["name"] == "Private favorites" and row["external_id"] == "42"


async def test_discovery_requires_member_and_csrf(client, admin, discovery):
    csrf = client.headers.pop("X-CSRF-Token")
    response = await client.put("/api/reading-accounts/goodreads", json={"profile": "123"})
    assert response.status_code == 403
    client.headers["X-CSRF-Token"] = csrf
    created = await client.post(
        "/api/auth/users",
        json={
            "username": "readonly",
            "display_name": "Viewer",
            "role": "viewer",
            "password": "separate viewer password",
        },
    )
    assert created.status_code == 201
    await client.post("/api/auth/logout")
    signed_in = await client.post(
        "/api/auth/login",
        json={
            "username": "readonly",
            "password": "separate viewer password",
        },
    )
    client.headers["X-CSRF-Token"] = signed_in.json()["csrf_token"]
    for path in ["goodreads", "subscriptions"]:
        assert (await client.get(f"/api/reading-accounts/{path}")).status_code == 403
    assert (
        await client.put("/api/reading-accounts/goodreads", json={"profile": "123"})
    ).status_code == 403
