from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select

from app.adapters.goodreads import feed_identity, feed_url
from app.api.dependencies import Database, Member
from app.api.operations import OperationView
from app.db.models import AuditEvent, ListEntry, ListObservation, ListSubscription, Operation, Work
from app.domain.acquisition import withdraw_list_reasons
from app.domain.list_subscriptions import begin, ensure_membership, owned_list, repair_job
from app.domain.visibility import visible_work
from app.domain.work_graph import canonical_work, family_ids, graph_lock
from app.security import decrypt_secrets, encrypt_secrets

router = APIRouter(prefix="/lists/{list_id}/subscription", tags=["list-subscriptions"])


class SubscriptionInput(BaseModel):
    feed_url: str | None = Field(default=None, max_length=2000)
    enabled: bool = True
    interval_minutes: int = Field(default=30, ge=30, le=1440)
    expected_generation: int = Field(default=0, ge=0)

    @field_validator("feed_url")
    @classmethod
    def url(cls, value):
        return feed_url(value) if value else None


class SubscriptionView(BaseModel):
    id: UUID
    generation: int
    enabled: bool
    interval_minutes: int
    state: str
    message: str
    shelf: str
    feed_configured: bool = True
    last_success_at: datetime | None
    baseline_at: datetime | None
    next_sync_at: datetime | None
    observed_count: int
    excluded_count: int
    completeness: str = "partial-feed"
    acquisition_mode: str = "browse"


class ObservationView(BaseModel):
    id: UUID
    external_id: str
    work_id: UUID | None
    title: str
    authors: list[str]
    catalog_title: str | None
    excluded: bool
    identity_changed: bool
    first_seen_at: datetime
    last_seen_at: datetime


class ObservationPage(BaseModel):
    items: list[ObservationView]
    total: int
    offset: int
    limit: int


class ObservationInput(BaseModel):
    excluded: bool | None = None
    work_id: UUID | None = None


async def subscription(db, user, list_id):
    await owned_list(db, user, list_id)
    return await db.scalar(select(ListSubscription).where(ListSubscription.list_id == list_id))


async def view(db, row):
    await repair_job(db, row)
    count, excluded = (
        await db.execute(
            select(func.count(), func.count().filter(ListObservation.excluded.is_(True))).where(
                ListObservation.subscription_id == row.id
            )
        )
    ).one()
    return SubscriptionView(
        id=row.id,
        generation=row.generation,
        enabled=row.enabled,
        interval_minutes=row.interval_minutes,
        state=row.state,
        message=row.message,
        shelf=feed_identity(decrypt_secrets(row.encrypted_config)["url"])[1],
        last_success_at=row.last_success_at,
        baseline_at=row.baseline_at,
        next_sync_at=row.next_sync_at,
        observed_count=count,
        excluded_count=excluded,
    )


@router.get("", response_model=SubscriptionView | None)
async def detail(list_id: UUID, user: Member, db: Database):
    row = await subscription(db, user, list_id)
    result = await view(db, row) if row else None
    await db.commit()
    return result


@router.put("", response_model=SubscriptionView)
async def configure(list_id: UUID, body: SubscriptionInput, user: Member, db: Database):
    row = await subscription(db, user, list_id)
    if not row:
        if body.expected_generation or not body.feed_url:
            raise HTTPException(422, "Enter a feed URL and revision zero to follow a shelf")
        row = ListSubscription(
            list_id=list_id, encrypted_config=encrypt_secrets({"url": body.feed_url})
        )
        db.add(row)
        await db.flush()
    else:
        if row.generation != body.expected_generation:
            raise HTTPException(409, "Shelf settings changed; reload before saving")
        config = decrypt_secrets(row.encrypted_config)
        if body.feed_url and feed_identity(body.feed_url) != feed_identity(config["url"]):
            raise HTTPException(
                422, "Follow a different shelf in a new list, or detach this subscription first"
            )
        if body.feed_url:
            # Credentials/ordering can change, but cached validators do not cross a changed URL.
            row.encrypted_config = encrypt_secrets({"url": body.feed_url})
        row.generation += 1
        if row.operation_id:
            operation = await db.get(Operation, row.operation_id)
            if operation.status in {"queued", "running"}:
                operation.status, operation.message = (
                    "failed",
                    "Shelf settings changed before observation finished",
                )
    row.enabled, row.interval_minutes = body.enabled, body.interval_minutes
    row.run_token, row.operation_id = None, None
    row.state = "idle" if body.enabled else "paused"
    row.message = (
        "Waiting for the next shelf observation"
        if body.enabled
        else "Observation paused; existing books and exclusions are preserved"
    )
    row.next_sync_at = datetime.now(UTC) if body.enabled else None
    db.add(AuditEvent(actor_id=user.id, action="list.subscription.configured", entity_id=row.id))
    result = await view(db, row)
    await db.commit()
    return result


