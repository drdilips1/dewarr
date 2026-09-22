from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from app.api.dependencies import Admin, Database
from app.config import get_settings
from app.db.models import (
    DownloadInspection,
    FrozenImportPlan,
    Operation,
)
from app.domain.operations import transaction_lock
from app.importing.filesystem import relative_parts
from app.importing.inspection import InspectionSnapshot
from app.importing.naming import (
    StrictModel,
)
from app.importing.planning import FreezeInput, FrozenPlanView, assert_admin, owned_inspection
from app.importing.planning import freeze_plan as plan_import_command
from app.importing.storage import import_sources
from app.jobs.queue import enqueue

router = APIRouter(prefix="/organization", tags=["organization"])


class InspectInput(StrictModel):
    source_key: str = Field(pattern=r"^[a-z0-9_-]{1,60}$")
    relative_path: str = Field(min_length=1, max_length=1024)
    completed_download: Literal[True]

    @model_validator(mode="after")
    def valid_path(self):
        relative_parts(self.relative_path)
        return self


class InspectionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime
    operation_id: UUID
    source_key: str
    relative_path: str
    state: str
    message: str
    snapshot: InspectionSnapshot | None = None


@router.get("/download-roots", response_model=list[str])
async def download_roots(admin: Admin, db: Database):
    return sorted(await import_sources(db))


@router.post("/inspections", status_code=202, response_model=InspectionView)
async def create_inspection(
    body: InspectInput,
    admin: Admin,
    db: Database,
    idempotency_key: str = Header(min_length=8, max_length=200),
):
    if get_settings().recovery_mode:
        raise HTTPException(409, "Inspection is paused for recovery")
    root = (await import_sources(db)).get(body.source_key)
    if not root:
        raise HTTPException(422, "Select a download root configured on the worker")
    await transaction_lock(db, f"operation:{admin.id}:{idempotency_key}")
    await assert_admin(db, admin.id)
    payload = {**body.model_dump(), "source_path": str(root)}
    operation = await db.scalar(
        select(Operation).where(
            Operation.owner_id == admin.id, Operation.idempotency_key == idempotency_key
        )
    )
    if operation:
        if operation.kind != "organization.inspect" or operation.payload != payload:
            raise HTTPException(409, "This operation key was already used for another command")
        return await db.scalar(
            select(DownloadInspection).where(DownloadInspection.operation_id == operation.id)
        )
    operation = Operation(
        owner_id=admin.id,
        kind="organization.inspect",
        idempotency_key=idempotency_key,
        payload=payload,
    )
    db.add(operation)
    await db.flush()
    row = DownloadInspection(
        owner_id=admin.id,
        operation_id=operation.id,
        source_key=body.source_key,
        source_path=str(root),
        relative_path=body.relative_path,
    )
    db.add(row)
    operation.job_id = await enqueue(db, "organization.inspect", operation_id=str(operation.id))
    await db.commit()
    await db.refresh(row)
    return row


@router.get("/inspections", response_model=list[InspectionView])
async def inspections(admin: Admin, db: Database, offset: int = Query(0, ge=0)):
    # Summary list does not load potentially large file snapshots.
    rows = (
        (
            await db.execute(
                select(
                    DownloadInspection.id,
                    DownloadInspection.created_at,
                    DownloadInspection.operation_id,
                    DownloadInspection.source_key,
                    DownloadInspection.relative_path,
                    DownloadInspection.state,
                    DownloadInspection.message,
                )
                .where(DownloadInspection.owner_id == admin.id)
                .order_by(DownloadInspection.created_at.desc(), DownloadInspection.id)
                .offset(offset)
                .limit(25)
            )
        )
        .mappings()
        .all()
    )
    return [InspectionView.model_validate(row) for row in rows]


@router.get("/inspections/{inspection_id}", response_model=InspectionView)
async def inspection(inspection_id: UUID, admin: Admin, db: Database):
    return await owned_inspection(db, admin.id, inspection_id)


@router.post("/inspections/{inspection_id}/plans", response_model=FrozenPlanView, status_code=201)
async def freeze_plan(inspection_id: UUID, body: FreezeInput, admin: Admin, db: Database):
    row = await plan_import_command(db, admin, inspection_id, body)
    await db.commit()
    return row


@router.get("/plans/{plan_id}", response_model=FrozenPlanView)
async def frozen_plan(plan_id: UUID, admin: Admin, db: Database):
    row = await db.scalar(
        select(FrozenImportPlan).where(
            FrozenImportPlan.id == plan_id, FrozenImportPlan.owner_id == admin.id
        )
    )
    if not row:
        raise HTTPException(404, "Import plan not found")
    return row
