# ruff: noqa: F811
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select, text

from app.adapters.contracts import AdapterError, FailureKind
from app.adapters.hardcover_lists import ListPage
from app.db.models import (
    CatalogAccount,
    ListObservation,
    ListSubscription,
    Operation,
    Work,
)
from app.domain import hardcover_subscriptions as hardcover
from app.domain import list_subscriptions as shelves
from app.jobs.retry import ShelfRetry
from app.security import encrypt_secrets
from tests.integration.test_acquisition import catalog  # noqa: F401
from tests.integration.test_correction_migration import migrate

pytestmark = pytest.mark.integration


@pytest.fixture
async def service(monkeypatch):
    class Service:
        items = [
            {
                "entry_id": 1,
                "external_id": "42",
                "title": "Harbor",
                "authors": ["Writer"],
                "isbn": None,
                "isbn13": None,
                "edition_id": None,
                "position": 1,
                "date_added": None,
            },
            {
                "entry_id": 2,
                "external_id": "43",
                "title": "Second Book",
                "authors": ["Writer"],
                "isbn": None,
                "isbn13": None,
                "edition_id": "123",
                "position": 2,
                "date_added": None,
            },
        ]
        calls = []
        callback = None
        error = None

        async def page(self, owner, generation, token, external_id, cursor):
            self.calls.append((owner, generation, token, external_id, cursor))
            if self.callback:
                await self.callback()
            if self.error:
                raise self.error
            return ListPage(
                {
                    "external_id": "9",
                    "name": "Hardcover shelf",
                    "count": len(self.items),
                    "updated_at": "2026-09-18T00:00:00+00:00",
                    "public": False,
                    "owner_id": "7",
                },
                [r for r in self.items if r["entry_id"] > cursor][:1],
                min((r["entry_id"] for r in self.items if r["entry_id"] > cursor), default=cursor),
            )

    service = Service()
    monkeypatch.setattr(hardcover, "fetch_page", service.page)
    return service


@pytest.fixture
async def shelf(client, database, admin):
    async with database() as db, db.begin():
        db.add(
            CatalogAccount(
                user_id=UUID(admin["id"]),
                encrypted_token=encrypt_secrets({"token": "private-hardcover-token"}),
                generation=1,
                enabled=True,
            )
        )
    shelf = (await client.post("/api/lists", json={"name": "Followed Hardcover"})).json()["id"]
    response = await client.put(
        f"/api/lists/{shelf}/subscription", json={"provider": "hardcover", "hardcover_list_id": 9}
    )
    assert response.status_code == 200, response.text
    return shelf


async def start(client, shelf, key="hardcover-observe"):
    response = await client.post(
        f"/api/lists/{shelf}/subscription/sync", headers={"Idempotency-Key": key}
    )
    assert response.status_code == 202, response.text
    return UUID(response.json()["id"])


async def finish(operation):
    for _ in range(20):
        try:
            await shelves.run(operation)
        except ShelfRetry:
            continue
        return
    raise AssertionError("List observation did not finish")


async def test_staged_two_pass_observation_matches_library_without_inventing_editions(
    client, database, shelf, service, catalog
):
    operation = await start(client, shelf)
    with pytest.raises(ShelfRetry):
        await shelves.run(operation)
    assert (await client.get(f"/api/lists/{shelf}")).json()["count"] == 0
    async with database() as db:
        assert (await db.get(Operation, operation)).payload["stage"]["cursor"] == 1
        assert await db.scalar(select(func.count()).select_from(ListObservation)) == 0
    await finish(operation)
    result = (await client.get(f"/api/lists/{shelf}")).json()
    assert result["count"] == 2
    assert next(r for r in result["items"] if r["title"] == "Harbor")["availability"]["owned"]
    settings = (await client.get(f"/api/lists/{shelf}/subscription")).json()
    assert (
        settings["provider"] == "hardcover" and settings["completeness"] == "verified-observation"
    )
    assert settings["present_count"] == 2 and settings["baseline_at"]
    assert "private-hardcover-token" not in str(settings)
    assert [call[-1] for call in service.calls] == [0, 1, 2, 0, 1, 2]
    assert all(call[2] == "private-hardcover-token" for call in service.calls)
    count = len(service.calls)
    await shelves.run(operation)
    assert len(service.calls) == count
    async with database() as db:
        assert "stage" not in (await db.get(Operation, operation)).payload


