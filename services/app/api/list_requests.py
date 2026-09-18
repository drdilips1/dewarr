from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.dependencies import Database, Member
from app.api.requests import TargetView
from app.db.models import Operation
from app.domain import list_requests
from app.domain.acquisition import RequestSpec
from app.domain.list_requests import BatchInput

router = APIRouter(prefix="/lists/{list_id}/requests", tags=["list-requests"])


class BatchRecord(BaseModel):
    work_id: UUID
    title: str
    targets: list[TargetView]
    issue: str | None = None


class BatchReceipt(BaseModel):
    work_id: UUID
    request_id: UUID


class BatchView(BaseModel):
    id: UUID
    status: str
    message: str
    specification: RequestSpec
    expires_at: datetime
    records: list[BatchRecord]
    counts: dict[str, int]
    receipt: list[BatchReceipt] | None = None


class BatchSummary(BaseModel):
    id: UUID
    status: str
    message: str
    created_at: datetime
    count: int


class BatchPage(BaseModel):
    items: list[BatchSummary]
    total: int
    offset: int
    limit: int


async def view(db, user, operation):
    records = await list_requests.status_records(db, user, operation)
    counts = {
        key: 0
        for key in ("satisfied", "wanted", "pending", "awaiting-inventory", "paused", "unresolved")
    }
    for record in records:
        if record["issue"]:
            counts["unresolved"] += 1
        for target in record["targets"]:
            counts[target["state"]] += 1
    return BatchView(
        id=operation.id,
        status=operation.status,
        message=operation.message,
        specification=operation.payload["command"]["specification"],
        expires_at=operation.payload["expires_at"],
        records=records,
        counts=counts,
        receipt=operation.payload.get("receipt"),
    )


@router.post("/preview", response_model=BatchView)
async def preview(
    list_id: UUID,
    body: BatchInput,
    user: Member,
    db: Database,
    idempotency_key: str = Header(min_length=8, max_length=200),
):
    operation = await list_requests.preview(db, user, list_id, body, idempotency_key)
    response = await view(db, user, operation)
    await db.commit()
    return response


@router.get("", response_model=BatchPage)
async def history(
    list_id: UUID,
    user: Member,
    db: Database,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=50),
):
    await list_requests.owner_context(db, user.id, list_id)
    where = [
        Operation.owner_id == user.id,
        Operation.kind == list_requests.KIND,
        Operation.payload["command"]["list_id"].astext == str(list_id),
    ]
    rows = list(
        await db.scalars(
            select(Operation)
            .where(*where)
            .order_by(Operation.created_at.desc(), Operation.id)
            .offset(offset)
            .limit(limit)
        )
    )
    for row in rows:
        await list_requests.repair(db, row)
    response = BatchPage(
        items=[
            BatchSummary(
                id=r.id,
                status=r.status,
                message=r.message,
                created_at=r.created_at,
                count=len(r.payload["records"]),
            )
            for r in rows
        ],
        total=await db.scalar(select(func.count()).select_from(Operation).where(*where)),
        offset=offset,
        limit=limit,
    )
    await db.commit()
    return response


@router.get("/{operation_id}", response_model=BatchView)
async def detail(list_id: UUID, operation_id: UUID, user: Member, db: Database):
    operation = await list_requests.owned(db, user, list_id, operation_id)
    response = await view(db, user, operation)
    await db.commit()
    return response


@router.post("/{operation_id}/submit", response_model=BatchView, status_code=202)
async def submit(list_id: UUID, operation_id: UUID, user: Member, db: Database):
    operation = await list_requests.owned(db, user, list_id, operation_id)
    await list_requests.start(db, user, operation)
    response = await view(db, user, operation)
    await db.commit()
    return response


@router.post("/{operation_id}/cancel", response_model=BatchView)
async def cancel(list_id: UUID, operation_id: UUID, user: Member, db: Database):
    operation = await list_requests.owned(db, user, list_id, operation_id)
    await list_requests.cancel(db, user, operation)
    response = await view(db, user, operation)
    await db.commit()
    return response
