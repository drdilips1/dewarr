"""Paged membership differences and explicit, atomic selected reconciliation."""

import json
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select

from app.adapters.hardcover_writeback import Observation
from app.api.dependencies import Database, Member
from app.api.list_writeback import command
from app.config import get_settings
from app.db.models import AuditEvent, ListComparisonRow, Operation
from app.domain import hardcover_subscriptions as hardcover
from app.domain import list_comparisons as service
from app.domain import list_curation
from app.domain import list_writeback as writes

router = APIRouter(prefix="/lists/{list_id}/writeback/differences", tags=["list-writeback"])


class ListDifferenceView(BaseModel):
    id: UUID
    work_id: UUID | None
    title: str
    state: str
    local_present: bool | None
    remote_present: bool | None
    remote_memberships: int | None
    can_apply_local: bool
    can_keep_remote: bool
    reason: str | None


class ListDifferencePage(BaseModel):
    id: UUID
    status: str
    message: str
    expires_at: datetime | None
    counts: dict[str, int]
    items: list[ListDifferenceView]
    total: int
    offset: int
    limit: int


class ListDifferenceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    row_ids: list[UUID] = Field(min_length=1, max_length=100)
    action: Literal["apply_local", "keep_remote"]
    expected_policy_generation: int = Field(ge=0)

    @model_validator(mode="after")
    def distinct(self):
        if len(set(self.row_ids)) != len(self.row_ids):
            raise ValueError("Select each difference only once")
        return self


class ListDifferenceReceipt(BaseModel):
    id: UUID
    selected: int
    action: str
    outbound_ids: list[UUID]
    message: str


def row_view(row):
    observation = row.snapshot.get("observation")
    supported = row.state in {"local_only", "remote_only"}
    return ListDifferenceView(
        id=row.id,
        work_id=row.work_id,
        title=row.title,
        state=row.state,
        local_present=row.snapshot["local"],
        remote_present=bool(observation["memberships"]) if observation else None,
        remote_memberships=len(observation["memberships"]) if observation else None,
        can_apply_local=supported and row.work_id is not None,
        can_keep_remote=supported,
        reason=row.snapshot.get("reason")
        or (
            "Add this Hardcover book locally or match its catalog identity before sending a removal"
            if supported and row.work_id is None
            else None
        ),
    )


@router.get("/{comparison_id}", response_model=ListDifferencePage)
async def page(
    list_id: UUID,
    comparison_id: UUID,
    user: Member,
    db: Database,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
    state: Literal["differences", "all", "local_only", "remote_only", "unmatched"] = "differences",
    q: str = Query(default="", max_length=200),
):
    operation, _ = await service.current(db, comparison_id, user.id, list_id)
    if operation.status in {"queued", "running"}:
        await writes.repair_job(db, operation)
        if operation.status == "attention":
            operation.status, operation.message = (
                "failed",
                "Comparison worker ended; compare existing books again",
            )
    counts = dict(
        (
            await db.execute(
                select(ListComparisonRow.state, func.count())
                .where(ListComparisonRow.comparison_id == comparison_id)
                .group_by(ListComparisonRow.state)
            )
        ).all()
    )
    where = [ListComparisonRow.comparison_id == comparison_id]
    if state == "differences":
        where.append(ListComparisonRow.state != "same")
    elif state != "all":
        where.append(ListComparisonRow.state == state)
    if q.strip():
        from app.api.lists import search_pattern

        where.append(ListComparisonRow.title.ilike(search_pattern(q), escape="\\"))
    total = await db.scalar(select(func.count()).select_from(ListComparisonRow).where(*where))
    rows = await db.scalars(
        select(ListComparisonRow)
        .where(*where)
        .order_by(ListComparisonRow.position)
        .offset(offset)
        .limit(limit)
    )
    result = ListDifferencePage(
        id=operation.id,
        status=operation.status,
        message=operation.message,
        expires_at=operation.payload.get("expires_at"),
        counts=counts,
        items=[row_view(row) for row in rows],
        total=total or 0,
        offset=offset,
        limit=limit,
    )
    await db.commit()
    return result


