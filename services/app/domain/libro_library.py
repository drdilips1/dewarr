"""Queue a pre-release lookup for audiobook copies Hardcover does not know."""

import asyncio
from datetime import UTC, datetime, time, timedelta
from types import SimpleNamespace

from cryptography.fernet import InvalidToken
from sqlalchemy import or_, select

from app.adapters.audiobookshelf import Audiobookshelf
from app.adapters.contracts import AdapterError, FailureKind
from app.adapters.librofm import open_client
from app.db.models import (
    AssetContains,
    Integration,
    Library,
    LibraryAsset,
    MonitoredRelease,
    Version,
    Work,
    WorkMetadataSource,
)
from app.db.session import session_factory
from app.domain.hardcover_matching import MatchEvidence
from app.domain.libro_enrichment import evidence_isbn, field_locked, prepare, stage
from app.domain.visibility import visible_library
from app.domain.work_graph import family_ids
from app.importing.covers import CoverError, fetch_cover
from app.security import decrypt_secrets


def _identifiers(snapshot):
    raw = (snapshot or {}).get("identifiers") or {}
    pairs = []
    for kind in ("isbn", "isbn13"):
        value = raw.get(kind)
        if isinstance(value, str) and value.strip():
            pairs.append((kind, value.strip()))
    return pairs


async def audio_context(db, user, work):
    """The linked audiobook item, or an ebook marker when that is all the library has."""
    rows = (
        await db.execute(
            select(LibraryAsset, Integration, Version)
            .join(AssetContains, AssetContains.asset_id == LibraryAsset.id)
            .join(Library, Library.id == LibraryAsset.library_id)
            .join(Integration, Integration.id == Library.integration_id)
            .outerjoin(Version, Version.id == LibraryAsset.version_id)
            .where(
                AssetContains.work_id.in_(family_ids(work.id)),
                AssetContains.verified.is_(True),
                LibraryAsset.state.in_(["present", "stale"]),
                Library.accessible.is_(True),
                Integration.enabled.is_(True),
                Integration.kind == "audiobookshelf",
                visible_library(user),
            )
            .order_by((LibraryAsset.medium == "audio").desc(), LibraryAsset.created_at.desc())
        )
    ).all()
    if not rows:
        return None
    if rows[0][0].medium != "audio":
        return {"medium": "ebook"}
    asset, integration, version = rows[0]
    return {
        "medium": "audio",
        "work_id": work.id,
        "title": work.title,
        "authors": list(work.authors),
        "language": work.language,
        "description": work.description,
        "cover_url": work.cover_url,
        "publication_year": work.publication_year,
        "fields": dict(work.metadata_fields or {}),
        "identifiers": _identifiers(asset.metadata_snapshot),
        "narrators": list(version.narrators) if version and version.narrators else [],
        "item_id": asset.external_id,
        "version_id": version.id if version else None,
        "base_url": integration.base_url,
        "encrypted_secrets": integration.encrypted_secrets,
    }


def library_token(ciphertext):
    """Decrypt only when a confirmed match is about to be written."""
    try:
        secrets = decrypt_secrets(ciphertext)
    except (InvalidToken, ValueError, TypeError) as error:
        raise AdapterError(
            FailureKind.AUTHENTICATION, "Audiobookshelf credentials could not be read."
        ) from error
    token = secrets.get("token") if isinstance(secrets, dict) else None
    if not isinstance(token, str) or not token:
        raise AdapterError(
            FailureKind.AUTHENTICATION, "Audiobookshelf credentials could not be read."
        )
    return token


