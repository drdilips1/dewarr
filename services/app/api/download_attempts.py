from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.adapters.contracts import AdapterError
from app.api.dependencies import Admin, CurrentUser, Database, Member
from app.api.metadata import adapter_http_error
from app.db.models import (
    AcquisitionIntent,
    AcquisitionSelection,
    AcquisitionTarget,
    AutomaticImport,
    DownloadAttempt,
    DownloadFulfillment,
    DownloadInspection,
    ImportEntry,
)
from app.domain import download_attempts as downloads
from app.domain import download_repairs as repairs
from app.domain.acquisition import RequestSpec, assess
from app.domain.acquisition_selection import configuration_current

router = APIRouter(prefix="/acquisition/downloads", tags=["downloads"])


class StartInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selection_id: UUID


class FulfillmentView(BaseModel):
    confirmed_at: datetime
    basis: str
    available_now: bool


class RepairInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")


class RepairPreview(BaseModel):
    revision: str
    changes: list[str]


class RepairView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    state: str
    message: str
    changes: list[str]
    created_at: datetime
    applied_at: datetime | None


class AttemptView(BaseModel):
    id: UUID
    created_at: datetime
    selection_id: UUID
    operation_id: UUID
    state: str
    work_title: str
    release_title: str
    message: str
    external_may_exist: bool
    can_recheck: bool
    can_cancel: bool
    progress: float | None
    inspection_id: UUID | None
    fulfillment: FulfillmentView | None
    repair: RepairView | None
    can_repair: bool


class AttemptPage(BaseModel):
    items: list[AttemptView]
    total: int
    offset: int
    limit: int


async def view(db, user, row, selection):
    message = row.message
    automatic = await db.scalar(select(AutomaticImport).where(AutomaticImport.attempt_id == row.id))
    if automatic and automatic.state == "held":
        message = automatic.message
    if automatic and automatic.import_run_id:
        if await db.scalar(
            select(ImportEntry.id).where(
                ImportEntry.run_id == automatic.import_run_id,
                ImportEntry.state.in_(["held", "cancel-held"]),
            )
        ):
            message = "Import needs administrator attention; the completed download is preserved"
    inspection = await db.get(DownloadInspection, row.inspection_id) if row.inspection_id else None
    repair = await repairs.latest(db, row.id)
    repairing = bool(repair and repair.state == "pending")
    repairable = (
        user.role == "admin"
        and row.external_may_exist
        and not repairing
        and row.state not in {"complete", "cancelled"}
        and (not row.lease_until or row.lease_until <= datetime.now(UTC))
    )
    needs_review = repairable and not await configuration_current(
        db,
        selection,
        committed=True,
        configuration=await repairs.accepted_configuration(db, selection),
    )
    fulfillment = await db.scalar(
        select(DownloadFulfillment).where(
            DownloadFulfillment.attempt_id == row.id,
            DownloadFulfillment.target_id == selection.target_id,
        )
    )
    confirmed = None
    if fulfillment:
        intent = await db.get(AcquisitionIntent, selection.intent_id)
        target = await db.get(AcquisitionTarget, selection.target_id)
        outcomes = await assess(
            db, user, intent.work_id, RequestSpec.model_validate(intent.specification)
        )
        confirmed = FulfillmentView(
            confirmed_at=fulfillment.created_at,
            basis=fulfillment.evidence["basis"],
            available_now=any(
                item["slot"] == target.slot and item["state"] == "satisfied" for item in outcomes
            ),
        )
    return AttemptView(
        id=row.id,
        created_at=row.created_at,
        selection_id=row.selection_id,
        operation_id=row.operation_id,
        state=row.state,
        work_title=selection.frozen["work_title"],
        release_title=selection.frozen["release"]["title"],
        message=message,
        external_may_exist=row.external_may_exist,
        can_cancel=not row.external_may_exist and row.state != "cancelled",
        can_recheck=row.state != "cancelled"
        and not repairing
        and (not row.lease_until or row.lease_until <= datetime.now(UTC))
        and (not row.next_check_at or row.next_check_at <= datetime.now(UTC)),
        progress=(row.observation or {}).get("progress"),
        inspection_id=inspection.id
        if inspection and inspection.owner_id == user.id and user.role == "admin"
        else None,
        fulfillment=confirmed,
        repair=RepairView.model_validate(repair) if repair else None,
        can_repair=needs_review,
    )


@router.post("", response_model=AttemptView, status_code=202)
async def start(
    body: StartInput,
    user: Member,
    db: Database,
    idempotency_key: str = Header(min_length=8, max_length=200),
):
    try:
        row = await downloads.start(db, user, body.selection_id, idempotency_key)
    except AdapterError as error:
        raise adapter_http_error(error) from error
    result = await view(db, user, row, await db.get(AcquisitionSelection, row.selection_id))
    await db.commit()
    return result


@router.get("", response_model=AttemptPage)
async def listing(
    user: CurrentUser,
    db: Database,
    selection_id: UUID | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    where = [DownloadAttempt.owner_id == user.id]
    if selection_id:
        where.append(DownloadAttempt.selection_id == selection_id)
    rows = await db.scalars(
        select(DownloadAttempt)
        .where(*where)
        .order_by(DownloadAttempt.created_at.desc(), DownloadAttempt.id)
        .offset(offset)
        .limit(limit)
    )
    rows = list(rows)
    selections = {
        item.id: item
        for item in await db.scalars(
            select(AcquisitionSelection).where(
                AcquisitionSelection.id.in_([row.selection_id for row in rows])
            )
        )
    }
    return AttemptPage(
        items=[await view(db, user, row, selections[row.selection_id]) for row in rows],
        offset=offset,
        limit=limit,
        total=await db.scalar(select(func.count()).select_from(DownloadAttempt).where(*where)),
    )


@router.get("/{attempt_id}", response_model=AttemptView)
async def detail(attempt_id: UUID, user: CurrentUser, db: Database):
    row = await downloads.owned_attempt(db, user, attempt_id)
    return await view(db, user, row, await db.get(AcquisitionSelection, row.selection_id))


@router.delete("/{attempt_id}", response_model=AttemptView)
async def cancel(attempt_id: UUID, user: Member, db: Database):
    row = await downloads.cancel(db, user, attempt_id)
    result = await view(db, user, row, await db.get(AcquisitionSelection, row.selection_id))
    await db.commit()
    return result


@router.post("/{attempt_id}/recheck", response_model=AttemptView, status_code=202)
async def recheck(attempt_id: UUID, user: Member, db: Database):
    row = await downloads.recheck(db, user, attempt_id)
    result = await view(db, user, row, await db.get(AcquisitionSelection, row.selection_id))
    await db.commit()
    return result


@router.get("/{attempt_id}/repair-preview", response_model=RepairPreview)
async def repair_preview(attempt_id: UUID, user: Admin, db: Database):
    return await repairs.preview(db, user, attempt_id)


@router.post("/{attempt_id}/repairs", response_model=RepairView, status_code=202)
async def repair_download(
    attempt_id: UUID,
    body: RepairInput,
    user: Admin,
    db: Database,
    idempotency_key: str = Header(min_length=8, max_length=200),
):
    try:
        row = await repairs.start(db, user, attempt_id, body.revision, idempotency_key)
    except AdapterError as error:
        raise adapter_http_error(error) from error
    result = RepairView.model_validate(row)
    await db.commit()
    return result
