"""Fresh, scoped review of local/Hardcover differences before another intent."""

import json
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.adapters.contracts import AdapterError
from app.adapters.hardcover_writeback import Observation
from app.api.dependencies import Database, Member
from app.api.list_writeback import command
from app.config import get_settings
from app.db.models import AuditEvent, Operation, Work
from app.domain import list_curation
from app.domain import list_writeback as service
from app.domain.visibility import visible_work
from app.domain.work_graph import canonical_work, graph_lock
from app.security import decrypt_secrets

router = APIRouter(prefix="/lists/{list_id}/writeback", tags=["list-writeback"])


class WritebackChangePreviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    work_id: UUID


class WritebackChangePreviewView(BaseModel):
    id: UUID
    work_id: UUID
    title: str
    local_present: bool
    remote_present: bool
    remote_memberships: int
    expires_at: datetime


class WritebackResolveInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_id: UUID
    action: Literal["apply_local", "keep_remote"]


class WritebackResolutionView(BaseModel):
    id: UUID
    message: str
    outbound_id: UUID | None = None


async def review_context(db, owner_id, list_id, work_id):
    ctx = await service.context(db, owner_id, list_id)
    _, owner, account, subscription, policy = ctx
    external_id = service.binding(account, subscription)
    if (
        not policy
        or policy.subscription_id != subscription.id
        or policy.account_generation != account.generation
    ):
        raise HTTPException(409, "Review and enable write-back for the current account first")
    await graph_lock(db)
    work = await canonical_work(db, work_id)
    if not await db.scalar(select(Work.id).where(Work.id == work.id, visible_work(owner))):
        raise HTTPException(404, "Book not found")
    book_id, _ = await service.external_identity(db, owner, work.id, subscription)
    if not book_id:
        raise HTTPException(
            409, "Match this book to one Hardcover identity before reviewing its list difference"
        )
    return (
        ctx,
        work,
        {
            "list_id": str(list_id),
            "work_id": str(work.id),
            "external_list_id": external_id,
            "book_id": book_id,
            "account_generation": account.generation,
            "policy_generation": policy.generation,
            "subscription_id": str(subscription.id),
            "remote_owner_id": policy.remote_owner_id,
            "revision": await list_curation.content_revision(db, list_id),
            "episode": await service.episode(db, list_id, work.id),
        },
    )


@router.post("/changes/preview", response_model=WritebackChangePreviewView)
async def preview(
    list_id: UUID,
    body: WritebackChangePreviewInput,
    user: Member,
    db: Database,
    idempotency_key: str = Header(min_length=8, max_length=200),
):
    owner_id = user.id
    ctx, work, before = await review_context(db, owner_id, list_id, body.work_id)
    payload = {"list_id": str(list_id), **body.model_dump(mode="json")}
    old = await command(db, owner_id, idempotency_key, "lists.writeback.review", payload)
    if old:
        return WritebackChangePreviewView(id=old.id, **old.payload["view"])
    secret = decrypt_secrets(ctx[2].encrypted_token)["token"]
    await db.commit()
    try:
        remote = await service.fetch_membership(
            owner_id,
            before["account_generation"],
            secret,
            before["external_list_id"],
            before["book_id"],
        )
    except (AdapterError, TimeoutError) as error:
        await service.context(db, owner_id, list_id)
        raise HTTPException(
            422,
            str(error)
            if isinstance(error, AdapterError)
            else "Hardcover membership check timed out",
        ) from None
    _, work, after = await review_context(db, owner_id, list_id, body.work_id)
    old = await command(db, owner_id, idempotency_key, "lists.writeback.review", payload)
    if old:
        return WritebackChangePreviewView(id=old.id, **old.payload["view"])
    if before != after or remote.owner_id != before["remote_owner_id"]:
        raise HTTPException(409, "List, book or account changed; create a fresh review")
    view = {
        "work_id": str(work.id),
        "title": work.title,
        "local_present": bool(before["episode"]),
        "remote_present": bool(remote.memberships),
        "remote_memberships": len(remote.memberships),
        "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
    }
    operation = Operation(
        owner_id=owner_id,
        kind="lists.writeback.review",
        idempotency_key=idempotency_key,
        status="completed",
        message="Current local and Hardcover membership compared",
        payload={
            "command": payload,
            "view": view,
            "binding": before,
            "observation": remote.model_dump(mode="json"),
        },
    )
    db.add(operation)
    await db.commit()
    return WritebackChangePreviewView(id=operation.id, **view)


