"""Resolve accepted provider identities without inferring a match from title text."""

from sqlalchemy import select, tuple_

from app.db.models import Work, WorkMetadataSource
from app.domain.visibility import visible_origin_work, visible_work
from app.domain.work_graph import canonical_map


async def visible_provider_works(db, user, identities):
    identities = set(identities)
    if not identities:
        return {}
    mapping = canonical_map()
    candidates = {}
    for provider, external_id, root in await db.execute(
        select(WorkMetadataSource.provider, WorkMetadataSource.external_id, mapping.c.work_id)
        .join(Work, Work.id == WorkMetadataSource.work_id)
        .join(mapping, mapping.c.origin_id == Work.id)
        .where(
            tuple_(WorkMetadataSource.provider, WorkMetadataSource.external_id).in_(identities),
            WorkMetadataSource.accepted.is_(True),
            visible_origin_work(user),
        )
    ):
        candidates.setdefault((provider, external_id), set()).add(root)
    roots = {next(iter(values)) for values in candidates.values() if len(values) == 1}
    works = {
        work.id: work
        for work in await db.scalars(select(Work).where(Work.id.in_(roots), visible_work(user)))
    }
    return {
        key: works[next(iter(values))]
        for key, values in candidates.items()
        if len(values) == 1 and next(iter(values)) in works
    }