@router.post("/sync", response_model=OperationView, status_code=202)
async def refresh(
    list_id: UUID,
    user: Member,
    db: Database,
    idempotency_key: str = Header(min_length=8, max_length=200),
):
    operation = await begin(db, user, list_id, idempotency_key)
    await db.commit()
    await db.refresh(operation)
    return operation


@router.delete("", status_code=204)
async def detach(list_id: UUID, user: Member, db: Database):
    row = await subscription(db, user, list_id)
    if not row:
        return
    for entry in await db.scalars(select(ListEntry).where(ListEntry.list_id == list_id)):
        entry.locally_added = True
    if row.operation_id:
        operation = await db.get(Operation, row.operation_id)
        if operation.status in {"queued", "running"}:
            operation.status, operation.message = "failed", "Shelf subscription detached"
    await db.delete(row)
    db.add(AuditEvent(actor_id=user.id, action="list.subscription.detached", entity_id=list_id))
    await db.commit()


@router.get("/observations", response_model=ObservationPage)
async def observations(list_id: UUID, user: Member, db: Database, offset: int = 0, limit: int = 50):
    if offset < 0 or not 1 <= limit <= 100:
        raise HTTPException(422, "Use a nonnegative offset and page size 1–100")
    row = await subscription(db, user, list_id)
    if not row:
        raise HTTPException(404, "Shelf subscription not found")
    total = await db.scalar(
        select(func.count())
        .select_from(ListObservation)
        .where(ListObservation.subscription_id == row.id)
    )
    records = list(
        await db.scalars(
            select(ListObservation)
            .where(ListObservation.subscription_id == row.id)
            .order_by(ListObservation.created_at, ListObservation.id)
            .offset(offset)
            .limit(limit)
        )
    )
    items = []
    for record in records:
        work = await canonical_work(db, record.work_id)
        allowed = await db.scalar(select(Work.id).where(Work.id == work.id, visible_work(user)))
        items.append(
            ObservationView(
                id=record.id,
                external_id=record.external_id,
                work_id=work.id if allowed else None,
                title=record.snapshot["title"],
                authors=record.snapshot["authors"],
                catalog_title=work.title if allowed else None,
                excluded=record.excluded,
                identity_changed=record.snapshot.get("identity_changed", False),
                first_seen_at=record.created_at,
                last_seen_at=record.last_seen_at,
            )
        )
    return ObservationPage(items=items, total=total or 0, offset=offset, limit=limit)


async def remove_unneeded(db, user, row, work_id):
    kept = await db.scalar(
        select(ListObservation.id)
        .where(
            ListObservation.subscription_id == row.id,
            ListObservation.work_id.in_(family_ids(work_id)),
            ListObservation.excluded.is_(False),
        )
        .limit(1)
    )
    if not kept:
        await db.execute(
            delete(ListEntry).where(
                ListEntry.list_id == row.list_id,
                ListEntry.work_id.in_(family_ids(work_id)),
                ListEntry.locally_added.is_(False),
            )
        )
        remaining = await db.scalar(
            select(ListEntry.id)
            .where(ListEntry.list_id == row.list_id, ListEntry.work_id.in_(family_ids(work_id)))
            .limit(1)
        )
        if not remaining:
            await withdraw_list_reasons(db, user, row.list_id, work_id)


@router.patch("/observations/{observation_id}", status_code=204)
async def change_observation(
    list_id: UUID, observation_id: UUID, body: ObservationInput, user: Member, db: Database
):
    row = await subscription(db, user, list_id)
    record = await db.get(ListObservation, observation_id)
    if not row or not record or record.subscription_id != row.id:
        raise HTTPException(404, "Shelf observation not found")
    await graph_lock(db)
    previous = record.work_id
    if body.work_id:
        work = await canonical_work(db, body.work_id)
        if not await db.scalar(select(Work.id).where(Work.id == work.id, visible_work(user))):
            raise HTTPException(404, "Catalog book not found")
        record.work_id = work.id
        record.snapshot = {**record.snapshot, "identity_changed": False, "manual_match": True}
    if body.excluded is not None:
        record.excluded = body.excluded
    await db.flush()
    await remove_unneeded(db, user, row, previous)
    await ensure_membership(db, row, record)
    db.add(AuditEvent(actor_id=user.id, action="list.observation.updated", entity_id=record.id))
    await db.commit()
