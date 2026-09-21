"""Bundled public collections and fenced refreshes of reader-selected sources."""

import json
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select

from app.adapters.contracts import AdapterError
from app.adapters.goodreads_discovery import fetch_collection
from app.db.models import DiscoveryFollow, User
from app.db.session import session_factory

DATA = Path(__file__).resolve().parents[1] / "data/discovery"


@lru_cache
def catalog():
    return {v["id"]: v for p in sorted(DATA.glob("gr-*.json")) if (v := json.loads(p.read_text()))}


@lru_cache
def coverage():
    path = DATA / "coverage.json"
    return json.loads(path.read_text()) if path.exists() else {"years": {}}


async def refresh(user_id, collection_id, generation):
    async with session_factory()() as db:
        row = await db.get(DiscoveryFollow, (user_id, collection_id))
        user = await db.get(User, user_id)
        if (
            not row
            or not row.tracking
            or row.generation != generation
            or not user
            or not user.active
        ):
            return
        url, old = row.snapshot["source_url"], dict(row.snapshot)
    value, error = None, None
    try:
        value = await fetch_collection(url)
        value.update(title=old["title"], genres=old.get("genres", []), category=old.get("category"))
    except (AdapterError, ValueError):
        error = "Could not refresh Goodreads. Your saved books are still available."
    async with session_factory()() as db, db.begin():
        row = await db.get(DiscoveryFollow, (user_id, collection_id), with_for_update=True)
        user = await db.get(User, user_id)
        if (
            not row
            or not row.tracking
            or row.generation != generation
            or not user
            or not user.active
        ):
            return
        row.error = error
        row.next_check_at = datetime.now(UTC) + timedelta(
            hours=24 if error or old["kind"] == "listopia" else 168
        )
        if value:
            row.snapshot = value


async def schedule():
    from app.config import get_settings
    from app.jobs.queue import enqueue

    if get_settings().recovery_mode:
        return
    async with session_factory()() as db, db.begin():
        rows = list(
            await db.scalars(
                select(DiscoveryFollow)
                .join(User)
                .where(
                    DiscoveryFollow.tracking.is_(True),
                    User.active.is_(True),
                    DiscoveryFollow.next_check_at <= datetime.now(UTC),
                )
                .order_by(DiscoveryFollow.next_check_at)
                .limit(10)
                .with_for_update(skip_locked=True)
            )
        )
        for row in rows:
            row.next_check_at = datetime.now(UTC) + timedelta(hours=1)
            await enqueue(
                db,
                "discovery.refresh",
                user_id=str(row.user_id),
                collection_id=row.collection_id,
                generation=row.generation,
            )
