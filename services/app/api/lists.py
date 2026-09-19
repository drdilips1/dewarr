from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import delete, func, or_, select

from app.api.catalog import WorkView, work_view
from app.api.dependencies import CurrentUser, Database, Member
from app.db.models import BookList, ListEntry, ListObservation, ListSubscription, Work
from app.domain import list_curation
from app.domain.acquisition import withdraw_list_reasons
from app.domain.availability import availability_for
from app.domain.list_curation import CurationInput, CurationReceipt
from app.domain.visibility import visible_work
from app.domain.work_graph import canonical_map, canonical_work, family_ids, graph_lock

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
    settings_revision: str


class ListDetail(ListView):
    items: list[WorkView]
    content_revision: str


class ListPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=200, pattern=r"\S")
    description: str | None = Field(default=None, max_length=3000)
    shared: bool | None = None
    expected_settings_revision: str | None = Field(default=None, min_length=64, max_length=64)

    @model_validator(mode="after")
    def non_nullable_fields(self):
        for key in ("name", "shared"):
            if key in self.model_fields_set and getattr(self, key) is None:
                raise ValueError(f"{key} cannot be null")
        return self


class EntryInput(BaseModel):
    work_id: UUID


class OrderInput(BaseModel):
    work_ids: list[UUID] = Field(max_length=10000)
    expected_revision: str | None = Field(default=None, min_length=64, max_length=64)


def list_view(item: BookList, count: int, user_id: UUID) -> ListView:
    return ListView(
        id=item.id,
        owner_id=item.owner_id,
        name=item.name,
        description=item.description,
        shared=item.shared,
        count=count,
        editable=item.owner_id == user_id,
        settings_revision=list_curation.settings_revision(item),
    )


async def visible_list(
    list_id: UUID, user: CurrentUser, db: Database, *, edit=False, lock_read=False
) -> BookList:
    if edit:
        item, _ = await list_curation.owner_context(db, user.id, list_id)
        return item
    query = select(BookList).where(BookList.id == list_id)
    query = query.where(or_(BookList.owner_id == user.id, BookList.shared.is_(True)))
    if lock_read:
        query = query.with_for_update(read=True)
    item = await db.scalar(query)
    if not item:
        raise HTTPException(404, "List not found")
    return item


