from contextlib import aclosing
from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.adapters.contracts import AdapterError, FailureKind
from app.adapters.storygraph import ListResult
from app.db.models import (
    ListEntry,
    ListObservation,
    ListSubscription,
    Operation,
    StorygraphAccount,
)
from app.domain import list_subscriptions, storygraph_subscriptions
from app.security import decrypt_secrets
from tests.integration.test_list_subscriptions import member

pytestmark = pytest.mark.integration

HARBOR = "f3158a48-cb26-4887-a8df-9b8cae6cc377"
QUEUE = "11111111-1111-4111-8111-111111111111"
TAG = "9d7e824e-e4d8-40b1-8fef-6d6b5a6a44ba"
SESSION = "session-token"
REMEMBER = "remember-token"
TAG_URL = f"https://app.thestorygraph.com/tags/{TAG}"
SHELF_URL = "https://app.thestorygraph.com/to-read/nadia"


@pytest.fixture
async def storygraph(monkeypatch):
    state = {"hold": False, "shelf_pass": 0, "username": "nadia"}

    async def discover(secret, **_kwargs):
        return {
            "session_cookie": secret["session_cookie"],
            "remember_token": secret["remember_token"],
            "username": state["username"],
            "shelves": [
                {"external_id": "to-read", "name": "To-read", "count": None, "kind": "shelf"},
                {"external_id": TAG, "name": "Summer", "count": None, "kind": "tag"},
            ],
        }

    async def read_list(_cookies, target, session_out=None, **_kwargs):
        if state["hold"]:
            if session_out is not None:
                session_out["session_cookie"] = "held-rotation"
            raise AdapterError(
                FailureKind.AUTHENTICATION,
                "StoryGraph blocked this check. Existing books are preserved",
            )
        if target.kind == "tag":
            return ListResult(
                [{"external_id": TAG, "title": "Tagged", "authors": ["Ada"]}],
                False,
                None,
                "Summer",
            )
        state["shelf_pass"] += 1
        books = [{"external_id": HARBOR, "title": "Harbor", "authors": ["Ada"]}]
        if state["shelf_pass"] > 1:
            books.append({"external_id": QUEUE, "title": "Queue", "authors": ["Grace"]})
        return ListResult(books, False, "rotated-token", "To-read")

    async def ready(*_args, **_kwargs):
        return 0

    monkeypatch.setattr("app.adapters.storygraph.discover", discover)
    monkeypatch.setattr("app.adapters.storygraph.read_list", read_list)
    monkeypatch.setattr(storygraph_subscriptions, "read_list", read_list)
    monkeypatch.setattr(storygraph_subscriptions, "storygraph_budget", ready)
    return state


async def connect(client):
    response = await client.put(
        "/api/reading-accounts/storygraph",
        json={"session_cookie": SESSION, "remember_token": REMEMBER},
    )
    assert response.status_code == 200, response.text
    assert SESSION not in response.text
    assert REMEMBER not in response.text
    return response.json()


async def run_sync(client, database, list_id, key):
    response = await client.post(
        f"/api/lists/{list_id}/subscription/sync", headers={"Idempotency-Key": key}
    )
    assert response.status_code == 202, response.text
    await list_subscriptions.run(UUID(response.json()["id"]))


async def observed(database):
    async with database() as db:
        return set(await db.scalars(select(ListObservation.external_id)))


async def test_fetch_lock_is_exclusive(database):
    from app.domain.storygraph_subscriptions import fetch_lock

    user_id = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    async with fetch_lock(user_id):
        async with fetch_lock(user_id, wait=False) as acquired:
            assert acquired is False


async def test_refresh_retargets_shelves_after_a_rename(client, database, admin, storygraph):
    await connect(client)
    followed = await client.post(
        "/api/reading-accounts/follow", json={"provider": "storygraph", "external_id": "to-read"}
    )
    assert followed.status_code == 200, followed.text
    storygraph["username"] = "nadia-new"
    refreshed = await client.post("/api/reading-accounts/storygraph/discover")
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["username"] == "nadia-new"
    async with database() as db:
        saved = decrypt_secrets(
            (
                await db.scalar(
                    select(ListSubscription).where(ListSubscription.provider == "storygraph")
                )
            ).encrypted_config
        )
    assert saved["username"] == "nadia-new"


async def test_refresh_waits_when_storygraph_is_limited(client, admin, storygraph, monkeypatch):
    await connect(client)

    async def waiting(*_args, **_kwargs):
        return 30

    monkeypatch.setattr(storygraph_subscriptions, "storygraph_budget", waiting)
    refreshed = await client.post("/api/reading-accounts/storygraph/discover")
    assert refreshed.status_code == 429, refreshed.text


async def test_in_flight_budget_shrinks_after_the_read(database):
    from app.domain.list_subscriptions import storygraph_budget

    user_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    async with database() as db, db.begin():
        assert await storygraph_budget(db, user_id) == 0
        await storygraph_budget(db, user_id, block=20 * 32)
    async with database() as db, db.begin():
        assert await storygraph_budget(db, user_id) > 5
        await storygraph_budget(db, user_id, block=2, replace=True)
    async with database() as db, db.begin():
        wait = await storygraph_budget(db, user_id)
    assert 0 < wait <= 3