async def test_verified_removal_preserves_local_membership_and_exclusions_on_reappearance(
    client, database, shelf, service
):
    await finish(await start(client, shelf))
    records = (await client.get(f"/api/lists/{shelf}/subscription/observations")).json()["items"]
    first = next(r for r in records if r["external_id"] == "42")
    second = next(r for r in records if r["external_id"] == "43")
    await client.post(f"/api/lists/{shelf}/entries", json={"work_id": first["work_id"]})
    service.items = []
    await finish(await start(client, shelf, "empty-hardcover-list"))
    result = (await client.get(f"/api/lists/{shelf}")).json()
    assert result["count"] == 1 and result["items"][0]["id"] == first["work_id"]
    records = (await client.get(f"/api/lists/{shelf}/subscription/observations")).json()["items"]
    assert all(not r["present"] for r in records)
    await client.patch(
        f"/api/lists/{shelf}/subscription/observations/{second['id']}", json={"excluded": True}
    )
    service.items = [
        {
            "entry_id": 3,
            "external_id": "43",
            "title": "Second Book",
            "authors": ["Writer"],
            "isbn": None,
            "isbn13": None,
            "edition_id": None,
            "position": 1,
            "date_added": None,
        }
    ]
    await finish(await start(client, shelf, "reappeared-hardcover"))
    assert (await client.get(f"/api/lists/{shelf}")).json()["count"] == 1
    await client.patch(
        f"/api/lists/{shelf}/subscription/observations/{second['id']}", json={"excluded": False}
    )
    assert (await client.get(f"/api/lists/{shelf}")).json()["count"] == 2


async def test_changed_second_pass_and_provider_outage_preserve_last_baseline(
    client, database, shelf, service
):
    await finish(await start(client, shelf))
    original = (await client.get(f"/api/lists/{shelf}/subscription")).json()["baseline_at"]
    operation = await start(client, shelf, "changed-hardcover")
    for _ in range(3):
        with pytest.raises(ShelfRetry):
            await shelves.run(operation)
    service.items = [{**r, "title": "Changed after first pass"} for r in service.items]
    await finish(operation)
    async with database() as db:
        assert (await db.get(Operation, operation)).status == "failed"
    assert (await client.get(f"/api/lists/{shelf}")).json()["count"] == 2
    assert (await client.get(f"/api/lists/{shelf}/subscription")).json()["baseline_at"] == original
    service.error = AdapterError(FailureKind.PERMISSION, "Private list no longer available")
    await finish(await start(client, shelf, "outage-hardcover"))
    assert (await client.get(f"/api/lists/{shelf}")).json()["count"] == 2


async def test_credential_rotation_during_page_cannot_publish_or_continue_old_scope(
    client, database, shelf, service, admin
):
    async def rotate():
        async with database() as db, db.begin():
            account = await db.get(CatalogAccount, UUID(admin["id"]))
            account.generation += 1

    service.callback = rotate
    operation = await start(client, shelf)
    await shelves.run(operation)
    async with database() as db:
        assert (await db.get(Operation, operation)).status == "failed"
        assert await db.scalar(select(func.count()).select_from(Work)) == 0


async def test_cooldown_retains_cursor_and_expired_partial_pass_restarts(
    client, database, shelf, service
):
    operation = await start(client, shelf)
    with pytest.raises(ShelfRetry):
        await shelves.run(operation)
    service.error = AdapterError(
        FailureKind.RATE_LIMIT, "Hardcover is cooling down", retry_after=3600
    )
    with pytest.raises(ShelfRetry) as delay:
        await shelves.run(operation)
    assert delay.value.retry_after == 3600
    async with database() as db, db.begin():
        row = await db.get(Operation, operation)
        assert row.payload["stage"]["cursor"] == 1
        row.payload = {
            **row.payload,
            "stage": {
                **row.payload["stage"],
                "started_at": (datetime.now(UTC) - timedelta(minutes=20)).isoformat(),
            },
        }
    service.error = None
    with pytest.raises(ShelfRetry):
        await shelves.run(operation)
    assert service.calls[-1][-1] == 0
    await finish(operation)


async def test_provider_and_target_switches_and_downgrade_are_guarded(client, database, shelf):
    for body in [
        {"provider": "goodreads", "expected_generation": 1},
        {"hardcover_list_id": 10, "expected_generation": 1},
    ]:
        response = await client.put(f"/api/lists/{shelf}/subscription", json=body)
        assert response.status_code == 422
    async with database() as db:
        before = await db.scalar(text("SELECT version_num FROM alembic_version"))
    response = await migrate("downgrade", "0026_list_csv")
    assert response.returncode != 0 and "pre-upgrade backup" in response.stderr
    async with database() as db:
        assert await db.scalar(text("SELECT version_num FROM alembic_version")) == before


