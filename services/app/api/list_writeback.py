from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.adapters.contracts import AdapterError
from app.api.dependencies import Database, Member
from app.config import get_settings
from app.db.models import AuditEvent, ListWritebackPolicy, Operation, Work
from app.domain import list_writeback as service
from app.domain.list_curation import content_revision
from app.domain.operations import transaction_lock
from app.domain.visibility import visible_work
from app.domain.work_graph import canonical_work, graph_lock
from app.jobs.queue import enqueue
from app.security import decrypt_secrets

router = APIRouter(prefix="/lists/{list_id}/writeback", tags=["list-writeback"])


class WritebackPolicyView(BaseModel):
    generation: int
    enabled: bool
    available: bool
    message: str
    external_list_id: int | None = None
    confirmed_at: datetime | None = None


class WritebackPreviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_generation: int = Field(default=0, ge=0)


class WritebackPreviewView(BaseModel):
    id: UUID
    list_name: str
    external_list_id: int
    expires_at: datetime
    comparison_id: UUID | None = None
    message: str = (
        "Enable future local membership changes only; existing differences will not be sent"
    )


class WritebackConfigureInput(WritebackPreviewInput):
    enabled: bool
    preview_id: UUID | None = None


class WritebackIntentView(BaseModel):
    id: UUID
    work_id: UUID | None
    title: str
    desired_present: bool
    status: str
    message: str
    created_at: datetime
    may_have_applied: bool


class WritebackIntentPage(BaseModel):
    items: list[WritebackIntentView]
    total: int
    offset: int
    limit: int


async def intent_view(db, user, operation):
    work = await canonical_work(db, UUID(operation.payload["work_id"]))
    allowed = await db.scalar(select(Work.id).where(Work.id == work.id, visible_work(user)))
    return WritebackIntentView(
        id=operation.id,
        work_id=work.id if allowed else None,
        title=work.title if allowed else "Unavailable book",
        desired_present=operation.payload["desired"],
        status=operation.status,
        message=operation.message,
        created_at=operation.created_at,
        may_have_applied=bool(operation.payload["pending_attempt"]),
    )


def policy_view(ctx):
    _, _, account, subscription, policy = ctx
    try:
        external_id = service.binding(account, subscription)
        available, message = (
            True,
            "Future local additions and removals can be synchronized to your owned Hardcover list",
        )
    except HTTPException as error:
        external_id, available, message = None, False, str(error.detail)
    if (
        policy
        and policy.enabled
        and (
            not account
            or policy.account_generation != account.generation
            or not subscription
            or policy.subscription_id != subscription.id
        )
    ):
        available, message = (
            False,
            "Account or subscription changed; review and enable write-back again",
        )
    return WritebackPolicyView(
        generation=policy.generation if policy else 0,
        enabled=bool(policy and policy.enabled),
        available=available,
        message=message,
        external_list_id=external_id,
        confirmed_at=policy.confirmed_at if policy else None,
    )


async def command(db, owner_id, key, kind, payload):
    await transaction_lock(db, f"operation:{owner_id}:{key}")
    old = await db.scalar(
        select(Operation).where(Operation.owner_id == owner_id, Operation.idempotency_key == key)
    )
    if old and (old.kind != kind or old.payload.get("command") != payload):
        raise HTTPException(409, "This command key was already used for a different action")
    return old


@router.get("", response_model=WritebackPolicyView)
async def detail(list_id: UUID, user: Member, db: Database):
    return policy_view(await service.context(db, user.id, list_id))


@router.post("/preview", response_model=WritebackPreviewView)
async def preview(
    list_id: UUID,
    body: WritebackPreviewInput,
    user: Member,
    db: Database,
    idempotency_key: str = Header(min_length=8, max_length=200),
):
    owner_id = user.id
    ctx = await service.context(db, owner_id, list_id)
    payload = {"list_id": str(list_id), **body.model_dump(mode="json")}
    old = await command(db, owner_id, idempotency_key, "lists.writeback.preview", payload)
    if old:
        return WritebackPreviewView(id=old.id, **old.payload["view"])
    _, _, account, subscription, policy = ctx
    if body.expected_generation != (policy.generation if policy else 0):
        raise HTTPException(409, "Write-back settings changed; reload before previewing")
    external_id = service.binding(account, subscription)
    account_generation, subscription_id = account.generation, subscription.id
    secret = decrypt_secrets(account.encrypted_token)["token"]
    await graph_lock(db)
    revision = await content_revision(db, list_id)
    await db.commit()
    try:
        remote = await service.fetch_owner(owner_id, account_generation, secret, external_id)
    except (AdapterError, TimeoutError) as error:
        # Authorization is rechecked even when the provider failed during I/O.
        await service.context(db, owner_id, list_id)
        raise HTTPException(
            422,
            str(error)
            if isinstance(error, AdapterError)
            else "Hardcover ownership check timed out",
        ) from None
    ctx = await service.context(db, owner_id, list_id)
    old = await command(db, owner_id, idempotency_key, "lists.writeback.preview", payload)
    if old:
        return WritebackPreviewView(id=old.id, **old.payload["view"])
    _, _, account, subscription, policy = ctx
    await graph_lock(db)
    if (
        service.binding(account, subscription) != external_id
        or account.generation != account_generation
        or subscription.id != subscription_id
        or (policy.generation if policy else 0) != body.expected_generation
        or revision != await content_revision(db, list_id)
    ):
        raise HTTPException(409, "Account, list or membership changed; create a fresh preview")
    from app.domain import list_comparisons

    comparison = await list_comparisons.start(db, owner_id, ctx, remote.owner_id)
    view = {
        "list_name": remote.name,
        "external_list_id": remote.id,
        "expires_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
        "comparison_id": str(comparison.id),
    }
    operation = Operation(
        owner_id=owner_id,
        kind="lists.writeback.preview",
        idempotency_key=idempotency_key,
        status="completed",
        message="Hardcover list ownership verified; write scope must allow the requested mutation",
        payload={
            "command": payload,
            "view": view,
            "account_generation": account_generation,
            "subscription_id": str(subscription_id),
            "remote_owner_id": remote.owner_id,
            "revision": revision,
        },
    )
    db.add(operation)
    await db.commit()
    return WritebackPreviewView(id=operation.id, **view)


