# ruff: noqa: F811
from contextlib import aclosing
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest
from sqlalchemy import delete, func, select, text

from app.adapters.contracts import AdapterError, FailureKind
from app.adapters.goodreads import FeedResult
from app.db.models import (
    ListEntry,
    ListObservation,
    ListSubscription,
    Operation,
    RateLimit,
    User,
    Version,
    Work,
)
from app.domain import list_subscriptions as shelves
from app.jobs.retry import CatalogRetry
from app.main import create_app
from app.security import decrypt_secrets, hash_password
from tests.integration.test_acquisition import catalog  # noqa: F401
from tests.integration.test_correction_migration import migrate
from tests.unit.test_goodreads import URL

pytestmark = pytest.mark.integration


@pytest.fixture
async def shelf(client, admin):
    response = await client.post("/api/lists", json={"name": "Shelf additions"})
    identifier = response.json()["id"]
    response = await client.put(f"/api/lists/{identifier}/subscription", json={"feed_url": URL})
    assert response.status_code == 200, response.text
    return identifier


@pytest.fixture
async def feeds(monkeypatch):
    class Service:
        items = [
            {
                "external_id": "42",
                "title": "Harbor",
                "authors": ["Writer"],
                "isbn": None,
                "isbn13": None,
            }
        ]
        error = None
        calls = []
        unchanged = False
        callback = None

        async def fetch(self, url, **options):
            self.calls.append(options)
            if self.callback:
                await self.callback()
            if self.error:
                raise self.error
            return FeedResult(self.items, self.unchanged, '"shelf-v1"', None)

    service = Service()
    monkeypatch.setattr(shelves, "fetch_feed", service.fetch)
    return service


async def sync(client, database, shelf, key="observe-shelf-key"):
    async with database() as db, db.begin():
        await db.execute(delete(RateLimit).where(RateLimit.key == "goodreads:rss"))
    response = await client.post(
        f"/api/lists/{shelf}/subscription/sync", headers={"Idempotency-Key": key}
    )
    assert response.status_code == 202, response.text
    operation = UUID(response.json()["id"])
    await shelves.run(operation)
    return operation


async def member(database, name="member"):
    async with database() as db, db.begin():
        user = User(
            username=name,
            display_name=name,
            role="member",
            password_hash=hash_password("private member password"),
        )
        db.add(user)
        await db.flush()
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()),
        base_url="http://testserver",
        headers={"Origin": "http://testserver"},
    )
    response = await client.post(
        "/api/auth/login", json={"username": name, "password": "private member password"}
    )
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return client


async def test_observe_replay_conditional_sync_and_omissions_preserve_membership(
    client, database, shelf, feeds
):
    operation = await sync(client, database, shelf)
    await shelves.run(operation)
    assert len(feeds.calls) == 1
    page = (await client.get(f"/api/lists/{shelf}")).json()
    assert len(page["items"]) == 1 and page["items"][0]["provisional"]
    assert not page["items"][0]["availability"]["owned"]
    feeds.items = []
    await sync(client, database, shelf, "empty-feed-key")
    assert (await client.get(f"/api/lists/{shelf}")).json()["count"] == 1
    feeds.unchanged = True
    await sync(client, database, shelf, "unchanged-key")
    assert feeds.calls[-1]["etag"] == '"shelf-v1"'
    view = (await client.get(f"/api/lists/{shelf}/subscription")).json()
    assert view["baseline_at"] and view["completeness"] == "partial-feed"
    assert view["observed_count"] == 1 and view["acquisition_mode"] == "browse"
    assert "private-feed-key" not in str(view)
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(Work)) == 1
        row = await db.scalar(select(ListSubscription))
        assert URL not in row.encrypted_config
        assert decrypt_secrets(row.encrypted_config)["url"] == URL
        assert await db.scalar(select(func.count()).select_from(Version)) == 0
        assert await db.scalar(text("SELECT count(*) FROM acquisition_intents")) == 0


