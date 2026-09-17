from sqlalchemy import exists, or_, select

from app.db.models import (
    AssetContains,
    Integration,
    Library,
    LibraryAsset,
    LibraryGrant,
    User,
    Work,
)


def visible_library(user: User):
    if user.role == "admin":
        return True
    return exists(
        select(LibraryGrant.library_id).where(
            LibraryGrant.library_id == Library.id,
            LibraryGrant.user_id == user.id,
        )
    )


def visible_work(user: User):
    if user.role == "admin":
        return True
    return or_(
        Work.catalog_public.is_(True),
        exists(
            select(AssetContains.work_id)
            .join(LibraryAsset, AssetContains.asset_id == LibraryAsset.id)
            .join(Library, LibraryAsset.library_id == Library.id)
            .join(Integration, Library.integration_id == Integration.id)
            .where(
                AssetContains.work_id == Work.id,
                Library.accessible.is_(True),
                Integration.enabled.is_(True),
                visible_library(user),
            )
        ),
    )
