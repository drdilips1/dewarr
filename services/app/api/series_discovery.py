"""Catalog-observed series gaps, without inferring reading progress or main membership."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.catalog import WorkView, work_view
from app.api.dependencies import CurrentUser, Database
from app.db.models import CatalogSeries, SeriesMembership, Work
from app.domain.availability import availability_for, availability_rows
from app.domain.catalog_display import display_map
from app.domain.pack_coverage import CATALOG_FRESH_FOR
from app.domain.visibility import visible_work

router = APIRouter(prefix="/discovery", tags=["discovery"])
Medium = Literal["any", "ebook", "audio"]


class SeriesGapBook(BaseModel):
    work: WorkView
    position: str | None
    ambiguous_position: bool


class SeriesGap(BaseModel):
    external_id: str
    name: str
    fetched_at: datetime
    catalog_stale: bool
    inventory_stale: bool
    owned: int
    ebook: int
    audio: int
    published: int
    missing: int
    unknown_publication: int
    future_publication: int
    books: list[SeriesGapBook]


class SeriesGapShelf(BaseModel):
    items: list[SeriesGap] = Field(default_factory=list)
    medium: Medium
    page: int
    has_more: bool
    attribution: str = "Your observed Hardcover catalogs and accessible library holdings"


def normal_entry():
    data = SeriesMembership.snapshot
    return (
        data["compilation"].as_boolean().is_(False),
        data["partial"].as_boolean().is_(False),
        data["canonical_id"].as_string().is_(None),
    )


def entries_for(user, mapping):
    return (
        select(SeriesMembership.series_id)
        .join(mapping, mapping.c.origin_id == SeriesMembership.work_id)
        .join(Work, Work.id == mapping.c.work_id)
        .where(SeriesMembership.present.is_(True), visible_work(user), *normal_entry())
    )


def present(availability, medium):
    return availability.owned if medium == "any" else getattr(availability, medium)


def projection(series, pairs, available, medium, now):
    # Group original entries by canonical identity before counting or selecting gaps.
    grouped = {}
    positions = {}
    for entry, work in pairs:
        data = entry.snapshot
        if data["compilation"] or data["partial"] or data["canonical_id"]:
            continue
        grouped.setdefault(work.id, (work, []))[1].append(data)
        if data["position"] is not None:
            positions.setdefault(Decimal(data["position"]), set()).add(work.id)
    owned = sum(available[key].owned for key in grouped)
    if not owned:
        return None
    candidates = []
    published = unknown = future = 0
    for work, records in grouped.values():
        dates = [date.fromisoformat(r["release_date"]) for r in records if r["release_date"]]
        if not dates:
            unknown += 1
            continue
        if min(dates) > now.date():
            future += 1
            continue
        published += 1
        if present(available[work.id], medium):
            continue
        known_positions = {Decimal(r["position"]) for r in records if r["position"] is not None}
        position = min(known_positions) if known_positions else None
        ambiguous = len(known_positions) > 1 or any(len(positions[p]) > 1 for p in known_positions)
        candidates.append((position, work, ambiguous))
    if not candidates:
        return None
    candidates.sort(
        key=lambda value: (
            value[0] is None,
            value[0] if value[0] is not None else Decimal(0),
            value[1].title.casefold(),
            str(value[1].id),
        )
    )
    return SeriesGap(
        external_id=series.external_id,
        name=series.name,
        fetched_at=series.fetched_at,
        catalog_stale=series.fetched_at < now - CATALOG_FRESH_FOR,
        inventory_stale=any(available[key].stale for key in grouped),
        owned=owned,
        ebook=sum(available[key].ebook for key in grouped),
        audio=sum(available[key].audio for key in grouped),
        published=published,
        missing=len(candidates),
        unknown_publication=unknown,
        future_publication=future,
        books=[
            SeriesGapBook(
                work=work_view(work, available[work.id]),
                position=str(position) if position is not None else None,
                ambiguous_position=ambiguous,
            )
            for position, work, ambiguous in candidates[:3]
        ],
    )


@router.get("/series", response_model=SeriesGapShelf)
async def series_gaps(
    user: CurrentUser,
    db: Database,
    medium: Medium = "any",
    page: int = Query(default=1, ge=1, le=100),
    limit: int = Query(default=4, ge=1, le=12),
):
    now = datetime.now(UTC)
    ownership = availability_rows(user, display_map(user)).subquery()
    owned = select(ownership.c.work_id).distinct()
    satisfied = owned if medium == "any" else owned.where(ownership.c.medium == medium)
    mapping = display_map(user)
    entries = entries_for(user, mapping)
    seed_series = entries.where(mapping.c.work_id.in_(owned))
    missing_series = entries.where(
        mapping.c.work_id.not_in(satisfied),
        SeriesMembership.snapshot["release_date"].as_string() <= now.date().isoformat(),
    )
    rows = list(
        await db.scalars(
            select(CatalogSeries)
            .where(
                CatalogSeries.owner_id == user.id,
                CatalogSeries.provider == "hardcover",
                CatalogSeries.fetched_at.is_not(None),
                CatalogSeries.id.in_(seed_series),
                CatalogSeries.id.in_(missing_series),
            )
            .order_by(CatalogSeries.fetched_at.desc(), CatalogSeries.name, CatalogSeries.id)
            .offset((page - 1) * limit)
            .limit(limit + 1)
        )
    )
    selected = rows[:limit]
    if not selected:
        return SeriesGapShelf(medium=medium, page=page, has_more=False)
    members = (
        await db.execute(
            select(SeriesMembership, Work)
            .join(mapping, mapping.c.origin_id == SeriesMembership.work_id)
            .join(Work, Work.id == mapping.c.work_id)
            .where(
                SeriesMembership.series_id.in_([row.id for row in selected]),
                SeriesMembership.present.is_(True),
                visible_work(user),
            )
        )
    ).all()
    grouped = {}
    for member, work in members:
        grouped.setdefault(member.series_id, []).append((member, work))
    available = await availability_for(db, user, list({work.id for _, work in members}))
    items = [projection(row, grouped.get(row.id, []), available, medium, now) for row in selected]
    return SeriesGapShelf(
        items=[item for item in items if item],
        medium=medium,
        page=page,
        has_more=len(rows) > limit,
    )
