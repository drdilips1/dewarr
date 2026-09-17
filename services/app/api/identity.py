from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.adapters.catalog_types import EditionData
from app.api.dependencies import Admin, Database
from app.db.models import IdentityChange, ProviderObject, User, Version, WorkMetadataSource
from app.domain.corrections import (
    change_state,
    detach_source,
    review_version,
    revision,
    undo_change,
    version_state,
)

router = APIRouter(prefix="/identity", tags=["identity"])


class ChangeView(BaseModel):
    id: UUID
    kind: str
    entity_id: UUID
    work_id: UUID | None
    summary: str
    actor_name: str
    created_at: datetime
    undone_at: datetime | None
    can_undo: bool


class ChangePage(BaseModel):
    items: list[ChangeView]
    total: int
    offset: int
    limit: int


@router.get("/changes", response_model=ChangePage)
async def changes(
    admin: Admin,
    db: Database,
    entity_id: UUID | None = None,
    work_id: UUID | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
):
    if not entity_id and not work_id:
        raise HTTPException(422, "Select a book or library item to view its corrections")
    conditions = []
    if entity_id:
        conditions.append(IdentityChange.entity_id == entity_id)
    if work_id:
        conditions.append(
            or_(
                IdentityChange.work_id == work_id,
                IdentityChange.before["work_id"].astext == str(work_id),
            )
        )
    rows = (
        await db.execute(
            select(IdentityChange, User.display_name)
            .join(User, User.id == IdentityChange.actor_id)
            .where(*conditions)
            .order_by(IdentityChange.sequence.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    total = await db.scalar(select(func.count()).select_from(IdentityChange).where(*conditions))
    latest_rows = (
        await db.execute(
            select(IdentityChange.entity_id, func.max(IdentityChange.sequence))
            .where(
                IdentityChange.entity_id.in_([row[0].entity_id for row in rows]),
                IdentityChange.undone_at.is_(None),
            )
            .group_by(IdentityChange.entity_id)
        )
    ).all()
    latest = dict(latest_rows)
    result = []
    for change, actor_name in rows:
        can_undo = False
        if not change.undone_at and latest.get(change.entity_id) == change.sequence:
            try:
                current, _ = await change_state(db, change)
                can_undo = current == change.after
            except HTTPException:
                pass
        result.append(
            ChangeView(
                id=change.id,
                kind=change.kind,
                entity_id=change.entity_id,
                work_id=change.work_id,
                summary=change.summary,
                actor_name=actor_name,
                created_at=change.created_at,
                undone_at=change.undone_at,
                can_undo=can_undo,
            )
        )
    return ChangePage(items=result, total=total or 0, offset=offset, limit=limit)


@router.post("/changes/{change_id}/undo", status_code=204)
async def undo(change_id: UUID, admin: Admin, db: Database):
    await undo_change(db, admin.id, change_id)
    await db.commit()


class RevisionInput(BaseModel):
    expected_revision: str = Field(pattern=r"^[a-f0-9]{64}$")


@router.post("/sources/{source_id}/unmatch", status_code=204)
async def unmatch(source_id: UUID, body: RevisionInput, admin: Admin, db: Database):
    await detach_source(db, admin.id, source_id, body.expected_revision)
    await db.commit()


class VersionReview(BaseModel):
    id: UUID
    provider: str
    external_id: str
    current_version_id: UUID
    current_title: str | None
    current_medium: str
    current_narrators: list[str]
    current_language: str | None
    current_publication_year: int | None
    current_identifiers: dict
    current_abridged: bool | None
    proposed: EditionData
    revision: str


@router.get("/works/{work_id}/version-reviews", response_model=list[VersionReview])
async def version_reviews(work_id: UUID, admin: Admin, db: Database):
    rows = (
        await db.execute(
            select(ProviderObject, Version, WorkMetadataSource.provider)
            .join(Version, ProviderObject.version_id == Version.id)
            .join(WorkMetadataSource, ProviderObject.metadata_source_id == WorkMetadataSource.id)
            .where(
                ProviderObject.work_id == work_id,
                WorkMetadataSource.accepted.is_(True),
                ProviderObject.kind == "edition",
                ProviderObject.match_status == "needs-review",
                ProviderObject.pending_snapshot.is_not(None),
            )
            .order_by(ProviderObject.id)
            .limit(100)
        )
    ).all()
    return [
        VersionReview(
            id=link.id,
            provider=provider,
            external_id=link.external_id,
            current_version_id=version.id,
            current_title=version.title,
            current_medium=version.medium,
            current_narrators=version.narrators,
            current_language=version.language,
            current_publication_year=version.publication_year,
            current_identifiers=version.identifiers,
            current_abridged=version.abridged,
            proposed=EditionData.model_validate(link.pending_snapshot),
            revision=revision(version_state(link)),
        )
        for link, version, provider in rows
    ]


class ReviewInput(RevisionInput):
    decision: Literal["keep", "separate"]


@router.post("/versions/{link_id}/review", status_code=204)
async def resolve_version(link_id: UUID, body: ReviewInput, admin: Admin, db: Database):
    await review_version(db, admin.id, link_id, body.decision, body.expected_revision)
    await db.commit()
