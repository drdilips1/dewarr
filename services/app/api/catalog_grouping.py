"""Reader-visible grouping evidence and administrator separation decisions."""

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.catalog import WorkView, work_view
from app.api.dependencies import Admin, CurrentUser, Database
from app.db.models import AuditEvent, Work
from app.domain.availability import availability_for
from app.domain.catalog_display import display_family
from app.domain.catalog_titles import display_title
from app.domain.corrections import revision
from app.domain.visibility import visible_work
from app.domain.work_graph import canonical_map, canonical_work, graph_lock

router = APIRouter(prefix="/catalog", tags=["catalog"])


class GroupMember(BaseModel):
    work: WorkView
    separate: bool
    revision: str


class GroupingView(BaseModel):
    reason: str
    members: list[GroupMember]


class GroupingEdit(BaseModel):
    separate: bool
    expected_revision: str = Field(pattern=r"^[a-f0-9]{64}$")


def grouping_revision(work):
    return revision(
        {
            "id": str(work.id),
            "title": work.title,
            "authors": work.authors,
            "language": work.language,
            "redirect_to": str(work.redirect_to),
            "separate": bool(work.metadata_fields.get("display_separate")),
            "primary_editions": work.metadata_fields.get("primary_editions", {}),
        }
    )


@router.get("/works/{work_id}/grouping", response_model=GroupingView)
async def grouping(work_id: UUID, user: CurrentUser, db: Database):
    root = await canonical_work(db, work_id)
    if not await db.scalar(select(Work.id).where(Work.id == root.id, visible_work(user))):
        raise HTTPException(404, "Book not found")
    canonical = canonical_map()
    roots = select(canonical.c.work_id).where(
        canonical.c.origin_id.in_(display_family(user, root.id))
    )
    works = (
        await db.scalars(
            select(Work)
            .where(Work.id.in_(roots), visible_work(user))
            .order_by(Work.created_at, Work.id)
        )
    ).all()
    availability = await availability_for(db, user, [work.id for work in works])
    separate = bool(root.metadata_fields.get("display_separate"))
    if separate:
        reason = (
            "Kept separate by an administrator. Automatic grouping is disabled for this record."
        )
    elif len(works) > 1:
        reason = (
            "Grouped by matching authors and a unique short/full title with compatible language."
            if len({display_title(work.title) for work in works}) > 1
            else (
                "Grouped by matching title and authors with compatible language. "
                "Edition labels are ignored."
            )
        )
        reason += " Individual editions and files remain separate."
    else:
        reason = "This book uses one catalog identity, including any confirmed merged records."
    return GroupingView(
        reason=reason,
        members=[
            GroupMember(
                work=work_view(work, availability[work.id]),
                separate=bool(work.metadata_fields.get("display_separate")),
                revision=grouping_revision(work),
            )
            for work in works
        ],
    )


@router.patch("/works/{work_id}/grouping", status_code=204)
async def edit_grouping(work_id: UUID, body: GroupingEdit, user: Admin, db: Database):
    await graph_lock(db, exclusive=True)
    work = await db.get(Work, work_id, with_for_update=True)
    if not work:
        raise HTTPException(404, "Book not found")
    if work.redirect_to or grouping_revision(work) != body.expected_revision:
        raise HTTPException(409, "This book changed. Refresh its grouping before trying again.")
    before = bool(work.metadata_fields.get("display_separate"))
    work.metadata_fields = {**work.metadata_fields, "display_separate": body.separate}
    db.add(
        AuditEvent(
            actor_id=user.id,
            action="catalog.grouping.changed",
            entity_id=work.id,
            detail={"before_separate": before, "separate": body.separate},
        )
    )
    await db.commit()


class PrimaryEditionEdit(BaseModel):
    medium: str = Field(pattern="^(ebook|audio)$")
    version_id: UUID | None = None
    expected_revision: str = Field(pattern=r"^[a-f0-9]{64}$")


@router.patch("/works/{work_id}/primary-edition", status_code=204)
async def primary_edition(work_id: UUID, body: PrimaryEditionEdit, user: Admin, db: Database):
    from datetime import UTC, datetime

    from app.db.models import LibraryAsset
    from app.domain.availability import availability_rows
    from app.domain.catalog_display import display_map

    await graph_lock(db, exclusive=True)
    work = await db.get(Work, work_id, with_for_update=True)
    if not work:
        raise HTTPException(404, "Book not found")
    if work.redirect_to or grouping_revision(work) != body.expected_revision:
        raise HTTPException(409, "This book changed. Refresh before choosing its primary edition.")
    if body.version_id:
        mapping = display_map(user)
        root = select(mapping.c.work_id).where(mapping.c.origin_id == work.id).scalar_subquery()
        available = await db.scalar(
            availability_rows(user, mapping)
            .with_only_columns(LibraryAsset.id)
            .where(
                mapping.c.work_id == root,
                LibraryAsset.medium == body.medium,
                LibraryAsset.version_id == body.version_id,
            )
            .limit(1)
        )
        if not available:
            raise HTTPException(
                422, "Choose an accessible library edition of this book and format."
            )
    choices = dict(work.metadata_fields.get("primary_editions", {}))
    choices[body.medium] = {
        "version_id": str(body.version_id) if body.version_id else None,
        "chosen_at": datetime.now(UTC).isoformat(),
    }
    work.metadata_fields = {**work.metadata_fields, "primary_editions": choices}
    db.add(
        AuditEvent(
            actor_id=user.id,
            action="catalog.primary_edition.changed",
            entity_id=work.id,
            detail={"medium": body.medium, "version_id": choices[body.medium]["version_id"]},
        )
    )
    await db.commit()
