from uuid import UUID

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, exists, func, or_, select

from app.adapters.contracts import AdapterError
from app.api.dependencies import Admin, Database
from app.api.metadata import adapter_http_error
from app.db.models import AcquisitionSelection, DownloadAttempt, DownloadHandoff
from app.domain import download_reviews as reviews

router = APIRouter(prefix="/acquisition/reviews", tags=["downloads"])


class ReviewView(BaseModel):
    attempt_id: UUID
    work_title: str
    medium: str
    message: str
    revision: str
    inspection_id: UUID | None
    can_claim: bool
    reassignment: bool
    retry: bool


class ReviewPage(BaseModel):
    items: list[ReviewView]
    total: int
    offset: int
    limit: int


class ClaimInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")


@router.get("", response_model=ReviewPage)
async def listing(
    admin: Admin,
    db: Database,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    active = exists().where(
        DownloadHandoff.attempt_id == DownloadAttempt.id, DownloadHandoff.active.is_(True)
    )
    pending = and_(
        DownloadAttempt.inspection_id.is_(None), AcquisitionSelection.state == "committed"
    )
    query = (
        select(DownloadAttempt, AcquisitionSelection)
        .join(AcquisitionSelection)
        .where(DownloadAttempt.state == "complete", or_(pending, active))
    )
    rows = await db.execute(
        query.order_by(DownloadAttempt.created_at, DownloadAttempt.id).offset(offset).limit(limit)
    )
    return ReviewPage(
        items=[
            await reviews.queue_view(db, admin, attempt, selection) for attempt, selection in rows
        ],
        total=await db.scalar(select(func.count()).select_from(query.subquery())),
        offset=offset,
        limit=limit,
    )


@router.post("/{attempt_id}/claim", response_model=ReviewView, status_code=202)
async def claim(
    attempt_id: UUID,
    body: ClaimInput,
    admin: Admin,
    db: Database,
    idempotency_key: str = Header(min_length=8, max_length=200),
):
    try:
        result = await reviews.claim(db, admin, attempt_id, body.revision, idempotency_key)
    except AdapterError as error:
        raise adapter_http_error(error) from error
    await db.commit()
    return result
