import hashlib
import json
import unicodedata

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.audiobookshelf import ABSItem
from app.db.models import ProviderObject, Version, Work


def normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def work_key(title: str, authors: list[str]) -> str | None:
    if not authors:
        return None  # Title alone cannot identify a work.
    return hashlib.sha256(
        json.dumps(
            [
                normalized(title),
                sorted(normalized(author) for author in authors),
            ]
        ).encode()
    ).hexdigest()


async def resolve_abs_work(db: AsyncSession, item: ABSItem, link: ProviderObject) -> Work | None:
    if link.manual_lock:
        return await db.get(Work, link.work_id) if link.work_id else None
    key = work_key(item.title, item.authors)
    if link.work_id:
        old = link.snapshot
        if old and work_key(old.get("title", ""), old.get("authors", [])) != key:
            link.match_status = "needs-review"
            return None
        return await db.get(Work, link.work_id)
    candidates = (
        (
            await db.scalars(
                select(Work).where(
                    Work.redirect_to.is_(None),
                    or_(Work.match_key == key, func.lower(Work.title) == item.title.lower()),
                )
            )
        ).all()
        if key
        else []
    )
    candidates = [
        candidate
        for candidate in candidates
        if work_key(candidate.title, candidate.authors) == key
        and (
            not candidate.language
            or not item.language
            or normalized(candidate.language) == normalized(item.language)
        )
    ]
    if len(candidates) > 1:
        link.match_status = "needs-review"
        return None
    if candidates:
        work = candidates[0]
    else:
        work = Work(
            title=item.title,
            authors=item.authors,
            description=item.description,
            language=item.language,
            provisional=True,
            catalog_public=False,
            match_key=key,
            metadata_fields={"origin": "audiobookshelf", "fields": {}},
        )
        db.add(work)
        await db.flush()
    link.work_id, link.match_status = work.id, "matched"
    return work


async def resolve_abs_version(
    db: AsyncSession, work: Work, item: ABSItem, medium: str, link: ProviderObject
) -> Version:
    if link.version_id:
        version = await db.get(Version, link.version_id)
        if version and version.work_id == work.id and version.medium == medium:
            return version
    # Unknown recording metadata cannot establish equivalence to another recording.
    version = None
    identifier = "asin" if medium == "audio" else "isbn"
    if item.identifiers.get(identifier):
        candidates = (
            await db.scalars(
                select(Version).where(
                    Version.work_id == work.id,
                    Version.medium == medium,
                    Version.identifiers[identifier].astext == item.identifiers[identifier],
                    Version.narrators == (item.narrators if medium == "audio" else []),
                    Version.language == item.language,
                    Version.abridged == item.abridged,
                    Version.publication_year == item.year,
                )
            )
        ).all()
        if len(candidates) == 1:
            version = candidates[0]
    if not version:
        version = Version(
            work_id=work.id,
            medium=medium,
            title=item.title,
            language=item.language,
            narrators=item.narrators if medium == "audio" else [],
            abridged=item.abridged,
            publication_year=item.year,
            identifiers=item.identifiers,
        )
        db.add(version)
        await db.flush()
    link.version_id = version.id
    return version


def version_changed(item: ABSItem, link: ProviderObject, medium: str) -> bool:
    """Changed recording/edition evidence requires review, even with a locked work match."""
    if not link.version_id or not link.snapshot:
        return False
    fields = ["language", "year", "abridged", "identifiers"]
    if medium == "audio":
        fields.append("narrators")
    current = item.model_dump(mode="json")
    return any(link.snapshot.get(field) != current.get(field) for field in fields)
