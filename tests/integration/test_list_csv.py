# ruff: noqa: F811
import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select, text

from app.db.models import (
    AuditEvent,
    ListCatalogBinding,
    ListCsvImport,
    ListEntry,
    Operation,
    User,
    Version,
    Work,
)
from app.domain import list_csv
from tests.integration.test_acquisition import catalog  # noqa: F401
from tests.integration.test_correction_migration import migrate
from tests.unit.test_csv_parser import fixture

pytestmark = pytest.mark.integration


@pytest.fixture
async def shelf(client, admin):
    return (await client.post("/api/lists", json={"name": "CSV reading list"})).json()["id"]


async def preview(client, shelf, rows=None, **options):
    response = await client.post(
        f"/api/lists/{shelf}/csv/preview",
        content=fixture(rows or [["42", "Harbor", "Writer", "9780306406157", "private-note"]]),
        headers={"Content-Type": "text/csv"},
        **options,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def commit(client, shelf, value, rows=None):
    response = await client.post(
        f"/api/lists/{shelf}/csv/{value['id']}/commit",
        json={"rows": rows or [r["row_number"] for r in value["records"]]},
    )
    assert response.status_code == 202, response.text
    return UUID(response.json()["id"])


async def test_preview_is_private_inert_then_atomic_idempotent_worker(client, database, shelf):
    value = await preview(client, shelf)
    assert not value["records"][0]["availability"]["owned"]
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(Work)) == 0
        assert "private-note" not in str((await db.get(ListCsvImport, UUID(value["id"]))).snapshot)
    operation = await commit(client, shelf, value)
    await asyncio.gather(list_csv.run(operation), list_csv.run(operation))
    await list_csv.run(operation)
    assert await commit(client, shelf, value) == operation
    assert (await client.get(f"/api/lists/{shelf}")).json()["count"] == 1
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(Work)) == 1
        assert await db.scalar(select(func.count()).select_from(Version)) == 0
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "list.csv.imported")
            )
            == 1
        )
        assert (await db.get(Operation, operation)).status == "completed"
    value2 = await preview(client, shelf)
    assert value2["records"][0]["work_id"]
    await list_csv.run(await commit(client, shelf, value2))
    assert (await client.get(f"/api/lists/{shelf}")).json()["count"] == 1


async def test_selection_and_omissions_never_remove_and_replay_never_restores(
    client, database, shelf
):
    value = await preview(
        client, shelf, [["1", "First", "Writer", "", ""], ["2", "Second", "Writer", "", ""]]
    )
    operation = await commit(client, shelf, value, [2])
    await list_csv.run(operation)
    work = (await client.get(f"/api/lists/{shelf}")).json()["items"][0]
    assert work["title"] == "First"
    changed = await client.post(f"/api/lists/{shelf}/csv/{value['id']}/commit", json={"rows": [3]})
    assert changed.status_code == 409
    next_value = await preview(client, shelf, [["2", "Second", "Writer", "", ""]])
    await list_csv.run(await commit(client, shelf, next_value))
    assert (await client.get(f"/api/lists/{shelf}")).json()["count"] == 2
    await client.delete(f"/api/lists/{shelf}/entries/{work['id']}")
    await list_csv.run(await commit(client, shelf, value, [2]))
    assert (await client.get(f"/api/lists/{shelf}")).json()["count"] == 1


async def test_valid_isbn_matches_catalog_and_alternate_source_ids_dedupe(client, database, shelf):
    value = await preview(
        client,
        shelf,
        [
            ["1", "Harbor", "Writer", "9780306406157", ""],
            ["2", "Harbor", "Writer", "9780306406157", ""],
        ],
    )
    await list_csv.run(await commit(client, shelf, value))
    assert (await client.get(f"/api/lists/{shelf}")).json()["count"] == 1
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(ListCatalogBinding)) == 2
    wrong = await preview(client, shelf, [["1", "Wrong Book", "Writer", "9780306406157", ""]])
    assert wrong["records"][0]["issue"]
    response = await client.post(f"/api/lists/{shelf}/csv/{wrong['id']}/commit", json={"rows": [2]})
    assert response.status_code == 409


