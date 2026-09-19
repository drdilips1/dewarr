from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel

from app.adapters.contracts import AdapterError
from app.adapters.source_releases import SourceRelease
from app.adapters.torrent_descriptor import TorrentDescriptor
from app.api.dependencies import Database, Member
from app.api.metadata import adapter_http_error
from app.db.models import SourceArtifact, SourceConnection
from app.domain.source_artifacts import resolve_mam

router = APIRouter(tags=["source-artifacts"])


class SourceArtifactView(BaseModel):
    id: UUID
    created_at: datetime
    source_key: str
    source_id: str
    source_generation: int
    current_connection: bool
    descriptor: TorrentDescriptor
    release: SourceRelease
    dispatch_available: bool = False


async def artifact_view(db, identifier, user_id):
    row = await db.get(SourceArtifact, identifier)
    if not row or row.owner_id != user_id:
        raise HTTPException(404, "Source artifact not found")
    source = await db.get(SourceConnection, row.source_key, populate_existing=True)
    return SourceArtifactView(
        id=row.id,
        created_at=row.created_at,
        source_key=row.source_key,
        source_id=row.source_id,
        source_generation=row.source_generation,
        current_connection=bool(
            source and source.enabled and source.generation == row.source_generation
        ),
        descriptor=row.descriptor,
        release=row.release_snapshot,
    )


@router.post("/sources/mam/releases/{source_id}/artifact", response_model=SourceArtifactView)
async def resolve_artifact(
    user: Member, db: Database, source_id: str = Path(pattern=r"^[1-9][0-9]{0,17}$")
):
    user_id = user.id
    await db.rollback()
    try:
        identifier = await resolve_mam(user_id, source_id)
    except AdapterError as error:
        raise adapter_http_error(error) from error
    return await artifact_view(db, identifier, user_id)


@router.get("/source-artifacts/{artifact_id}", response_model=SourceArtifactView)
async def get_artifact(artifact_id: UUID, user: Member, db: Database):
    return await artifact_view(db, artifact_id, user.id)
