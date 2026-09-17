from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AssetContains, LibraryAsset, LibraryGrant, User


class Availability(BaseModel):
    owned: bool = False
    ebook: bool = False
    audio: bool = False
    stale: bool = False


async def availability_for(
    db: AsyncSession,
    user: User,
    work_ids: list[UUID],
) -> dict[UUID, Availability]:
    result = {work_id: Availability() for work_id in work_ids}
    if not work_ids:
        return result
    query = (
        select(AssetContains.work_id, LibraryAsset.medium, LibraryAsset.state)
        .join(LibraryAsset, AssetContains.asset_id == LibraryAsset.id)
        .where(
            AssetContains.work_id.in_(work_ids),
            AssetContains.verified.is_(True),
            LibraryAsset.full_content.is_(True),
            LibraryAsset.state.in_(["present", "stale"]),
        )
    )
    if user.role != "admin":
        query = query.join(LibraryGrant, LibraryGrant.library_id == LibraryAsset.library_id).where(
            LibraryGrant.user_id == user.id
        )
    for work_id, medium, state in (await db.execute(query)).all():
        availability = result[work_id]
        availability.owned = True
        availability.ebook |= medium == "ebook"
        availability.audio |= medium == "audio"
        availability.stale |= state == "stale"
    return result