async def test_expired_preview_and_queue_rollback(client, database, shelf, monkeypatch):
    value = await preview(client, shelf)

    async def fail(*args, **kwargs):
        raise RuntimeError("queue unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(list_csv, "enqueue", fail)
        with pytest.raises(RuntimeError, match="queue unavailable"):
            await commit(client, shelf, value)
    async with database() as db, db.begin():
        row = await db.get(ListCsvImport, UUID(value["id"]))
        assert row.selected_rows is None and row.operation_id is None
        assert await db.scalar(select(func.count()).select_from(Operation)) == 0
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    response = await client.post(f"/api/lists/{shelf}/csv/{value['id']}/commit", json={"rows": [2]})
    assert response.status_code == 409


async def test_worker_failure_rolls_back_all_memberships_then_retries(
    client, database, shelf, monkeypatch
):
    value = await preview(
        client, shelf, [["1", "First", "Writer", "", ""], ["2", "Second", "Writer", "", ""]]
    )
    operation = await commit(client, shelf, value)
    resolve = list_csv.resolve
    calls = 0

    async def fail(db, owner, record):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise RuntimeError("worker interrupted after first addition")
        return await resolve(db, owner, record)

    with monkeypatch.context() as patch:
        patch.setattr(list_csv, "resolve", fail)
        with pytest.raises(RuntimeError, match="worker interrupted"):
            await list_csv.run(operation)
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(Work)) == 0
        assert await db.scalar(select(func.count()).select_from(ListEntry)) == 0
        assert (await db.get(ListCsvImport, UUID(value["id"]))).receipt is None
    await list_csv.run(operation)
    assert (await client.get(f"/api/lists/{shelf}")).json()["count"] == 2


async def test_role_revocation_fences_pending_import(client, database, shelf, admin):
    value = await preview(client, shelf)
    operation = await commit(client, shelf, value)
    async with database() as db, db.begin():
        (await db.get(User, UUID(admin["id"]))).role = "viewer"
    await list_csv.run(operation)
    async with database() as db:
        assert (await db.get(Operation, operation)).status == "failed"
        assert await db.scalar(select(func.count()).select_from(Work)) == 0


async def test_preview_mapping_invalid_files_and_history_guard(client, database, shelf):
    response = await client.post(
        f"/api/lists/{shelf}/csv/preview", content=b"Name,Creator\nHarbor,Writer"
    )
    assert response.status_code == 200 and response.json()["needs_mapping"]
    assert response.json()["id"] is None
    mapped = await client.post(
        f"/api/lists/{shelf}/csv/preview",
        content=b"Name,Creator\nHarbor,Writer",
        params={"mapping": '{"title":"Name","author":"Creator"}'},
    )
    assert mapped.status_code == 200 and mapped.json()["records"][0]["title"] == "Harbor"
    bad = await client.post(
        f"/api/lists/{shelf}/csv/preview", content=b"Title\nHarbor", params={"mapping": "not-json"}
    )
    assert bad.status_code == 422
    before = None
    async with database() as db:
        before = await db.scalar(text("select version_num from alembic_version"))
    downgrade = await migrate("downgrade", "0025_list_subscriptions")
    assert downgrade.returncode != 0 and "pre-upgrade backup" in downgrade.stderr
    async with database() as db:
        assert await db.scalar(text("select version_num from alembic_version")) == before


async def test_owner_isolation_shared_membership_and_existing_library_availability(
    client, database, shelf, catalog
):
    from contextlib import aclosing

    from tests.integration.test_list_subscriptions import member

    async with database() as db, db.begin():
        (await db.get(Version, catalog["versions"][0])).identifiers = {"isbn13": "9780306406157"}
    value = await preview(client, shelf)
    assert value["records"][0]["work_id"] == str(catalog["work"])
    assert value["records"][0]["availability"]["ebook"]
    await list_csv.run(await commit(client, shelf, value))
    async with aclosing(await member(database, "csv-other")) as other:
        assert (await other.get(f"/api/lists/{shelf}/csv")).status_code == 404
        assert (
            await other.post(f"/api/lists/{shelf}/csv/preview", content=b"Title\nOther")
        ).status_code == 404
        assert (
            await other.post(f"/api/lists/{shelf}/csv/{value['id']}/commit", json={"rows": [2]})
        ).status_code == 404
        await client.patch(f"/api/lists/{shelf}", json={"name": "Shared CSV", "shared": True})
        assert (await other.get(f"/api/lists/{shelf}/csv/{value['id']}")).status_code == 404
        target = (await other.post("/api/lists", json={"name": "Separate CSV"})).json()["id"]
        own = await preview(other, target, [["70", "Private Book", "Writer", "", ""]])
        await list_csv.run(await commit(other, target, own))
        async with database() as db:
            bindings = (await db.scalars(select(ListCatalogBinding))).all()
            assert len({binding.owner_id for binding in bindings}) == 2
        # A second ordinary member cannot see the provisional book until deliberately shared.
        async with aclosing(await member(database, "csv-third")) as third:
            assert (await third.get("/api/catalog/works", params={"q": "Private Book"})).json()[
                "total"
            ] == 0
            await other.patch(f"/api/lists/{target}", json={"name": "Separate CSV", "shared": True})
            assert (await third.get("/api/catalog/works", params={"q": "Private Book"})).json()[
                "total"
            ] == 1
            await other.patch(
                f"/api/lists/{target}", json={"name": "Separate CSV", "shared": False}
            )
            assert (await third.get("/api/catalog/works", params={"q": "Private Book"})).json()[
                "total"
            ] == 0


