# ruff: noqa: F811
"""Member ownership survives administrator inspection and publication handoff."""

import asyncio
from contextlib import aclosing
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select, text

from app.config import get_settings
from app.db.models import (
    AcquisitionReason,
    AcquisitionSelection,
    DownloadAttempt,
    DownloadHandoff,
    DownloadInspection,
    ImportDestination,
    LibraryGrant,
    Operation,
    User,
    Version,
)
from app.domain import download_attempts as downloads
from app.domain import download_reviews as reviews
from app.importing.workflow import run_inspection
from app.main import create_app
from app.security import hash_password
from tests.integration.test_acquisition import catalog  # noqa: F401
from tests.integration.test_acquisition_selections import selection_route  # noqa: F401
from tests.integration.test_correction_migration import migrate
from tests.integration.test_download_attempts import downloader, selected, start  # noqa: F401

pytestmark = pytest.mark.integration


async def admin_client(database, name="reviewer"):
    async with database() as db, db.begin():
        user = User(
            username=name,
            display_name="Review administrator",
            role="admin",
            password_hash=hash_password("reviewer long password"),
        )
        db.add(user)
        await db.flush()
        identifier = user.id
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()),
        base_url="http://testserver",
        headers={"Origin": "http://testserver"},
    )
    response = await client.post(
        "/api/auth/login", json={"username": name, "password": "reviewer long password"}
    )
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return client, identifier


@pytest.fixture
async def completed(client, admin, database, selected, downloader):
    async with database() as db, db.begin():
        selection = await db.get(AcquisitionSelection, UUID(selected["id"]))
        destination = await db.get(ImportDestination, selection.destination_id)
        (await db.get(User, UUID(admin["id"]))).role = "member"
        db.add(LibraryGrant(user_id=UUID(admin["id"]), library_id=destination.library_id))
    downloader.complete = True
    response = await start(client, selected)
    assert response.status_code == 202, response.text
    identifier = UUID(response.json()["id"])
    await downloads.run(identifier)
    async with database() as db:
        attempt = await db.get(DownloadAttempt, identifier)
        assert attempt.state == "complete" and attempt.inspection_id is None
    return identifier


@pytest.fixture
async def review_account(database, admin):
    client, identifier = await admin_client(database)
    async with aclosing(client):
        yield client, identifier


@pytest.fixture
async def reviewer(review_account, completed):
    return review_account


async def proposal(client):
    result = await client.get("/api/acquisition/reviews")
    assert result.status_code == 200, result.text
    return result.json()["items"][0]


async def claim(client, row, key="claim-download-review"):
    return await client.post(
        f"/api/acquisition/reviews/{row['attempt_id']}/claim",
        json={"revision": row["revision"]},
        headers={"Idempotency-Key": key},
    )


async def test_private_queue_idempotency_and_original_owner_projection(
    client, database, completed, reviewer
):
    review, admin_id = reviewer
    assert (await client.get("/api/acquisition/reviews")).status_code == 403
    row = await proposal(review)
    assert row["can_claim"] and row["inspection_id"] is None
    assert (await claim(client, row)).status_code == 403
    replies = await asyncio.gather(*(claim(review, row) for _ in range(3)))
    assert all(r.status_code == 202 for r in replies), [r.text for r in replies]
    assert len({r.json()["inspection_id"] for r in replies}) == 1
    assigned = replies[0].json()
    assert assigned["inspection_id"] and not assigned["can_claim"]
    assert (await claim(review, row, "stale-review-key")).status_code == 409
    assert (await claim(review, assigned, "already-assigned-key")).status_code == 409
    assert (await review.get(f"/api/acquisition/downloads/{completed}")).status_code == 404
    assert (await client.get(f"/api/acquisition/downloads/{completed}")).json()[
        "inspection_id"
    ] is None
    assert (
        await client.get(f"/api/organization/inspections/{assigned['inspection_id']}")
    ).status_code == 403
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(DownloadHandoff)) == 1
        inspection = await db.get(DownloadInspection, UUID(assigned["inspection_id"]))
        assert inspection.owner_id == admin_id
        assert (await db.get(DownloadAttempt, completed)).owner_id != admin_id
    assert all(
        value not in str(assigned)
        for value in ("mam_id", "/downloads", "private-password", "list_id")
    )


