from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from app.adapters.contracts import AdapterError
from app.adapters.mam import MAMRelease
from app.adapters.prowlarr import ProwlarrRelease
from app.api.dependencies import CurrentUser, Database, Member
from app.api.metadata import adapter_http_error
from app.api.prowlarr import resolve as resolve_prowlarr
from app.api.source_artifacts import SourceArtifactView, artifact_view
from app.db.models import Operation, SourceConnection, SourceResult
from app.domain.book_sources import SearchInput, accessible_work, checked, refresh_status, start
from app.domain.operations import transaction_lock
from app.domain.release_profiles import (
    ProfileSnapshot,
    ReleaseAssessment,
    assess_release,
    ranking_key,
)
from app.domain.source_artifacts import resolve_mam

router = APIRouter(tags=["book-sources"])


class SearchSourceView(BaseModel):
    key: str
    name: str
    state: str
    count: int = 0
    message: str
    has_more: bool = False
    observed_at: datetime | None = None


class RankedReleaseView(BaseModel):
    id: UUID
    release: MAMRelease | ProwlarrRelease = Field(discriminator="source")
    assessment: ReleaseAssessment
    expires_at: datetime
    current_connection: bool


class BookSearchView(BaseModel):
    id: UUID
    work_id: UUID
    query: str
    medium: str
    offset: int
    status: str
    message: str
    stale_identity: bool
    profile: ProfileSnapshot
    sources: list[SearchSourceView]
    items: list[RankedReleaseView]
    expires_at: datetime


async def view(db, user, operation_id):
    await transaction_lock(db, f"source-search:{operation_id}")
    operation, changed = await checked(db, operation_id, user.id)
    payload = deepcopy(operation.payload)
    # Queue truth repairs exhausted workers; do not infer failure from slow polling.
    for source, worker in payload["workers"].items():
        status = await db.scalar(
            text("SELECT status::text FROM book_queue.procrastinate_jobs WHERE id=:id"),
            {"id": worker["job_id"]},
        )
        if status in {"failed", "aborted", "succeeded"} or status is None:
            for key, unit in payload["sources"].items():
                if (key == source or key.startswith(source + ":")) and unit["state"] not in {
                    "completed",
                    "failed",
                }:
                    unit.update(
                        state="failed",
                        message="Search worker stopped. Start a new search to retry.",
                    )
                    worker.pop("token", None)
    refresh_status(operation, payload)
    profile = ProfileSnapshot.model_validate(payload["profile"])
    connections = {s.key: s for s in await db.scalars(select(SourceConnection))}
    rows = list(
        await db.scalars(
            select(SourceResult)
            .where(SourceResult.operation_id == operation.id)
            .order_by(SourceResult.created_at, SourceResult.id)
        )
    )
    ranked = []
    for row in rows:
        release = (MAMRelease if row.source_key == "mam" else ProwlarrRelease).model_validate(
            row.release_snapshot
        )
        connection = connections.get(row.source_key)
        ranked.append(
            RankedReleaseView(
                id=row.id,
                release=release,
                assessment=assess_release(
                    release, payload["work"], profile.preferences, payload["medium"]
                ),
                expires_at=row.expires_at,
                current_connection=bool(
                    not changed
                    and connection
                    and connection.enabled
                    and connection.generation == row.source_generation
                    and row.expires_at > datetime.now(UTC)
                ),
            )
        )
    ranked.sort(key=lambda item: ranking_key(item.release, item.assessment, profile.preferences))
    response = BookSearchView(
        id=operation.id,
        work_id=payload["work"]["id"],
        query=payload["query"],
        medium=payload["medium"],
        offset=payload["offset"],
        status=operation.status,
        message=operation.message,
        stale_identity=changed,
        profile=profile,
        sources=[SearchSourceView(key=k, **v) for k, v in payload["sources"].items()],
        items=ranked,
        expires_at=payload["expires_at"],
    )
    await db.commit()
    return response


@router.post(
    "/catalog/works/{work_id}/source-searches", response_model=BookSearchView, status_code=202
)
async def begin(
    work_id: UUID,
    body: SearchInput,
    user: CurrentUser,
    db: Database,
    idempotency_key: str = Header(min_length=8, max_length=200),
):
    operation = await start(db, user, work_id, body, idempotency_key)
    await db.commit()
    return await view(db, user, operation.id)


@router.get("/catalog/works/{work_id}/source-searches/latest", response_model=BookSearchView | None)
async def latest(work_id: UUID, user: CurrentUser, db: Database):
    work = await accessible_work(db, user, work_id)
    operation = await db.scalar(
        select(Operation)
        .where(
            Operation.owner_id == user.id,
            Operation.kind == "sources.search",
            Operation.payload["work"]["id"].astext == str(work.id),
        )
        .order_by(Operation.created_at.desc(), Operation.id)
        .limit(1)
    )
    return await view(db, user, operation.id) if operation else None


@router.get("/source-searches/{search_id}", response_model=BookSearchView)
async def search_detail(search_id: UUID, user: CurrentUser, db: Database):
    return await view(db, user, search_id)


@router.post(
    "/source-searches/{search_id}/results/{result_id}/artifact", response_model=SourceArtifactView
)
async def inspect(search_id: UUID, result_id: UUID, user: Member, db: Database):
    operation, changed = await checked(db, search_id, user.id)
    row = await db.get(SourceResult, result_id)
    if not row or row.owner_id != user.id or row.operation_id != operation.id:
        raise HTTPException(404, "Source result not found")
    if changed or row.expires_at <= datetime.now(UTC):
        raise HTTPException(409, "Search results changed or expired. Search again.")
    connection = await db.get(SourceConnection, row.source_key)
    if not connection or not connection.enabled or connection.generation != row.source_generation:
        raise HTTPException(409, "Source connection changed. Search again.")
    if row.source_key == "prowlarr":
        return await resolve_prowlarr(result_id, user, db)
    owner_id, generation, source_id = (
        user.id,
        row.source_generation,
        row.release_snapshot["source_id"],
    )
    await db.rollback()
    try:
        identifier = await resolve_mam(owner_id, source_id, expected_generation=generation)
    except AdapterError as error:
        raise adapter_http_error(error) from error
    return await artifact_view(db, identifier, owner_id)
