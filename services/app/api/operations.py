from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.dependencies import Admin, CurrentUser, Database
from app.config import get_settings
from app.db.models import Operation
from app.domain.operations import transaction_lock
from app.jobs.queue import enqueue

router = APIRouter(tags=["operations"])


class OperationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    kind: str
    status: str
    message: str
    created_at: datetime
    updated_at: datetime


@router.get("/activity", response_model=list[OperationView])
async def activity(user: CurrentUser, db: Database):
    return (
        await db.scalars(
            select(Operation)
            .where(Operation.owner_id == user.id)
            .order_by(Operation.created_at.desc())
            .limit(100)
        )
    ).all()


@router.post("/system/probe", response_model=OperationView, status_code=202)
async def probe(
    admin: Admin,
    db: Database,
    idempotency_key: str = Header(min_length=8, max_length=200),
):
    if get_settings().recovery_mode:
        raise HTTPException(409, "Dispatch is paused for recovery")
    await transaction_lock(db, f"operation:{admin.id}:{idempotency_key}")
    existing = await db.scalar(
        select(Operation).where(
            Operation.owner_id == admin.id,
            Operation.idempotency_key == idempotency_key,
        )
    )
    if existing:
        if existing.kind != "system.probe":
            raise HTTPException(409, "This operation key was already used for another command")
        return existing
    operation = Operation(
        owner_id=admin.id,
        kind="system.probe",
        idempotency_key=idempotency_key,
    )
    db.add(operation)
    await db.flush()
    operation.job_id = await enqueue(db, "system.probe", operation_id=str(operation.id))
    await db.commit()
    await db.refresh(operation)
    return operation