async def test_competing_reviewers_and_reassignment_invalidate_old_worker(database, reviewer):
    first, _ = reviewer
    second, _ = await admin_client(database, "other-reviewer")
    async with aclosing(second):
        row = await proposal(first)
        results = await asyncio.gather(claim(first, row), claim(second, row))
        assert sorted(r.status_code for r in results) == [202, 409]
        winner, loser = (first, second) if results[0].status_code == 202 else (second, first)
        old = await proposal(winner)
        next_review = await claim(loser, await proposal(loser), "reassign-review-key")
        assert next_review.status_code == 202, next_review.text
        assert next_review.json()["inspection_id"] != old["inspection_id"]
        assert (
            await winner.get(f"/api/organization/inspections/{old['inspection_id']}")
        ).status_code == 409
        async with database() as db:
            inspection = await db.get(DownloadInspection, UUID(old["inspection_id"]))
            operation_id = inspection.operation_id
        await run_inspection(operation_id)
        async with database() as db:
            assert (await db.get(DownloadInspection, inspection.id)).state == "failed"
            assert (await db.get(Operation, operation_id)).status == "failed"
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(DownloadHandoff)
                    .where(DownloadHandoff.active.is_(True))
                )
                == 1
            )


@pytest.mark.parametrize("change", ["grant", "role", "withdraw", "mapping", "recovery"])
async def test_claim_rechecks_current_authority_and_mapping(
    database, admin, reviewer, selected, change, monkeypatch
):
    review, _ = reviewer
    row = await proposal(review)
    async with database() as db, db.begin():
        if change == "grant":
            await db.execute(delete(LibraryGrant))
        elif change == "role":
            (await db.get(User, UUID(admin["id"]))).role = "viewer"
        elif change == "withdraw":
            for reason in await db.scalars(select(AcquisitionReason)):
                reason.active = False
        elif change == "mapping":
            monkeypatch.setattr(get_settings(), "import_sources", {})
        else:
            monkeypatch.setattr(get_settings(), "recovery_mode", True)
    result = await claim(review, row)
    assert result.status_code in {404, 409, 422}, result.text
    async with database() as db:
        assert not await db.scalar(select(DownloadHandoff.id))
        assert (await db.get(DownloadAttempt, UUID(row["attempt_id"]))).inspection_id is None


async def test_failed_enqueue_rolls_back_handoff(database, reviewer, monkeypatch):
    review, _ = reviewer
    row = await proposal(review)

    async def fail(*args, **kwargs):
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(downloads, "enqueue", fail)
    with pytest.raises(RuntimeError, match="queue unavailable"):
        await claim(review, row)
    async with database() as db:
        assert not await db.scalar(select(DownloadHandoff.id))
        assert not await db.scalar(select(DownloadInspection.id))
        assert (await db.get(DownloadAttempt, UUID(row["attempt_id"]))).inspection_id is None


async def test_handoff_rejects_destination_and_exact_version_drift(database, selected, reviewer):
    review, _ = reviewer
    assigned = (await claim(review, await proposal(review))).json()
    async with database() as db, db.begin():
        selection = await db.get(AcquisitionSelection, UUID(selected["id"]))
        version = await db.scalar(
            select(Version).where(
                Version.work_id == UUID(selection.frozen["origin_work_id"]),
                Version.medium == "audio",
            )
        )
        selection.frozen = {
            **selection.frozen,
            "requirements": {**selection.frozen["requirements"], "version_id": str(uuid4())},
        }
    async with database() as db:
        with pytest.raises(HTTPException) as wrong_destination:
            await reviews.validate_inspection(
                db, UUID(assigned["inspection_id"]), destination_id=uuid4()
            )
        assert wrong_destination.value.status_code == 422
        with pytest.raises(HTTPException) as wrong_version:
            await reviews.validate_inspection(db, UUID(assigned["inspection_id"]), version=version)
        assert wrong_version.value.status_code == 422


