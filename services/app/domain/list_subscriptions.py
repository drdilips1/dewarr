"""Durable inbound shelf observation. Never dispatches, deletes media, or infers removals."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import func, or_, select, text

from app.adapters.contracts import AdapterError, FailureKind
from app.adapters.goodreads import fetch_feed
from app.config import get_settings
from app.db.models import (
    BookList,
    ListEntry,
    ListObservation,
    ListSubscription,
    Operation,
    RateLimit,
    User,
    Version,
    Work,
)
from app.db.session import session_factory
from app.domain.operations import transaction_lock
from app.domain.release_profiles import normalized
from app.domain.visibility import visible_origin_work, visible_work
from app.domain.work_graph import canonical_work, family_ids, graph_lock
from app.importing.match_evidence import ISBN_KEYS, isbn_forms
from app.jobs.queue import enqueue
from app.jobs.retry import ShelfRetry
from app.security import decrypt_secrets, encrypt_secrets


def next_due(row, now, *, failed=False, retry_after=0):
    # Stable subscription-specific jitter keeps restarts from aligning all feeds.
    delay = row.interval_minutes * 60
    if failed:
        delay = min(delay * 2 ** min(row.failures, 5), 86400)
    return now + timedelta(seconds=max(delay, retry_after) + row.id.int % 181)


async def owned_list(db, user, list_id):
    item = await db.scalar(
        select(BookList)
        .where(BookList.id == list_id, BookList.owner_id == user.id)
        .with_for_update()
    )
    if not item:
        raise HTTPException(404, "List not found")
    return item


async def repair_job(db, row):
    if row.state not in {"queued", "running"} or not row.operation_id:
        return
    operation = await db.get(Operation, row.operation_id)
    status = await db.scalar(
        text("SELECT status::text FROM book_queue.procrastinate_jobs WHERE id=:id"),
        {"id": operation.job_id},
    )
    if status not in {"todo", "doing"}:
        row.state, row.message = "failed", "Shelf worker stopped; the next observation will retry"
        row.failures += 1
        row.run_token = None
        row.next_sync_at = next_due(row, datetime.now(UTC), failed=True)
        operation.status, operation.message = "failed", row.message


async def begin(db, user, list_id, key):
    if get_settings().recovery_mode:
        raise HTTPException(409, "Shelf observations are paused for recovery")
    await owned_list(db, user, list_id)
    await transaction_lock(db, f"operation:{user.id}:{key}")
    old = await db.scalar(
        select(Operation).where(Operation.owner_id == user.id, Operation.idempotency_key == key)
    )
    if old:
        if old.kind != "lists.sync" or old.payload.get("list_id") != str(list_id):
            raise HTTPException(409, "This command was used for a different operation")
        return old
    row = await db.scalar(select(ListSubscription).where(ListSubscription.list_id == list_id))
    if not row or not row.enabled:
        raise HTTPException(409, "Enable a Goodreads subscription before refreshing")
    await repair_job(db, row)
    if row.state in {"queued", "running"}:
        return await db.get(Operation, row.operation_id)
    operation = Operation(
        owner_id=user.id,
        kind="lists.sync",
        idempotency_key=key,
        payload={
            "subscription_id": str(row.id),
            "list_id": str(list_id),
            "generation": row.generation,
        },
        message="Waiting to observe Goodreads shelf additions",
    )
    db.add(operation)
    await db.flush()
    operation.job_id = await enqueue(db, "lists.sync", operation_id=str(operation.id))
    row.operation_id, row.state, row.message = operation.id, "queued", operation.message
    return operation


async def context(db, operation_id):
    operation = await db.get(Operation, operation_id)
    if not operation or operation.kind != "lists.sync":
        return None
    item = await db.scalar(
        select(BookList).where(BookList.id == UUID(operation.payload["list_id"])).with_for_update()
    )
    row = await db.get(
        ListSubscription, UUID(operation.payload["subscription_id"]), populate_existing=True
    )
    owner = await db.scalar(
        select(User)
        .where(User.id == operation.owner_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        not item
        or not row
        or not owner
        or not owner.active
        or owner.role == "viewer"
        or item.owner_id != owner.id
        or not row.enabled
        or row.generation != operation.payload["generation"]
        or row.operation_id != operation.id
    ):
        operation.status, operation.message = (
            "failed",
            "Shelf observation settings or account access changed",
        )
        if row and row.operation_id == operation.id:
            row.state, row.message, row.run_token = "failed", operation.message, None
            row.next_sync_at = next_due(row, datetime.now(UTC), failed=True)
        return None
    return operation, row, owner


async def budget(db, *, block=0):
    await transaction_lock(db, "goodreads:rss-budget")
    now = datetime.now(UTC)
    row = await db.get(RateLimit, "goodreads:rss")
    if block:
        until = now + timedelta(seconds=block)
        if not row:
            db.add(RateLimit(key="goodreads:rss", count=1, resets_at=until))
        else:
            row.resets_at = max(row.resets_at, until)
        return 0
    if row and row.resets_at > now:
        return max(1, int((row.resets_at - now).total_seconds()) + 1)
    until = now + timedelta(seconds=5)
    if row:
        row.resets_at = until
    else:
        db.add(RateLimit(key="goodreads:rss", count=1, resets_at=until))
    return 0


async def catalog_match(db, owner, record):
    previous = await db.scalar(
        select(ListObservation)
        .join(ListSubscription)
        .join(BookList)
        .where(BookList.owner_id == owner.id, ListObservation.external_id == record["external_id"])
        .order_by(ListObservation.created_at)
        .limit(1)
    )
    if previous:
        work = await canonical_work(db, previous.work_id)
        if await db.scalar(select(Work.id).where(Work.id == work.id, visible_work(owner))):
            return work
    values = set()
    for key in ("isbn", "isbn13"):
        if record.get(key):
            values |= isbn_forms(record[key])
    if values and record["authors"]:
        clauses = [
            func.upper(
                func.regexp_replace(Version.identifiers[key].astext, r"[-[:space:]]", "", "g")
            ).in_(values)
            for key in ISBN_KEYS
        ]
        candidates = (
            await db.scalars(
                select(Work)
                .join(Version)
                .where(visible_origin_work(owner), or_(*clauses))
                .distinct()
                .limit(101)
            )
        ).all()
        matches = {}
        for work in candidates:
            if normalized(work.title) == normalized(record["title"]) and (
                {normalized(a) for a in work.authors} & {normalized(a) for a in record["authors"]}
            ):
                root = await canonical_work(db, work.id)
                matches[root.id] = root
        if len(matches) == 1 and len(candidates) < 101:
            return next(iter(matches.values()))
    work = Work(
        title=record["title"],
        authors=record["authors"],
        provisional=True,
        catalog_public=False,
        catalog_owner_id=owner.id,
    )
    db.add(work)
    await db.flush()
    return work


async def ensure_membership(db, row, observation):
    if observation.excluded:
        return
    exists = await db.scalar(
        select(ListEntry.id).where(
            ListEntry.list_id == row.list_id, ListEntry.work_id.in_(family_ids(observation.work_id))
        )
    )
    if not exists:
        position = await db.scalar(
            select(func.max(ListEntry.position)).where(ListEntry.list_id == row.list_id)
        )
        db.add(
            ListEntry(
                list_id=row.list_id,
                work_id=observation.work_id,
                position=(position or 0) + 1,
                locally_added=False,
            )
        )
        await db.flush()


async def apply_records(db, row, owner, items):
    await graph_lock(db)
    await transaction_lock(db, f"goodreads:catalog:{owner.id}")
    now, added = datetime.now(UTC), 0
    observed = {
        o.external_id: o
        for o in await db.scalars(
            select(ListObservation).where(ListObservation.subscription_id == row.id)
        )
    }
    for record in items:
        observation = observed.get(record["external_id"])
        if not observation:
            work = await catalog_match(db, owner, record)
            observation = ListObservation(
                subscription_id=row.id,
                external_id=record["external_id"],
                work_id=work.id,
                snapshot=record,
                last_seen_at=now,
                excluded=False,
            )
            db.add(observation)
            await db.flush()
            added += 1
        else:
            previous = observation.snapshot
            changed = any(
                previous.get(k) != record.get(k) for k in ("title", "authors", "isbn", "isbn13")
            )
            observation.snapshot = {
                **record,
                "identity_changed": bool(changed or previous.get("identity_changed")),
            }
            observation.last_seen_at = now
        await ensure_membership(db, row, observation)
    return added


async def run(operation_id):
    if get_settings().recovery_mode:
        raise ShelfRetry(60)
    token = uuid4()
    async with session_factory()() as db, db.begin():
        ctx = await context(db, operation_id)
        if not ctx:
            return
        operation, row, _ = ctx
        if operation.status in {"completed", "failed"}:
            return
        now = datetime.now(UTC)
        if operation.created_at < now - timedelta(days=7):
            row.state, row.message, row.run_token = (
                "failed",
                "Shelf observation expired; retry with a new observation",
                None,
            )
            row.next_sync_at = next_due(row, now, failed=True)
            operation.status, operation.message = "failed", row.message
            return
        if row.run_token and row.lease_until > now:
            raise ShelfRetry((row.lease_until - now).total_seconds() + 1)
        wait = await budget(db)
        if wait:
            row.run_token, row.state = None, "queued"
            operation.status = "queued"
            row.message = operation.message = "Waiting for the Goodreads request budget"
        else:
            row.run_token, row.lease_until, row.state = token, now + timedelta(minutes=2), "running"
            operation.status, operation.message = "running", "Observing Goodreads shelf additions"
            row.message = operation.message
            config = decrypt_secrets(row.encrypted_config)
    if wait:
        raise ShelfRetry(wait)
    try:
        response = await fetch_feed(
            config["url"], etag=config.get("etag"), modified=config.get("modified")
        )
    except AdapterError as error:
        async with session_factory()() as db, db.begin():
            ctx = await context(db, operation_id)
            if not ctx or ctx[1].run_token != token:
                return
            operation, row, _ = ctx
            row.state, row.message, row.run_token = "failed", str(error), None
            row.failures += 1
            row.next_sync_at = next_due(
                row, datetime.now(UTC), failed=True, retry_after=error.retry_after or 0
            )
            operation.status, operation.message = "failed", row.message
            if error.kind == FailureKind.RATE_LIMIT:
                await budget(db, block=error.retry_after or 1800)
        return
    async with session_factory()() as db, db.begin():
        ctx = await context(db, operation_id)
        if not ctx or ctx[1].run_token != token:
            return
        operation, row, owner = ctx
        if response.not_modified and not row.baseline_at:
            raise RuntimeError("An unchanged response cannot establish the first shelf observation")
        added = 0 if response.not_modified else await apply_records(db, row, owner, response.items)
        now = datetime.now(UTC)
        row.encrypted_config = encrypt_secrets(
            {**config, "etag": response.etag, "modified": response.modified}
        )
        row.baseline_at = row.baseline_at or now
        row.last_success_at, row.next_sync_at = now, next_due(row, now)
        row.state, row.failures, row.run_token = "idle", 0, None
        row.message = (
            "Feed unchanged; existing memberships preserved"
            if response.not_modified
            else (
                f"Observed {len(response.items)} books; {added} new. "
                "RSS may omit older shelf entries."
            )
        )
        operation.status, operation.message = "completed", row.message


async def schedule():
    if get_settings().recovery_mode:
        return
    async with session_factory()() as db:
        ids = list(
            await db.scalars(
                select(ListSubscription.list_id)
                .where(
                    ListSubscription.enabled.is_(True),
                    ListSubscription.next_sync_at <= datetime.now(UTC),
                )
                .order_by(ListSubscription.next_sync_at)
                .limit(50)
            )
        )
    for list_id in ids:
        async with session_factory()() as db, db.begin():
            item = await db.scalar(select(BookList).where(BookList.id == list_id).with_for_update())
            if not item:
                continue
            row = await db.scalar(
                select(ListSubscription).where(ListSubscription.list_id == list_id)
            )
            owner = await db.get(User, item.owner_id)
            if not row or not row.enabled or not owner.active or owner.role == "viewer":
                continue
            await repair_job(db, row)
            if row.next_sync_at <= datetime.now(UTC):
                await begin(db, owner, list_id, f"shelf-schedule:{row.id}:{uuid4()}")
