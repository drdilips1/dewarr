from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Text, cast, func, or_, select

from app.api.dependencies import CurrentUser, Database, Member
from app.db.models import AuditEvent, Work
from app.domain.availability import Availability, availability_for
from app.domain.identity import work_key
from app.domain.visibility import visible_work

router = APIRouter(prefix="/catalog", tags=["catalog"])


class WorkInput(BaseModel):
    title: str = Field(min_length=1, max_length=600)
    authors: list[str] = Field(default_factory=list, max_length=30)
    description: str | None = Field(default=None, max_length=30000)
    language: str | None = Field(default=None, max_length=20)
    publication_year: int | None = Field(default=None, ge=0, le=9999)

    @field_validator("title")
    @classmethod
    def title_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Enter a title")
        return value.strip()

    @field_validator("authors")
    @classmethod
    def validate_authors(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 300 for value in values):
            raise ValueError("Each author must contain 1–300 characters")
        return [value.strip() for value in values]


class WorkView(BaseModel):
    id: UUID
    title: str
    authors: list[str]
    description: str | None
    language: str | None
    publication_year: int | None
    cover_url: str | None
    provisional: bool
    availability: Availability


class WorkPage(BaseModel):
    items: list[WorkView]
    total: int
    offset: int
    limit: int


def work_view(work: Work, availability: Availability) -> WorkView:
    return WorkView(
        id=work.id,
        title=work.title,
        authors=work.authors,
        description=work.description,
        language=work.language,
        publication_year=work.publication_year,
        cover_url=work.cover_url,
        provisional=work.provisional,
        availability=availability,
    )


@router.get("/works", response_model=WorkPage)
async def works(
    user: CurrentUser,
    db: Database,
    q: str = Query(default="", max_length=300),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=40, ge=1, le=100),
):
    conditions = [Work.redirect_to.is_(None), visible_work(user)]
    if q.strip():
        pattern = (
            "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        )
        conditions.append(or_(Work.title.ilike(pattern), cast(Work.authors, Text).ilike(pattern)))
    rows = (
        await db.scalars(
            select(Work)
            .where(*conditions)
            .order_by(Work.title, Work.id)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    total = await db.scalar(select(func.count()).select_from(Work).where(*conditions))
    availability = await availability_for(db, user, [work.id for work in rows])
    return WorkPage(
        items=[work_view(work, availability[work.id]) for work in rows],
        total=total or 0,
        offset=offset,
        limit=limit,
    )


@router.post("/works", response_model=WorkView, status_code=201)
async def add_work(body: WorkInput, user: Member, db: Database):
    work = Work(**body.model_dump())
    work.metadata_fields = {
        "fields": {
            field: {
                "value": value,
                "provider": "manual",
                "locked": True,
                "reason": "Entered by user",
            }
            for field, value in body.model_dump(exclude_unset=True).items()
        }
    }
    work.match_key = work_key(work.title, work.authors)
    db.add(work)
    await db.flush()
    db.add(AuditEvent(actor_id=user.id, action="catalog.work.created", entity_id=work.id))
    await db.commit()
    return work_view(work, Availability())


@router.get("/works/{work_id}", response_model=WorkView)
async def work_detail(work_id: UUID, user: CurrentUser, db: Database):
    work = await db.scalar(select(Work).where(Work.id == work_id, visible_work(user)))
    if not work:
        raise HTTPException(404, "Book not found")
    availability = await availability_for(db, user, [work.id])
    return work_view(work, availability[work.id])
