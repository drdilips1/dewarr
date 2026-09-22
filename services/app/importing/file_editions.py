"""Attach a reviewed download to a catalog book that has no edition of its format."""

import re

from fastapi import HTTPException
from sqlalchemy import select

from app.db.models import AuditEvent, ProviderObject, Version, Work
from app.domain.catalog_language import catalog_language
from app.domain.catalog_titles import display_text, display_title, stripped_title, title_narrators
from app.domain.identity import normalized
from app.domain.operations import transaction_lock
from app.domain.visibility import visible_work
from app.domain.work_graph import canonical_work, graph_lock
from app.importing.grouping import current_grouping
from app.importing.match_evidence import catalog_identifiers, group_evidence
from app.importing.naming import fingerprint

FILE_EDITION_PROVIDER = "file-import"


def inferred_abridged(title, facts):
    if len(facts.abridged) == 1:
        return facts.abridged[0]
    label = display_text(title or "")
    if re.search(r"\(\s*unabridged\s*\)", label):
        return False
    if re.search(r"\(\s*abridged\s*\)", label):
        return True
    return None


def edition_blocker(facts):
    """Identifier noise is review evidence. A group that is not one inspected book is not."""
    for issue in facts.issues:
        if issue == "Some files have not passed content inspection" or issue.startswith(
            "Files disagree about "
        ):
            return issue
    return None


def edition_language(work, facts):
    observed = catalog_language(facts.languages[0]) if len(facts.languages) == 1 else None
    fallback = catalog_language(work.language) if work.language else None
    language = observed or fallback
    if language and len(language) > 20:
        language = fallback if fallback and len(fallback) <= 20 else None
    return language


def edition_identifiers(facts):
    """Keep an identifier only when the file asserts that namespace once."""
    grouped = {}
    for item in facts.identifiers:
        grouped.setdefault(item.namespace, []).append(item.value)
    identifiers = {}
    if len(grouped.get("isbn", [])) == 1:
        identifiers["isbn_13"] = grouped["isbn"][0]
    if len(grouped.get("asin", [])) == 1:
        identifiers["asin"] = grouped["asin"][0]
    return identifiers


def edition_fields(work, group, facts):
    file_title = stripped_title(group.title or "")
    if file_title and display_title(file_title) == display_title(work.title):
        title = work.title
    else:
        title = file_title or work.title
    narrators = list(group.narrators)
    if group.medium == "audio" and not narrators:
        narrators = title_narrators(group.title or "")
    if group.medium != "audio":
        narrators = []
    return {
        "title": title,
        "narrators": narrators,
        "language": edition_language(work, facts),
        "year": facts.years[0] if len(facts.years) == 1 else None,
        "abridged": inferred_abridged(group.title, facts),
        "identifiers": edition_identifiers(facts),
    }


def edition_key(work, group, fields, facts):
    return fingerprint(
        {
            "work_id": str(work.id),
            "medium": group.medium,
            "title": display_title(fields["title"]),
            "narrators": sorted(normalized(name) for name in fields["narrators"]),
            "language": fields["language"],
            "year": fields["year"],
            "abridged": fields["abridged"],
            "identifiers": sorted((item.namespace, item.value) for item in facts.identifiers),
        }
    )


async def matching_version(db, work, group, facts):
    if not facts.identifiers:
        return None
    expected = {(item.namespace, item.value) for item in facts.identifiers}
    rows = (
        await db.scalars(
            select(Version).where(Version.work_id == work.id, Version.medium == group.medium)
        )
    ).all()
    shared = [
        version for version in rows if expected <= catalog_identifiers(version.identifiers or {})
    ]
    # Ambiguous or conflicted editions are not a choice this screen can make.
    # A new edition from the file remains available.
    if len(shared) != 1:
        return None
    pending = await db.scalar(
        select(ProviderObject.id)
        .where(
            ProviderObject.version_id == shared[0].id,
            ProviderObject.match_status == "needs-review",
        )
        .limit(1)
    )
    return None if pending else shared[0]


async def attach_file_edition(db, admin, inspection_id, work_id, group_key, grouping_revision):
    from app.importing.planning import assert_admin, owned_inspection

    await transaction_lock(db, f"inspection-plan:{inspection_id}")
    await assert_admin(db, admin.id)
    row = await owned_inspection(db, admin.id, inspection_id)
    if row.state != "ready" or not row.snapshot:
        raise HTTPException(409, "A completed inspection is required")
    current_revision, grouping = await current_grouping(db, row)
    if grouping_revision != current_revision:
        raise HTTPException(409, "File groups changed; review their current membership")
    group = next((item for item in grouping.groups if item.key == group_key), None)
    if not group:
        raise HTTPException(422, "Selected group is not in this inspection")
    if group.medium not in {"ebook", "audio"}:
        raise HTTPException(422, "Choose an ebook or audiobook group")
    facts = group_evidence(row.snapshot, group)
    if blocker := edition_blocker(facts):
        raise HTTPException(409, blocker)
    await graph_lock(db)
    work = await canonical_work(db, work_id)
    work = await db.get(Work, work.id, with_for_update=True, populate_existing=True)
    if not work or work.redirect_to:
        raise HTTPException(409, "Open the current book record before adding an edition")
    if not await db.scalar(select(Work.id).where(Work.id == work.id, visible_work(admin))):
        raise HTTPException(404, "Book not found")
    if work.metadata_fields.get("identity_rejected"):
        raise HTTPException(409, "Book identity needs review")
    fields = edition_fields(work, group, facts)
    external_id = edition_key(work, group, fields, facts)
    await transaction_lock(db, f"file-edition:{external_id}")
    existing = await matching_version(db, work, group, facts)
    if existing:
        return existing, False
    link = await db.scalar(
        select(ProviderObject).where(
            ProviderObject.provider == FILE_EDITION_PROVIDER,
            ProviderObject.kind == "edition",
            ProviderObject.external_id == external_id,
        )
    )
    if link:
        version = await db.get(Version, link.version_id)
        if (
            not version
            or version.work_id != work.id
            or version.medium != group.medium
            or link.match_status != "matched"
        ):
            raise HTTPException(409, "This file edition is already attached to another book")
        return version, False
    version = Version(
        work_id=work.id,
        medium=group.medium,
        title=fields["title"],
        language=fields["language"],
        narrators=fields["narrators"],
        abridged=fields["abridged"],
        publication_year=fields["year"],
        identifiers=fields["identifiers"],
    )
    db.add(version)
    await db.flush()
    db.add(
        ProviderObject(
            provider=FILE_EDITION_PROVIDER,
            kind="edition",
            external_id=external_id,
            work_id=work.id,
            version_id=version.id,
            snapshot={
                "inspection_id": str(row.id),
                "group_key": group.key,
                "evidence": facts.model_dump(mode="json"),
            },
            match_status="matched",
        )
    )
    db.add(
        AuditEvent(
            actor_id=admin.id,
            action="import.edition.created",
            entity_id=version.id,
            detail={"work_id": str(work.id), "medium": group.medium, "inspection_id": str(row.id)},
        )
    )
    return version, True