async def test_follow_sync_paste_challenge_and_isolation(client, database, admin, storygraph):
    assert (await client.get("/api/reading-accounts/storygraph")).json() is None
    account = await connect(client)
    assert account["username"] == "nadia"
    assert [shelf["external_id"] for shelf in account["shelves"]] == ["to-read", TAG]
    assert "session_cookie" not in account
    async with database() as db:
        stored = (await db.get(StorygraphAccount, UUID(admin["id"]))).encrypted_config
    assert SESSION not in stored and REMEMBER not in stored

    followed = await client.post(
        "/api/reading-accounts/follow", json={"provider": "storygraph", "external_id": "to-read"}
    )
    assert followed.status_code == 200, followed.text
    list_id = followed.json()["list_id"]
    again = await client.post(
        "/api/reading-accounts/follow", json={"provider": "storygraph", "external_id": "to-read"}
    )
    assert again.json() == {"list_id": list_id, "reused": True}
    async with database() as db:
        operation = await db.scalar(select(Operation).where(Operation.kind == "lists.sync"))
    await list_subscriptions.run(operation.id)
    assert await observed(database) == {HARBOR}

    await run_sync(client, database, list_id, "storygraph-add-book")
    assert await observed(database) == {HARBOR, QUEUE}
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(ListEntry)) == 2
        account = await db.get(StorygraphAccount, UUID(admin["id"]))
        saved = decrypt_secrets(account.encrypted_config)
    assert saved["session_cookie"] == "rotated-token"
    row = (await client.get("/api/reading-accounts/subscriptions")).json()[0]
    assert row["subscription"]["provider"] == "storygraph"
    assert "rotated-token" not in str(row)
    assert "Books left off a later check stay on this list." in row["subscription"]["message"]
    paused = await client.put(
        f"/api/lists/{list_id}/subscription",
        json={
            "provider": "storygraph",
            "enabled": False,
            "interval_minutes": 120,
            "expected_generation": row["subscription"]["generation"],
        },
    )
    assert paused.status_code == 200, paused.text
    assert paused.json()["enabled"] is False and paused.json()["interval_minutes"] == 120
    row["subscription"]["generation"] = paused.json()["generation"]

    preview = await client.post("/api/discovery/personal-list/preview", json={"url": TAG_URL})
    assert preview.status_code == 200, preview.text
    assert preview.json()["name"] == "Summer" and preview.json()["count"] == 1
    created = await client.post("/api/discovery/personal-list", json={"url": TAG_URL})
    assert created.status_code == 200, created.text
    tag_id = created.json()["list_id"]
    repeated = await client.post("/api/discovery/personal-list", json={"url": TAG_URL})
    assert repeated.json()["list_id"] == tag_id
    same_shelf = await client.post("/api/discovery/personal-list", json={"url": SHELF_URL})
    assert same_shelf.json()["list_id"] == list_id
    rejected = await client.put(
        f"/api/lists/{list_id}/subscription",
        json={
            "provider": "storygraph",
            "feed_url": SHELF_URL,
            "enabled": True,
            "interval_minutes": 60,
            "expected_generation": row["subscription"]["generation"],
        },
    )
    assert rejected.status_code == 422

    async with aclosing(await member(database)) as other:
        assert (await other.get("/api/reading-accounts/storygraph")).json() is None
        assert (await other.get("/api/reading-accounts/subscriptions")).json() == []
        assert (await other.get(f"/api/lists/{list_id}")).status_code == 404
        denied = await other.post("/api/discovery/personal-list/preview", json={"url": TAG_URL})
        assert denied.status_code == 409

    resumed = await client.put(
        f"/api/lists/{list_id}/subscription",
        json={
            "provider": "storygraph",
            "enabled": True,
            "interval_minutes": 60,
            "expected_generation": row["subscription"]["generation"],
        },
    )
    assert resumed.status_code == 200, resumed.text
    storygraph["hold"] = True
    await run_sync(client, database, list_id, "storygraph-held-check")
    assert await observed(database) == {HARBOR, QUEUE}
    held = (await client.get(f"/api/lists/{list_id}/subscription")).json()
    assert held["state"] == "failed"
    assert "preserved" in held["message"]
    async with database() as db:
        saved = decrypt_secrets(
            (await db.get(StorygraphAccount, UUID(admin["id"]))).encrypted_config
        )
    assert saved["session_cookie"] == "held-rotation"
    assert "held-rotation" not in (await client.get("/api/reading-accounts/storygraph")).text

    assert (await client.delete("/api/reading-accounts/storygraph")).status_code == 204
    assert (await client.get("/api/reading-accounts/storygraph")).json() is None
    storygraph["hold"] = False
    await run_sync(client, database, list_id, "storygraph-reconnect-check")
    assert await observed(database) == {HARBOR, QUEUE}
    waiting = (await client.get(f"/api/lists/{list_id}/subscription")).json()
    assert "Reconnect StoryGraph" in waiting["message"]
