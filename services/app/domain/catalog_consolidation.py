"""Reconcile verified same-provider work identities using the reversible merge journal."""

from fastapi import HTTPException
from sqlalchemy import select

from app.db.models import Work, WorkMetadataSource
from app.domain.catalog_language import catalog_language
from app.domain.hardcover_matching import authors_key
from app.domain.work_graph import canonical_map
from app.domain.work_merges import merge_works, preview_merge


async def consolidate(db, actor, owned_ids):
    mapping = canonical_map()
    rows = (
        await db.execute(
            select(WorkMetadataSource.external_id, Work)
            .join(mapping, mapping.c.origin_id == WorkMetadataSource.work_id)
            .join(Work, Work.id == mapping.c.work_id)
            .where(
                WorkMetadataSource.provider == "hardcover",
                WorkMetadataSource.accepted.is_(True),
                WorkMetadataSource.manual_match.is_(False),
                Work.id.in_(owned_ids),
            )
            .order_by(Work.catalog_public.desc(), Work.created_at, Work.id)
        )
    ).all()
    groups = {}
    for external_id, work in rows:
        fields = work.metadata_fields.get("fields", {})
        if work.metadata_fields.get("identity_rejected") or any(
            fields.get(field, {}).get("locked") for field in ("title", "authors")
        ):
            continue
        language = catalog_language(work.language)
        if not language:
            continue
        key = (external_id, language, tuple(sorted(authors_key(work.authors))))
        groups.setdefault(key, {})[work.id] = work
    results = []
    for (external_id, _, _), records in groups.items():
        target, *sources = list(records.values())
        for source in sources:
            # Do not reconcile a family containing conflicting/rejected provider sources.
            from app.domain.work_graph import family_ids

            evidence = (
                await db.execute(
                    select(
                        WorkMetadataSource.external_id,
                        WorkMetadataSource.accepted,
                        WorkMetadataSource.manual_match,
                    ).where(
                        WorkMetadataSource.work_id.in_(family_ids(source.id)),
                        WorkMetadataSource.provider == "hardcover",
                    )
                )
            ).all()
            target_evidence = (
                await db.execute(
                    select(
                        WorkMetadataSource.external_id,
                        WorkMetadataSource.accepted,
                        WorkMetadataSource.manual_match,
                    ).where(
                        WorkMetadataSource.work_id.in_(family_ids(target.id)),
                        WorkMetadataSource.provider == "hardcover",
                    )
                )
            ).all()
            if any(
                key != external_id or not accepted or manual
                for key, accepted, manual in [*evidence, *target_evidence]
            ):
                continue
            source_id, target_id = source.id, target.id
            try:
                async with db.begin_nested():
                    preview = await preview_merge(db, source_id, target_id, actor.id)
                    await merge_works(db, actor.id, source_id, target_id, preview["revision"])
                results.append(
                    {
                        "source_id": str(source_id),
                        "target_id": str(target_id),
                        "hardcover_id": external_id,
                        "status": "merged",
                    }
                )
            except HTTPException as error:
                results.append(
                    {
                        "source_id": str(source_id),
                        "target_id": str(target_id),
                        "status": "needs-review",
                        "reason": str(error.detail),
                    }
                )
    return results
