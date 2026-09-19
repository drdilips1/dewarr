from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import Text, cast, delete, func, or_, select

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
from app.domain.corrections import asset_state, correct_asset, revision
from app.domain.visibility import visible_library, visible_work
from app.domain.work_graph import canonical_map, family_ids

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
    authors: list[str] = Field(default_factory=list)
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
    match_revision: str | None = None
    collection: bool = False
    collection_work_id: UUID | None = None
    contents: list["ContainedBookView"] = Field(default_factory=list)


class ContainedBookView(BaseModel):
    work_id: UUID
    title: str
    verified: bool


class AssetPage(BaseModel):
    items: list[AssetView]
    total: int
    offset: int
    limit: int


class MatchInput(BaseModel):
    work_id: UUID | None
    expected_revision: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class ContentsInput(BaseModel):
    work_ids: list[UUID] = Field(min_length=2, max_length=100)
    expected_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    complete_books_confirmed: Literal[True]


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
    q: str = Query(default="", max_length=300),
    medium: Literal["any", "ebook", "audio"] = "any",
    state: Literal[
        "any",
        "present",
        "stale",
        "missing-suspected",
        "missing-confirmed",
        "scope-unavailable",
        "moved",
    ] = "any",
    sort: Literal["title", "recent"] = "title",
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
                select(AssetContains.asset_id).where(AssetContains.work_id.in_(family_ids(work_id)))
            )
        )
    if library_id:
        conditions.append(Library.id == library_id)
    if needs_review:
        conditions.append(LibraryAsset.match_status == "needs-review")
    if medium != "any":
        conditions.append(LibraryAsset.medium == medium)
    if state != "any":
        conditions.append(LibraryAsset.state == state)
    if q.strip():
        # Search only declared title/credit fields, never arbitrary provider payloads.
        pattern = (
            "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        )
        mapping = canonical_map()
        catalog_matches = (
            select(AssetContains.asset_id)
            .join(mapping, mapping.c.origin_id == AssetContains.work_id)
            .join(Work, Work.id == mapping.c.work_id)
            .where(
                visible_work(user),
                or_(Work.title.ilike(pattern), cast(Work.authors, Text).ilike(pattern)),
            )
        )
        conditions.append(
            or_(
                LibraryAsset.title.ilike(pattern),
                cast(LibraryAsset.metadata_snapshot["authors"], Text).ilike(pattern),
                cast(LibraryAsset.metadata_snapshot["narrators"], Text).ilike(pattern),
                LibraryAsset.id.in_(catalog_matches),
            )
        )
    query = (
        select(LibraryAsset, Library, Integration)
        .join(Library, LibraryAsset.library_id == Library.id)
        .join(Integration, Library.integration_id == Integration.id)
        .where(*conditions)
    )
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        await db.execute(
            query.order_by(
                *([LibraryAsset.created_at.desc()] if sort == "recent" else []),
                LibraryAsset.title.asc().nulls_last(),
                LibraryAsset.id,
            )
            .offset(offset)
            .limit(limit)
        )
    ).all()
    coverage = (
        await db.execute(
            select(AssetContains.asset_id, AssetContains.work_id, AssetContains.verified).where(
                AssetContains.asset_id.in_([row[0].id for row in rows]),
            )
        )
    ).all()
    mapping = canonical_map()
    roots = dict(
        (
            await db.execute(
                select(mapping).where(mapping.c.origin_id.in_([row.work_id for row in coverage]))
            )
        ).all()
    )
    links = (
        (
            await db.scalars(
                select(ProviderObject).where(
                    ProviderObject.provider.in_([f"abs:{row[2].id}" for row in rows]),
                    ProviderObject.external_id.in_([row[0].external_id for row in rows]),
                )
            )
        ).all()
        if user.role == "admin"
        else []
    )
    by_key = {(link.provider, link.kind, link.external_id): link for link in links}
    titles = dict(
        (
            await db.execute(select(Work.id, Work.title).where(Work.id.in_(set(roots.values()))))
        ).all()
    )
    contents = {}
    for row in coverage:
        by_work = contents.setdefault(row.asset_id, {})
        root = roots[row.work_id]
        by_work[root] = by_work.get(root, False) or row.verified
    views = []
    for asset, library, connection in rows:
        link = by_key.get((f"abs:{connection.id}", f"item:{asset.medium}", asset.external_id))
        match_revision = (
            revision(
                await asset_state(
                    db, asset, link, coverage=[row for row in coverage if row.asset_id == asset.id]
                )
            )
            if link
            else None
        )
        views.append(
            AssetView(
                id=asset.id,
                library_id=library.id,
                library_name=library.name,
                title=asset.title or "Unidentified book",
                authors=asset.metadata_snapshot.get("authors", []),
                medium=asset.medium,
                state=asset.state,
                full_content=asset.full_content,
                match_status=asset.match_status,
                work_ids=list(
                    dict.fromkeys(
                        roots[row.work_id] for row in coverage if row.asset_id == asset.id
                    )
                ),
                match_revision=match_revision,
                collection=asset.containment is not None,
                collection_work_id=roots.get(UUID(asset.containment["physical_work_id"]))
                if asset.containment and asset.containment.get("physical_work_id")
                else None,
                contents=[
                    ContainedBookView(work_id=root, title=titles[root], verified=verified)
                    for root, verified in sorted(contents.get(asset.id, {}).items())
                    if root in {roots[UUID(value)] for value in asset.containment["work_ids"]}
                ]
                if asset.containment
                else [],
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
    await correct_asset(db, admin.id, asset_id, body.work_id, body.expected_revision)
    await db.commit()


@router.put("/assets/{asset_id}/contents", status_code=204)
async def review_contents(asset_id: UUID, body: ContentsInput, admin: Admin, db: Database):
    from app.domain.containment import review

    await review(db, admin.id, asset_id, body.work_ids, body.expected_revision)
    await db.commit()
