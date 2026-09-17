import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest
from sqlalchemy import func, select, text

from app.adapters.catalog_types import BookData
from app.db.models import AuditEvent, Operation, User, Work, WorkMetadataSource
from app.domain import catalog_enrichment as enrichment
from app.domain.catalog_metadata import import_book
from app.domain.catalog_network import CatalogGateway
from app.jobs.queue import enqueue, get_queue

pytestmark = pytest.mark.integration


@pytest.fixture
def secondary(monkeypatch):
    state = {"calls": [], "count": 1, "wrong": False, "broken": False, "stale": False}

    async def respond(request):
        state["calls"].append(request.url.path)
        assert not request.headers.get("Authorization")
        if state.get("pause") and request.url.path == "/works/OL1W.json":
            state["entered"].set()
            await state["release"].wait()
        if state["broken"]:
            return httpx.Response(503, json={"message": "private-upstream-diagnostic"})
        if state.get("quota"):
            return httpx.Response(429, headers={"Retry-After": "3600"}, json={"error": "cooldown"})
        if request.url.path == "/search.json":
            assert 'title:"Harbor"' in request.url.params["q"]
            return httpx.Response(
                200,
                json={
                    "numFound": state["count"],
                    "docs": [
                        {"key": f"/works/OL{i + 1}W", "title": "Harbor", "author_name": ["Writer"]}
                        for i in range(min(state["count"], 20))
                    ],
                },
            )
        if request.url.path == "/works/OL1W.json":
            return httpx.Response(
                200,
                json={
                    "key": "/works/OL1W",
                    "title": "Wrong book" if state["wrong"] else "Harbor",
                    "authors": [{"author": {"key": "/authors/OL1A"}}],
                    "description": "Secondary description",
                    "first_publish_date": "2001",
                    "covers": [123],
                },
            )
        if request.url.path == "/authors/OL1A.json":
            return httpx.Response(200, json={"name": "Writer"})
        if request.url.path == "/works/OL1W/editions.json":
            return httpx.Response(200, json={"entries": []})
        raise AssertionError(request.url.path)

    class Gateway(CatalogGateway):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs, transport=httpx.MockTransport(respond))
            self.stale = state["stale"]

        async def reserve(self):
            pass  # Rate budgeting is separately tested; keep concurrency fixtures deterministic.

    monkeypatch.setattr(enrichment, "CatalogGateway", Gateway)
    return state


async def prepared(database, admin):
    async with database() as db, db.begin():
        user = await db.get(User, UUID(admin["id"]))
        book = BookData(
            provider="hardcover",
            external_id="42",
            title="Harbor",
            authors=["Writer"],
            description="Primary description",
        )
        work = await import_book(db, user, book)
        operation = await enrichment.schedule_enrichment(db, user, work)
        return work.id, operation.id


async def test_worker_enriches_missing_fields_once_preserving_primary_and_manual_fields(
    database, admin, client, secondary
):
    work_id, operation_id = await prepared(database, admin)
    response = await client.patch(
        f"/api/metadata/works/{work_id}", json={"values": {"publication_year": 1999}}
    )
    assert response.status_code == 200
    await asyncio.wait_for(get_queue().run_worker_async(wait=False, concurrency=1), timeout=15)
    async with database() as db:
        work = await db.get(Work, work_id)
        assert work.description == "Primary description"
        assert work.publication_year == 1999
        assert work.cover_url == "https://covers.openlibrary.org/b/id/123-L.jpg"
        assert work.metadata_fields["fields"]["cover_url"]["provider"] == "openlibrary"
        assert work.metadata_fields["fields"]["publication_year"]["locked"]
        assert (await db.get(Operation, operation_id)).status == "completed"
        await enqueue(db, "metadata.enrich", operation_id=str(operation_id))
        await db.commit()
    calls = len(secondary["calls"])
    await asyncio.wait_for(get_queue().run_worker_async(wait=False, concurrency=1), timeout=15)
    assert len(secondary["calls"]) == calls
    async with database() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "metadata.enriched")
            )
            == 1
        )
    view = (await client.get(f"/api/metadata/works/{work_id}")).json()
    assert view["enrichment"]["status"] == "completed"
    assert not view["enrichment_retryable"]


