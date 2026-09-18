"""Durable, owner-scoped source searches with independently persisted source outcomes."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.adapters.contracts import AdapterError, FailureKind
from app.adapters.mam import MAMSearch
from app.adapters.prowlarr import ProwlarrSearch
from app.config import get_settings
from app.db.models import Operation, SourceConnection, SourceResult, User, Work
from app.db.session import session_factory
from app.domain.operations import transaction_lock
from app.domain.prowlarr_network import prowlarr_call
from app.domain.release_profiles import profile_snapshot
from app.domain.source_network import source_call
from app.domain.visibility import visible_work
from app.domain.work_graph import canonical_work
from app.jobs.queue import enqueue
from app.jobs.retry import SourceSearchRetry
from app.security import encrypt_secrets

MAX_INDEXERS = 20


class SearchInput(BaseModel):
    q: str | None = Field(default=None, min_length=1, max_length=300)
    medium: str = Field(default="all", pattern="^(all|ebook|audio)$")
    profile_id: UUID | None = None
    profile_generation: int | None = Field(default=None, ge=0)
    offset: int = Field(default=0, ge=0, le=10000)


async def accessible_work(db, user, identifier):
    canonical = await canonical_work(db, identifier)
    work = await db.scalar(select(Work).where(Work.id == canonical.id, visible_work(user)))
    if not work:
        raise HTTPException(404, "Book not found")
    return work


def identity(work):
    return {"id": str(work.id), "title": work.title, "authors": work.authors}


async def start(db, user, work_id, body, key):
    if get_settings().recovery_mode:
        raise HTTPException(409, "Source searches are paused for recovery")
    work = await accessible_work(db, user, work_id)
    command = {"work_id": str(work.id), **body.model_dump(mode="json")}
    await transaction_lock(db, f"operation:{user.id}:{key}")
    existing = await db.scalar(
        select(Operation).where(Operation.owner_id == user.id, Operation.idempotency_key == key)
    )
    if existing:
        if existing.kind != "sources.search" or existing.payload.get("command") != command:
            raise HTTPException(409, "This search command was already used for different options")
        return existing
    profile = await profile_snapshot(db, user.id, body.profile_id, body.profile_generation)
    query = (body.q if body.q is not None else work.title[:300]).strip()
    if not query:
        raise HTTPException(422, "Enter a source-search query")
    connections = {
        s.key: s
        for s in await db.scalars(
            select(SourceConnection).where(SourceConnection.enabled.is_(True))
        )
    }
    sources = {
        key: {
            "state": "queued",
            "name": "MAM" if key == "mam" else "Prowlarr indexers",
            "count": 0,
            "message": "Waiting for a worker",
            "generation": row.generation,
        }
        for key, row in connections.items()
        if key in {"mam", "prowlarr"}
    }
    operation = Operation(
        owner_id=user.id,
        kind="sources.search",
        idempotency_key=key,
        payload={
            "command": command,
            "work": identity(work),
            "query": query,
            "medium": body.medium,
            "offset": body.offset,
            "profile": profile.model_dump(mode="json"),
            "sources": sources,
            "workers": {},
            "expires_at": (datetime.now(UTC) + timedelta(minutes=25)).isoformat(),
        },
        message="Searching connected sources"
        if sources
        else "Connect MAM or Prowlarr to search releases",
        status="queued" if sources else "completed",
    )
    db.add(operation)
    await db.flush()
    payload = deepcopy(operation.payload)
    for source in sources:
        job = await enqueue(db, "sources.search", operation_id=str(operation.id), source=source)
        payload["workers"][source] = {"job_id": job, "attempts": 0}
        if operation.job_id is None:
            operation.job_id = job
    operation.payload = payload
    return operation


async def checked(db, identifier, user_id=None):
    operation = await db.get(Operation, identifier, populate_existing=True)
    if (
        not operation
        or operation.kind != "sources.search"
        or (user_id and operation.owner_id != user_id)
    ):
        raise HTTPException(404, "Source search not found")
    user = await db.get(User, operation.owner_id, populate_existing=True)
    if not user or not user.active:
        raise HTTPException(401, "This search account is no longer active")
    work = await accessible_work(db, user, UUID(operation.payload["work"]["id"]))
    return operation, identity(work) != operation.payload["work"]


def refresh_status(operation, payload):
    states = [s["state"] for s in payload["sources"].values()]
    operation.status = (
        "completed" if all(s in {"completed", "failed"} for s in states) else "running"
    )
    operation.message = (
        ("Search finished with source errors" if "failed" in states else "Source search completed")
        if operation.status == "completed"
        else "Searching connected sources"
    )
    operation.payload = payload


async def update_unit(identifier, source, token, unit, changes, hits=None, generation=None):
    async with session_factory()() as db, db.begin():
        await transaction_lock(db, f"source-search:{identifier}")
        operation, changed = await checked(db, identifier)
        payload = deepcopy(operation.payload)
        if payload["workers"][source].get("token") != str(token):
            return False
        payload["workers"][source]["until"] = (datetime.now(UTC) + timedelta(minutes=3)).isoformat()
        if datetime.fromisoformat(payload["expires_at"]) <= datetime.now(UTC):
            raise HTTPException(409, "Search expired. Start a new source search.")
        if changed:
            raise HTTPException(409, "Catalog identity changed. Start a new source search.")
        if generation is not None:
            await transaction_lock(db, f"source:{source}")
            connection = await db.get(SourceConnection, source, populate_existing=True)
            if not connection or not connection.enabled or connection.generation != generation:
                raise HTTPException(409, "Source settings changed. Start a new search.")
        if hits is not None:
            now = datetime.now(UTC)
            await db.execute(delete(SourceResult).where(SourceResult.expires_at <= now))
            hits = list(
                {
                    (release.source, release.indexer_id, release.source_id): (release, reference)
                    for release, reference in hits
                }.values()
            )
            changes = {**changes, "count": len(hits)}
            for release, reference in hits:
                db.add(
                    SourceResult(
                        owner_id=operation.owner_id,
                        source_key=source,
                        source_generation=generation,
                        operation_id=operation.id,
                        expires_at=datetime.fromisoformat(payload["expires_at"]),
                        encrypted_reference=encrypt_secrets({"link": reference}),
                        release_snapshot=release.model_dump(mode="json"),
                    )
                )
        payload["sources"][unit] = {**payload["sources"].get(unit, {}), **changes}
        refresh_status(operation, payload)
        return True


async def fail_worker(identifier, source, token, message):
    async with session_factory()() as db, db.begin():
        await transaction_lock(db, f"source-search:{identifier}")
        operation = await db.get(Operation, identifier)
        if not operation:
            return
        payload = deepcopy(operation.payload)
        if payload["workers"][source].get("token") != str(token):
            return
        for key, unit in payload["sources"].items():
            if (key == source or key.startswith(source + ":")) and unit["state"] not in {
                "completed",
                "failed",
            }:
                unit.update(state="failed", message=message)
        payload["workers"][source].pop("token", None)
        refresh_status(operation, payload)


async def run(identifier, source):
    if get_settings().recovery_mode:
        raise SourceSearchRetry(60)
    token = uuid4()
    async with session_factory()() as db, db.begin():
        await transaction_lock(db, f"source-search:{identifier}")
        operation = await db.get(Operation, identifier, populate_existing=True)
        if (
            not operation
            or operation.kind != "sources.search"
            or source not in operation.payload["workers"]
        ):
            return
        payload = deepcopy(operation.payload)
        unit_states = [
            unit["state"]
            for key, unit in payload["sources"].items()
            if key == source or key.startswith(source + ":")
        ]
        if all(state in {"completed", "failed"} for state in unit_states):
            return
        worker = payload["workers"][source]
        if worker.get("token") and datetime.fromisoformat(worker["until"]) > datetime.now(UTC):
            raise SourceSearchRetry(
                max(
                    1,
                    int(
                        (
                            datetime.fromisoformat(worker["until"]) - datetime.now(UTC)
                        ).total_seconds()
                    )
                    + 1,
                )
            )
        worker.update(
            token=str(token),
            until=(datetime.now(UTC) + timedelta(minutes=3)).isoformat(),
            attempts=worker["attempts"] + 1,
        )
        operation.payload = payload
        owner_id = operation.owner_id
    try:
        async with session_factory()() as db:
            _, changed = await checked(db, identifier)
            if changed:
                raise HTTPException(409, "Catalog identity changed. Start a new search.")
        if datetime.fromisoformat(payload["expires_at"]) <= datetime.now(UTC):
            raise HTTPException(409, "Search expired. Start a new search.")
        generation = payload["sources"][source]["generation"]
        if source == "mam":
            await update_unit(
                identifier, source, token, source, {"state": "running", "message": "Searching MAM"}
            )
            page, generation = await source_call(
                owner_id,
                "search",
                MAMSearch(
                    q=payload["query"],
                    medium=payload["medium"],
                    language_ids=[],
                    offset=payload["offset"],
                    limit=50,
                ),
                with_generation=True,
                expected_generation=generation,
            )
            await update_unit(
                identifier,
                source,
                token,
                source,
                {
                    "state": "completed",
                    "message": "Results received",
                    "count": len(page.items),
                    "has_more": page.has_more,
                    "observed_at": datetime.now(UTC).isoformat(),
                },
                [(release, None) for release in page.items],
                generation,
            )
        else:
            if payload["sources"][source]["state"] != "completed":
                indexers, generation = await prowlarr_call(
                    owner_id, "indexers", expected_generation=generation
                )
                eligible = [
                    i
                    for i in indexers
                    if i.enabled
                    and i.supports_search
                    and not i.excluded
                    and (not i.categories or bool(set(i.categories) & {3000, 3030, 7000, 7020}))
                ]
                async with session_factory()() as db, db.begin():
                    await transaction_lock(db, f"source-search:{identifier}")
                    operation, changed = await checked(db, identifier)
                    current = deepcopy(operation.payload)
                    if current["workers"][source].get("token") != str(token):
                        return
                    if changed:
                        raise HTTPException(409, "Catalog identity changed. Start a new search.")
                    for indexer in eligible[:MAX_INDEXERS]:
                        current["sources"][f"prowlarr:{indexer.id}"] = {
                            "state": "queued",
                            "name": indexer.name,
                            "generation": generation,
                            "indexer_id": indexer.id,
                            "paging": indexer.supports_pagination,
                            "count": 0,
                            "message": "Waiting to search",
                        }
                    current["sources"][source].update(
                        state="completed",
                        message="Indexer discovery complete"
                        if len(eligible) <= MAX_INDEXERS
                        else (
                            f"Search limited to {MAX_INDEXERS} indexers; "
                            "use direct source search for others"
                        ),
                    )
                    refresh_status(operation, current)
                    payload = current
            for unit, state in payload["sources"].items():
                if not unit.startswith("prowlarr:") or state["state"] in {"completed", "failed"}:
                    continue
                try:
                    if payload["offset"] and not state["paging"]:
                        raise AdapterError(
                            FailureKind.UNSUPPORTED, "This indexer does not support further pages"
                        )
                    await update_unit(
                        identifier,
                        source,
                        token,
                        unit,
                        {"state": "running", "message": "Searching this indexer"},
                    )
                    batch, generation = await prowlarr_call(
                        owner_id,
                        "search",
                        ProwlarrSearch(
                            q=payload["query"],
                            medium=payload["medium"],
                            indexer_id=state["indexer_id"],
                            offset=payload["offset"],
                            limit=50,
                        ),
                        expected_generation=generation,
                    )
                    await update_unit(
                        identifier,
                        source,
                        token,
                        unit,
                        {
                            "state": "completed",
                            "count": len(batch.hits),
                            "has_more": batch.returned_count >= 50 and state["paging"],
                            "message": (
                                "Results received; empty responses can also "
                                "indicate upstream failure"
                            ),
                            "observed_at": datetime.now(UTC).isoformat(),
                        },
                        [(h.release, h.reference) for h in batch.hits],
                        generation,
                    )
                except AdapterError as error:
                    if error.kind == FailureKind.RATE_LIMIT:
                        raise
                    await update_unit(
                        identifier, source, token, unit, {"state": "failed", "message": str(error)}
                    )
    except AdapterError as error:
        if error.kind == FailureKind.RATE_LIMIT and worker["attempts"] < 5:
            async with session_factory()() as db, db.begin():
                await transaction_lock(db, f"source-search:{identifier}")
                operation = await db.get(Operation, identifier)
                current = deepcopy(operation.payload)
                if current["workers"][source].get("token") != str(token):
                    return
                current["workers"][source].pop("token", None)
                for key, state in current["sources"].items():
                    if (key == source or key.startswith(source + ":")) and state["state"] in {
                        "queued",
                        "running",
                    }:
                        state.update(state="queued", message="Waiting for source rate limit")
                refresh_status(operation, current)
            raise SourceSearchRetry(error.retry_after or 5) from error
        await fail_worker(identifier, source, token, str(error))
    except HTTPException as error:
        await fail_worker(identifier, source, token, str(error.detail))