@router.post("/changes/resolve", response_model=WritebackResolutionView)
async def resolve(
    list_id: UUID,
    body: WritebackResolveInput,
    user: Member,
    db: Database,
    idempotency_key: str = Header(min_length=8, max_length=200),
):
    if get_settings().recovery_mode:
        raise HTTPException(409, "List changes are paused for recovery")
    await service.context(db, user.id, list_id)
    payload = {"list_id": str(list_id), **body.model_dump(mode="json")}
    old = await command(db, user.id, idempotency_key, "lists.writeback.resolve", payload)
    if old:
        return WritebackResolutionView(id=old.id, **old.payload["receipt"])
    saved = await db.get(Operation, body.preview_id)
    if (
        not saved
        or saved.owner_id != user.id
        or saved.kind != "lists.writeback.review"
        or saved.payload["command"]["list_id"] != str(list_id)
    ):
        raise HTTPException(404, "Membership review not found")
    from app.domain.recovery_approvals import require_current

    await require_current(db, "operation", saved.id)
    ctx, work, current = await review_context(
        db, user.id, list_id, UUID(saved.payload["binding"]["work_id"])
    )
    if current != saved.payload["binding"] or datetime.fromisoformat(
        saved.payload["view"]["expires_at"]
    ) < datetime.now(UTC):
        raise HTTPException(
            409, "Membership review expired or changed; compare the current state again"
        )
    base = Observation.model_validate_json(json.dumps(saved.payload["observation"]))
    unresolved = await db.scalar(
        select(Operation.id)
        .where(
            Operation.kind == service.KIND,
            Operation.payload["remote_owner_id"].as_integer() == base.owner_id,
            Operation.payload["external_list_id"].as_integer() == base.list_id,
            Operation.payload["book_id"].as_integer() == base.book_id,
            Operation.payload["pending_attempt"].astext.is_not(None),
        )
        .limit(1)
    )
    if unresolved:
        raise HTTPException(
            409,
            "An earlier write is still unconfirmed; check its remote state before resolving "
            "this difference",
        )
    if body.action == "apply_local" and not ctx[4].enabled:
        raise HTTPException(409, "Enable write-back before applying local membership to Hardcover")
    resolution = Operation(
        owner_id=user.id,
        kind="lists.writeback.resolve",
        idempotency_key=idempotency_key,
        status="completed",
        payload={"command": payload},
    )
    db.add(resolution)
    await db.flush()
    # Retire only this owner's inactive intents for the same reviewed target.
    for row in await db.scalars(
        select(Operation).where(
            *service.records(list_id),
            Operation.owner_id == user.id,
            Operation.status.in_(["attention", "paused"]),
            Operation.payload["book_id"].as_integer() == base.book_id,
            Operation.payload["external_list_id"].as_integer() == base.list_id,
        )
    ):
        row.status, row.message = "superseded", "Resolved by a newer membership review"
        row.payload = {**row.payload, "resolved_by": str(resolution.id)}
    outbound = None
    if body.action == "apply_local":
        outbound = await service.record_change(
            db, ctx[1], list_id, work.id, bool(current["episode"]), base=base
        )
        message = "Reviewed local membership queued for Hardcover confirmation"
    else:
        await list_curation.curate(
            db,
            ctx[1],
            list_id,
            list_curation.CurationInput(
                action="add" if base.memberships else "remove",
                work_ids=[work.id],
                expected_revision=current["revision"],
            ),
            f"writeback-resolution:{resolution.id}",
            suppress_writeback=True,
        )
        message = "Local membership now matches the reviewed Hardcover state"
    receipt = {"message": message, "outbound_id": str(outbound.id) if outbound else None}
    resolution.message, resolution.payload = message, {**resolution.payload, "receipt": receipt}
    db.add(
        AuditEvent(
            actor_id=user.id,
            action="list.writeback.resolved",
            entity_id=resolution.id,
            detail={"action": body.action},
        )
    )
    await db.commit()
    return WritebackResolutionView(id=resolution.id, **receipt)