async def test_disabled_hardcover_does_not_block_other_due_lists_and_can_be_paused(
    client, database, shelf, admin
):
    from tests.unit.test_goodreads import URL

    other = (await client.post("/api/lists", json={"name": "Independent RSS"})).json()["id"]
    await client.put(f"/api/lists/{other}/subscription", json={"feed_url": URL})
    async with database() as db, db.begin():
        (await db.get(CatalogAccount, UUID(admin["id"]))).enabled = False
    await shelves.schedule()
    async with database() as db:
        current = await db.scalar(
            select(ListSubscription).where(ListSubscription.list_id == UUID(shelf))
        )
        independent = await db.scalar(
            select(ListSubscription).where(ListSubscription.list_id == UUID(other))
        )
        assert current.state == "failed" and independent.state == "queued"
    result = await client.put(
        f"/api/lists/{shelf}/subscription", json={"enabled": False, "expected_generation": 1}
    )
    assert result.status_code == 200 and result.json()["state"] == "paused"


async def test_pause_during_fetch_and_historical_completion_survive_later_settings(
    client, database, shelf, service
):
    async def pause():
        result = await client.put(
            f"/api/lists/{shelf}/subscription", json={"enabled": False, "expected_generation": 1}
        )
        assert result.status_code == 200

    service.callback = pause
    operation = await start(client, shelf)
    await shelves.run(operation)
    assert (await client.get(f"/api/lists/{shelf}")).json()["count"] == 0
    service.callback = None
    await client.put(
        f"/api/lists/{shelf}/subscription", json={"enabled": True, "expected_generation": 2}
    )
    completed = await start(client, shelf, "resumed-hardcover")
    await finish(completed)
    await client.put(
        f"/api/lists/{shelf}/subscription", json={"enabled": False, "expected_generation": 3}
    )
    await shelves.run(completed)
    async with database() as db:
        assert (await db.get(Operation, completed)).status == "completed"


async def test_numeric_ids_do_not_collide_across_hardcover_goodreads_and_csv(
    client, database, shelf, service, monkeypatch
):
    from app.adapters.goodreads import FeedResult
    from tests.unit.test_csv_parser import fixture
    from tests.unit.test_goodreads import URL

    await finish(await start(client, shelf))
    other = (await client.post("/api/lists", json={"name": "Other provider"})).json()["id"]
    await client.put(f"/api/lists/{other}/subscription", json={"feed_url": URL})

    async def feed(*args, **kwargs):
        return FeedResult(
            [
                {
                    "external_id": "42",
                    "title": "Different Goodreads Book",
                    "authors": ["Other Writer"],
                    "isbn": None,
                    "isbn13": None,
                }
            ]
        )

    monkeypatch.setattr(shelves, "fetch_feed", feed)
    await shelves.run(await start(client, other, "rss-collision-check"))
    work = (await client.get(f"/api/lists/{other}")).json()["items"][0]
    assert work["title"] == "Different Goodreads Book"
    response = await client.post(
        f"/api/lists/{other}/csv/preview",
        content=fixture([["42", "Different Goodreads Book", "Other Writer", "", ""]]),
    )
    assert response.status_code == 200
    assert response.json()["records"][0]["work_id"] == work["id"]


async def test_live_list_gateway_never_uses_cached_snapshot_on_outage(database, monkeypatch):
    import httpx

    from app.db.models import ProviderCache
    from app.domain.catalog_network import CatalogGateway

    async def no_wait(self):
        pass

    monkeypatch.setattr(CatalogGateway, "reserve", no_wait)
    async with CatalogGateway(
        "hardcover",
        "owner-a",
        "credential-a",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"data": {"lists": [{"private": "old membership"}]}}
            )
        ),
    ) as gateway:
        await gateway.request("POST", "v1/graphql", json={"query": "same-list-query"})
        cache_key = gateway.used_keys[0]
    async with CatalogGateway(
        "hardcover",
        "owner-a",
        "credential-a",
        cache=False,
        transport=httpx.MockTransport(lambda request: httpx.Response(503)),
    ) as gateway:
        with pytest.raises(AdapterError):
            await gateway.request("POST", "v1/graphql", json={"query": "same-list-query"})
        assert not gateway.stale
    async with CatalogGateway(
        "hardcover",
        "owner-b",
        "credential-b",
        cache=False,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"data": {"lists": []}})
        ),
    ) as gateway:
        await gateway.request("POST", "v1/graphql", json={"query": "same-list-query"})
        async with database() as db:
            assert await db.get(ProviderCache, gateway.used_keys[0]) is None
            assert await db.get(ProviderCache, cache_key)


async def test_full_catalog_import_enriches_followed_book_without_duplicate_or_privacy_promotion(
    client, database, shelf, service, admin
):
    from app.adapters.catalog_types import BookData
    from app.db.models import User
    from app.domain.catalog_metadata import import_book

    await finish(await start(client, shelf))
    before = (await client.get(f"/api/lists/{shelf}")).json()["items"]
    target = next(w for w in before if w["title"] == "Harbor")
    async with database() as db, db.begin():
        owner = await db.get(User, UUID(admin["id"]))
        work = await import_book(
            db,
            owner,
            BookData(
                provider="hardcover",
                external_id="42",
                title="Harbor",
                authors=["Writer"],
                description="Confirmed catalog description",
            ),
        )
        assert str(work.id) == target["id"] and not work.catalog_public
        assert work.description == "Confirmed catalog description"
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(Work)) == 2


