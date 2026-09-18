from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.adapters.contracts import AdapterError
from app.api.dependencies import Database, Member
from app.api.metadata import adapter_http_error
from app.db.models import AcquisitionSelection, ImportDestination, Integration, Library
from app.domain import acquisition_selection as selections
from app.domain.acquisition_selection import SelectionInput
from app.domain.downloaders import mapped_path, mappings_current
from app.domain.visibility import visible_library
from app.importing.destinations import destination_configuration
from app.importing.naming import fingerprint

router = APIRouter(prefix="/acquisition/selections", tags=["acquisition-selections"])


class SelectionView(BaseModel):
    id: UUID
    created_at: datetime
    intent_id: UUID
    artifact_id: UUID
    state: str
    message: str
    work_id: UUID
    work_title: str
    medium: str
    release_title: str
    configuration_current: bool
    dispatch_available: bool = False


class SelectionPage(BaseModel):
    items: list[SelectionView]
    total: int
    offset: int
    limit: int


class DownloaderChoice(BaseModel):
    id: UUID
    name: str
    generation: int
    source_key: str | None
    ready: bool


class DestinationChoice(BaseModel):
    id: UUID
    library_id: UUID
    name: str
    medium: str
    revision: str
    source_key: str | None
    ready: bool


class SelectionOptions(BaseModel):
    downloaders: list[DownloaderChoice]
    destinations: list[DestinationChoice]


async def view(db, row):
    return SelectionView(
        id=row.id,
        created_at=row.created_at,
        intent_id=row.intent_id,
        artifact_id=row.artifact_id,
        state=row.state,
        message=row.message,
        work_id=row.frozen["work_id"],
        work_title=row.frozen["work_title"],
        medium=row.frozen["requirements"]["medium"],
        release_title=row.frozen["release"]["title"],
        configuration_current=await selections.configuration_current(db, row),
    )


@router.get("/options", response_model=SelectionOptions)
async def options(user: Member, db: Database):
    downloaders = []
    for row in await db.scalars(
        select(Integration)
        .where(
            Integration.kind == "qbittorrent",
            Integration.owner_id.is_(None),
            Integration.enabled.is_(True),
        )
        .order_by(Integration.name, Integration.id)
    ):
        current = mappings_current(row)
        mapping = mapped_path(row, row.config["save_path"]) if current else None
        downloaders.append(
            DownloaderChoice(
                id=row.id,
                name=row.name,
                generation=row.credential_generation,
                source_key=mapping["source_key"] if mapping else None,
                ready=current and row.status == "connected",
            )
        )
    destinations = []
    rows = await db.execute(
        select(ImportDestination, Library.name)
        .join(Library)
        .join(Integration)
        .where(
            ImportDestination.enabled.is_(True),
            Library.accessible.is_(True),
            Integration.enabled.is_(True),
            Integration.kind == "audiobookshelf",
            visible_library(user),
        )
        .order_by(Library.name, ImportDestination.id)
    )
    for row, name in rows:
        configuration = await destination_configuration(db, row)
        source_key = (row.probe or {}).get("source_key")
        destinations.append(
            DestinationChoice(
                id=row.id,
                library_id=row.library_id,
                name=name,
                medium=row.medium,
                revision=fingerprint(configuration),
                source_key=source_key,
                ready=selections.verified_probe(row, configuration, {"source_key": source_key}),
            )
        )
    return SelectionOptions(downloaders=downloaders, destinations=destinations)


@router.post("", response_model=SelectionView, status_code=201)
async def create(
    body: SelectionInput,
    user: Member,
    db: Database,
    idempotency_key: str = Header(min_length=8, max_length=200),
):
    try:
        row = await selections.prepare(db, user, body, idempotency_key)
    except AdapterError as error:
        raise adapter_http_error(error) from error
    result = await view(db, row)
    await db.commit()
    return result


@router.get("", response_model=SelectionPage)
async def listing(
    user: Member,
    db: Database,
    artifact_id: UUID | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
):
    where = [AcquisitionSelection.owner_id == user.id]
    if artifact_id:
        where.append(AcquisitionSelection.artifact_id == artifact_id)
    rows = await db.scalars(
        select(AcquisitionSelection)
        .where(*where)
        .order_by(
            AcquisitionSelection.created_at.desc(),
            AcquisitionSelection.id,
        )
        .offset(offset)
        .limit(limit)
    )
    return SelectionPage(
        items=[await view(db, row) for row in rows],
        total=await db.scalar(select(func.count()).select_from(AcquisitionSelection).where(*where)),
        offset=offset,
        limit=limit,
    )


@router.get("/{selection_id}", response_model=SelectionView)
async def detail(selection_id: UUID, user: Member, db: Database):
    return await view(db, await selections.owned_selection(db, user, selection_id))


@router.delete("/{selection_id}", response_model=SelectionView)
async def cancel(selection_id: UUID, user: Member, db: Database):
    row = await selections.cancel(
        db, user, await selections.owned_selection(db, user, selection_id)
    )
    result = await view(db, row)
    await db.commit()
    return result