@pytest.mark.parametrize("during", [False, True])
async def test_inspection_rechecks_requester_before_read_and_snapshot(
    database, reviewer, monkeypatch, during
):
    from app.importing import workflow

    review, _ = reviewer
    assigned = (await claim(review, await proposal(review))).json()
    async with database() as db:
        inspection = await db.get(DownloadInspection, UUID(assigned["inspection_id"]))
    loop = asyncio.get_running_loop()
    reads = []

    async def revoke():
        async with database() as db, db.begin():
            await db.execute(delete(LibraryGrant))

    def inspect(*args):
        reads.append(True)
        asyncio.run_coroutine_threadsafe(revoke(), loop).result(timeout=10)
        return {"revision": "never-publish-this-snapshot"}

    monkeypatch.setattr(workflow, "inspect_download", inspect)
    if not during:
        await revoke()
    await run_inspection(inspection.operation_id)
    assert len(reads) == int(during)
    async with database() as db:
        row = await db.get(DownloadInspection, inspection.id)
        assert row.state == "failed" and row.snapshot is None


@pytest.mark.parametrize("change", ["grant", "reason", "user"])
async def test_authority_rows_remain_locked_through_publication_guard(database, reviewer, change):
    review, _ = reviewer
    assigned = (await claim(review, await proposal(review))).json()

    async def revoke():
        async with database() as db, db.begin():
            await db.execute(text("SET LOCAL lock_timeout = '100ms'"))
            if change == "grant":
                await db.execute(delete(LibraryGrant))
            elif change == "reason":
                await db.execute(text("UPDATE acquisition_reasons SET active = false"))
            else:
                await db.execute(text("UPDATE users SET active = false WHERE role = 'member'"))

    from sqlalchemy.exc import OperationalError

    async with database() as db, db.begin():
        await reviews.lock_principals(db, UUID(assigned["inspection_id"]))
        await reviews.validate_inspection(db, UUID(assigned["inspection_id"]), lock=True)
        # PostgreSQL, not a mocked lock, must reject a concurrent authority mutation.
        with pytest.raises(OperationalError, match="lock timeout"):
            await revoke()
    await revoke()
    async with database() as db:
        with pytest.raises(HTTPException):
            await reviews.validate_inspection(db, UUID(assigned["inspection_id"]))


async def test_populated_review_history_blocks_lossy_downgrade(database, reviewer):
    review, _ = reviewer
    assert (await claim(review, await proposal(review))).status_code == 202
    async with database() as db:
        before = await db.scalar(text("SELECT version_num FROM alembic_version"))
    result = await migrate("downgrade", "0020_repairs")
    assert result.returncode != 0 and "Download review history requires" in result.stderr
    async with database() as db:
        assert await db.scalar(text("SELECT version_num FROM alembic_version")) == before


async def test_assigned_administrator_can_retry_failed_inspection(database, reviewer):
    review, _ = reviewer
    assigned = (await claim(review, await proposal(review))).json()
    async with database() as db:
        inspection = await db.get(DownloadInspection, UUID(assigned["inspection_id"]))
    # This transfer-contract fixture has no files; the real inspector must fail safely.
    await run_inspection(inspection.operation_id)
    current = await proposal(review)
    assert current["retry"] and current["can_claim"]
    assert (await claim(review, assigned, "stale-inspection-retry")).status_code == 409
    retried = await claim(review, current, "retry-failed-inspection")
    assert retried.status_code == 202, retried.text
    assert retried.json()["inspection_id"] != assigned["inspection_id"]
    assert not retried.json()["retry"]
    assert (await claim(review, current, "retry-failed-inspection")).json() == retried.json()
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(DownloadHandoff)) == 2
        assert (
            await db.scalar(
                select(func.count())
                .select_from(DownloadHandoff)
                .where(DownloadHandoff.active.is_(True))
            )
            == 1
        )
