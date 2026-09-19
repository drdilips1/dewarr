from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text

from app.db.models import (
    BookList,
    ListCsvImport,
    RecoveryQueueFence,
    RecoveryQueueSubject,
    RestoreCheckpoint,
)
from app.domain.recovery_approvals import require_current
from app.recovery_queue import seal
from tests.integration.test_recovery_scan_workflow import pause

pytestmark = pytest.mark.integration


async def seal_history(database, admin):
    checkpoint = await pause(database, admin)
    async with database() as db, db.begin():
        await seal(db, checkpoint)
        # Test persistence beyond the pause; this is not a supported resume action.
        (await db.get(RestoreCheckpoint, checkpoint)).active = False
    return checkpoint


async def csv_record(database, admin):
    async with database() as db, db.begin():
        shelf = BookList(owner_id=UUID(admin["id"]), name="Restored CSV")
        db.add(shelf)
        await db.flush()
        row = ListCsvImport(
            owner_id=UUID(admin["id"]),
            list_id=shelf.id,
            snapshot={"records": []},
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
        db.add(row)
        await db.flush()
        return row.id


async def test_approval_membership_is_exact_immutable_and_preserves_deleted_evidence(
    client, admin, database
):
    old = await csv_record(database, admin)
    checkpoint = await seal_history(database, admin)
    fresh = await csv_record(database, admin)
    async with database() as db, db.begin():
        fence = await db.get(RecoveryQueueFence, checkpoint)
        assert fence.approval_version == 1 and fence.subject_counts["csv-preview"] == 1
        with pytest.raises(HTTPException, match="predates restore"):
            await require_current(db, "csv-preview", old)
        # Old timestamps do not falsely fence records absent from the restored set.
        (await db.get(ListCsvImport, fresh)).created_at = datetime(2000, 1, 1, tzinfo=UTC)
        await require_current(db, "csv-preview", fresh)
        await db.delete(await db.get(ListCsvImport, old))
    async with database() as db:
        with pytest.raises(HTTPException, match="predates restore"):
            await require_current(db, "csv-preview", old)
        assert await db.get(RecoveryQueueSubject, (checkpoint, "csv-preview", old))


@pytest.mark.parametrize("kind", ["operation", "selection", "import-plan", "csv-preview"])
async def test_missing_or_legacy_approval_boundary_fails_closed(client, admin, database, kind):
    checkpoint = await pause(database, admin)
    async with database() as db, db.begin():
        (await db.get(RestoreCheckpoint, checkpoint)).active = False
        with pytest.raises(HTTPException, match="protection is incomplete"):
            await require_current(db, kind, uuid4())
        db.add(
            RecoveryQueueFence(
                checkpoint_id=checkpoint,
                job_id_through=0,
                job_count=0,
                subject_counts={},
                approval_version=0,
            )
        )
    async with database() as db:
        with pytest.raises(HTTPException, match="protection is incomplete"):
            await require_current(db, kind, uuid4())


async def test_offline_upgrade_backfills_active_approval_membership(client, admin, database):
    import asyncio
    import subprocess

    old = await csv_record(database, admin)

    async def migrate(*args):
        result = await asyncio.to_thread(
            subprocess.run, ["uv", "run", "alembic", *args], capture_output=True, timeout=20
        )
        assert result.returncode == 0, result.stderr.decode()

    await migrate("downgrade", "0043_recovery_queue_fences")
    checkpoint = await pause(database, admin)
    async with database() as db, db.begin():
        await db.execute(
            text(
                "INSERT INTO recovery_queue_fences"
                "(checkpoint_id,job_id_through,job_count,subject_counts) VALUES(:id,0,0,'{}')"
            ),
            {"id": checkpoint},
        )
    await migrate("upgrade", "head")
    async with database() as db:
        fence = await db.get(RecoveryQueueFence, checkpoint)
        assert fence.approval_version == 1 and fence.job_id_through == 0 and fence.job_count == 0
        assert fence.subject_counts == {"csv-preview": 1}
        assert (
            await db.scalar(
                select(RecoveryQueueSubject.subject_id).where(
                    RecoveryQueueSubject.kind == "csv-preview"
                )
            )
            == old
        )


async def test_legacy_approval_header_also_blocks_fresh_ordinary_queue_jobs(
    client, admin, database
):
    from app.db.models import Operation
    from app.jobs.queue import get_queue

    checkpoint = await seal_history(database, admin)
    async with database() as db, db.begin():
        (await db.get(RecoveryQueueFence, checkpoint)).approval_version = 0
    result = await client.post(
        "/api/system/probe", headers={"Idempotency-Key": "legacy-approval-boundary"}
    )
    assert result.status_code == 202, result.text
    await get_queue().run_worker_async(wait=False, concurrency=1)
    async with database() as db:
        row = await db.get(Operation, UUID(result.json()["id"]))
        assert row.status == "queued"
        status = await db.scalar(
            text("SELECT status::text FROM book_queue.procrastinate_jobs WHERE id=:id"),
            {"id": row.job_id},
        )
        assert status == "aborted"