async def claim(db, limit=5):
    cutoff = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
    accepted = (
        select(WorkMetadataSource.id)
        .where(
            WorkMetadataSource.work_id == Work.id,
            WorkMetadataSource.provider.in_(["hardcover", "librofm"]),
            WorkMetadataSource.accepted.is_(True),
        )
        .exists()
    )
    checked = Work.metadata_fields["libro"]["checked_at"].astext
    rows = list(
        await db.scalars(
            select(Work)
            .join(AssetContains, AssetContains.work_id == Work.id)
            .join(LibraryAsset, LibraryAsset.id == AssetContains.asset_id)
            .where(
                AssetContains.verified.is_(True),
                LibraryAsset.medium == "audio",
                LibraryAsset.state.in_(["present", "stale"]),
                ~accepted,
                Work.metadata_fields["libro"]["confirmed"].astext.is_distinct_from("true"),
                or_(checked.is_(None), checked < cutoff),
            )
            .order_by(Work.created_at, Work.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    now = datetime.now(UTC).isoformat()
    for work in rows:
        fields = dict(work.metadata_fields or {})
        libro = dict(fields.get("libro") or {})
        libro["checked_at"] = now
        fields["libro"] = libro
        work.metadata_fields = fields
    return [work.id for work in rows]


def _holder(context):
    return SimpleNamespace(
        title=context["title"],
        authors=list(context["authors"]),
        description=context["description"],
        cover_url=context["cover_url"],
        publication_year=context["publication_year"],
        metadata_fields=dict(context["fields"]),
    )


def _evidence(context):
    return MatchEvidence(
        title=context["title"],
        authors=context["authors"],
        language=context["language"],
        identifiers=context["identifiers"],
    )


async def _cover(url):
    if not url:
        return None
    try:
        return await fetch_cover(url)
    except (CoverError, OSError, ValueError):
        return None


async def lookup(context, *, search, publication):
    """Ebook copies never call the pre-release provider."""
    medium = "audio" if context and context.get("medium") == "audio" else "ebook"
    evidence = (
        _evidence(context) if medium == "audio" else MatchEvidence(title="Ebook", authors=["None"])
    )
    return await prepare(evidence, medium=medium, search=search, publication=publication)


async def _write_item(context, applied, cover):
    token = library_token(context["encrypted_secrets"])
    async with Audiobookshelf(context["base_url"], token) as library:
        await library.update_item(
            context["item_id"],
            title=applied["title"],
            authors=applied["authors"],
            narrators=applied["narrators"],
        )
        if cover:
            await library.update_cover(context["item_id"], cover)


async def store(db, context, result):
    work = await db.get(Work, context["work_id"], with_for_update=True)
    if not work or work.title != context["title"] or list(work.authors) != list(context["authors"]):
        return None
    holder = _holder({**context, "fields": dict(work.metadata_fields or {})})
    applied = stage(holder, result, context["narrators"])
    work.title = holder.title
    work.authors = holder.authors
    work.description = holder.description
    work.cover_url = holder.cover_url
    work.publication_year = holder.publication_year
    work.metadata_fields = holder.metadata_fields
    if not applied:
        return None
    if context["version_id"]:
        version = await db.get(Version, context["version_id"])
        if version and version.work_id == work.id:
            if not field_locked(holder.metadata_fields, "title"):
                version.title = holder.title
            if applied["narrators"]:
                version.narrators = applied["narrators"]
            version.identifiers = {**(version.identifiers or {}), "isbn": applied["isbn"]}
            if applied["release_date"] and not field_locked(
                holder.metadata_fields, "publication_year"
            ):
                version.publication_year = applied["release_date"].year
    if applied["release_date"]:
        monitors = await db.scalars(
            select(MonitoredRelease).where(
                MonitoredRelease.work_id == work.id,
                MonitoredRelease.state == "waiting",
            )
        )
        for row in monitors:
            row.release_date = applied["release_date"]
            row.basis = "audiobook"
            row.next_check_at = datetime.combine(applied["release_date"], time.min, tzinfo=UTC)
    return applied


async def _open_lookup(context):
    endpoint, page, client = open_client()

    async def search(query, isbn=False):
        return await client.search(query, isbn=isbn)

    async def publication(isbn):
        await asyncio.sleep(1.1)
        return await client.publication(isbn)

    async with endpoint, page:
        return await lookup(context, search=search, publication=publication)


async def _reader(db, work):
    from app.db.models import User

    if work.catalog_owner_id:
        owner = await db.get(User, work.catalog_owner_id)
        if owner and owner.active:
            return owner
    return await db.scalar(select(User).where(User.role == "admin", User.active.is_(True)))


async def process(work_id):
    async with session_factory()() as db:
        work = await db.get(Work, work_id)
        user = await _reader(db, work) if work else None
        context = await audio_context(db, user, work) if user and work else None
    if not context or context.get("medium") != "audio":
        return
    if evidence_isbn(_evidence(context)) is None and not context["authors"]:
        return
    try:
        result = await _open_lookup(context)
    except AdapterError:
        return
    if result.get("status") == "matched":
        holder = _holder(context)
        applied = stage(holder, result, context["narrators"])
        cover = None
        if applied and not field_locked(holder.metadata_fields, "cover_url"):
            cover = await _cover(applied["cover_url"])
        try:
            if applied:
                await _write_item(
                    context,
                    {**applied, "title": holder.title, "authors": list(holder.authors)},
                    cover,
                )
        except AdapterError:
            return
    async with session_factory()() as db, db.begin():
        work = await db.get(Work, work_id)
        user = await _reader(db, work) if work else None
        fresh = await audio_context(db, user, work) if user and work else None
        same = (
            fresh
            and fresh["title"] == context["title"]
            and list(fresh["authors"]) == list(context["authors"])
        )
        if not same:
            return
        await store(db, fresh, result)


async def schedule():
    from app.config import get_settings

    if get_settings().recovery_mode:
        return
    async with session_factory()() as db, db.begin():
        work_ids = await claim(db)
    for work_id in work_ids:
        await process(work_id)
        await asyncio.sleep(1.1)
