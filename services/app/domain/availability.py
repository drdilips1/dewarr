from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AssetContains, Integration, Library, LibraryAsset, LibraryGrant, User
from app.domain.work_graph import canonical_map


class Availability(BaseModel):
    owned: bool = False
    ebook: bool = False
    audio: bool = False
    stale: bool = False
    in_collection: bool = False


async def availability_for(
    db: AsyncSession,
    user: User,
    work_ids: list[UUID],
) -> dict[UUID, Availability]:
    result = {work_id: Availability() for work_id in work_ids}
    if not work_ids:
        return result
    mapping = canonical_map()
    roots = dict((await db.execute(select(mapping).where(mapping.c.origin_id.in_(work_ids)))).all())
    by_root = {}
    for origin, root in roots.items():
        by_root.setdefault(root, []).append(origin)
    query = (
        select(mapping.c.work_id, LibraryAsset.medium, LibraryAsset.state, LibraryAsset.containment)
        .select_from(AssetContains)
        .join(mapping, mapping.c.origin_id == AssetContains.work_id)
        .join(LibraryAsset, AssetContains.asset_id == LibraryAsset.id)
        .join(Library, LibraryAsset.library_id == Library.id)
        .join(Integration, Library.integration_id == Integration.id)
        .where(
            mapping.c.work_id.in_(by_root),
            AssetContains.verified.is_(True),
            LibraryAsset.full_content.is_(True),
            LibraryAsset.state.in_(["present", "stale"]),
            Library.accessible.is_(True),
            Integration.enabled.is_(True),
        )
    )
    if user.role != "admin":
        query = query.join(LibraryGrant, LibraryGrant.library_id == LibraryAsset.library_id).where(
            LibraryGrant.user_id == user.id
        )
    for work_id, medium, state, containment in (await db.execute(query)).all():
        for origin in by_root[work_id]:
            availability = result[origin]
            availability.owned = True
            availability.ebook |= medium == "ebook"
            availability.audio |= medium == "audio"
            availability.stale |= state == "stale"
            availability.in_collection |= containment is not None
    return result
