import json
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.adapters.list_csv import MAX_BYTES, MAX_ROWS, parse_snapshot
from app.api.dependencies import Database, Member
from app.api.operations import OperationView
from app.db.models import ListCsvImport, Operation, User, Work
from app.domain import list_csv
from app.domain.availability import Availability, availability_for
from app.domain.list_subscriptions import owned_list
from app.domain.visibility import visible_work
from app.domain.work_graph import graph_lock

router = APIRouter(prefix="/lists/{list_id}/csv", tags=["list-csv"])


class CsvRow(BaseModel):
    row_number: int
    title: str
    authors: list[str]
    isbn: str | None
    isbn13: str | None
    external_id: str | None
    shelves: list[str]
    work_id: UUID | None = None
    issue: str | None = None
    availability: Availability = Field(default_factory=Availability)


class CsvPreview(BaseModel):
    id: UUID | None
    headers: list[str]
    mapping: dict[str, str]
    records: list[CsvRow]
    duplicates: int
    shelves: list[str]
    needs_mapping: bool = False
    expires_at: datetime | None = None
    state: str = "preview"
    message: str = "Review these additions. This snapshot never removes books or starts downloads."
    receipt: dict[str, int] | None = None
    selected_rows: list[int] | None = None


class CsvSelection(BaseModel):
    rows: list[int] = Field(min_length=1, max_length=MAX_ROWS)


async def require_owner(db, user, list_id):
    await owned_list(db, user, list_id)
    current = await db.scalar(
        select(User)
        .where(User.id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not current.active or current.role == "viewer":
        raise HTTPException(403, "Your account cannot change this list")


async def imported_row(db, user, list_id, import_id):
    await require_owner(db, user, list_id)
    row = await db.scalar(
        select(ListCsvImport).where(
            ListCsvImport.id == import_id,
            ListCsvImport.list_id == list_id,
            ListCsvImport.owner_id == user.id,
        )
    )
    if not row:
        raise HTTPException(404, "CSV preview not found")
    return row


async def view(db, user, row):
    from app.domain.recovery_approvals import denial

    hold = await denial(db, "csv-preview", row.id) if not row.committed_at else None
    if hold:
        operation = await db.get(Operation, row.operation_id) if row.operation_id else None
    else:
        operation = await list_csv.repair(db, row)
    records = []
    allowed = set(
        await db.scalars(
            select(Work.id).where(
                Work.id.in_(
                    [UUID(r["work_id"]) for r in row.snapshot["records"] if r.get("work_id")]
                ),
                visible_work(user),
            )
        )
    )
    availability = await availability_for(db, user, list(allowed))
    for value in row.snapshot["records"]:
        record = CsvRow.model_validate(value)
        if record.work_id and record.work_id not in allowed:
            record.work_id = None
            record.issue = "Catalog access changed; upload again to review"
        if record.work_id:
            record.availability = availability[record.work_id]
        records.append(record)
    return CsvPreview(
        id=row.id,
        **{k: row.snapshot[k] for k in ("headers", "mapping", "duplicates", "shelves")},
        records=records,
        expires_at=row.expires_at,
        state="held" if hold else operation.status if operation else "preview",
        message=hold
        or (
            operation.message
            if operation
            else "Review these additions. This snapshot never removes books or starts downloads."
        ),
        receipt=row.receipt,
        selected_rows=row.selected_rows,
    )


@router.post(
    "/preview",
    response_model=CsvPreview,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"text/csv": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
async def preview(
    list_id: UUID,
    request: Request,
    user: Member,
    db: Database,
    mapping: str | None = Query(default=None, max_length=4000),
    encoding: Literal["auto", "utf-8-sig", "cp1252"] = "auto",
    delimiter: Literal[",", ";", "\t"] = ",",
):
    # Authenticate and authorize before accepting a potentially large private file.
    # No database locks are held while receiving the upload.
    from app.db.models import BookList

    if not await db.scalar(
        select(BookList.id).where(BookList.id == list_id, BookList.owner_id == user.id)
    ):
        raise HTTPException(404, "List not found")
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_BYTES:
            raise HTTPException(413, "CSV files must be no larger than 4 MiB")
        content.extend(chunk)
    try:
        columns = json.loads(mapping) if mapping is not None else None
        snapshot = parse_snapshot(
            bytes(content), mapping=columns, encoding=encoding, delimiter=delimiter
        )
    except (ValueError, TypeError) as error:
        raise HTTPException(
            422,
            str(error)
            if not isinstance(error, json.JSONDecodeError)
            else "Column mapping must be a JSON object",
        ) from None
    if snapshot.needs_mapping:
        return CsvPreview(
            id=None,
            headers=snapshot.headers,
            mapping=snapshot.mapping,
            records=[],
            duplicates=0,
            shelves=[],
            needs_mapping=True,
            message="Choose the title column to preview this file",
        )
    await require_owner(db, user, list_id)
    await graph_lock(db)
    records = []
    for record in snapshot.records:
        work, issue = await list_csv.resolve(db, user, record)
        records.append({**record, "work_id": str(work.id) if work else None, "issue": issue})
    # Bound abandoned previews per owner; completed receipts are retained.
    old = (
        await db.scalars(
            select(ListCsvImport.id)
            .where(ListCsvImport.owner_id == user.id, ListCsvImport.operation_id.is_(None))
            .order_by(ListCsvImport.created_at.desc())
            .offset(9)
        )
    ).all()
    if old:
        await db.execute(delete(ListCsvImport).where(ListCsvImport.id.in_(old)))
    row = ListCsvImport(
        owner_id=user.id,
        list_id=list_id,
        expires_at=datetime.now(UTC) + timedelta(hours=24),
        snapshot={
            "headers": snapshot.headers,
            "mapping": snapshot.mapping,
            "records": records,
            "duplicates": snapshot.duplicates,
            "shelves": snapshot.shelves,
        },
    )
    db.add(row)
    await db.flush()
    result = await view(db, user, row)
    await db.commit()
    return result


@router.get("", response_model=list[CsvPreview])
async def recent(list_id: UUID, user: Member, db: Database):
    await require_owner(db, user, list_id)
    rows = (
        await db.scalars(
            select(ListCsvImport)
            .where(ListCsvImport.list_id == list_id, ListCsvImport.owner_id == user.id)
            .order_by(ListCsvImport.created_at.desc())
            .limit(10)
        )
    ).all()
    # History is compact; full rows are fetched only for the selected preview.
    results = []
    for row in rows:
        operation = await list_csv.repair(db, row)
        results.append(
            CsvPreview(
                id=row.id,
                headers=[],
                mapping={},
                records=[],
                duplicates=row.snapshot["duplicates"],
                shelves=[],
                expires_at=row.expires_at,
                state=operation.status if operation else "preview",
                message=operation.message if operation else "Saved CSV preview",
                receipt=row.receipt,
                selected_rows=row.selected_rows,
            )
        )
    await db.commit()
    return results


@router.get("/{import_id}", response_model=CsvPreview)
async def detail(list_id: UUID, import_id: UUID, user: Member, db: Database):
    row = await imported_row(db, user, list_id, import_id)
    result = await view(db, user, row)
    await db.commit()
    return result


@router.post("/{import_id}/commit", response_model=OperationView, status_code=202)
async def commit(list_id: UUID, import_id: UUID, body: CsvSelection, user: Member, db: Database):
    row = await imported_row(db, user, list_id, import_id)
    operation = await list_csv.start(db, user, list_id, row, body.rows)
    await db.commit()
    await db.refresh(operation)
    return operation
