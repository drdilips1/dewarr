"""Upcoming releases, the month calendar, and monitored requests."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select

from app.adapters.catalog_types import catalog_snapshot, cover_url
from app.adapters.contracts import AdapterError
from app.adapters.librofm import LibroHit
from app.api.dependencies import CurrentUser, Database, Member
from app.api.discovery import DiscoveryShelf, project
from app.api.metadata import accessible_work, adapter_http_error, current_actor, provider_call
from app.db.models import MonitoredRelease, Work, WorkMetadataSource
from app.domain.acquisition import RequestOptions
from app.domain.availability import availability_for
from app.domain.catalog_bindings import displayed_provider_works
from app.domain.hardcover_matching import MatchEvidence
from app.domain.libro_enrichment import agrees, field_locked, stage
from app.domain.libro_library import _cover, _open_lookup, _write_item, audio_context, store
from app.domain.operations import transaction_lock
from app.domain.quick_add import begin
from app.domain.release_dates import (
    GENRES,
    assign_release,
    merge_month,
    month_bounds,
    parse_iso_day,
    release_facts,
)
from app.domain.release_monitor import (
    adopt_release_days,
    personal_entries,
    record_release_day,
    save_genres,
    saved_genres,
    stop,
)
from app.domain.visibility import visible_work
from app.domain.work_graph import canonical_work

router = APIRouter(prefix="/releases", tags=["releases"])


class GenrePreferences(BaseModel):
    selected: list[str]
    choices: list[str]


class GenreInput(BaseModel):
    genres: list[str] = Field(default_factory=list, max_length=len(GENRES))


class ReleaseEntry(BaseModel):
    work_id: UUID | None = None
    provider: Literal["hardcover", "local", "librofm"]
    external_id: str | None = None
    title: str
    authors: list[str]
    cover_url: str | None = None
    release_date: str | None = None
    basis: Literal["audiobook", "work", "unknown"]
    followed: bool = False
    in_library: bool = False
    genres: list[str] = Field(default_factory=list)
    state: str | None = None


class ReleaseMonth(BaseModel):
    month: str
    genres: list[str]
    choices: list[str]
    items: list[ReleaseEntry]
    undated: list[ReleaseEntry]
    page: int
    has_more: bool = False
    status: Literal["ready", "not-connected", "unavailable"] = "ready"
    warning: str | None = None
    stale: bool = False


class FollowInput(BaseModel):
    work_id: UUID | None = None
    provider: Literal["hardcover"] | None = None
    external_id: str | None = Field(default=None, max_length=40)
    title: str | None = Field(default=None, max_length=600)
    authors: list[str] = Field(default_factory=list, max_length=40)
    cover_url: str | None = None
    release_date: str | None = None
    basis: Literal["audiobook", "work", "unknown"] = "unknown"


class FollowView(BaseModel):
    work_id: UUID
    state: Literal["waiting", "wanted", "available", "stopped"]
    release_date: str | None = None
    basis: Literal["audiobook", "work", "unknown"]
    message: str


class PreReleaseCandidate(BaseModel):
    title: str
    authors: list[str]
    narrators: list[str] = Field(default_factory=list)
    isbn: str
    cover_url: str | None = None
    coming_soon: bool = False


class PreReleaseView(BaseModel):
    status: str
    candidates: list[PreReleaseCandidate] = Field(default_factory=list)
    release_date: str | None = None
    basis: Literal["audiobook", "work", "unknown"] = "unknown"
    message: str = ""


class ConfirmInput(BaseModel):
    isbn: str = Field(pattern=r"\d{10}|\d{13}")


def _month(value: str, today):
    try:
        year, month = (int(part) for part in value.split("-"))
        start, end = month_bounds(year, month)
    except (TypeError, ValueError):
        raise HTTPException(422, "Choose a month as YYYY-MM") from None
    if start.year < 2000 or (start.year - today.year) * 12 + (start.month - today.month) > 18:
        raise HTTPException(422, "Choose a month within the next year and a half")
    return start, end


def _entry(item) -> ReleaseEntry:
    day = item.get("release_date")
    return ReleaseEntry(
        work_id=item.get("work_id"),
        provider=item.get("provider") or "local",
        external_id=item.get("external_id"),
        title=item["title"],
        authors=item.get("authors") or [],
        cover_url=item.get("cover_url"),
        release_date=day.isoformat() if hasattr(day, "isoformat") else day,
        basis=item.get("basis") or "unknown",
        followed=bool(item.get("followed")),
        in_library=bool(item.get("in_library")),
        genres=list(item.get("genres") or []),
        state=item.get("state"),
    )


def _follow_view(row, message) -> FollowView:
    return FollowView(
        work_id=row.work_id,
        state=row.state,
        release_date=row.release_date.isoformat() if row.release_date else None,
        basis=row.basis,
        message=message,
    )


@router.get("/genres", response_model=GenrePreferences)
async def genres(user: CurrentUser, db: Database):
    return GenrePreferences(selected=await saved_genres(db, user.id), choices=list(GENRES))


@router.put("/genres", response_model=GenrePreferences)
async def update_genres(body: GenreInput, user: Member, db: Database):
    if any(genre not in GENRES for genre in body.genres):
        raise HTTPException(422, "Choose genres from the discover list")
    selected = await save_genres(db, user, body.genres)
    await db.commit()
    return GenrePreferences(selected=selected, choices=list(GENRES))


@router.get("/calendar", response_model=ReleaseMonth)
async def calendar(
    user: CurrentUser,
    db: Database,
    month: str = Query(min_length=7, max_length=7),
    page: int = Query(default=1, ge=1, le=25),
):
    today = datetime.now(UTC).date()
    start, end = _month(month, today)
    selected = await saved_genres(db, user.id)
    user_id = user.id
    result = ReleaseMonth(
        month=f"{start.year:04d}-{start.month:02d}",
        genres=selected,
        choices=list(GENRES),
        items=[],
        undated=[],
        page=page,
    )
    discover = []
    if selected:
        from app.db.models import CatalogAccount

        account = await db.get(CatalogAccount, user.id)
        if not account or not account.enabled:
            result.status = "not-connected"
            result.warning = (
                "Connect Hardcover to browse upcoming releases. Books you follow still show."
            )
        else:
            try:
                batch, result.stale, result.warning = await provider_call(
                    db, user_id, "hardcover", "upcoming", start, end, page
                )
                user = await current_actor(db, user_id)
                linked = await displayed_provider_works(db, user, "hardcover", batch.items)
                owned = await availability_for(
                    db, user, list({work.id for work in linked.values()})
                )
                for book in batch.items:
                    work = linked.get(("hardcover", book.external_id))
                    info = owned.get(work.id) if work else None
                    discover.append(
                        {
                            "work_id": work.id if work else None,
                            "external_id": book.external_id,
                            "provider": "hardcover",
                            "title": book.title,
                            "authors": book.authors,
                            "cover_url": book.cover_url,
                            "release_date": book.release_date,
                            "basis": book.date_basis,
                            "followed": False,
                            "in_library": bool(
                                info
                                and (info.audio if book.date_basis == "audiobook" else info.owned)
                            ),
                            "genres": book.genres,
                            "state": None,
                        }
                    )
                result.has_more = batch.has_more
            except AdapterError as error:
                result.status = "unavailable"
                result.warning = str(error)
                user = await current_actor(db, user_id)
    else:
        result.warning = "Choose genres to see upcoming releases. Books you follow still show."
    if result.status != "unavailable":
        user = await current_actor(db, user_id)
    personal = await personal_entries(db, user, start, end)
    if discover and await adopt_release_days(db, user, discover):
        await db.commit()
        user = await current_actor(db, user_id)
        personal = await personal_entries(db, user, start, end)
    merged = merge_month(personal, discover, selected)
    result.items = [_entry(item) for item in merged if item.get("release_date")]
    result.undated = [_entry(item) for item in merged if not item.get("release_date")]
    return result


@router.get("/upcoming", response_model=DiscoveryShelf)
async def upcoming(
    user: CurrentUser,
    db: Database,
    page: int = Query(default=1, ge=1, le=25),
):
    today = datetime.now(UTC).date()
    start, end = month_bounds(today.year, today.month)
    selected = await saved_genres(db, user.id)
    result = DiscoveryShelf(
        title="Upcoming releases",
        attribution="Hardcover · audiobook editions in your genres",
        page=page,
    )
    if not selected:
        result.warning = "Choose genres on the calendar to see upcoming releases."
        return result
    from app.db.models import CatalogAccount

    account = await db.get(CatalogAccount, user.id)
    if not account or not account.enabled:
        result.status = "not-connected"
        result.warning = "Connect your Hardcover account to browse upcoming releases."
        return result
    user_id = user.id
    try:
        batch, result.stale, result.warning = await provider_call(
            db, user_id, "hardcover", "upcoming", start, end, page
        )
    except AdapterError as error:
        result.status = "unavailable"
        result.warning = str(error)
        result.retry_after = error.retry_after
        return result
    user = await current_actor(db, user_id)
    chosen = [book for book in batch.items if set(selected) & set(book.genres)]
    result.items = await project(db, user, chosen, result.attribution)
    result.has_more = batch.has_more
    return result


async def _catalog_work(db, user, body: FollowInput):
    if body.work_id:
        return await accessible_work(db, user, body.work_id, lock=True)
    if not body.external_id or not body.title:
        raise HTTPException(422, "Choose a book to follow")
    rows = list(
        await db.scalars(
            select(Work)
            .join(WorkMetadataSource)
            .where(
                WorkMetadataSource.provider == "hardcover",
                WorkMetadataSource.external_id == body.external_id,
                WorkMetadataSource.accepted.is_(True),
                visible_work(user),
            )
        )
    )
    roots = {}
    for found in rows:
        root = await canonical_work(db, found.id)
        roots[root.id] = root
    if len(roots) > 1:
        raise HTTPException(409, "Multiple books match this catalog record. Open the one you mean.")
    if roots:
        return await accessible_work(db, user, next(iter(roots)).id, lock=True)
    safe_cover = cover_url(body.cover_url)
    try:
        snapshot = catalog_snapshot(
            "hardcover", body.external_id, body.title, body.authors, safe_cover
        )
    except ValidationError as error:
        raise HTTPException(422, "Choose a book to follow") from error
    work = Work(
        title=body.title,
        authors=body.authors,
        cover_url=safe_cover,
        provisional=True,
        catalog_public=False,
        catalog_owner_id=user.id,
    )
    db.add(work)
    await db.flush()
    db.add(
        WorkMetadataSource(
            work_id=work.id,
            provider="hardcover",
            external_id=body.external_id,
            snapshot=snapshot,
            fetched_at=datetime.now(UTC),
            accepted=True,
        )
    )
    return work


async def _learn_release_day(db, work, row, body: FollowInput):
    """A follow that is still waiting can record the first full day it learns."""
    if row.state != "waiting" or row.release_date is not None:
        return None
    incoming = parse_iso_day(body.release_date)
    source = "hardcover" if body.provider == "hardcover" or body.external_id else "local"
    basis = body.basis
    if incoming is None:
        incoming, basis, _ = release_facts(work.metadata_fields)
        source = "local"
    if incoming is None:
        return None
    if not await record_release_day(db, row, work, incoming, basis, source=source):
        return None
    return f"Waiting until {row.release_date.isoformat()}; source search starts on release day"


@router.post("/follow", response_model=FollowView, status_code=201)
async def follow(body: FollowInput, user: Member, db: Database):
    work = await _catalog_work(db, user, body)
    await transaction_lock(db, f"monitored-release:{user.id}:{work.id}")
    row = await db.scalar(
        select(MonitoredRelease).where(
            MonitoredRelease.owner_id == user.id, MonitoredRelease.work_id == work.id
        )
    )
    if row and row.state in {"waiting", "wanted", "available"}:
        learned = await _learn_release_day(db, work, row, body)
        await db.commit()
        return _follow_view(row, learned or "Already following this book")
    day = parse_iso_day(body.release_date)
    work.metadata_fields = assign_release(
        work.metadata_fields,
        day,
        body.basis if day else "unknown",
        coming_soon=day is None,
        source="hardcover" if body.provider == "hardcover" or body.external_id else "local",
    )
    generation = row.generation if row else 0
    if row and row.state == "stopped":
        row.state = "waiting"
    options = RequestOptions(mode="audio") if body.basis == "audiobook" else RequestOptions()
    operation = await begin(db, user, work.id, options, f"release-follow:{work.id}:{generation}")
    row = await db.scalar(
        select(MonitoredRelease).where(
            MonitoredRelease.owner_id == user.id, MonitoredRelease.work_id == work.id
        )
    )
    if not row or row.operation_id != operation.id:
        raise HTTPException(409, operation.message)
    await db.commit()
    return _follow_view(row, operation.message)


@router.delete("/follow/{work_id}", response_model=FollowView)
async def unfollow(work_id: UUID, user: Member, db: Database):
    row = await stop(db, user, work_id)
    if not row:
        raise HTTPException(404, "You are not following this book")
    await db.commit()
    return _follow_view(row, "Monitoring stopped")


def _pre_release(work) -> PreReleaseView:
    fields = work.metadata_fields or {}
    libro = fields.get("libro") or {}
    release = fields.get("release") or {}
    candidates = []
    for item in libro.get("candidates") or []:
        try:
            candidates.append(PreReleaseCandidate.model_validate(item))
        except ValidationError:
            continue
    status = "matched" if libro.get("confirmed") else libro.get("status") or "unmatched"
    return PreReleaseView(
        status=status,
        candidates=candidates,
        release_date=release.get("date"),
        basis=release.get("basis") or "unknown",
        message="Confirmed audiobook metadata"
        if libro.get("confirmed")
        else "Confirm a match before it updates your library"
        if candidates
        else "No pre-release match yet",
    )


@router.get("/works/{work_id}", response_model=PreReleaseView)
async def pre_release(work_id: UUID, user: CurrentUser, db: Database):
    work = await accessible_work(db, user, work_id)
    return _pre_release(work)


async def _finish_lookup(db, user_id, work_id, context, result):
    from types import SimpleNamespace

    if result.get("status") == "matched":
        holder = SimpleNamespace(
            title=context["title"],
            authors=list(context["authors"]),
            description=context["description"],
            cover_url=context["cover_url"],
            publication_year=context["publication_year"],
            metadata_fields=dict(context["fields"]),
        )
        applied = stage(holder, result, context["narrators"])
        if applied:
            cover = None
            if not field_locked(holder.metadata_fields, "cover_url"):
                cover = await _cover(applied["cover_url"])
            try:
                await _write_item(
                    context,
                    {**applied, "title": holder.title, "authors": list(holder.authors)},
                    cover,
                )
            except AdapterError as error:
                raise adapter_http_error(error) from error
    user = await current_actor(db, user_id)
    work = await accessible_work(db, user, work_id, lock=True)
    fresh = await audio_context(db, user, work)
    if (
        not fresh
        or fresh.get("medium") != "audio"
        or fresh["title"] != context["title"]
        or list(fresh["authors"]) != list(context["authors"])
    ):
        raise HTTPException(409, "Library evidence changed. Retry the search.")
    await store(db, fresh, result)
    await db.commit()
    return _pre_release(await accessible_work(db, user, work_id))


@router.post("/works/{work_id}/search", response_model=PreReleaseView)
async def search_pre_release(work_id: UUID, user: Member, db: Database):
    work = await accessible_work(db, user, work_id)
    context = await audio_context(db, user, work)
    if not context or context.get("medium") != "audio":
        return PreReleaseView(
            status="skipped",
            message="Pre-release lookup runs for an audiobook in your library.",
        )
    user_id = user.id
    await db.rollback()
    try:
        result = await _open_lookup(context)
    except AdapterError as error:
        raise adapter_http_error(error) from error
    return await _finish_lookup(db, user_id, work_id, context, result)


@router.post("/works/{work_id}/confirm", response_model=PreReleaseView)
async def confirm_pre_release(work_id: UUID, body: ConfirmInput, user: Member, db: Database):
    """Choosing a listed candidate applies it, including a unique title-and-author match."""
    work = await accessible_work(db, user, work_id)
    context = await audio_context(db, user, work)
    if not context or context.get("medium") != "audio":
        raise HTTPException(409, "Pre-release lookup runs for an audiobook in your library.")
    stored = (work.metadata_fields or {}).get("libro") or {}
    raw = next(
        (item for item in stored.get("candidates") or [] if item.get("isbn") == body.isbn),
        None,
    )
    if not raw:
        raise HTTPException(404, "That audiobook is not waiting for confirmation")
    hit = LibroHit.model_validate(raw)
    evidence = MatchEvidence(
        title=work.title,
        authors=work.authors,
        language=work.language,
        identifiers=context["identifiers"],
    )
    if not agrees(evidence, hit):
        raise HTTPException(409, "That match no longer agrees with this book's title and author")
    user_id = user.id
    confirmed = {**context, "identifiers": [("isbn", hit.isbn)]}
    await db.rollback()
    try:
        result = await _open_lookup(confirmed)
    except AdapterError as error:
        raise adapter_http_error(error) from error
    if result.get("status") != "matched":
        raise HTTPException(409, "That audiobook is no longer a single matching ISBN")
    return await _finish_lookup(db, user_id, work_id, context, result)
