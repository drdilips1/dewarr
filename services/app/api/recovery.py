from datetime import datetime
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.dependencies import Admin, Database
from app.config import get_settings
from app.db.models import DownloadAttempt, ImportEntry
from app.recovery import active_restore, restore_pending

router = APIRouter(prefix="/recovery", tags=["recovery"])


class RecoveryView(BaseModel):
    paused: bool
    backup_id: UUID | None
    restored_at: datetime | None
    downloads: dict[str, int]
    imports: dict[str, int]
    resume_available: bool = False


@router.get("", response_model=RecoveryView)
async def review(admin: Admin, db: Database):
    checkpoint = await active_restore(db)
    return RecoveryView(
        paused=get_settings().recovery_mode or await restore_pending(db),
        backup_id=checkpoint.backup_id if checkpoint else None,
        restored_at=checkpoint.created_at if checkpoint else None,
        downloads=dict(
            (
                await db.execute(
                    select(DownloadAttempt.state, func.count()).group_by(DownloadAttempt.state)
                )
            ).all()
        ),
        imports=dict(
            (
                await db.execute(
                    select(ImportEntry.state, func.count()).group_by(ImportEntry.state)
                )
            ).all()
        ),
    )