async def test_scheduling_coalesces_and_rollback_does_not_leave_a_job(database, admin, secondary):
    work_id, operation_id = await prepared(database, admin)

    async def schedule():
        async with database() as db, db.begin():
            user = await db.get(User, UUID(admin["id"]))
            return (await enrichment.schedule_enrichment(db, user, await db.get(Work, work_id))).id

    assert set(await asyncio.gather(*(schedule() for _ in range(6)))) == {operation_id}
    async with database() as db:
        operation = await db.get(Operation, operation_id)
        operation.status = "failed"
        await db.commit()
        user = await db.get(User, UUID(admin["id"]))
        await enrichment.schedule_enrichment(db, user, await db.get(Work, work_id), retry=True)
        await db.rollback()
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(Operation)) == 1
        assert await db.scalar(text("SELECT count(*) FROM book_queue.procrastinate_jobs")) == 1


@pytest.mark.parametrize(
    "count,wrong,status",
    [
        (0, False, "completed"),
        (2, False, "needs-review"),
        (21, False, "needs-review"),
        (1, True, "needs-review"),
    ],
)
async def test_ambiguous_incomplete_or_changed_secondary_results_do_not_attach(
    database, admin, secondary, count, wrong, status
):
    secondary.update(count=count, wrong=wrong)
    work_id, operation_id = await prepared(database, admin)
    await enrichment.enrich(operation_id)
    async with database() as db:
        assert (await db.get(Operation, operation_id)).status == status
        assert (await db.get(Work, work_id)).cover_url is None
        assert await db.scalar(select(func.count()).select_from(WorkMetadataSource)) == 1


@pytest.mark.parametrize("change", ["title", "source", "permission", "preferences", "unmatch"])
async def test_inflight_lookup_cannot_overwrite_new_identity_or_authority(
    database, admin, client, secondary, change
):
    work_id, operation_id = await prepared(database, admin)
    secondary.update(pause=True, entered=asyncio.Event(), release=asyncio.Event())
    task = asyncio.create_task(enrichment.enrich(operation_id))
    try:
        await asyncio.wait_for(secondary["entered"].wait(), 5)
        # A separate writer can commit while provider I/O is paused: no work lock is retained.
        if change == "title":
            result = await client.patch(
                f"/api/metadata/works/{work_id}", json={"values": {"title": "A corrected identity"}}
            )
            assert result.status_code == 200
        elif change == "preferences":
            result = await client.put(
                "/api/metadata/preferences", json={"automatic_enrichment": False}
            )
            assert result.status_code == 200
        else:
            async with database() as db, db.begin():
                if change == "permission":
                    (await db.get(User, UUID(admin["id"]))).role = "viewer"
                elif change == "source":
                    source = await db.scalar(
                        select(WorkMetadataSource).where(WorkMetadataSource.work_id == work_id)
                    )
                    source.accepted = False
                else:
                    db.add(
                        WorkMetadataSource(
                            work_id=work_id,
                            provider="openlibrary",
                            external_id="OL1W",
                            snapshot={},
                            accepted=False,
                            manual_match=True,
                            fetched_at=(await db.get(Work, work_id)).created_at,
                        )
                    )
        secondary["release"].set()
        await asyncio.wait_for(task, 5)
    finally:
        secondary["release"].set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    async with database() as db:
        assert (await db.get(Operation, operation_id)).status == "cancelled"
        assert (await db.get(Work, work_id)).cover_url is None


async def test_failures_are_bounded_redacted_and_explicit_retry_can_recover(
    database, admin, client, secondary
):
    secondary["broken"] = True
    work_id, operation_id = await prepared(database, admin)
    for _ in range(4):
        with pytest.raises(RuntimeError, match="Retryable secondary"):
            await enrichment.enrich(operation_id)
    await enrichment.enrich(operation_id)
    metadata = (await client.get(f"/api/metadata/works/{work_id}")).json()
    assert metadata["enrichment"]["status"] == "failed"
    assert "private-upstream" not in str(metadata)
    assert metadata["enrichment_retryable"]
    secondary["broken"] = False
    retry = await client.post(f"/api/metadata/works/{work_id}/enrichment")
    assert retry.status_code == 202, retry.text
    assert retry.json()["id"] != str(operation_id)
    again = await client.post(f"/api/metadata/works/{work_id}/enrichment")
    assert again.json()["id"] == retry.json()["id"]
    await enrichment.enrich(UUID(retry.json()["id"]))
    assert (await client.get(f"/api/metadata/works/{work_id}")).json()["enrichment"][
        "status"
    ] == "completed"


