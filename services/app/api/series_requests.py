from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.dependencies import Database, Member
from app.api.list_requests import BatchReceipt, BatchSummary
from app.api.requests import TargetView
from app.db.models import Operation
from app.domain import series_acquisition, series_requests
from app.domain.acquisition import RequestSpec
from app.domain.release_profiles import ProfileSnapshot
from app.domain.series_requests import SeriesRequestInput

router = APIRouter(
    prefix="/catalog/series/hardcover/{external_id}/requests", tags=["series-requests"]
)


class SeriesRequestRecord(BaseModel):
    work_id: UUID
    title: str
    authors: list[str]
    warnings: list[str]
    position: str | None = None
    targets: list[TargetView]
    issue: str | None
    acquisition_state: str | None = None
    acquisition_message: str | None = None
    next_check_at: datetime | None = None


class OmittedSeriesBook(BaseModel):
    work_id: UUID
    title: str
    warnings: list[str]
    reason: str


class SeriesRequestView(BaseModel):
    id: UUID
    status: str
    message: str
    series_name: str
    catalog_generation: int
    scope: str
    main_membership: str
    specification: RequestSpec
    release_policy: ProfileSnapshot
    expires_at: datetime
    accepted_at: datetime | None
    records: list[SeriesRequestRecord]
    omitted: list[OmittedSeriesBook]
    counts: dict[str, int]
    receipt: list[BatchReceipt] | None
    automatic: bool = False
    acquisition_status: str | None = None
    acquisition_message: str | None = None
    can_retry_acquisition: bool = False


class SeriesRequestHistory(BaseModel):
    items: list[BatchSummary]
    total: int
    offset: int
    limit: int


async def view(db, user, operation):
    records = await series_requests.status_records(db, user, operation)
    controller = (
        await db.get(Operation, UUID(operation.payload["acquisition_id"]))
        if operation.payload.get("acquisition_id")
        else None
    )
    if controller:
        for record in records:
            progress = controller.payload["books"].get(record["_origin_work_id"], {})
            record.update(
                acquisition_state=progress.get("state"),
                acquisition_message=progress.get("message"),
                next_check_at=progress.get("next_at"),
            )
    counts = {
        key: 0
        for key in (
            "satisfied",
            "wanted",
            "pending",
            "awaiting-inventory",
            "paused",
            "unresolved",
            "cancelled",
        )
    }
    for record in records:
        if record["issue"]:
            counts["unresolved"] += 1
        for target in record["targets"]:
            counts[target["state"]] += 1
    payload = operation.payload
    return SeriesRequestView(
        id=operation.id,
        status=operation.status,
        message=operation.message,
        series_name=payload["series"]["name"],
        catalog_generation=payload["series"]["generation"],
        scope=payload["command"]["scope"],
        main_membership=payload["main_membership"],
        specification=payload["effective_specification"],
        release_policy=payload["release_policy"],
        expires_at=payload["expires_at"],
        accepted_at=payload.get("accepted_at"),
        records=records,
        omitted=payload["omitted"],
        counts=counts,
        receipt=payload.get("receipt"),
        automatic=bool(payload.get("automatic_configuration")),
        acquisition_status=controller.status if controller else None,
        acquisition_message=controller.message if controller else None,
        can_retry_acquisition=bool(
            controller
            and (
                controller.status == "held"
                or any(book["state"] == "held" for book in controller.payload["books"].values())
            )
            and controller.payload["enabled"]
            and operation.status == "completed"
            and await series_acquisition.job_status(db, controller) not in {"todo", "doing"}
        ),
    )


@router.post("/preview", response_model=SeriesRequestView, status_code=201)
async def preview(
    external_id: str,
    body: SeriesRequestInput,
    user: Member,
    db: Database,
    idempotency_key: str = Header(min_length=8, max_length=200),
):
    operation = await series_requests.preview(db, user, external_id, body, idempotency_key)
    response = await view(db, user, operation)
    await db.commit()
    return response


@router.post("/{operation_id}/retry-acquisition", response_model=SeriesRequestView, status_code=202)
async def retry_acquisition(external_id: str, operation_id: UUID, user: Member, db: Database):
    operation = await series_requests.owned(db, user, external_id, operation_id)
    await series_acquisition.retry(db, user, operation)
    response = await view(db, user, operation)
    await db.commit()
    return response


@router.get("", response_model=SeriesRequestHistory)
async def history(
    external_id: str,
    user: Member,
    db: Database,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=50),
):
    await series_requests.context(db, user.id, external_id)
    where = [
        Operation.owner_id == user.id,
        Operation.kind == series_requests.KIND,
        Operation.payload["command"]["external_id"].astext == external_id,
    ]
    operations = list(
        await db.scalars(
            select(Operation)
            .where(*where)
            .order_by(Operation.created_at.desc(), Operation.id)
            .offset(offset)
            .limit(limit)
        )
    )
    return SeriesRequestHistory(
        items=[
            BatchSummary(
                id=o.id,
                status=o.status,
                message=o.message,
                created_at=o.created_at,
                count=len(o.payload["records"]),
            )
            for o in operations
        ],
        total=await db.scalar(select(func.count()).select_from(Operation).where(*where)),
        offset=offset,
        limit=limit,
    )


@router.get("/{operation_id}", response_model=SeriesRequestView)
async def detail(external_id: str, operation_id: UUID, user: Member, db: Database):
    operation = await series_requests.owned(db, user, external_id, operation_id)
    response = await view(db, user, operation)
    await db.commit()
    return response


@router.post("/{operation_id}/submit", response_model=SeriesRequestView, status_code=202)
async def submit(external_id: str, operation_id: UUID, user: Member, db: Database):
    operation = await series_requests.owned(db, user, external_id, operation_id)
    await series_requests.start(db, user, operation)
    response = await view(db, user, operation)
    await db.commit()
    return response


@router.post("/{operation_id}/cancel", response_model=SeriesRequestView)
async def cancel(external_id: str, operation_id: UUID, user: Member, db: Database):
    operation = await series_requests.owned(db, user, external_id, operation_id)
    await series_requests.cancel(db, user, operation)
    response = await view(db, user, operation)
    await db.commit()
    return response
