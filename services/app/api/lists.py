from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select

from app.api.catalog import WorkView, work_view
from app.api.dependencies import CurrentUser, Database, Member
from app.db.models import BookList, ListEntry, Work
from app.domain.availability import availability_for
from app.domain.visibility import visible_work

router = APIRouter(prefix="/lists", tags=["lists"])


class ListInput(BaseModel):
    name: str = Field(min_length=1, max_length=200, pattern=r"\S")
    description: str | None = Field(default=None, max_length=3000)
    shared: bool = False


class ListView(ListInput):
    id: UUID
    owner_id: UUID
    count: int
    editable: bool


class ListDetail(ListView):
    items: list[WorkView]


class EntryInput(BaseModel):
    work_id: UUID


class OrderInput(BaseModel):
    work_ids: list[UUID] = Field(max_length=10000)


def list_view(item: BookList, count: int, user_id: UUID) -> ListView:
    return ListView(
        id=item.id,
        owner_id=item.owner_id,
        name=item.name,
        description=item.description,
        shared=item.shared,
        count=count,
        editable=item.owner_id == user_id,
    )


async def visible_list(list_id: UUID, user: CurrentUser, db: Database, *, edit=False) -> BookList:
    query = select(BookList).where(BookList.id == list_id)
    if edit:
        query = query.where(BookList.owner_id == user.id).with_for_update()
    else:
        query = query.where(or_(BookList.owner_id == user.id, BookList.shared.is_(True)))
    item = await db.scalar(query)
    if not item:
        raise HTTPException(404, "List not found")
    return item


@router.get("", response_model=list[ListView])
async def list_all(user: CurrentUser, db: Database):
    rows = (
        await db.execute(
            select(
                BookList,
                func.count(ListEntry.id).filter(
                    ListEntry.work_id.in_(select(Work.id).where(visible_work(user)))
                ),
            )
            .outerjoin(ListEntry, ListEntry.list_id == BookList.id)
            .where(or_(BookList.owner_id == user.id, BookList.shared.is_(True)))
            .group_by(BookList.id)
            .order_by(BookList.created_at.desc())
            .limit(200)
        )
    ).all()
    return [list_view(item, count, user.id) for item, count in rows]


@router.post("", response_model=ListView, status_code=201)
async def create_list(body: ListInput, user: Member, db: Database):
    item = BookList(owner_id=user.id, **body.model_dump())
    db.add(item)
    await db.commit()
    return list_view(item, 0, user.id)


@router.get("/{list_id}", response_model=ListDetail)
async def detail(list_id: UUID, user: CurrentUser, db: Database):
    item = await visible_list(list_id, user, db)
    works = (
        await db.scalars(
            select(Work)
            .join(ListEntry, ListEntry.work_id == Work.id)
            .where(ListEntry.list_id == list_id, visible_work(user))
            .order_by(ListEntry.position, ListEntry.id)
            .limit(10000)
        )
    ).all()
    availability = await availability_for(db, user, [work.id for work in works])
    return ListDetail(
        **list_view(item, len(works), user.id).model_dump(),
        items=[work_view(work, availability[work.id]) for work in works],
    )


@router.patch("/{list_id}", response_model=ListView)
async def edit_list(list_id: UUID, body: ListInput, user: Member, db: Database):
    item = await visible_list(list_id, user, db, edit=True)
    for key, value in body.model_dump().items():
        setattr(item, key, value)
    count = await db.scalar(
        select(func.count())
        .select_from(ListEntry)
        .where(
            ListEntry.list_id == list_id,
            ListEntry.work_id.in_(select(Work.id).where(visible_work(user))),
        )
    )
    await db.commit()
    return list_view(item, count or 0, user.id)


@router.delete("/{list_id}", status_code=204)
async def remove_list(list_id: UUID, user: Member, db: Database):
    item = await visible_list(list_id, user, db, edit=True)
    await db.delete(item)
    await db.commit()


@router.post("/{list_id}/entries", status_code=204)
async def add_entry(list_id: UUID, body: EntryInput, user: Member, db: Database):
    await visible_list(list_id, user, db, edit=True)
    if not await db.scalar(select(Work.id).where(Work.id == body.work_id, visible_work(user))):
        raise HTTPException(404, "Book not found")
    if not await db.scalar(
        select(ListEntry.id).where(
            ListEntry.list_id == list_id,
            ListEntry.work_id == body.work_id,
        )
    ):
        position = await db.scalar(
            select(func.max(ListEntry.position)).where(ListEntry.list_id == list_id)
        )
        db.add(ListEntry(list_id=list_id, work_id=body.work_id, position=(position or 0) + 1))
    await db.commit()


@router.delete("/{list_id}/entries/{work_id}", status_code=204)
async def remove_entry(list_id: UUID, work_id: UUID, user: Member, db: Database):
    await visible_list(list_id, user, db, edit=True)
    await db.execute(
        delete(ListEntry).where(ListEntry.list_id == list_id, ListEntry.work_id == work_id)
    )
    await db.commit()


@router.put("/{list_id}/order", status_code=204)
async def reorder(list_id: UUID, body: OrderInput, user: Member, db: Database):
    await visible_list(list_id, user, db, edit=True)
    entries = (await db.scalars(select(ListEntry).where(ListEntry.list_id == list_id))).all()
    if len(set(body.work_ids)) != len(body.work_ids) or set(body.work_ids) != {
        e.work_id for e in entries
    }:
        raise HTTPException(422, "Include every book in this list exactly once")
    positions = {work_id: index for index, work_id in enumerate(body.work_ids)}
    for entry in entries:
        entry.position = positions[entry.work_id]
    await db.commit()