async def test_explicit_removal_is_a_durable_exclusion_and_can_be_restored(
    client, database, shelf, feeds
):
    await sync(client, database, shelf)
    work = (await client.get(f"/api/lists/{shelf}")).json()["items"][0]
    assert (await client.delete(f"/api/lists/{shelf}/entries/{work['id']}")).status_code == 204
    await sync(client, database, shelf, "after-exclusion")
    assert (await client.get(f"/api/lists/{shelf}")).json()["count"] == 0
    observation = (await client.get(f"/api/lists/{shelf}/subscription/observations")).json()[
        "items"
    ][0]
    assert observation["excluded"]
    result = await client.patch(
        f"/api/lists/{shelf}/subscription/observations/{observation['id']}",
        json={"excluded": False},
    )
    assert result.status_code == 204, result.text
    assert (await client.get(f"/api/lists/{shelf}")).json()["count"] == 1


async def test_private_source_catalog_shared_list_and_other_account_access(
    client, database, shelf, feeds
):
    await sync(client, database, shelf)
    async with aclosing(await member(database)) as other:
        assert (await other.get("/api/catalog/works")).json()["total"] == 0
        assert (await other.get(f"/api/lists/{shelf}/subscription")).status_code == 404
        assert (
            await client.patch(
                f"/api/lists/{shelf}", json={"name": "Shelf additions", "shared": True}
            )
        ).status_code == 200
        assert (await other.get(f"/api/lists/{shelf}")).json()["count"] == 1
        assert (await other.get("/api/catalog/works")).json()["total"] == 1
        assert (await other.get(f"/api/lists/{shelf}/subscription/observations")).status_code == 404
        assert (
            await client.patch(
                f"/api/lists/{shelf}", json={"name": "Shelf additions", "shared": False}
            )
        ).status_code == 200
        assert (await other.get("/api/catalog/works")).json()["total"] == 0


async def test_exact_isbn_title_and_author_reuse_without_inventing_versions(
    client, database, shelf, feeds
):
    work = (
        await client.post("/api/catalog/works", json={"title": "Harbor", "authors": ["Writer"]})
    ).json()
    async with database() as db, db.begin():
        db.add(
            Version(
                work_id=UUID(work["id"]), medium="ebook", identifiers={"isbn13": "9780306406157"}
            )
        )
    feeds.items[0] = {**feeds.items[0], "isbn": "9780306406157"}
    await sync(client, database, shelf)
    assert (await client.get(f"/api/lists/{shelf}")).json()["items"][0]["id"] == work["id"]
    feeds.items = [{**feeds.items[0], "external_id": "43", "authors": ["Different Writer"]}]
    await sync(client, database, shelf, "wrong-author-feed")
    assert (await client.get(f"/api/lists/{shelf}")).json()["count"] == 2
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(Version)) == 1


async def test_error_and_rate_limit_preserve_baseline_and_share_cooldown(
    client, database, shelf, feeds
):
    await sync(client, database, shelf)
    first = (await client.get(f"/api/lists/{shelf}/subscription")).json()["baseline_at"]
    feeds.error = AdapterError(FailureKind.RATE_LIMIT, "Source cooldown", retry_after=7200)
    failed_operation = await sync(client, database, shelf, "rate-limited-key")
    calls = len(feeds.calls)
    # A redelivered terminal job cannot bypass the persisted observation backoff.
    await shelves.run(failed_operation)
    assert len(feeds.calls) == calls
    row = (await client.get(f"/api/lists/{shelf}/subscription")).json()
    assert row["state"] == "failed" and row["baseline_at"] == first
    assert datetime.fromisoformat(row["next_sync_at"]) > datetime.now(UTC) + timedelta(hours=2)
    assert (await client.get(f"/api/lists/{shelf}")).json()["count"] == 1
    async with database() as db:
        assert (await db.get(RateLimit, "goodreads:rss")).resets_at > datetime.now(UTC) + timedelta(
            minutes=119
        )