@router.post("/{comparison_id}/resolve", response_model=ListDifferenceReceipt)
async def resolve(
    list_id: UUID,
    comparison_id: UUID,
    body: ListDifferenceSelection,
    user: Member,
    db: Database,
    idempotency_key: str = Header(min_length=8, max_length=200),
):
    if get_settings().recovery_mode:
        raise HTTPException(409, "List changes are paused for recovery")
    await writes.context(db, user.id, list_id)
    payload = {
        "list_id": str(list_id),
        "comparison_id": str(comparison_id),
        **body.model_dump(mode="json"),
    }
    old = await command(db, user.id, idempotency_key, "lists.writeback.compare.resolve", payload)
    if old:
        return ListDifferenceReceipt(id=old.id, **old.payload["receipt"])
    comparison, ctx = await service.current(db, comparison_id, user.id, list_id)
    if comparison.status != "completed":
        raise HTTPException(409, "Wait for the complete verified comparison")
    policy = ctx[4]
    if body.expected_policy_generation != (policy.generation if policy else 0):
        raise HTTPException(409, "Write-back settings changed; review the selection again")
    if body.action == "apply_local" and (
        not policy
        or not policy.enabled
        or policy.account_generation != ctx[2].generation
        or policy.subscription_id != ctx[3].id
        or policy.remote_owner_id != comparison.payload["remote_owner_id"]
    ):
        raise HTTPException(409, "Enable write-back for this owned Hardcover list first")
    rows = list(
        await db.scalars(
            select(ListComparisonRow)
            .where(
                ListComparisonRow.comparison_id == comparison_id,
                ListComparisonRow.id.in_(body.row_ids),
            )
            .order_by(ListComparisonRow.position)
        )
    )
    if len(rows) != len(body.row_ids) or any(
        row.state not in {"local_only", "remote_only"}
        or body.action == "apply_local"
        and row.work_id is None
        for row in rows
    ):
        raise HTTPException(
            409, "Some selected differences need catalog matching before this action"
        )
    bases = [
        Observation.model_validate_json(json.dumps(row.snapshot["observation"])) for row in rows
    ]
    unresolved = await db.scalar(
        select(Operation.id)
        .where(
            Operation.kind == writes.KIND,
            Operation.payload["remote_owner_id"].as_integer()
            == comparison.payload["remote_owner_id"],
            Operation.payload["external_list_id"].as_integer()
            == comparison.payload["binding"]["external_list_id"],
            Operation.payload["book_id"].as_integer().in_([base.book_id for base in bases]),
            Operation.payload["pending_attempt"].astext.is_not(None),
        )
        .limit(1)
    )
    if unresolved:
        raise HTTPException(
            409, "A selected book has an unconfirmed write; check its remote state first"
        )
    resolution = Operation(
        owner_id=user.id,
        kind="lists.writeback.compare.resolve",
        idempotency_key=idempotency_key,
        status="completed",
        payload={"command": payload},
    )
    db.add(resolution)
    await db.flush()
    outbound = []
    for row, base in zip(rows, bases, strict=True):
        work_id = row.work_id
        if work_id is not None:
            identity, _ = await writes.external_identity(db, user, work_id, ctx[3])
            if identity != base.book_id:
                raise HTTPException(409, "Selected catalog identity changed; compare again")
        elif body.action == "keep_remote":
            work = await hardcover.catalog_match(db, user, row.snapshot["record"])
            work_id = work.id
            await db.flush()
            identity, _ = await writes.external_identity(db, user, work_id, ctx[3])
            if identity != base.book_id:
                raise HTTPException(409, "This Hardcover book needs catalog identity review")
        if body.action == "apply_local":
            operation = await writes.record_change(
                db, user, list_id, work_id, row.snapshot["local"], base=base
            )
            outbound.append(operation.id)
        else:
            await list_curation.curate(
                db,
                user,
                list_id,
                list_curation.CurationInput(
                    action="add" if base.memberships else "remove",
                    work_ids=[work_id],
                ),
                f"comparison:{resolution.id}:{row.id}",
                suppress_writeback=True,
            )
    for previous in await db.scalars(
        select(Operation).where(
            *writes.records(list_id),
            Operation.status.in_(["attention", "paused"]),
            Operation.payload["book_id"].as_integer().in_([base.book_id for base in bases]),
            Operation.payload["external_list_id"].as_integer()
            == comparison.payload["binding"]["external_list_id"],
        )
    ):
        previous.status, previous.message = (
            "superseded",
            "Resolved by a selected membership comparison",
        )
    outcome = "queued for Hardcover confirmation" if outbound else "applied to this local list"
    receipt = {
        "selected": len(rows),
        "action": body.action,
        "outbound_ids": [str(key) for key in outbound],
        "message": f"{len(rows)} selected membership differences {outcome}",
    }
    resolution.payload, resolution.message = (
        {**resolution.payload, "receipt": receipt},
        receipt["message"],
    )
    comparison.payload = {**comparison.payload, "consumed_by": str(resolution.id)}
    db.add(
        AuditEvent(
            actor_id=user.id,
            action="list.comparison.resolved",
            entity_id=resolution.id,
            detail={"action": body.action, "selected": len(rows)},
        )
    )
    await db.commit()
    return ListDifferenceReceipt(id=resolution.id, **receipt)
