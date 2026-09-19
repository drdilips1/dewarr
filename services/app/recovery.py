"""Persistent restore fencing and cooperative offline maintenance locks."""

from contextlib import asynccontextmanager

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RestoreCheckpoint
from app.db.session import get_engine

# Session-scoped: every supported API/worker process holds a shared lock for its lifetime.
MAINTENANCE_LOCK = 720041


async def active_restore(db: AsyncSession) -> RestoreCheckpoint | None:
    return await db.scalar(select(RestoreCheckpoint).where(RestoreCheckpoint.active.is_(True)))


async def restore_pending(db: AsyncSession) -> bool:
    # The database setting survives a crash between pg_restore and checkpoint insertion.
    return bool(
        await db.scalar(
            text(
                "SELECT coalesce(current_setting('book_search.restore_pending', true), '') "
                "= 'true' "
                "OR EXISTS(SELECT 1 FROM restore_checkpoints WHERE active)"
            )
        )
    )


@asynccontextmanager
async def runtime_lease():
    async with get_engine().connect() as connection:
        acquired = await connection.scalar(
            text("SELECT pg_try_advisory_lock_shared(:key)"), {"key": MAINTENANCE_LOCK}
        )
        await connection.commit()
        if not acquired:
            raise RuntimeError("Offline maintenance is in progress; retry startup afterwards")
        try:
            yield
        finally:
            await connection.execute(
                text("SELECT pg_advisory_unlock_shared(:key)"), {"key": MAINTENANCE_LOCK}
            )
            await connection.commit()