async def test_settings_change_during_fetch_cannot_publish_old_results(
    client, database, shelf, feeds
):
    async def change():
        response = await client.put(
            f"/api/lists/{shelf}/subscription", json={"enabled": False, "expected_generation": 1}
        )
        assert response.status_code == 200, response.text

    feeds.callback = change
    await sync(client, database, shelf)
    assert (await client.get(f"/api/lists/{shelf}")).json()["count"] == 0
    row = (await client.get(f"/api/lists/{shelf}/subscription")).json()
    assert row["state"] == "paused" and row["baseline_at"] is None


async def test_detach_keeps_books_and_fences_inflight_worker(client, database, shelf, feeds):
    await sync(client, database, shelf)
    feeds.callback = lambda: client.delete(f"/api/lists/{shelf}/subscription")
    await sync(client, database, shelf, "detached-while-fetching")
    assert (await client.get(f"/api/lists/{shelf}")).json()["count"] == 1
    assert (await client.get(f"/api/lists/{shelf}/subscription")).json() is None
    async with database() as db:
        assert (await db.scalar(select(ListEntry))).locally_added
        assert await db.scalar(select(func.count()).select_from(ListObservation)) == 0


async def test_atomic_enqueue_idempotency_and_scheduler(
    client, database, shelf, feeds, monkeypatch
):
    real = shelves.enqueue

    async def fail(*args, **kwargs):
        await real(*args, **kwargs)
        raise RuntimeError("commit prevented")

    monkeypatch.setattr(shelves, "enqueue", fail)
    with pytest.raises(RuntimeError):
        await client.post(
            f"/api/lists/{shelf}/subscription/sync", headers={"Idempotency-Key": "rollback-shelf"}
        )
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(Operation)) == 0
        assert await db.scalar(text("SELECT count(*) FROM book_queue.procrastinate_jobs")) == 0
    monkeypatch.setattr(shelves, "enqueue", real)
    await shelves.schedule()
    await shelves.schedule()
    async with database() as db:
        op = await db.scalar(select(Operation))
        assert await db.scalar(select(func.count()).select_from(Operation)) == 1
    await shelves.run(op.id)
    await shelves.schedule()
    assert len(feeds.calls) == 1


async def test_live_lease_retries_and_exhausted_job_is_visible(client, database, shelf, feeds):
    response = await client.post(
        f"/api/lists/{shelf}/subscription/sync", headers={"Idempotency-Key": "lease-repair-key"}
    )
    op_id = UUID(response.json()["id"])
    async with database() as db, db.begin():
        row = await db.scalar(select(ListSubscription))
        row.run_token = op_id
        row.lease_until = datetime.now(UTC) + timedelta(minutes=1)
    with pytest.raises(CatalogRetry):
        await shelves.run(op_id)
    assert not feeds.calls
    async with database() as db, db.begin():
        op = await db.get(Operation, op_id)
        await db.execute(
            text("UPDATE book_queue.procrastinate_jobs SET status='failed' WHERE id=:id"),
            {"id": op.job_id},
        )
    response = await client.get(f"/api/lists/{shelf}/subscription")
    assert response.json()["state"] == "failed"


async def test_followed_books_show_existing_library_ownership(
    client, database, shelf, feeds, catalog
):
    async with database() as db, db.begin():
        version = await db.get(Version, catalog["versions"][0])
        version.identifiers = {"isbn13": "9780306406157"}
    feeds.items[0] = {**feeds.items[0], "isbn13": "9780306406157"}
    await sync(client, database, shelf)
    book = (await client.get(f"/api/lists/{shelf}")).json()["items"][0]
    assert book["id"] == str(catalog["work"])
    assert book["availability"]["owned"] and book["availability"]["ebook"]
    assert not book["availability"]["audio"]


