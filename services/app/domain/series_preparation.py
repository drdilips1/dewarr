"""Durable metadata prerequisites for a source search; never download authorization."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, text

from app.adapters.catalog_providers import identifier
from app.adapters.contracts import AdapterError
from app.config import get_settings
from app.db.models import (
    CatalogAccount,
    CatalogSeries,
    Operation,
    SeriesMembership,
    User,
    Work,
    WorkMetadataSource,
)
from app.db.session import session_factory
from app.domain import catalog_series
from app.domain.operations import transaction_lock
from app.domain.pack_coverage import CATALOG_FRESH_FOR
from app.domain.visibility import visible_origin_work
from app.domain.work_graph import family_ids
from app.jobs.retry import DependencyRetry

KIND = "sources.prepare"
MAX_SERIES = 3
FRESH_FOR = CATALOG_FRESH_FOR
FAILURE_BACKOFF = timedelta(minutes=15)
WAIT_LIMIT = timedelta(minutes=10)
ACTIVE = {"pending", "waiting"}


async def references(db, user, work):
    sources = list(
        await db.scalars(
            select(WorkMetadataSource)
            .join(Work, Work.id == WorkMetadataSource.work_id)
            .where(
                WorkMetadataSource.work_id.in_(family_ids(work.id)),
                WorkMetadataSource.provider == "hardcover",
                WorkMetadataSource.accepted.is_(True),
                visible_origin_work(user),
            )
            .order_by(WorkMetadataSource.external_id, WorkMetadataSource.id)
            .limit(50)
        )
    )
    candidates = {}
    for source in sources:
        for entry in source.snapshot.get("series", [])[:50]:
            if entry.get("compilation"):
                continue
            key = str(entry.get("external_id", ""))
            try:
                identifier("hardcover", key)
            except AdapterError:
                continue
            candidates.setdefault(key, str(entry.get("name") or "Series")[:600])
    rows = list(
        await db.scalars(
            select(CatalogSeries)
            .where(
                CatalogSeries.owner_id == user.id,
                CatalogSeries.provider == "hardcover",
                CatalogSeries.id.in_(
                    select(SeriesMembership.series_id).where(
                        SeriesMembership.present.is_(True),
                        SeriesMembership.work_id.in_(family_ids(work.id)),
                    )
                ),
            )
            .order_by(CatalogSeries.external_id)
            .limit(50)
        )
    )
    for row in rows:
        try:
            identifier("hardcover", row.external_id)
        except AdapterError:
            continue
        candidates.setdefault(row.external_id, row.name)
    return [
        {"external_id": key, "name": candidates[key]}
        for key in sorted(candidates, key=int)[:MAX_SERIES]
    ]


async def plan(db, user, work, enabled):
    if not enabled or user.role == "viewer":
        return None
    refs = await references(db, user, work)
    if not refs:
        return None
    account = await db.get(CatalogAccount, user.id)
    catalogs = {
        r.external_id: r
        for r in await db.scalars(
            select(CatalogSeries).where(
                CatalogSeries.owner_id == user.id,
                CatalogSeries.provider == "hardcover",
                CatalogSeries.external_id.in_([r["external_id"] for r in refs]),
            )
        )
    }
    now = datetime.now(UTC)
    needed = [
        r
        for r in refs
        if r["external_id"] not in catalogs
        or not catalogs[r["external_id"]].fetched_at
        or catalogs[r["external_id"]].fetched_at < now - FRESH_FOR
    ]
    if not needed:
        return None
    connected = bool(account and account.enabled)
    return {
        "state": "pending" if connected else "completed",
        "message": "Loading series metadata before searching releases"
        if connected
        else "Searching with available metadata",
        "references": needed,
        "dependencies": [],
        "warnings": []
        if connected
        else [
            "Connect Hardcover to load missing or stale series coverage; "
            "ordinary source search remains available"
        ],
        "deadline": (now + WAIT_LIMIT).isoformat(),
        "account_generation": account.generation if connected else None,
        "endpoint": get_settings().hardcover_url,
    }


async def ensure(db, user, ref, parent_id):
    # Reuse an in-flight observation, including one explicitly started in the UI.
    # A failed automatic lookup gets a bounded cooldown rather than a new job on
    # every list tick or source-search refresh.
    row = await db.scalar(
        select(CatalogSeries).where(
            CatalogSeries.owner_id == user.id,
            CatalogSeries.provider == "hardcover",
            CatalogSeries.external_id == ref["external_id"],
        )
    )
    if row and row.fetched_at and row.fetched_at >= datetime.now(UTC) - FRESH_FOR:
        return {
            **ref,
            "operation_id": None,
            "state": "completed",
            "message": "Using current series catalog",
        }
    previous = await db.get(Operation, row.operation_id) if row and row.operation_id else None
    account = await db.get(CatalogAccount, user.id)
    if (
        previous
        and previous.status in {"failed", "cancelled"}
        and previous.created_at > datetime.now(UTC) - FAILURE_BACKOFF
        and previous.payload.get("account_generation") == account.generation
        and previous.payload.get("endpoint") == get_settings().hardcover_url
    ):
        return {
            **ref,
            "operation_id": str(previous.id),
            "state": "failed",
            "message": "Recent series lookup failed; retry after the metadata cooldown",
        }
    operation = await catalog_series.start(
        db,
        user,
        ref["external_id"],
        f"search-series:{parent_id}:{ref['external_id']}",
        reuse_active=True,
    )
    return {
        **ref,
        "operation_id": str(operation.id),
        "state": "waiting",
        "message": "Waiting for verified series membership",
    }


async def repair(db, operation):
    prep = operation.payload.get("catalog_preparation")
    if not prep or prep["state"] not in ACTIVE:
        return
    status = await db.scalar(
        text("SELECT status::text FROM book_queue.procrastinate_jobs WHERE id=:id"),
        {"id": operation.job_id},
    )
    if status not in {"todo", "doing"}:
        payload = deepcopy(operation.payload)
        fail(payload, "Metadata preparation stopped; refresh this source search")
        operation.payload = payload


def fail(payload, message):
    payload["catalog_preparation"].update(state="failed", message=message)
    for unit in payload["sources"].values():
        unit.update(state="failed", message=message)


async def run(search_id):
    if get_settings().recovery_mode:
        raise DependencyRetry(60)
    waiting = False
    async with session_factory()() as db, db.begin():
        from app.domain import book_sources

        await transaction_lock(db, f"source-search:{search_id}")
        operation = await db.get(Operation, search_id, populate_existing=True)
        if not operation or operation.kind != "sources.search":
            return
        prep = operation.payload.get("catalog_preparation")
        if not prep or prep["state"] not in ACTIVE:
            return
        payload = deepcopy(operation.payload)
        prep = payload["catalog_preparation"]
        try:
            operation, changed = await book_sources.checked(db, search_id)
            if changed:
                raise HTTPException(409, "Book identity changed; refresh this source search")
            user = await db.get(User, operation.owner_id, populate_existing=True)
            work = await book_sources.accessible_work(db, user, UUID(payload["work"]["id"]))
            current_refs = {r["external_id"] for r in await references(db, user, work)}
            if not {r["external_id"] for r in prep["references"]} <= current_refs:
                raise HTTPException(409, "Series references changed; refresh this source search")
            account = await db.get(CatalogAccount, user.id, populate_existing=True)
            available = bool(
                user.role != "viewer"
                and account
                and account.enabled
                and account.generation == prep["account_generation"]
                and get_settings().hardcover_url == prep["endpoint"]
            )
            now = datetime.now(UTC)
            expired = now >= datetime.fromisoformat(prep["deadline"])
            if available and not expired and prep["state"] == "pending":
                prep["dependencies"] = [
                    await ensure(db, user, ref, operation.id) for ref in prep["references"]
                ]
                prep["state"] = "waiting"
            if not available:
                prep["warnings"].append(
                    "Catalog connection changed; searching with available metadata"
                )
            elif expired:
                prep["warnings"].append(
                    "Series metadata did not finish within ten minutes; "
                    "searching with available metadata"
                )
            else:
                for item in prep["dependencies"]:
                    if item["state"] in {"completed", "failed"}:
                        continue
                    child = await db.get(
                        Operation, UUID(item["operation_id"]), populate_existing=True
                    )
                    state, message = await catalog_series.operation_status(db, child)
                    if state in {"queued", "running", "retrying"}:
                        retry_at = child.payload.get("retry_at")
                        if (
                            state == "retrying"
                            and retry_at
                            and datetime.fromisoformat(retry_at)
                            > datetime.fromisoformat(prep["deadline"])
                        ):
                            item.update(
                                state="failed",
                                message="Provider cooldown exceeds this preparation window",
                            )
                        else:
                            item.update(state="waiting", message=message)
                            waiting = True
                    else:
                        item.update(
                            state="completed" if state == "completed" else "failed", message=message
                        )
                if waiting:
                    prep["message"] = (
                        "Waiting for verified series metadata before source queries begin"
                    )
            if not waiting:
                if not available or expired:
                    for item in prep["dependencies"]:
                        if item["state"] == "waiting":
                            item.update(
                                state="failed",
                                message="Preparation window ended; metadata may finish separately",
                            )
                prep["warnings"].extend(
                    f"{d['name']}: {d['message']}"
                    for d in prep["dependencies"]
                    if d["state"] == "failed"
                )
                prep["warnings"] = list(dict.fromkeys(prep["warnings"]))
                prep.update(
                    state="completed", message="Series preparation finished; searching releases"
                )
                operation.payload = payload
                await book_sources.launch(db, operation, user, work)
            else:
                operation.payload = payload
                operation.status, operation.message = "running", prep["message"]
        except (HTTPException, AdapterError) as error:
            waiting = False
            fail(payload, str(error.detail) if isinstance(error, HTTPException) else str(error))
            operation.payload = payload
            book_sources.refresh_status(operation, payload)
    if waiting:
        raise DependencyRetry(15)
