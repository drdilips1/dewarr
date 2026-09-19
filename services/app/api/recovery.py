from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.dependencies import Admin, Database
from app.config import get_settings
from app.db.models import DownloadAttempt, ImportEntry, Operation, RecoveryFinding, RecoveryScan
from app.recovery import active_restore, restore_pending

router = APIRouter(prefix="/recovery", tags=["recovery"])


class RecoveryView(BaseModel):
    paused: bool
    backup_id: UUID | None
    restored_at: datetime | None
    downloads: dict[str, int]
    imports: dict[str, int]
    resume_available: bool = False
    latest_scan: "ScanView | None" = None


class ScanView(BaseModel):
    id: UUID
    state: str
    created_at: datetime
    finished_at: datetime | None
    summary: dict
    message: str


async def scan_view(db, scan):
    operation = await db.get(Operation, scan.operation_id)
    return ScanView(
        id=scan.id,
        state=scan.state,
        created_at=scan.created_at,
        finished_at=scan.finished_at,
        summary=scan.summary,
        message=operation.message,
    )


@router.get("", response_model=RecoveryView)
async def review(admin: Admin, db: Database):
    checkpoint = await active_restore(db)
    latest = (
        await db.scalar(
            select(RecoveryScan)
            .where(RecoveryScan.checkpoint_id == checkpoint.id)
            .order_by(RecoveryScan.created_at.desc())
            .limit(1)
        )
        if checkpoint
        else None
    )
    return RecoveryView(
        paused=get_settings().recovery_mode or await restore_pending(db),
        backup_id=checkpoint.backup_id if checkpoint else None,
        restored_at=checkpoint.created_at if checkpoint else None,
        latest_scan=await scan_view(db, latest) if latest else None,
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


@router.post("/scans", response_model=ScanView, status_code=202)
async def begin_scan(
    admin: Admin, db: Database, idempotency_key: str = Header(min_length=8, max_length=200)
):
    from app.domain.recovery_scans import ScanHeld, start

    checkpoint = await active_restore(db)
    if not checkpoint or checkpoint.operator_id != admin.id:
        raise HTTPException(409, "An active restore checkpoint is required")
    try:
        scan = await start(db, checkpoint, idempotency_key)
    except ScanHeld as error:
        raise HTTPException(409, str(error)) from None
    await db.commit()
    return await scan_view(db, scan)


class FindingView(BaseModel):
    id: UUID
    domain: str
    state: str
    title: str
    message: str
    entity_id: UUID | None
    evidence: dict
    has_evidence: bool


class FindingsPage(BaseModel):
    scan: ScanView
    items: list[FindingView]
    total: int
    next_offset: int | None


@router.get("/scans/{scan_id}", response_model=FindingsPage)
async def findings(
    scan_id: UUID,
    admin: Admin,
    db: Database,
    offset: int = Query(0, ge=0, le=30000),
    domain: str | None = Query(None, pattern="^(downloads|library|lists|files|review)$"),
):
    checkpoint = await active_restore(db)
    scan = await db.get(RecoveryScan, scan_id)
    if (
        not checkpoint
        or checkpoint.operator_id != admin.id
        or not scan
        or scan.checkpoint_id != checkpoint.id
    ):
        raise HTTPException(404, "Recovery observation not found")
    conditions = [RecoveryFinding.scan_id == scan.id]
    if domain:
        conditions.append(RecoveryFinding.domain == domain)
    total = await db.scalar(select(func.count()).select_from(RecoveryFinding).where(*conditions))
    summary_fields = [
        "external_id",
        "external_item_id",
        "medium",
        "integration_id",
        "saved_state",
        "source",
        "failure",
        "complete",
        "total_transfers",
        "relevant_transfers",
        "unrelated_transfers",
    ]
    summary = func.jsonb_strip_nulls(
        func.jsonb_build_object(
            *[value for key in summary_fields for value in (key, RecoveryFinding.evidence[key])]
        )
    )
    columns = [
        getattr(RecoveryFinding, key)
        for key in FindingView.model_fields
        if key not in {"evidence", "has_evidence"}
    ]
    rows = (
        (
            await db.execute(
                select(
                    *columns,
                    summary.label("evidence"),
                    (RecoveryFinding.evidence != {}).label("has_evidence"),
                )
                .where(*conditions)
                .order_by(RecoveryFinding.position)
                .offset(offset)
                .limit(50)
            )
        )
        .mappings()
        .all()
    )
    return FindingsPage(
        scan=await scan_view(db, scan),
        items=[FindingView(**row) for row in rows],
        total=total,
        next_offset=offset + 50 if offset + 50 < total else None,
    )


@router.get("/scans/{scan_id}/findings/{finding_id}", response_model=FindingView)
async def finding_detail(scan_id: UUID, finding_id: UUID, admin: Admin, db: Database):
    checkpoint = await active_restore(db)
    scan = await db.get(RecoveryScan, scan_id)
    if (
        not checkpoint
        or checkpoint.operator_id != admin.id
        or not scan
        or scan.checkpoint_id != checkpoint.id
    ):
        raise HTTPException(404, "Recovery observation not found")
    row = await db.get(RecoveryFinding, finding_id)
    if not row or row.scan_id != scan.id:
        raise HTTPException(404, "Recovery finding not found")
    return FindingView(
        **{key: getattr(row, key) for key in FindingView.model_fields if key != "has_evidence"},
        has_evidence=bool(row.evidence),
    )