async def test_manual_mapping_and_exclusion_keep_independent_local_membership(
    client, database, shelf, feeds
):
    existing = (
        await client.post(
            "/api/catalog/works", json={"title": "Catalog title", "authors": ["Writer"]}
        )
    ).json()
    await client.post(f"/api/lists/{shelf}/entries", json={"work_id": existing["id"]})
    await sync(client, database, shelf)
    record = (await client.get(f"/api/lists/{shelf}/subscription/observations")).json()["items"][0]
    route = f"/api/lists/{shelf}/subscription/observations/{record['id']}"
    assert (await client.patch(route, json={"work_id": existing["id"]})).status_code == 204
    assert (await client.get(f"/api/lists/{shelf}")).json()["count"] == 1
    assert (await client.patch(route, json={"excluded": True})).status_code == 204
    # Removing the source's reason must not remove a separately saved local entry.
    assert (await client.get(f"/api/lists/{shelf}")).json()["count"] == 1
    feeds.items = [{**feeds.items[0], "title": "Changed feed title"}]
    await sync(client, database, shelf, "changed-source-identity")
    record = (await client.get(f"/api/lists/{shelf}/subscription/observations")).json()["items"][0]
    assert record["identity_changed"] and record["catalog_title"] == "Catalog title"


async def test_new_member_catalog_is_visible_only_to_owner_and_revoked_link_is_redacted(
    client, database, admin, feeds
):
    async with aclosing(await member(database)) as other:
        target = (await other.post("/api/lists", json={"name": "Private member shelf"})).json()[
            "id"
        ]
        await other.put(f"/api/lists/{target}/subscription", json={"feed_url": URL})
        await sync(other, database, target)
        record = (await other.get(f"/api/lists/{target}/subscription/observations")).json()[
            "items"
        ][0]
        assert (await other.get(f"/api/catalog/works/{record['work_id']}")).status_code == 200
        async with database() as db, db.begin():
            work = await db.get(Work, UUID(record["work_id"]))
            work.catalog_owner_id = UUID(admin["id"])
            work.title = "Now inaccessible catalog text"
        record = (await other.get(f"/api/lists/{target}/subscription/observations")).json()[
            "items"
        ][0]
        assert record["work_id"] is None and record["catalog_title"] is None
        assert "Now inaccessible" not in str(record)


async def test_account_revoked_during_network_work_discards_observations(
    client, database, shelf, feeds, admin
):
    async def revoke():
        async with database() as db, db.begin():
            (await db.get(User, UUID(admin["id"]))).active = False

    feeds.callback = revoke
    operation = await sync(client, database, shelf)
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(ListObservation)) == 0
        assert (await db.get(Operation, operation)).status == "failed"


async def test_different_shelf_replacement_and_populated_downgrade_are_rejected(
    client, database, shelf
):
    replacement = await client.put(
        f"/api/lists/{shelf}/subscription",
        json={"feed_url": URL.replace("to-read", "read"), "expected_generation": 1},
    )
    assert replacement.status_code == 422
    stale = await client.put(f"/api/lists/{shelf}/subscription", json={"expected_generation": 0})
    assert stale.status_code == 409
    async with database() as db:
        before = await db.scalar(text("SELECT version_num FROM alembic_version"))
    result = await migrate("downgrade", "0024_book_sources")
    assert result.returncode != 0 and "pre-upgrade backup" in result.stderr
    async with database() as db:
        assert await db.scalar(text("SELECT version_num FROM alembic_version")) == before


async def test_budget_wait_persists_truthful_status_and_old_operation_eventually_expires(
    client, database, shelf, feeds
):
    from app.jobs.retry import ShelfRetry

    response = await client.post(
        f"/api/lists/{shelf}/subscription/sync", headers={"Idempotency-Key": "budget-wait-key"}
    )
    identifier = UUID(response.json()["id"])
    async with database() as db, db.begin():
        db.add(
            RateLimit(
                key="goodreads:rss", count=1, resets_at=datetime.now(UTC) + timedelta(seconds=4)
            )
        )
    with pytest.raises(ShelfRetry) as wait:
        await shelves.run(identifier)
    assert 1 <= wait.value.retry_after <= 5
    row = (await client.get(f"/api/lists/{shelf}/subscription")).json()
    assert row["state"] == "queued" and "request budget" in row["message"]
    assert not feeds.calls
    async with database() as db, db.begin():
        (await db.get(Operation, identifier)).created_at = datetime.now(UTC) - timedelta(days=8)
    await shelves.run(identifier)
    row = (await client.get(f"/api/lists/{shelf}/subscription")).json()
    assert row["state"] == "failed" and "expired" in row["message"]
    assert row["baseline_at"] is None