@router.put("", response_model=WritebackPolicyView)
async def configure(
    list_id: UUID,
    body: WritebackConfigureInput,
    user: Member,
    db: Database,
    idempotency_key: str = Header(min_length=8, max_length=200),
):
    if body.enabled and get_settings().recovery_mode:
        raise HTTPException(409, "External writes are paused for recovery")
    ctx = await service.context(db, user.id, list_id)
    payload = {"list_id": str(list_id), **body.model_dump(mode="json")}
    old = await command(db, user.id, idempotency_key, "lists.writeback.configure", payload)
    if old:
        return policy_view(ctx)
    _, _, account, subscription, policy = ctx
    if body.expected_generation != (policy.generation if policy else 0):
        raise HTTPException(409, "Write-back settings changed; reload before saving")
    if body.enabled:
        external_id = service.binding(account, subscription)
        saved = await db.get(Operation, body.preview_id) if body.preview_id else None
        await graph_lock(db)
        if (
            not saved
            or saved.owner_id != user.id
            or saved.kind != "lists.writeback.preview"
            or saved.payload["command"]["list_id"] != str(list_id)
            or saved.payload["command"]["expected_generation"] != body.expected_generation
            or datetime.fromisoformat(saved.payload["view"]["expires_at"]) < datetime.now(UTC)
            or saved.payload["account_generation"] != account.generation
            or saved.payload["subscription_id"] != str(subscription.id)
            or saved.payload["view"]["external_list_id"] != external_id
            or saved.payload["revision"] != await content_revision(db, list_id)
        ):
            raise HTTPException(
                409, "Create a fresh ownership and membership preview before enabling write-back"
            )
        from app.domain import list_comparisons

        comparison_id = saved.payload["view"].get("comparison_id")
        if not comparison_id:
            raise HTTPException(409, "Create a new preview to compare existing memberships")
        comparison, _ = await list_comparisons.current(db, UUID(comparison_id), user.id, list_id)
        if comparison.status != "completed":
            raise HTTPException(409, "Wait for the existing membership comparison before enabling")
        if not policy:
            policy = ListWritebackPolicy(list_id=list_id, generation=0, sequence=0)
            db.add(policy)
        policy.subscription_id, policy.account_generation = subscription.id, account.generation
        policy.external_list_id, policy.remote_owner_id = (
            external_id,
            saved.payload["remote_owner_id"],
        )
        policy.confirmed_at = None
    elif not policy:
        raise HTTPException(409, "Write-back is already disabled")
    policy.generation += 1
    policy.enabled = body.enabled
    db.add(
        Operation(
            owner_id=user.id,
            kind="lists.writeback.configure",
            idempotency_key=idempotency_key,
            status="completed",
            message="Hardcover write-back enabled"
            if body.enabled
            else "Hardcover write-back paused",
            payload={"command": payload, "generation": policy.generation},
        )
    )
    db.add(
        AuditEvent(
            actor_id=user.id,
            action="list.writeback.configured",
            entity_id=list_id,
            detail={"enabled": body.enabled, "generation": policy.generation},
        )
    )
    await db.commit()
    return policy_view(await service.context(db, user.id, list_id))


@router.get("/changes", response_model=WritebackIntentPage)
async def history(
    list_id: UUID,
    user: Member,
    db: Database,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
):
    await service.context(db, user.id, list_id)
    where = (*service.records(list_id), Operation.owner_id == user.id)
    total = await db.scalar(select(func.count()).select_from(Operation).where(*where))
    rows = await db.scalars(
        select(Operation)
        .where(*where)
        .order_by(Operation.created_at.desc(), Operation.id)
        .offset(offset)
        .limit(limit)
    )
    await graph_lock(db)
    items = []
    for row in rows:
        await service.repair_job(db, row)
        items.append(await intent_view(db, user, row))
    await db.commit()
    return WritebackIntentPage(items=items, total=total or 0, offset=offset, limit=limit)


@router.post("/changes/{operation_id}/reconcile", response_model=WritebackIntentView)
async def reconcile(list_id: UUID, operation_id: UUID, user: Member, db: Database):
    if get_settings().recovery_mode:
        raise HTTPException(
            409, "External writes and reconciliation workers are paused for recovery"
        )
    await service.context(db, user.id, list_id)
    operation = await db.get(Operation, operation_id)
    if (
        not operation
        or operation.owner_id != user.id
        or operation.kind != service.KIND
        or operation.payload["list_id"] != str(list_id)
    ):
        raise HTTPException(404, "List change not found")
    if operation.payload["book_id"] is None:
        raise HTTPException(409, "Match this book to Hardcover, then review its list difference")
    await service.repair_job(db, operation)
    if operation.status in service.TERMINAL and operation.status != "completed":
        operation.payload = {**operation.payload, "reconcile_only": True, "observations": 0}
        operation.status, operation.message = (
            "queued",
            "Checking remote state without sending another mutation",
        )
        operation.job_id = await enqueue(db, service.KIND, operation_id=str(operation.id))
    await db.commit()
    await service.context(db, user.id, list_id)
    await graph_lock(db)
    return await intent_view(db, user, operation)
