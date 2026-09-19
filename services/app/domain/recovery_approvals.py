"""Historical evidence can be read but cannot supply new execution authority."""

from fastapi import HTTPException
from sqlalchemy import or_, select

from app.db.models import RecoveryQueueFence, RecoveryQueueSubject, RestoreCheckpoint

KINDS = {"operation", "selection", "import-plan", "csv-preview"}


async def denial(db, kind, identifier):
    if kind not in KINDS:
        raise ValueError("Unsupported approval boundary")
    incomplete = await db.scalar(
        select(RestoreCheckpoint.id)
        .outerjoin(RecoveryQueueFence, RecoveryQueueFence.checkpoint_id == RestoreCheckpoint.id)
        .where(
            or_(
                RecoveryQueueFence.checkpoint_id.is_(None),
                RecoveryQueueFence.approval_version != 1,
            )
        )
        .limit(1)
    )
    if incomplete:
        return "Restore approval protection is incomplete; complete the supported offline upgrade"
    historical = await db.scalar(
        select(RecoveryQueueSubject.checkpoint_id)
        .where(RecoveryQueueSubject.kind == kind, RecoveryQueueSubject.subject_id == identifier)
        .limit(1)
    )
    if historical:
        return "This approval predates restore; create a fresh preview after recovery"
    return None


async def require_current(db, kind, identifier):
    reason = await denial(db, kind, identifier)
    if reason:
        raise HTTPException(409, reason)
