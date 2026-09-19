"""Read-only two-pass membership snapshots and explicitly selected reconciliation."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select

from app.adapters.contracts import AdapterError, FailureKind
from app.adapters.hardcover_lists import MAX_MEMBERS
from app.adapters.hardcover_writeback import MAX_MEMBERSHIPS, Membership, Observation
from app.config import get_settings
from app.db.models import (
    ListCatalogBinding,
    ListComparisonRow,
    ListEntry,
    ListObservation,
    Operation,
    Work,
    WorkMetadataSource,
)
from app.db.session import session_factory
from app.domain import hardcover_subscriptions as hardcover
from app.domain import list_curation
from app.domain import list_writeback as writes
from app.domain.visibility import visible_origin_work, visible_work
from app.domain.work_graph import canonical_map, graph_lock
from app.jobs.queue import enqueue
from app.jobs.retry import ShelfRetry
from app.security import decrypt_secrets

KIND = "lists.writeback.compare"
MAX_LOCAL = 5000


async def binding(db, ctx):
    item, _, account, subscription, _ = ctx
    external_id = writes.binding(account, subscription)
    await graph_lock(db)
    return {
        "list_id": str(item.id),
        "subscription_id": str(subscription.id),
        "account_generation": account.generation,
        "external_list_id": external_id,
        "revision": await list_curation.content_revision(db, item.id),
    }


async def start(db, owner_id, ctx, remote_owner_id):
    frozen = await binding(db, ctx)
    old = await db.scalar(
        select(Operation)
        .where(
            Operation.kind == KIND,
            Operation.owner_id == owner_id,
            Operation.payload["binding"] == frozen,
            Operation.status.in_(["queued", "running"]),
        )
        .order_by(Operation.created_at.desc())
        .limit(1)
    )
    if old:
        return old
    operation = Operation(
        owner_id=owner_id,
        kind=KIND,
        idempotency_key=f"compare:{uuid4()}",
        message="Reading existing local and Hardcover memberships",
        payload={"binding": frozen, "remote_owner_id": remote_owner_id, "failures": 0},
    )
    db.add(operation)
    await db.flush()
    operation.job_id = await enqueue(db, KIND, operation_id=str(operation.id))
    return operation


async def load(db, operation_id):
    operation = await db.get(Operation, operation_id)
    if not operation or operation.kind != KIND:
        raise HTTPException(404, "List comparison not found")
    ctx = await writes.context(
        db, operation.owner_id, UUID(operation.payload["binding"]["list_id"])
    )
    await db.refresh(operation)
    if await binding(db, ctx) != operation.payload["binding"]:
        raise HTTPException(409, "List or account changed; compare existing books again")
    return operation, ctx


async def identity_state(db, owner, subscription, remote_ids):
    """Bounded set queries; no per-book provider calls or title-based matching."""
    mapping = canonical_map()
    local = set(
        await db.scalars(
            select(mapping.c.work_id)
            .join(ListEntry, ListEntry.work_id == mapping.c.origin_id)
            .where(ListEntry.list_id == subscription.list_id)
            .distinct()
            .limit(MAX_LOCAL + 1)
        )
    )
    if len(local) > MAX_LOCAL:
        raise HTTPException(422, "Comparison supports at most 5,000 local books")
    # Find candidate canonical roots using only accepted provider identities.
    sources = (
        select(mapping.c.work_id)
        .join(WorkMetadataSource, WorkMetadataSource.work_id == mapping.c.origin_id)
        .join(Work, Work.id == mapping.c.origin_id)
        .where(
            WorkMetadataSource.provider == "hardcover",
            WorkMetadataSource.accepted.is_(True),
            WorkMetadataSource.external_id.in_(remote_ids),
            visible_origin_work(owner),
        )
    )
    bindings = (
        select(mapping.c.work_id)
        .join(ListCatalogBinding, ListCatalogBinding.work_id == mapping.c.origin_id)
        .where(
            ListCatalogBinding.owner_id == owner.id,
            ListCatalogBinding.identity_key.in_([f"hardcover:{key}" for key in remote_ids]),
        )
    )
    observed = (
        select(mapping.c.work_id)
        .join(ListObservation, ListObservation.work_id == mapping.c.origin_id)
        .where(
            ListObservation.subscription_id == subscription.id,
            ListObservation.external_id.in_(remote_ids),
        )
    )
    roots = local | set(await db.scalars(sources.union(bindings, observed)))
    if len(roots) > MAX_LOCAL + MAX_MEMBERS:
        raise HTTPException(422, "Too many competing catalog identities to compare this list")
    works = {
        str(w.id): {"title": w.title, "keys": [], "changed": []}
        for w in await db.scalars(select(Work).where(Work.id.in_(roots), visible_work(owner)))
    }
    allowed = [UUID(key) for key in works]
    queries = [
        select(mapping.c.work_id, WorkMetadataSource.external_id)
        .join(WorkMetadataSource, WorkMetadataSource.work_id == mapping.c.origin_id)
        .join(Work, Work.id == mapping.c.origin_id)
        .where(
            mapping.c.work_id.in_(allowed),
            WorkMetadataSource.provider == "hardcover",
            WorkMetadataSource.accepted.is_(True),
            visible_origin_work(owner),
        ),
        select(mapping.c.work_id, ListCatalogBinding.identity_key)
        .join(ListCatalogBinding, ListCatalogBinding.work_id == mapping.c.origin_id)
        .where(
            mapping.c.work_id.in_(allowed),
            ListCatalogBinding.owner_id == owner.id,
            ListCatalogBinding.identity_key.like("hardcover:%"),
        ),
    ]
    for query in queries:
        rows = (await db.execute(query.limit(50001))).all()
        if len(rows) > 50000:
            raise HTTPException(422, "Too many catalog assertions to compare this list")
        for root, key in rows:
            works[str(root)]["keys"].append(key.removeprefix("hardcover:"))
    for root, key, snapshot in await db.execute(
        select(mapping.c.work_id, ListObservation.external_id, ListObservation.snapshot)
        .join(ListObservation, ListObservation.work_id == mapping.c.origin_id)
        .where(
            mapping.c.work_id.in_(allowed),
            ListObservation.subscription_id == subscription.id,
        )
    ):
        works[str(root)]["changed" if snapshot.get("identity_changed") else "keys"].append(key)
    for value in works.values():
        value["keys"] = sorted(set(value["keys"]))
        value["changed"] = sorted(set(value["changed"]))
    return {"local": sorted(str(key) for key in local if str(key) in works), "works": works}


def make_rows(state, records, external_list_id, remote_owner_id):
    reverse = {}
    for root, work in state["works"].items():
        for key in work["keys"]:
            reverse.setdefault(key, set()).add(root)
    local = set(state["local"])
    remote = {r["external_id"]: r for r in records}
    rows, used = [], set()
    for root in sorted(local):
        work = state["works"][root]
        keys = work["keys"]
        valid = len(keys) == 1 and keys[0].isdecimal() and 1 <= int(keys[0]) <= 2147483647
        valid = valid and keys[0] not in work["changed"] and len(reverse[keys[0]]) == 1
        if not valid:
            rows.append(
                {
                    "work_id": UUID(root),
                    "title": work["title"],
                    "state": "unmatched",
                    "snapshot": {
                        "local": True,
                        "reason": "Match this book to one Hardcover identity",
                    },
                }
            )
            continue
        key = keys[0]
        used.add(key)
        rows.append(
            row(root, work["title"], True, remote.get(key), key, external_list_id, remote_owner_id)
        )
    for key, record in remote.items():
        if key in used:
            continue
        candidates = reverse.get(key, set())
        root = next(iter(candidates)) if len(candidates) == 1 else None
        valid = (
            root is None
            and not candidates
            or (
                root is not None
                and state["works"][root]["keys"] == [key]
                and key not in state["works"][root]["changed"]
            )
        )
        if not valid:
            rows.append(
                {
                    "work_id": None,
                    "title": record["title"],
                    "state": "unmatched",
                    "snapshot": {
                        "local": None,
                        "reason": "Competing or changed catalog identities",
                    },
                }
            )
            continue
        title = state["works"][root]["title"] if root else record["title"]
        rows.append(row(root, title, False, record, key, external_list_id, remote_owner_id))
    return sorted(rows, key=lambda r: (r["title"].casefold(), str(r["work_id"]), r["state"]))


def row(root, title, local, record, key, list_id, owner_id):
    if record and len(record["memberships"]) > MAX_MEMBERSHIPS:
        return {
            "work_id": UUID(root) if root else None,
            "title": title,
            "state": "unmatched",
            "snapshot": {
                "local": local,
                "reason": "More than 100 edition memberships need individual review",
            },
        }
    observation = Observation(
        list_id=list_id,
        owner_id=owner_id,
        book_id=int(key),
        memberships=tuple(
            Membership(
                id=m["entry_id"],
                list_id=list_id,
                book_id=int(key),
                edition_id=int(m["edition_id"]) if m["edition_id"] else None,
            )
            for m in (record["memberships"] if record else [])
        ),
    )
    return {
        "work_id": UUID(root) if root else None,
        "title": title,
        "state": "same" if local and record else "local_only" if local else "remote_only",
        "snapshot": {
            "local": local,
            "observation": observation.model_dump(mode="json"),
            "record": record,
            "reason": None,
        },
    }


async def run(operation_id):
    if get_settings().recovery_mode:
        raise ShelfRetry(60)
    async with session_factory()() as db, db.begin():
        operation = await db.get(Operation, operation_id)
        if not operation or operation.kind != KIND or operation.status in {"completed", "failed"}:
            return
        try:
            operation, ctx = await load(db, operation_id)
        except HTTPException as error:
            operation.status, operation.message = "failed", str(error.detail)
            return
        if operation.status in {"completed", "failed"}:
            return
        if operation.created_at < datetime.now(UTC) - timedelta(minutes=15):
            operation.status, operation.message = "failed", "Comparison expired; start again"
            return
        p = dict(operation.payload)
        if p.get("lease_until") and datetime.fromisoformat(p["lease_until"]) > datetime.now(UTC):
            raise ShelfRetry(5)
        token = str(uuid4())
        p.update(
            run_token=token, lease_until=(datetime.now(UTC) + timedelta(minutes=2)).isoformat()
        )
        operation.payload, operation.status = p, "running"
        owner_id, generation = operation.owner_id, ctx[2].generation
        secret = decrypt_secrets(ctx[2].encrypted_token)["token"]
    error = None
    try:
        page = await hardcover.fetch_page(
            owner_id,
            generation,
            secret,
            str(p["binding"]["external_list_id"]),
            p.get("stage", {}).get("cursor", 0),
        )
        if page.info["owner_id"] != str(p["remote_owner_id"]):
            raise AdapterError(FailureKind.PERMISSION, "Hardcover list ownership changed")
        stage, complete = hardcover.advance(p.get("stage"), page)
    except AdapterError as caught:
        error = caught
    async with session_factory()() as db, db.begin():
        operation = await db.get(Operation, operation_id)
        if not operation or operation.payload.get("run_token") != token:
            return
        try:
            operation, ctx = await load(db, operation_id)
            if operation.payload.get("run_token") != token or operation.status != "running":
                return
            p = {**operation.payload, "lease_until": None, "run_token": None}
            if error:
                p["failures"] += 1
                operation.payload = p
                operation.status = (
                    "queued"
                    if error.kind == FailureKind.RATE_LIMIT and p["failures"] < 5
                    else "failed"
                )
                operation.message = str(error)
            elif not complete:
                p["stage"] = stage
                operation.payload, operation.status = p, "queued"
                operation.message = "Verifying all existing Hardcover memberships"
            else:
                records = hardcover.books(stage)
                state = await identity_state(
                    db, ctx[1], ctx[3], [r["external_id"] for r in records]
                )
                rows = make_rows(
                    state, records, p["binding"]["external_list_id"], p["remote_owner_id"]
                )
                for position, values in enumerate(rows):
                    db.add(
                        ListComparisonRow(comparison_id=operation.id, position=position, **values)
                    )
                p.pop("stage", None)
                p.update(
                    identity_digest=list_curation.digest(state),
                    remote_ids=[r["external_id"] for r in records],
                    expires_at=(datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
                )
                operation.payload, operation.status = p, "completed"
                operation.message = "Existing memberships compared; no changes have been sent"
        except (HTTPException, AdapterError) as caught:
            operation.status = "failed"
            operation.message = (
                str(caught.detail) if isinstance(caught, HTTPException) else str(caught)
            )
        retry = operation.status == "queued"
    if retry:
        raise ShelfRetry(getattr(error, "retry_after", None) or 1)


async def current(db, operation_id, owner_id, list_id):
    await writes.context(db, owner_id, list_id)
    operation = await db.get(Operation, operation_id)
    if (
        not operation
        or operation.kind != KIND
        or operation.owner_id != owner_id
        or operation.payload["binding"]["list_id"] != str(list_id)
    ):
        raise HTTPException(404, "List comparison not found")
    operation, ctx = await load(db, operation_id)
    if operation.status == "completed":
        if operation.payload.get("consumed_by") or datetime.fromisoformat(
            operation.payload["expires_at"]
        ) < datetime.now(UTC):
            raise HTTPException(409, "Comparison used or expired; compare existing books again")
        state = await identity_state(db, ctx[1], ctx[3], operation.payload["remote_ids"])
        if list_curation.digest(state) != operation.payload["identity_digest"]:
            raise HTTPException(
                409, "Catalog identity or access changed; compare existing books again"
            )
    return operation, ctx