async def test_catalog_change_after_preview_fails_before_any_additions(client, database, shelf):
    work = (
        await client.post("/api/catalog/works", json={"title": "Harbor", "authors": ["Writer"]})
    ).json()
    async with database() as db, db.begin():
        db.add(
            Version(
                work_id=UUID(work["id"]), medium="ebook", identifiers={"isbn13": "9780306406157"}
            )
        )
    value = await preview(
        client,
        shelf,
        [["1", "New Book", "Writer", "", ""], ["42", "Harbor", "Writer", "9780306406157", ""]],
    )
    operation = await commit(client, shelf, value)
    async with database() as db, db.begin():
        (await db.get(Work, UUID(work["id"]))).title = "Corrected Different Book"
    await list_csv.run(operation)
    async with database() as db:
        assert (await db.get(Operation, operation)).status == "failed"
        assert await db.scalar(select(func.count()).select_from(ListEntry)) == 0
        assert await db.scalar(select(func.count()).select_from(Work)) == 1


async def test_csv_and_rss_share_catalog_but_not_exclusion_or_local_membership(
    client, database, shelf, monkeypatch
):
    from app.adapters.goodreads import FeedResult
    from app.domain import list_subscriptions
    from tests.unit.test_goodreads import URL

    value = await preview(client, shelf)
    await list_csv.run(await commit(client, shelf, value))
    await client.put(f"/api/lists/{shelf}/subscription", json={"feed_url": URL})

    async def feed(*args, **kwargs):
        return FeedResult(
            [
                {
                    "external_id": "42",
                    "title": "Harbor",
                    "authors": ["Writer"],
                    "isbn": None,
                    "isbn13": "9780306406157",
                }
            ]
        )

    monkeypatch.setattr(list_subscriptions, "fetch_feed", feed)
    operation = (
        await client.post(
            f"/api/lists/{shelf}/subscription/sync", headers={"Idempotency-Key": "rss-from-csv"}
        )
    ).json()["id"]
    await list_subscriptions.run(UUID(operation))
    page = (await client.get(f"/api/lists/{shelf}/subscription/observations")).json()
    assert len(page["items"]) == 1
    await client.patch(
        f"/api/lists/{shelf}/subscription/observations/{page['items'][0]['id']}",
        json={"excluded": True},
    )
    assert (await client.get(f"/api/lists/{shelf}")).json()["count"] == 1
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(Work)) == 1
        assert (await db.scalar(select(ListEntry))).locally_added


async def test_exhausted_worker_can_retry_saved_selection_and_preview_cap(client, database, shelf):
    value = await preview(client, shelf)
    operation = await commit(client, shelf, value)
    async with database() as db, db.begin():
        job = (await db.get(Operation, operation)).job_id
        await db.execute(
            text("UPDATE book_queue.procrastinate_jobs SET status='failed' WHERE id=:id"),
            {"id": job},
        )
    failed = (await client.get(f"/api/lists/{shelf}/csv/{value['id']}")).json()
    assert failed["state"] == "failed"
    assert await commit(client, shelf, value) == operation
    await list_csv.run(operation)
    for _ in range(11):
        await preview(client, shelf)
    async with database() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(ListCsvImport)
                .where(ListCsvImport.operation_id.is_(None))
            )
            == 10
        )
        assert (await db.get(ListCsvImport, UUID(value["id"]))).committed_at
    oversized = await client.post(
        f"/api/lists/{shelf}/csv/preview", content=b"x" * (4 * 1024 * 1024 + 1)
    )
    assert oversized.status_code == 413


async def test_deleted_list_cannot_publish_queued_csv(client, database, shelf):
    value = await preview(client, shelf)
    operation = await commit(client, shelf, value)
    assert (await client.delete(f"/api/lists/{shelf}")).status_code == 204
    await list_csv.run(operation)
    async with database() as db:
        assert (await db.get(Operation, operation)).status == "failed"
        assert await db.scalar(select(func.count()).select_from(Work)) == 0


async def test_largest_supported_snapshot_commits_without_truncation(client, database, shelf):
    from app.adapters.list_csv import MAX_ROWS

    value = await preview(
        client,
        shelf,
        [
            [str(index + 1), f"Capacity Book {index + 1}", "Fixture Writer", "", ""]
            for index in range(MAX_ROWS)
        ],
    )
    assert len(value["records"]) == MAX_ROWS
    operation = await commit(client, shelf, value)
    await list_csv.run(operation)
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(ListEntry)) == MAX_ROWS
        assert await db.scalar(select(func.count()).select_from(Work)) == MAX_ROWS
        row = await db.get(ListCsvImport, UUID(value["id"]))
        assert row.receipt["added"] == MAX_ROWS
        assert (await db.get(Operation, operation)).status == "completed"
