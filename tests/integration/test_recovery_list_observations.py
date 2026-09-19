# ruff: noqa: F811
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.adapters.goodreads import FeedResult
from app.db.models import ListObservation, ListSubscription, Operation, Work
from app.domain import recovery_observers as observers
from app.domain import recovery_scans as scans
from app.security import encrypt_secrets
from tests.integration.test_hardcover_subscriptions import (  # noqa: F401
    finish,
    service,
    shelf,
    start,
)
from tests.integration.test_recovery_scan_workflow import begin, pause, report

pytestmark = pytest.mark.integration


async def test_complete_hardcover_observation_preserves_membership_episodes_and_outbound_intent(
    client, admin, database, shelf, service
):
    await finish(await start(client, shelf))
    async with database() as db, db.begin():
        subscription = await db.scalar(
            select(ListSubscription).where(ListSubscription.list_id == UUID(shelf))
        )
        original = [
            (row.id, row.external_id, row.present)
            for row in await db.scalars(select(ListObservation))
        ]
        outbound = Operation(
            owner_id=UUID(admin["id"]),
            kind="lists.writeback",
            idempotency_key="saved-writeback",
            payload={
                "list_id": shelf,
                "book_id": 43,
                "desired": True,
                "pending_attempt": {"sent": True},
            },
            status="running",
        )
        db.add(outbound)
        await db.flush()
        outbound_id, subscription_id = outbound.id, subscription.id
    service.items = [
        service.items[1],
        {**service.items[0], "entry_id": 3, "external_id": "44", "title": "New after backup"},
    ]
    await pause(database, admin)
    identifier = await begin(client)
    await scans.run(UUID(identifier))
    result = await report(client, identifier, domain="lists")
    assert result["scan"]["state"] == "completed", result
    by_id = {
        row["evidence"].get("external_id"): row
        for row in result["items"]
        if row["evidence"].get("external_id")
    }
    assert by_id["42"]["state"] == "missing"
    assert by_id["44"]["state"] == "untracked"
    assert (
        next(row for row in result["items"] if row["entity_id"] == str(outbound_id))["state"]
        == "needs-review"
    )
    assert len(service.calls) >= 6
    async with database() as db:
        assert [
            (row.id, row.external_id, row.present)
            for row in await db.scalars(select(ListObservation))
        ] == original
        assert (await db.get(ListSubscription, subscription_id)).generation == 1
        assert (await db.get(Operation, outbound_id)).payload["pending_attempt"] == {"sent": True}
        assert (await db.get(Operation, outbound_id)).status == "running"


async def test_goodreads_feed_is_partial_and_never_proves_missing_membership(
    client, admin, database, monkeypatch
):
    shelf_id = (await client.post("/api/lists", json={"name": "RSS recovery"})).json()["id"]
    async with database() as db, db.begin():
        work = Work(title="Outside RSS window", authors=[])
        db.add(work)
        subscription = ListSubscription(
            list_id=UUID(shelf_id),
            provider="goodreads",
            encrypted_config=encrypt_secrets(
                {"url": "https://www.goodreads.com/review/list_rss/123?key=private-feed-key"}
            ),
        )
        db.add(subscription)
        await db.flush()
        db.add(
            ListObservation(
                subscription_id=subscription.id,
                external_id="42",
                snapshot={},
                work_id=work.id,
                last_seen_at=datetime.now(UTC),
            )
        )
    calls = []

    async def feed(url, **options):
        calls.append((url, options))
        return FeedResult(
            items=[
                {
                    "external_id": "43",
                    "title": "Visible addition",
                    "authors": [],
                    "isbn": None,
                    "isbn13": None,
                }
            ]
        )

    monkeypatch.setattr(observers, "fetch_feed", feed)
    await pause(database, admin)
    identifier = await begin(client)
    await scans.run(UUID(identifier))
    result = await report(client, identifier, domain="lists")
    assert result["scan"]["state"] == "completed", result
    assert {row["state"] for row in result["items"]} == {"partial", "untracked"}
    assert "private-feed-key" not in str(result)
    assert calls[0][1] == {}  # Force a fresh feed, not a stale 304 cache observation.
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(ListObservation)) == 1
        assert await db.scalar(select(ListObservation.present)) is True
