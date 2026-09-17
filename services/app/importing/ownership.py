"""Confirmed inventory satisfaction for an exact imported catalog version."""

from sqlalchemy import select

from app.db.models import Integration, Library, LibraryAsset


async def already_owned(db, version_id, library_id):
    return await db.scalar(
        select(LibraryAsset.id)
        .join(Library)
        .join(Integration)
        .where(
            LibraryAsset.version_id == version_id,
            LibraryAsset.library_id == library_id,
            LibraryAsset.state == "present",
            LibraryAsset.full_content.is_(True),
            LibraryAsset.match_status == "matched",
            Library.accessible.is_(True),
            Integration.enabled.is_(True),
        )
        .limit(1)
    )
