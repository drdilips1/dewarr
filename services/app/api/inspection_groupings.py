from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import Field
from sqlalchemy import select

from app.api.dependencies import Admin, Database
from app.api.imports import assert_admin, owned_inspection
from app.db.models import AuditEvent, FrozenImportPlan, ImportEntry, ImportRun, InspectionGrouping
from app.domain.operations import transaction_lock
from app.importing.grouping import (
    ExcludedFile,
    GroupingContent,
    ReviewedGroup,
    latest_grouping,
    proposed,
    regroup,
)
from app.importing.naming import StrictModel, fingerprint
from app.importing.workflow import source_matches

router = APIRouter(prefix="/organization/inspections", tags=["organization"])


class GroupingInput(StrictModel):
    inspection_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    action: Literal["replace", "reset"] = "replace"
    groups: list[ReviewedGroup] = Field(default_factory=list, max_length=100)
    excluded: list[ExcludedFile] = Field(default_factory=list, max_length=10000)


class GroupingView(StrictModel):
    revision: str
    position: int
    content: GroupingContent


def view(inspection, row):
    return GroupingView(
        revision=row.revision if row else inspection.snapshot["revision"],
        position=row.position if row else 0,
        content=row.content if row else proposed(inspection.snapshot),
    )


@router.get("/{inspection_id}/grouping", response_model=GroupingView)
async def get_grouping(inspection_id: UUID, admin: Admin, db: Database):
    inspection = await owned_inspection(db, admin.id, inspection_id)
    if inspection.state != "ready" or not inspection.snapshot:
        raise HTTPException(409, "Wait for a completed inspection before reviewing groups")
    return view(inspection, await latest_grouping(db, inspection_id))


@router.put("/{inspection_id}/grouping", response_model=GroupingView)
async def save_grouping(inspection_id: UUID, body: GroupingInput, admin: Admin, db: Database):
    await transaction_lock(db, f"inspection-plan:{inspection_id}")
    await assert_admin(db, admin.id)
    inspection = await owned_inspection(db, admin.id, inspection_id)
    if inspection.state != "ready" or not inspection.snapshot or not source_matches(inspection):
        raise HTTPException(409, "Inspect the current configured source before changing groups")
    if body.inspection_revision != inspection.snapshot["revision"]:
        raise HTTPException(409, "Inspection changed; review the current files")
    latest = await latest_grouping(db, inspection_id)
    current = view(inspection, latest)
    try:
        if body.action == "reset":
            if body.groups or body.excluded:
                raise ValueError("Reset uses the original proposals without replacement files")
            content = proposed(inspection.snapshot)
        else:
            content = regroup(inspection.snapshot, body.groups, body.excluded)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    serialized = content.model_dump(mode="json")
    if body.expected_revision != current.revision:
        if (
            latest
            and latest.previous_revision == body.expected_revision
            and latest.content == serialized
        ):
            return current  # Lost-response replay of the same reviewed change.
        raise HTTPException(409, "File groups changed; reload before saving your review")
    if serialized == current.content.model_dump(mode="json"):
        return current
    reserved = await db.scalar(
        select(ImportEntry.id)
        .join(ImportRun)
        .join(FrozenImportPlan)
        .where(FrozenImportPlan.inspection_id == inspection_id, ImportEntry.reserved.is_(True))
        .limit(1)
    )
    if reserved:
        raise HTTPException(
            409,
            "This inspection has reserved or published imports; review them before changing groups",
        )
    row = InspectionGrouping(
        inspection_id=inspection_id,
        position=current.position + 1,
        previous_revision=current.revision,
        revision=fingerprint({"previous": current.revision, "content": serialized}),
        content=serialized,
    )
    db.add(row)
    await db.flush()
    db.add(
        AuditEvent(
            actor_id=admin.id,
            action="organization.groups.reviewed",
            entity_id=inspection_id,
            detail={
                "revision": row.revision,
                "previous": current.revision,
                "groups": len(content.groups),
                "excluded": len(content.excluded),
                "action": body.action,
            },
        )
    )
    await db.commit()
    return view(inspection, row)