async def test_catalog_import_and_final_list_publication_serialize_identity_creation(
    client, database, shelf, service, admin
):
    import asyncio

    from app.adapters.catalog_types import BookData
    from app.db.models import User
    from app.domain.catalog_metadata import import_book

    service.items = service.items[:1]
    operation = await start(client, shelf)
    for _ in range(3):
        with pytest.raises(ShelfRetry):
            await shelves.run(operation)

    async def add_metadata():
        async with database() as db, db.begin():
            owner = await db.get(User, UUID(admin["id"]))
            await import_book(
                db,
                owner,
                BookData(
                    provider="hardcover", external_id="42", title="Harbor", authors=["Writer"]
                ),
            )

    await asyncio.gather(finish(operation), add_metadata())
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(Work)) == 1


async def test_second_member_uses_own_credentials_and_private_catalog_bindings(
    client, database, shelf, service, admin
):
    from contextlib import aclosing

    from tests.integration.test_list_subscriptions import member

    await finish(await start(client, shelf))
    admin_work = (await client.get(f"/api/lists/{shelf}")).json()["items"][0]["id"]
    async with aclosing(await member(database, "hardcover-member")) as other:
        me = (await other.get("/api/auth/me")).json()["user"]
        assert (
            await other.put("/api/metadata/account", json={"token": "separate-private-token"})
        ).status_code == 200
        target = (await other.post("/api/lists", json={"name": "Private member HC"})).json()["id"]
        response = await other.put(
            f"/api/lists/{target}/subscription",
            json={"provider": "hardcover", "hardcover_list_id": 9},
        )
        assert response.status_code == 200, response.text
        await finish(await start(other, target, "member-hc-observation"))
        assert (
            service.calls[-1][0] == UUID(me["id"])
            and service.calls[-1][2] == "separate-private-token"
        )
        assert (await other.get(f"/api/lists/{shelf}/subscription")).status_code == 404
        assert all(
            w["id"] != admin_work for w in (await other.get(f"/api/lists/{target}")).json()["items"]
        )


async def wait_for_database_blocker(db, pid):
    import asyncio

    async with asyncio.timeout(3):
        # PostgreSQL lock waits have no asyncio event; poll the actual blocker.
        while not await db.scalar(  # noqa: ASYNC110
            text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": pid}
        ):
            await asyncio.sleep(0.01)


async def test_account_save_audit_does_not_deadlock_waiting_subscription(
    client, database, shelf, admin
):
    import asyncio

    from app.api.metadata import AccountInput, save_account
    from app.db.models import User
    from app.domain.operations import transaction_lock

    operation = await start(client, shelf)
    async with database() as account_db, database() as observer_db:
        owner = await account_db.get(User, UUID(admin["id"]))
        await transaction_lock(account_db, f"catalog-account:{owner.id}")
        pid = await observer_db.scalar(text("SELECT pg_backend_pid()"))
        observation = asyncio.create_task(shelves.context(observer_db, operation))
        try:
            await wait_for_database_blocker(account_db, pid)
            async with asyncio.timeout(3):
                await save_account(AccountInput(enabled=True), owner, account_db)
                assert await observation is None  # The saved generation fences the run.
        finally:
            observation.cancel()
            await asyncio.gather(observation, return_exceptions=True)
            await account_db.rollback()
            await observer_db.rollback()


async def test_catalog_import_waits_for_actor_before_list_identity_lock(database, admin):
    import asyncio

    from app.adapters.catalog_types import BookData
    from app.db.models import AuditEvent, User
    from app.domain.catalog_metadata import import_book
    from app.domain.operations import transaction_lock

    async with database() as list_db, database() as catalog_db:
        owner = await list_db.get(User, UUID(admin["id"]), with_for_update=True)
        importer = await catalog_db.get(User, owner.id)
        pid = await catalog_db.scalar(text("SELECT pg_backend_pid()"))

        async def import_and_audit():
            work = await import_book(
                catalog_db,
                importer,
                BookData(
                    provider="hardcover", external_id="42", title="Harbor", authors=["Writer"]
                ),
            )
            catalog_db.add(
                AuditEvent(actor_id=owner.id, action="metadata.book.imported", entity_id=work.id)
            )
            await catalog_db.commit()

        task = asyncio.create_task(import_and_audit())
        try:
            await wait_for_database_blocker(list_db, pid)
            async with asyncio.timeout(3):
                await transaction_lock(list_db, f"goodreads:catalog:{owner.id}")
                await list_db.commit()
                await task
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await list_db.rollback()
            await catalog_db.rollback()
