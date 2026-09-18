from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from app.api.dependencies import Admin, Database
from app.api.imports import owned_inspection
from app.domain.work_graph import graph_lock
from app.importing.grouping import current_grouping
from app.importing.matching import MatchPage, match_group
from app.importing.workflow import source_matches

router = APIRouter(prefix="/organization/inspections", tags=["organization"])


@router.get("/{inspection_id}/matches", response_model=MatchPage)
async def matches(
    inspection_id: UUID,
    admin: Admin,
    db: Database,
    grouping_revision: str = Query(pattern=r"^[a-f0-9]{64}$"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=25),
):
    inspection = await owned_inspection(db, admin.id, inspection_id)
    if inspection.state != "ready" or not inspection.snapshot or not source_matches(inspection):
        raise HTTPException(409, "Inspect the current configured files before matching")
    revision, grouping = await current_grouping(db, inspection)
    if revision != grouping_revision:
        raise HTTPException(409, "File groups changed; reload before matching")
    await graph_lock(db)
    return MatchPage(
        inspection_revision=inspection.snapshot["revision"],
        grouping_revision=revision,
        items=[
            await match_group(db, inspection.snapshot, revision, group)
            for group in grouping.groups[offset : offset + limit]
        ],
        total=len(grouping.groups),
        offset=offset,
        limit=limit,
    )