@router.get("", response_model=list[ListView])
async def list_all(user: CurrentUser, db: Database):
    mapping = canonical_map()
    rows = (
        await db.execute(
            select(
                BookList,
                func.count(func.distinct(mapping.c.work_id)).filter(
                    mapping.c.work_id.in_(select(Work.id).where(visible_work(user)))
                ),
            )
            .outerjoin(ListEntry, ListEntry.list_id == BookList.id)
            .outerjoin(mapping, mapping.c.origin_id == ListEntry.work_id)
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
    # Keep the rendered order and revision in the same list/identity snapshot.
    item = await visible_list(list_id, user, db, lock_read=True)
    await graph_lock(db)
    mapping = canonical_map()
    works = (
        await db.scalars(
            select(Work)
            .join(mapping, mapping.c.work_id == Work.id)
            .join(ListEntry, ListEntry.work_id == mapping.c.origin_id)
            .where(ListEntry.list_id == list_id, visible_work(user))
            .group_by(Work.id)
            .order_by(func.min(ListEntry.position), Work.id)
            .limit(10000)
        )
    ).all()
    availability = await availability_for(db, user, [work.id for work in works])
    return ListDetail(
        **list_view(item, len(works), user.id).model_dump(),
        items=[work_view(work, availability[work.id]) for work in works],
        content_revision=await list_curation.content_revision(db, list_id),
    )


@router.patch("/{list_id}", response_model=ListView)
async def edit_list(list_id: UUID, body: ListPatch, user: Member, db: Database):
    item = await visible_list(list_id, user, db, edit=True)
    if (
        body.expected_settings_revision is not None
        and body.expected_settings_revision != list_curation.settings_revision(item)
    ):
        raise HTTPException(409, "List details changed. Reload them before saving your edit.")
    for key, value in body.model_dump(
        exclude_unset=True, exclude={"expected_settings_revision"}
    ).items():
        setattr(item, key, value)
    mapping = canonical_map()
    count = await db.scalar(
        select(func.count(func.distinct(mapping.c.work_id)))
        .select_from(ListEntry)
        .join(mapping, mapping.c.origin_id == ListEntry.work_id)
        .where(
            ListEntry.list_id == list_id,
            mapping.c.work_id.in_(select(Work.id).where(visible_work(user))),
        )
    )
    await db.commit()
    return list_view(item, count or 0, user.id)


@router.delete("/{list_id}", status_code=204)
async def remove_list(list_id: UUID, user: Member, db: Database):
    item = await visible_list(list_id, user, db, edit=True)
    await db.delete(item)
    await db.flush()
    await withdraw_list_reasons(db, user, list_id)
    await db.commit()


@router.post("/{list_id}/entries", status_code=204)
async def add_entry(list_id: UUID, body: EntryInput, user: Member, db: Database):
    await visible_list(list_id, user, db, edit=True)
    await graph_lock(db)
    work = await canonical_work(db, body.work_id)
    if not await db.scalar(select(Work.id).where(Work.id == work.id, visible_work(user))):
        raise HTTPException(404, "Book not found")
    existing = await db.scalar(
        select(ListEntry).where(
            ListEntry.list_id == list_id,
            ListEntry.work_id.in_(family_ids(work.id)),
        )
    )
    if existing:
        existing.locally_added = True
    else:
        position = await db.scalar(
            select(func.max(ListEntry.position)).where(ListEntry.list_id == list_id)
        )
        db.add(ListEntry(list_id=list_id, work_id=work.id, position=(position or 0) + 1))
    await db.commit()


@router.delete("/{list_id}/entries/{work_id}", status_code=204)
async def remove_entry(list_id: UUID, work_id: UUID, user: Member, db: Database):
    await visible_list(list_id, user, db, edit=True)
    await graph_lock(db)
    for observation in await db.scalars(
        select(ListObservation)
        .join(ListSubscription)
        .where(
            ListSubscription.list_id == list_id,
            ListObservation.work_id.in_(family_ids(work_id)),
        )
    ):
        observation.excluded = True
    await db.execute(
        delete(ListEntry).where(
            ListEntry.list_id == list_id, ListEntry.work_id.in_(family_ids(work_id))
        )
    )
    await withdraw_list_reasons(db, user, list_id, work_id)
    await db.commit()


@router.put("/{list_id}/order", status_code=204)
async def reorder(list_id: UUID, body: OrderInput, user: Member, db: Database):
    await visible_list(list_id, user, db, edit=True)
    await graph_lock(db)
    await list_curation.check_revision(db, list_id, body.expected_revision)
    entries = (await db.scalars(select(ListEntry).where(ListEntry.list_id == list_id))).all()
    mapping = canonical_map()
    roots = dict(
        (
            await db.execute(
                select(mapping).where(mapping.c.origin_id.in_([e.work_id for e in entries]))
            )
        ).all()
    )
    visible = set(
        await db.scalars(select(Work.id).where(Work.id.in_(roots.values()), visible_work(user)))
    )
    if len(set(body.work_ids)) != len(body.work_ids) or set(body.work_ids) != visible:
        raise HTTPException(422, "Include every book in this list exactly once")
    # Revoked source/library access can leave hidden memberships in an owned
    # list. Reorder visible books within their slots without exposing hidden IDs
    # or requiring the user to submit records they can no longer see.
    current = {}
    for entry in entries:
        root = roots[entry.work_id]
        current[root] = min(current.get(root, entry.position), entry.position)
    replacement = iter(body.work_ids)
    order = [
        next(replacement) if root in visible else root
        for root in sorted(current, key=lambda key: (current[key], key))
    ]
    positions = {work_id: index for index, work_id in enumerate(order)}
    for entry in entries:
        entry.position = positions[roots[entry.work_id]]
    await db.commit()


@router.post("/{list_id}/curation", response_model=CurationReceipt)
async def curate(
    list_id: UUID,
    body: CurationInput,
    user: Member,
    db: Database,
    idempotency_key: str = Header(min_length=8, max_length=200),
):
    receipt = await list_curation.curate(db, user, list_id, body, idempotency_key)
    await db.commit()
    return receipt
