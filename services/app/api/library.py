from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from app.adapters.audiobookshelf import ABSItem
from app.api.dependencies import Admin, CurrentUser, Database
from app.db.models import (
    AssetContains,
    AuditEvent,
    Integration,
    Library,
    LibraryAsset,
    LibraryGrant,
    ProviderObject,
    User,
    Work,
)
from app.domain.identity import resolve_abs_version
from app.domain.visibility import visible_library

router = APIRouter(prefix="/library", tags=["library"])


class LibraryView(BaseModel):
    id: UUID
    name: str
    integration_id: UUID
    accessible: bool
    last_complete_sync: datetime | None
    granted_user_ids: list[UUID]


class GrantInput(BaseModel):
    user_ids: list[UUID] = Field(max_length=1000)


class AssetView(BaseModel):
    id: UUID
    library_id: UUID
    library_name: str
    title: str
    medium: str
    state: str
    full_content: bool
    match_status: str
    work_ids: list[UUID]
    version_id: UUID | None
    narrators: list[str]
    formats: list[str]
    last_seen_at: datetime | None
    open_url: str


class AssetPage(BaseModel):
    items: list[AssetView]
    total: int
    offset: int
    limit: int


class MatchInput(BaseModel):
    work_id: UUID | None


@router.get("/libraries", response_model=list[LibraryView])
async def libraries(user: CurrentUser, db: Database):
    records = (
        await db.scalars(
            select(Library)
            .join(Integration)
            .where(
                visible_library(user),
                Integration.enabled.is_(True),
            )
            .order_by(Library.name)
        )
    ).all()
    grants = (
        (
            await db.execute(
                select(LibraryGrant.library_id, LibraryGrant.user_id).where(
                    LibraryGrant.library_id.in_([record.id for record in records]),
                )
            )
        ).all()
        if user.role == "admin"
        else []
    )
    return [
        LibraryView(
            id=record.id,
            name=record.name,
            integration_id=record.integration_id,
            accessible=record.accessible,
            last_complete_sync=record.last_complete_sync,
            granted_user_ids=[user_id for library_id, user_id in grants if library_id == record.id],
        )
        for record in records
    ]


@router.put("/libraries/{library_id}/grants", status_code=204)
async def replace_grants(library_id: UUID, body: GrantInput, admin: Admin, db: Database):
    library = await db.get(Library, library_id, with_for_update=True)
    if not library:
        raise HTTPException(404, "Library not found")
    users = set(
        (
            await db.scalars(
                select(User.id).where(User.id.in_(body.user_ids), User.active.is_(True))
            )
        ).all()
    )
    if users != set(body.user_ids):
        raise HTTPException(422, "One or more accounts are unavailable")
    await db.execute(delete(LibraryGrant).where(LibraryGrant.library_id == library_id))
    db.add_all([LibraryGrant(library_id=library_id, user_id=user_id) for user_id in users])
    db.add(
        AuditEvent(
            actor_id=admin.id,
            action="library.grants.updated",
            entity_id=library_id,
            detail={"user_ids": [str(user_id) for user_id in users]},
        )
    )
    await db.commit()


@router.get("/assets", response_model=AssetPage)
async def assets(
    user: CurrentUser,
    db: Database,
    work_id: UUID | None = None,
    library_id: UUID | None = None,
    needs_review: bool = False,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=40, ge=1, le=100),
):
    conditions = [
        visible_library(user),
        Integration.enabled.is_(True),
        Library.accessible.is_(True),
    ]
    if work_id:
        conditions.append(
            LibraryAsset.id.in_(
                select(AssetContains.asset_id).where(AssetContains.work_id == work_id)
            )
        )
    if library_id:
        conditions.append(Library.id == library_id)
    if needs_review:
        conditions.append(LibraryAsset.match_status == "needs-review")
    query = (
        select(LibraryAsset, Library, Integration)
        .join(Library, LibraryAsset.library_id == Library.id)
        .join(Integration, Library.integration_id == Integration.id)
        .where(*conditions)
    )
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        await db.execute(
            query.order_by(LibraryAsset.title, LibraryAsset.id).offset(offset).limit(limit)
        )
    ).all()
    coverage = (
        await db.execute(
            select(AssetContains.asset_id, AssetContains.work_id).where(
                AssetContains.asset_id.in_([row[0].id for row in rows]),
            )
        )
    ).all()
    views = []
    for asset, library, connection in rows:
        views.append(
            AssetView(
                id=asset.id,
                library_id=library.id,
                library_name=library.name,
                title=asset.title or "Unidentified book",
                medium=asset.medium,
                state=asset.state,
                full_content=asset.full_content,
                match_status=asset.match_status,
                work_ids=[work for identifier, work in coverage if identifier == asset.id],
                version_id=asset.version_id,
                narrators=asset.metadata_snapshot.get("narrators", [])
                if asset.medium == "audio"
                else [],
                formats=sorted({file.get("format", "unknown") for file in asset.files}),
                last_seen_at=asset.last_seen_at,
                open_url=(connection.config.get("public_url") or connection.base_url)
                + "/item/"
                + asset.external_id,
            )
        )
    return AssetPage(items=views, total=total or 0, offset=offset, limit=limit)


@router.post("/assets/{asset_id}/match", status_code=204)
async def match_asset(asset_id: UUID, body: MatchInput, admin: Admin, db: Database):
    integration_id = await db.scalar(
        select(Library.integration_id).join(LibraryAsset).where(LibraryAsset.id == asset_id)
    )
    if integration_id:
        # Match correction and snapshot publication use the same lock order.
        await db.get(Integration, integration_id, with_for_update=True)
    asset = await db.get(LibraryAsset, asset_id, with_for_update=True)
    if not asset:
        raise HTTPException(404, "Library item not found")
    library = await db.get(Library, asset.library_id)
    link = await db.scalar(
        select(ProviderObject)
        .where(
            ProviderObject.provider == f"abs:{library.integration_id}",
            ProviderObject.kind == f"item:{asset.medium}",
            ProviderObject.external_id == asset.external_id,
        )
        .with_for_update()
    )
    if not link:
        raise HTTPException(409, "Sync this library before correcting its match")
    previous = {
        "work_id": str(link.work_id) if link.work_id else None,
        "version_id": str(asset.version_id) if asset.version_id else None,
    }
    work = await db.get(Work, body.work_id) if body.work_id else None
    if body.work_id and (not work or work.redirect_to):
        raise HTTPException(404, "Book not found or merged; select its current record")
    await db.execute(delete(AssetContains).where(AssetContains.asset_id == asset.id))
    item = ABSItem.model_validate(asset.metadata_snapshot)
    link.work_id, link.version_id, link.manual_lock = body.work_id, None, True
    if work:
        version = await resolve_abs_version(db, work, item, asset.medium, link)
        asset.version_id, asset.match_status = version.id, "manual"
        asset.full_content = getattr(item, f"full_{asset.medium}")
        db.add(AssetContains(asset_id=asset.id, work_id=work.id, verified=True))
        link.match_status = "manual"
    else:
        asset.version_id, asset.full_content, asset.match_status = None, False, "needs-review"
        link.match_status = "unmatched"
    link.snapshot = item.model_dump(mode="json")
    db.add(
        AuditEvent(
            actor_id=admin.id,
            action="library.match.corrected",
            entity_id=asset.id,
            detail={
                "before": previous,
                "after": {"work_id": str(body.work_id) if body.work_id else None},
            },
        )
    )
    await db.commit()
