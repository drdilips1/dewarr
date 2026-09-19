from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, text

from app.api.dependencies import Admin, Database
from app.api.imports import assert_admin
from app.config import get_settings
from app.db.models import (
    AuditEvent,
    ImportDestination,
    ImportEntry,
    ImportRun,
    Operation,
)
from app.importing.destinations import destination_configuration
from app.importing.starting import ImportInput
from app.importing.starting import start_import as start_import_command
from app.jobs.queue import enqueue

router = APIRouter(prefix="/organization", tags=["organization"])


class CoverExportView(BaseModel):
    state: Literal["prepared", "unavailable"]
    message: str
    sha256: str | None = None
    backend_selected: bool | None = None
    unchanged: bool | None = None


class EntryView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    group_id: UUID
    version_id: UUID
    destination_id: UUID | None
    operation_id: UUID | None
    state: str
    message: str
    published_at: datetime | None
    confirmed_at: datetime | None
    asset_id: UUID | None
    can_retry: bool = False
    can_cancel: bool = False
    cover_export: CoverExportView | None = None


class RunView(BaseModel):
    id: UUID
    plan_id: UUID
    created_at: datetime
    entries: list[EntryView]


async def view(db, run):
    from app.domain.recovery_approvals import denial

    hold = await denial(db, "import-plan", run.plan_id)
    entries = (
        await db.scalars(
            select(ImportEntry)
            .where(ImportEntry.run_id == run.id)
            .order_by(ImportEntry.created_at, ImportEntry.id)
        )
    ).all()
    return RunView(
        id=run.id,
        plan_id=run.plan_id,
        created_at=run.created_at,
        entries=[
            EntryView.model_validate(entry).model_copy(
                update={
                    "can_retry": bool(
                        not hold
                        and entry.reserved
                        and entry.specification
                        and entry.state in {"held", "awaiting-library"}
                    ),
                    "can_cancel": not hold
                    and not entry.published_at
                    and entry.state in {"queued", "publishing", "held", "cancel-held"},
                    **({"message": hold} if hold and not entry.confirmed_at else {}),
                }
            )
            for entry in entries
        ],
    )


@router.post("/plans/{plan_id}/imports", response_model=RunView, status_code=202)
async def start_import(
    plan_id: UUID,
    body: ImportInput,
    admin: Admin,
    db: Database,
    idempotency_key: str = Header(min_length=8, max_length=200),
):
    run = await start_import_command(db, admin, plan_id, body, idempotency_key)
    await db.commit()
    return await view(db, run)


@router.post("/imports/{run_id}/entries/{entry_id}/cancel", response_model=RunView, status_code=202)
async def cancel_entry(run_id: UUID, entry_id: UUID, admin: Admin, db: Database):
    await assert_admin(db, admin.id)
    if get_settings().recovery_mode:
        raise HTTPException(409, "Import changes are paused for recovery")
    run = await db.scalar(
        select(ImportRun).where(ImportRun.id == run_id, ImportRun.owner_id == admin.id)
    )
    entry = await db.get(ImportEntry, entry_id, with_for_update=True)
    if not run or not entry or entry.run_id != run.id:
        raise HTTPException(404, "Import entry not found")
    if entry.state == "cancelled":
        return await view(db, run)
    from app.domain.recovery_approvals import require_current

    await require_current(db, "import-plan", run.plan_id)
    if entry.published_at or entry.state in {"confirmed", "skipped", "awaiting-library"}:
        raise HTTPException(
            409, "This book was already published or satisfied; its files are preserved"
        )
    if entry.state == "cancelling":
        return await view(db, run)  # Periodic recovery handles failed/expired queue attempts.
    entry.run_token, entry.next_check_at = None, None
    if not entry.specification and not entry.reserved:
        entry.state = "cancelled"
        entry.message = "Unstarted import stopped; you can review a new plan"
    else:
        operation = await db.get(Operation, entry.operation_id)
        status = await db.scalar(
            text("SELECT status::text FROM book_queue.procrastinate_jobs WHERE id=:id"),
            {"id": operation.job_id},
        )
        entry.state = "cancelling"
        entry.message = "Stopping import after checking whether any files were already published"
        entry.next_check_at = datetime.now(UTC) + timedelta(minutes=1)
        operation.status, operation.message = "queued", entry.message
        if status != "todo":
            operation.job_id = await enqueue(
                db, "organization.publish", operation_id=str(operation.id)
            )
    db.add(
        AuditEvent(
            actor_id=admin.id, action="organization.import.cancel-requested", entity_id=entry.id
        )
    )
    await db.commit()
    return await view(db, run)


@router.get("/plans/{plan_id}/imports", response_model=list[RunView])
async def plan_imports(plan_id: UUID, admin: Admin, db: Database):
    rows = (
        await db.scalars(
            select(ImportRun)
            .where(ImportRun.plan_id == plan_id, ImportRun.owner_id == admin.id)
            .order_by(ImportRun.created_at.desc())
            .limit(25)
        )
    ).all()
    return [await view(db, row) for row in rows]


@router.get("/imports/{run_id}", response_model=RunView)
async def import_run(run_id: UUID, admin: Admin, db: Database):
    row = await db.scalar(
        select(ImportRun).where(ImportRun.id == run_id, ImportRun.owner_id == admin.id)
    )
    if not row:
        raise HTTPException(404, "Import not found")
    return await view(db, row)


@router.post("/imports/{run_id}/entries/{entry_id}/retry", response_model=RunView, status_code=202)
async def retry_entry(run_id: UUID, entry_id: UUID, admin: Admin, db: Database):
    await assert_admin(db, admin.id)
    if get_settings().recovery_mode:
        raise HTTPException(409, "Publication is paused for recovery")
    run = await db.scalar(
        select(ImportRun).where(ImportRun.id == run_id, ImportRun.owner_id == admin.id)
    )
    entry = await db.get(ImportEntry, entry_id, with_for_update=True)
    if not run or not entry or entry.run_id != run.id:
        raise HTTPException(404, "Import entry not found")
    if (
        entry.state not in {"held", "awaiting-library"}
        or not entry.reserved
        or not entry.specification
    ):
        raise HTTPException(409, "This entry cannot be retried; review or create a fresh plan")
    operation = await db.get(Operation, entry.operation_id)
    from app.domain.recovery_approvals import require_current

    await require_current(db, "operation", operation.id)
    # Never restart a live job solely because its observation is delayed.
    from sqlalchemy import text

    status = await db.scalar(
        text("SELECT status::text FROM book_queue.procrastinate_jobs WHERE id=:id"),
        {"id": operation.job_id},
    )
    if status in {"todo", "doing"}:
        return await view(db, run)
    destination = await db.get(ImportDestination, entry.destination_id)
    current = await destination_configuration(db, destination)
    previous = entry.configuration["destination"]

    # Explicit retry may use a rotated token for the same server/library/paths.
    def without_generation(value):
        return {
            **value,
            "backend": {key: item for key, item in value["backend"].items() if key != "generation"},
        }

    if without_generation(previous) != without_generation(current):
        raise HTTPException(
            409, "The frozen server, library or paths changed; resolve the mapping before retrying"
        )
    entry.configuration = {**entry.configuration, "destination": current}
    entry.state = "awaiting-library" if entry.published_at else "queued"
    entry.message = "Import retry requested"
    operation.status = "queued"
    operation.job_id = await enqueue(db, "organization.publish", operation_id=str(operation.id))
    db.add(AuditEvent(actor_id=admin.id, action="organization.import.retry", entity_id=entry.id))
    await db.commit()
    return await view(db, run)
