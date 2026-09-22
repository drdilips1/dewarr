"""Library series suggestions. Catalog loads never authorize a search or download."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from app.adapters.contracts import AdapterError
from app.db.models import (
    AssetContains,
    CatalogAccount,
    CatalogSeries,
    Operation,
    SeriesGapBaseline,
    SeriesGapDismissal,
    SeriesGapSighting,
    User,
    Work,
    WorkMetadataSource,
)
from app.db.session import session_factory
from app.domain import catalog_series
from app.domain.availability import availability_rows
from app.domain.series_preparation import FAILURE_BACKOFF, series_links
from app.domain.visibility import visible_origin_work
from app.domain.work_graph import canonical_map
from app.jobs.queue import enqueue

PROVIDER = "hardcover"
SCAN_TASK = "series.library_scan"
MAX_PER_RUN = 2
FRESH_FOR = timedelta(days=7)
CHECK_EVERY = timedelta(minutes=15)
ACTIVE = {"queued", "running", "retrying"}


def _family(user):
    origins = (
        availability_rows(user, canonical_map()).with_only_columns(AssetContains.work_id).distinct()
    )
    mapping = canonical_map()
    roots = select(mapping.c.work_id).where(mapping.c.origin_id.in_(origins))
    return select(mapping.c.origin_id).where(mapping.c.work_id.in_(roots))


async def owned_series_refs(db, user):
    """Series ids on accepted Hardcover matches for works this user owns."""
    sources = list(
        await db.scalars(
            select(WorkMetadataSource)
            .join(Work, Work.id == WorkMetadataSource.work_id)
            .where(
                WorkMetadataSource.work_id.in_(_family(user)),
                WorkMetadataSource.provider == PROVIDER,
                WorkMetadataSource.accepted.is_(True),
                visible_origin_work(user),
            )
            .order_by(WorkMetadataSource.external_id, WorkMetadataSource.id)
        )
    )
    refs = {}
    for source in sources:
        raw = source.snapshot.get("series") if isinstance(source.snapshot, dict) else None
        if not isinstance(raw, list):
            continue
        for key, name in series_links(raw[:50]).items():
            refs.setdefault(key, name)
    dismissed = set(
        await db.scalars(
            select(SeriesGapDismissal.external_id).where(
                SeriesGapDismissal.user_id == user.id,
                SeriesGapDismissal.provider == PROVIDER,
            )
        )
    )
    return {key: name for key, name in refs.items() if key not in dismissed}


async def _due(db, user, refs, limit):
    if not refs or limit <= 0:
        return []
    now = datetime.now(UTC)
    rows = {
        row.external_id: row
        for row in await db.scalars(
            select(CatalogSeries).where(
                CatalogSeries.owner_id == user.id,
                CatalogSeries.provider == PROVIDER,
                CatalogSeries.external_id.in_(list(refs)),
            )
        )
    }
    operation_ids = [row.operation_id for row in rows.values() if row.operation_id]
    operations = {}
    if operation_ids:
        operations = {
            row.id: row
            for row in await db.scalars(select(Operation).where(Operation.id.in_(operation_ids)))
        }
    ranked = []
    for external_id in refs:
        row = rows.get(external_id)
        operation = operations.get(row.operation_id) if row and row.operation_id else None
        if row and row.fetched_at and row.fetched_at >= now - FRESH_FOR:
            continue
        if operation and operation.status in ACTIVE:
            continue
        if _recent_failure(operation, now):
            continue
        missing = row is None or row.fetched_at is None
        observed = row.fetched_at if row and row.fetched_at else datetime(1970, 1, 1, tzinfo=UTC)
        ranked.append((0 if missing else 1, observed, external_id))
    ranked.sort()
    return [external_id for _, _, external_id in ranked[:limit]]


async def _active_refreshes(db, user):
    return (
        await db.scalar(
            select(func.count())
            .select_from(Operation)
            .where(
                Operation.owner_id == user.id,
                Operation.kind == catalog_series.KIND,
                Operation.status.in_(ACTIVE),
            )
        )
        or 0
    )


async def enqueue_refreshes(db, user):
    """Queue a bounded set of catalog observations. Never creates a request."""
    account = await db.get(CatalogAccount, user.id)
    if (
        not user.active
        or user.role == "viewer"
        or not account
        or not account.enabled
        or not account.suggest_series_gaps
    ):
        return []
    refs = await owned_series_refs(db, user)
    await baseline_loaded(db, user, refs)
    slots = MAX_PER_RUN - await _active_refreshes(db, user)
    queued = []
    for external_id in await _due(db, user, refs, slots):
        try:
            operation = await catalog_series.start(
                db,
                user,
                external_id,
                f"series-gap:{external_id}:{uuid4()}",
                reuse_active=True,
            )
        except (HTTPException, AdapterError):
            break
        queued.append(operation)
    return queued


async def scan_user(user_id: UUID):
    from app.config import get_settings

    if get_settings().recovery_mode:
        return
    async with session_factory()() as db, db.begin():
        user = await db.get(User, user_id)
        if user:
            await enqueue_refreshes(db, user)


async def schedule():
    from app.config import get_settings

    if get_settings().recovery_mode:
        return
    now = datetime.now(UTC)
    async with session_factory()() as db, db.begin():
        accounts = list(
            await db.scalars(
                select(CatalogAccount)
                .join(User, User.id == CatalogAccount.user_id)
                .where(
                    CatalogAccount.enabled.is_(True),
                    CatalogAccount.suggest_series_gaps.is_(True),
                    User.active.is_(True),
                    User.role != "viewer",
                    or_(
                        CatalogAccount.series_gap_checked_at.is_(None),
                        CatalogAccount.series_gap_checked_at <= now - CHECK_EVERY,
                    ),
                )
                .order_by(CatalogAccount.series_gap_checked_at.asc().nullsfirst())
                .limit(10)
                .with_for_update(of=CatalogAccount, skip_locked=True)
            )
        )
        for account in accounts:
            account.series_gap_checked_at = now
            await enqueue(db, SCAN_TASK, user_id=str(account.user_id))


async def dismissed(db, user_id, external_id):
    return (await db.get(SeriesGapDismissal, (user_id, PROVIDER, external_id))) is not None


async def dismiss(db, user, external_id):
    from app.adapters.catalog_providers import identifier

    identifier(PROVIDER, external_id)
    await db.execute(
        insert(SeriesGapDismissal)
        .values(user_id=user.id, provider=PROVIDER, external_id=external_id)
        .on_conflict_do_nothing(index_elements=["user_id", "provider", "external_id"])
    )
    await db.execute(
        delete(SeriesGapSighting).where(
            SeriesGapSighting.user_id == user.id,
            SeriesGapSighting.provider == PROVIDER,
            SeriesGapSighting.external_id == external_id,
        )
    )
    await db.execute(
        delete(SeriesGapBaseline).where(
            SeriesGapBaseline.user_id == user.id,
            SeriesGapBaseline.provider == PROVIDER,
            SeriesGapBaseline.external_id == external_id,
        )
    )


async def mark_seen(db, user, external_id=None):
    now = datetime.now(UTC)
    statement = update(SeriesGapSighting).where(
        SeriesGapSighting.user_id == user.id,
        SeriesGapSighting.provider == PROVIDER,
        SeriesGapSighting.seen_at.is_(None),
    )
    if external_id:
        from app.adapters.catalog_providers import identifier

        identifier(PROVIDER, external_id)
        statement = statement.where(SeriesGapSighting.external_id == external_id)
    await db.execute(statement.values(seen_at=now))


async def unseen_index(db, user):
    rows = (
        await db.execute(
            select(SeriesGapSighting.external_id, SeriesGapSighting.work_id).where(
                SeriesGapSighting.user_id == user.id,
                SeriesGapSighting.provider == PROVIDER,
                SeriesGapSighting.seen_at.is_(None),
            )
        )
    ).all()
    index = {}
    for external_id, work_id in rows:
        index.setdefault(external_id, set()).add(work_id)
    return index


def _recent_failure(operation, now):
    """Cooldown from the last change, not from when the attempt was created."""
    if not operation or operation.status not in {"failed", "cancelled"}:
        return False
    changed = operation.updated_at or operation.created_at
    return changed > now - FAILURE_BACKOFF


async def baseline_loaded(db, user, refs):
    """Record catalogs already on hand so a later refresh can mark new books."""
    if not refs:
        return
    loaded = list(
        await db.scalars(
            select(CatalogSeries).where(
                CatalogSeries.owner_id == user.id,
                CatalogSeries.provider == PROVIDER,
                CatalogSeries.external_id.in_(list(refs)),
                CatalogSeries.fetched_at.is_not(None),
            )
        )
    )
    if not loaded:
        return
    known = set(
        await db.scalars(
            select(SeriesGapBaseline.external_id).where(
                SeriesGapBaseline.user_id == user.id,
                SeriesGapBaseline.provider == PROVIDER,
                SeriesGapBaseline.external_id.in_([row.external_id for row in loaded]),
            )
        )
    )
    for row in loaded:
        if row.external_id not in known:
            await record_sightings(db, user, row)


async def record_sightings(db, user, series):
    """Baseline the first observation. Later published gaps stay unseen until opened."""
    account = await db.get(CatalogAccount, user.id)
    if (
        not account
        or not account.suggest_series_gaps
        or await dismissed(db, user.id, series.external_id)
    ):
        return
    from app.api.series_discovery import series_gap_ids

    gap_ids = await series_gap_ids(db, user, series)
    if gap_ids is None:
        return
    now = datetime.now(UTC)
    baseline = await db.get(SeriesGapBaseline, (user.id, PROVIDER, series.external_id))
    known = set()
    if baseline is None:
        db.add(
            SeriesGapBaseline(
                user_id=user.id,
                provider=PROVIDER,
                external_id=series.external_id,
                baselined_at=now,
            )
        )
        seen_at = now
    else:
        seen_at = None
        known = set(
            await db.scalars(
                select(SeriesGapSighting.work_id).where(
                    SeriesGapSighting.user_id == user.id,
                    SeriesGapSighting.provider == PROVIDER,
                    SeriesGapSighting.external_id == series.external_id,
                )
            )
        )
    for work_id in gap_ids:
        if work_id in known:
            continue
        db.add(
            SeriesGapSighting(
                user_id=user.id,
                provider=PROVIDER,
                external_id=series.external_id,
                work_id=work_id,
                first_seen_at=now,
                seen_at=seen_at,
            )
        )
