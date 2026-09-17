from datetime import UTC, datetime
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.adapters.catalog_types import BookData, Provider
from app.db.models import MetadataSettings, ProviderObject, Version, Work, WorkMetadataSource
from app.domain.identity import normalized, work_key
from app.domain.operations import transaction_lock
from app.domain.visibility import visible_work

FIELDS = ("title", "authors", "description", "publication_year", "language", "cover_url")


class MetadataPreferences(BaseModel):
    primary: Provider = "hardcover"
    language: str = Field(default="en", min_length=2, max_length=20)
    covers: Literal["automatic", "hardcover", "openlibrary"] = "automatic"
    field_providers: dict[str, Provider] = Field(default_factory=dict)

    @field_validator("field_providers")
    @classmethod
    def supported(cls, value):
        if set(value) - set(FIELDS):
            raise ValueError("Unsupported metadata field")
        return value


async def preferences(db):
    row = await db.get(MetadataSettings, 1)
    return MetadataPreferences.model_validate(row.preferences if row else {})


def same_work(work, book):
    key = work_key(book.title, book.authors)
    return bool(key and key == work_key(work.title, work.authors))


async def resolve_fields(db, work, settings):
    sources = (
        await db.scalars(
            select(WorkMetadataSource)
            .where(WorkMetadataSource.work_id == work.id, WorkMetadataSource.accepted.is_(True))
            .order_by(WorkMetadataSource.fetched_at.desc(), WorkMetadataSource.id)
        )
    ).all()
    fields = dict(work.metadata_fields.get("fields", {}))
    for field in FIELDS:
        previous = fields.get(field, {})
        if previous.get("locked"):
            continue
        primary = settings.field_providers.get(field) or (
            settings.covers
            if field == "cover_url" and settings.covers != "automatic"
            else settings.primary
        )
        ordered = sorted(sources, key=lambda source: source.provider != primary)
        selected = next(
            (source for source in ordered if source.snapshot.get(field) not in (None, "", [])), None
        )
        if selected:
            value = selected.snapshot[field]
            setattr(work, field, value)
            fields[field] = {
                "value": value,
                "provider": selected.provider,
                "external_id": selected.external_id,
                "locked": False,
                "reason": "Preferred provider"
                if selected.provider == primary
                else "Filled missing field",
                "observed_at": selected.fetched_at.isoformat(),
            }
    work.metadata_fields = {**work.metadata_fields, "fields": fields}
    work.match_key = work_key(work.title, work.authors)


async def attach_source(db, work, book, *, explicit=False):
    link = await db.scalar(
        select(WorkMetadataSource).where(
            WorkMetadataSource.work_id == work.id,
            WorkMetadataSource.provider == book.provider,
            WorkMetadataSource.external_id == book.external_id,
        )
    )
    if link and not (explicit or link.manual_match):
        old = BookData.model_validate(link.snapshot)
        if work_key(old.title, old.authors) != work_key(book.title, book.authors) or (
            book.canonical_id and book.canonical_id != book.external_id
        ):
            raise HTTPException(
                409,
                "The provider changed this book's identity. Review the match before refreshing.",
            )
    elif not link and not explicit and not same_work(work, book):
        raise HTTPException(409, "This catalog result needs an explicit match confirmation.")
    if book.canonical_id and book.canonical_id != book.external_id:
        raise HTTPException(
            409, "This provider record was merged. Select its current catalog record."
        )
    if not link:
        link = WorkMetadataSource(
            work_id=work.id, provider=book.provider, external_id=book.external_id
        )
        db.add(link)
    snapshot = book.model_dump(mode="json")
    if book.editions_offset:
        if not link.snapshot or link.snapshot.get("next_edition_offset") != book.editions_offset:
            raise HTTPException(409, "Edition pagination changed. Refresh this book and retry.")
        previous = BookData.model_validate(link.snapshot)
        if work_key(previous.title, previous.authors) != work_key(book.title, book.authors):
            raise HTTPException(
                409, "The provider changed this book. Refresh before loading more editions."
            )
        snapshot = {**link.snapshot, "editions_more": book.editions_more}
    snapshot["next_edition_offset"] = book.editions_offset + 50 if book.editions_more else None
    link.snapshot, link.fetched_at, link.accepted = (
        snapshot,
        datetime.now(UTC),
        True,
    )
    link.manual_match = explicit or bool(link.manual_match)
    await db.flush()
    await resolve_fields(db, work, await preferences(db))
    work.provisional = False
    for edition in book.editions:
        # Per-work namespace prevents attaching a private library version to an unrelated catalog.
        namespace = f"{book.provider}:{work.id}"
        version_link = await db.scalar(
            select(ProviderObject).where(
                ProviderObject.provider == namespace,
                ProviderObject.kind == "edition",
                ProviderObject.external_id == edition.external_id,
            )
        )
        snapshot = edition.model_dump(mode="json")
        if version_link:
            identity_fields = (
                "medium",
                "title",
                "language",
                "narrators",
                "publication_year",
                "identifiers",
                "abridged",
            )
            if any(
                version_link.snapshot.get(field) != snapshot.get(field) for field in identity_fields
            ):
                # Existing assets keep their identity; review contradictory version changes.
                version_link.match_status = "needs-review"
            else:
                version_link.snapshot = snapshot
                version_link.match_status = "matched"
            continue
        version = Version(
            work_id=work.id,
            medium=edition.medium,
            title=edition.title,
            language=edition.language,
            narrators=edition.narrators,
            abridged=edition.abridged,
            publication_year=edition.publication_year,
            identifiers=edition.identifiers,
        )
        db.add(version)
        await db.flush()
        db.add(
            ProviderObject(
                provider=namespace,
                kind="edition",
                external_id=edition.external_id,
                work_id=work.id,
                version_id=version.id,
                snapshot=snapshot,
                match_status="matched",
            )
        )


async def import_book(db, user, book):
    await transaction_lock(db, "catalog:" + book.provider + ":" + book.external_id)
    await transaction_lock(db, "identity:" + normalized(book.title))
    linked = (
        await db.scalars(
            select(Work)
            .join(WorkMetadataSource)
            .where(
                WorkMetadataSource.provider == book.provider,
                WorkMetadataSource.external_id == book.external_id,
                WorkMetadataSource.accepted.is_(True),
                visible_work(user),
                Work.redirect_to.is_(None),
            )
        )
    ).all()
    if len(linked) > 1:
        raise HTTPException(
            409, "Multiple catalog records need reconciliation. Open the intended book to match it."
        )
    if linked:
        # Adding an already catalogued title is idempotent, not an implicit refresh.
        return linked[0]
    else:
        key = work_key(book.title, book.authors)
        matches = (
            (
                await db.scalars(
                    select(Work).where(
                        Work.match_key == key, visible_work(user), Work.redirect_to.is_(None)
                    )
                )
            ).all()
            if key
            else []
        )
        if len(matches) > 1:
            raise HTTPException(
                409, "Multiple books match. Choose the intended book from your catalog."
            )
        work = (
            matches[0]
            if matches
            else Work(title=book.title, authors=book.authors, catalog_public=True, match_key=key)
        )
        if not matches:
            db.add(work)
            await db.flush()
    # Matching private inventory never promotes its metadata to a public catalog record.
    await attach_source(db, work, book, explicit=False if linked or same_work(work, book) else True)
    return work
