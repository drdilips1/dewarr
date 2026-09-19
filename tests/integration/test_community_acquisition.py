# ruff: noqa: F401, F811
"""Public list → followed subscription → new upstream member → real-file acquisition."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.db.models import DownloadAttempt, ListEntry, ListSubscription, Work, WorkMetadataSource
from app.jobs.queue import get_queue
from tests.integration.test_automatic_acquisition import (
    destination_route,
    ready_route,
    review_account,
)
from tests.integration.test_automatic_acquisition import (
    test_search_to_automatic_download_and_confirmed_member_library as acquire,
)
from tests.integration.test_community_lists import follow, provider
from tests.integration.test_metadata import connect

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("medium", ["ebook", "audio"])
async def test_follow_new_upstream_member_reaches_library_once(
    client, admin, database, ready_route, review_account, monkeypatch, provider, medium
):
    class Origin:
        shelf = None

        async def finish(self):
            for _ in range(5):
                await get_queue().run_worker_async(wait=False, concurrency=1)
                async with database() as db:
                    sub = await db.scalar(
                        select(ListSubscription).where(ListSubscription.list_id == UUID(self.shelf))
                    )
                    if sub.state == "idle" and sub.last_success_at:
                        return
                    assert sub.state != "failed", sub.message
                await asyncio.sleep(1.1)
            raise AssertionError("Community membership did not finish syncing")

        async def create(self, work_id):
            await connect(client)
            async with database() as db, db.begin():
                work = await db.get(Work, UUID(work_id))
                snapshot = {
                    "provider": "hardcover",
                    "external_id": "42",
                    "title": work.title,
                    "authors": work.authors,
                }
                db.add(
                    WorkMetadataSource(
                        work_id=work.id,
                        provider="hardcover",
                        external_id="42",
                        fetched_at=datetime.now(UTC),
                        snapshot=snapshot,
                    )
                )
                provider["records"][42] = {
                    "id": 42,
                    "title": work.title,
                    "cached_contributors": [{"author": {"name": name}} for name in work.authors],
                }
            provider["keys"], provider["count"] = [43], 1
            result = await follow(client)
            assert result.status_code == 200, result.text
            self.shelf = result.json()["list_id"]
            await self.finish()
            async with database() as db:
                assert await db.scalar(select(func.count()).select_from(DownloadAttempt)) == 0
            return self.shelf

        async def add(self, shelf, work_id):
            # The user adds the book upstream after future-only activation.
            provider["keys"], provider["count"] = [43, 42], 2
            await self.sync("community-new-upstream-member")
            async with database() as db:
                entry = await db.scalar(
                    select(ListEntry).where(
                        ListEntry.list_id == UUID(shelf), ListEntry.work_id == UUID(work_id)
                    )
                )
                assert entry and not entry.locally_added

        async def sync(self, key):
            response = await client.post(
                f"/api/lists/{self.shelf}/subscription/sync", headers={"Idempotency-Key": key}
            )
            assert response.status_code == 202, response.text
            await self.finish()

    origin = Origin()
    await acquire(
        client,
        admin,
        database,
        ready_route,
        review_account,
        monkeypatch,
        medium=medium,
        delayed_backend=True,
        request_limits=True,
        via_list=True,
        list_origin=origin,
    )
    await origin.sync("community-repeated-sync")
    again = await follow(client, "community-repeat-follow")
    assert again.status_code == 200 and again.json()["list_id"] == origin.shelf
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(DownloadAttempt)) == 1
        assert await db.scalar(select(func.count()).select_from(ListSubscription)) == 1