async def test_stale_cache_is_not_used_for_new_automatic_associations(database, admin, secondary):
    secondary["stale"] = True
    work_id, operation_id = await prepared(database, admin)
    with pytest.raises(RuntimeError):
        await enrichment.enrich(operation_id)
    async with database() as db:
        assert (await db.get(Work, work_id)).cover_url is None
        assert (await db.get(Operation, operation_id)).status == "retrying"


async def test_secondary_source_unmatch_suppresses_automatic_reattachment(
    database, admin, client, secondary
):
    work_id, operation_id = await prepared(database, admin)
    await enrichment.enrich(operation_id)
    data = (await client.get(f"/api/metadata/works/{work_id}")).json()
    secondary_source = next(
        source for source in data["sources"] if source["provider"] == "openlibrary"
    )
    response = await client.post(
        f"/api/identity/sources/{secondary_source['id']}/unmatch",
        json={"expected_revision": secondary_source["revision"]},
    )
    assert response.status_code == 204
    response = await client.post(f"/api/metadata/works/{work_id}/enrichment")
    assert response.status_code == 409
    async with database() as db:
        assert (await db.get(Work, work_id)).cover_url is None


async def test_older_worker_result_is_fenced_by_newer_claim(database, admin, secondary):
    work_id, operation_id = await prepared(database, admin)
    secondary.update(pause=True, entered=asyncio.Event(), release=asyncio.Event())
    first = asyncio.create_task(enrichment.enrich(operation_id))
    try:
        await asyncio.wait_for(secondary["entered"].wait(), 5)
        secondary["pause"] = False
        await enrichment.enrich(operation_id)
        secondary["release"].set()
        await asyncio.wait_for(first, 5)
    finally:
        secondary["release"].set()
        if not first.done():
            first.cancel()
        await asyncio.gather(first, return_exceptions=True)
    async with database() as db:
        assert (await db.get(Operation, operation_id)).status == "completed"
        assert await db.scalar(select(func.count()).select_from(WorkMetadataSource)) == 2
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.entity_id == work_id, AuditEvent.action == "metadata.enriched")
            )
            == 1
        )


async def test_orphaned_queue_job_exposes_retry_and_gets_a_new_operation(
    database, admin, client, secondary
):
    work_id, operation_id = await prepared(database, admin)
    async with database() as db, db.begin():
        operation = await db.get(Operation, operation_id)
        operation.status = "running"
        await db.execute(
            text("UPDATE book_queue.procrastinate_jobs SET status='failed' WHERE id=:id"),
            {"id": operation.job_id},
        )
    view = (await client.get(f"/api/metadata/works/{work_id}")).json()
    assert view["enrichment"]["status"] == "failed"
    assert view["enrichment_retryable"]
    retry = await client.post(f"/api/metadata/works/{work_id}/enrichment")
    assert retry.status_code == 202, retry.text
    assert retry.json()["id"] != str(operation_id)
    await enrichment.enrich(UUID(retry.json()["id"]))
    async with database() as db:
        assert (await db.get(Operation, operation_id)).status == "failed"


async def test_queue_retry_respects_provider_cooldown(database, admin, secondary):
    secondary["quota"] = True
    _, operation_id = await prepared(database, admin)
    started = datetime.now(UTC)
    await asyncio.wait_for(get_queue().run_worker_async(wait=False, concurrency=1), timeout=15)
    async with database() as db:
        operation = await db.get(Operation, operation_id)
        assert operation.status == "retrying"
        scheduled = await db.scalar(
            text("SELECT scheduled_at FROM book_queue.procrastinate_jobs WHERE id=:id"),
            {"id": operation.job_id},
        )
        assert scheduled >= started + timedelta(seconds=3600)
