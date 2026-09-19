import hashlib
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Operation
from app.jobs.queue import enqueue


async def transaction_lock(db: AsyncSession, key: str) -> None:
    number = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], signed=True)
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": number})


async def try_transaction_lock(db: AsyncSession, key: str) -> bool:
    number = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], signed=True)
    return bool(await db.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": number}))


async def enqueue_sync(
    db: AsyncSession, owner_id: UUID, integration_id: UUID, key: str
) -> Operation:
    await transaction_lock(db, f"operation:{owner_id}:{key}")
    existing = await db.scalar(
        select(Operation).where(
            Operation.owner_id == owner_id,
            Operation.idempotency_key == key,
        )
    )
    if existing:
        if existing.kind != "library.sync" or existing.integration_id != integration_id:
            raise HTTPException(409, "This operation key was already used for another command")
        return existing
    await transaction_lock(db, f"sync:{integration_id}")
    current = await db.scalar(
        select(Operation)
        .where(
            Operation.integration_id == integration_id,
            Operation.kind == "library.sync",
            Operation.status.in_(["queued", "running"]),
        )
        .order_by(Operation.created_at.desc())
        .limit(1)
    )
    if current:
        # Queue truth distinguishes an active/retryable job from an exhausted one.
        # Never replace a live job merely because an observation timed out.
        job_status = await db.scalar(
            text("SELECT status::text FROM book_queue.procrastinate_jobs WHERE id = :id"),
            {"id": current.job_id},
        )
        if job_status in {"todo", "doing"}:
            return current
        current.status = "failed"
        current.message = "Previous inventory job ended before completion; a new sync was requested"
    operation = Operation(
        owner_id=owner_id,
        kind="library.sync",
        integration_id=integration_id,
        idempotency_key=key,
        message="Waiting to sync Audiobookshelf",
    )
    db.add(operation)
    await db.flush()
    operation.job_id = await enqueue(db, "library.sync", operation_id=str(operation.id))
    await db.flush()
    await db.refresh(operation)
    return operation


def require_live_command(operation):
    if operation.payload.get("recovery_retirement"):
        raise HTTPException(409, "Recovery retired this command; create a fresh preview")
