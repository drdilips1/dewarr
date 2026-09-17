import asyncio
from uuid import UUID

import pytest
from sqlalchemy import func, select, text

from app.db.models import AuditEvent, Operation
from app.jobs.queue import enqueue, get_queue

pytestmark = pytest.mark.integration


async def test_domain_and_queue_rollback_together(database, admin):
    async with database() as db:
        operation = Operation(
            owner_id=UUID(admin["id"]),
            kind="system.probe",
            idempotency_key="rollback",
        )
        db.add(operation)
        await db.flush()
        await enqueue(db, "system.probe", operation_id=str(operation.id))
        await db.rollback()
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(Operation)) == 0
        assert await db.scalar(text("SELECT count(*) FROM book_queue.procrastinate_jobs")) == 0


async def test_concurrent_command_commits_one_job(client, admin, database):
    results = await asyncio.gather(
        *[
            client.post("/api/system/probe", headers={"Idempotency-Key": "same-command"})
            for _ in range(8)
        ]
    )
    assert all(response.status_code == 202 for response in results), [r.text for r in results]
    assert len({response.json()["id"] for response in results}) == 1
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(Operation)) == 1
        assert await db.scalar(text("SELECT count(*) FROM book_queue.procrastinate_jobs")) == 1


async def test_real_worker_executes_and_redelivery_is_idempotent(client, admin, database):
    response = await client.post("/api/system/probe", headers={"Idempotency-Key": "worker-check"})
    operation_id = UUID(response.json()["id"])
    await asyncio.wait_for(get_queue().run_worker_async(wait=False, concurrency=1), timeout=15)
    async with database() as db:
        operation = await db.get(Operation, operation_id)
        assert operation.status == "completed"
        await enqueue(db, "system.probe", operation_id=str(operation_id))
        await db.commit()
    await asyncio.wait_for(get_queue().run_worker_async(wait=False, concurrency=1), timeout=15)
    async with database() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "system.probe.completed")
            )
            == 1
        )


async def test_readiness_checks_migrated_database(client):
    assert (await client.get("/api/health/ready")).json() == {"status": "ready"}
