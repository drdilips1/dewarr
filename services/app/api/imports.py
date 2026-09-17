from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid5

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from app.api.dependencies import Admin, Database
from app.api.organization import current_profile
from app.config import get_settings
from app.db.models import (
    AuditEvent,
    DownloadInspection,
    FrozenImportPlan,
    Operation,
    ProviderObject,
    User,
    Version,
)
from app.domain.operations import transaction_lock
from app.domain.work_graph import canonical_work, graph_lock
from app.importing.filesystem import relative_parts
from app.importing.inspection import InspectedFile, InspectionSnapshot
from app.importing.metadata import ExportMetadata, initial_sidecars
from app.importing.naming import (
    ImportGroup,
    ImportPlan,
    NamingMetadata,
    NamingProfile,
    PlannedSourceFile,
    StrictModel,
    fingerprint,
    plan_import,
)
from app.importing.workflow import source_matches
from app.jobs.queue import enqueue

router = APIRouter(prefix="/organization", tags=["organization"])


class InspectInput(StrictModel):
    source_key: str = Field(pattern=r"^[a-z0-9_-]{1,60}$")
    relative_path: str = Field(min_length=1, max_length=1024)
    completed_download: Literal[True]

    @model_validator(mode="after")
    def valid_path(self):
        relative_parts(self.relative_path)
        return self


class InspectionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime
    operation_id: UUID
    source_key: str
    relative_path: str
    state: str
    message: str
    snapshot: InspectionSnapshot | None = None


class GroupSelection(StrictModel):
    group_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    work_id: UUID
    version_id: UUID
    full_content: bool


class FreezeInput(StrictModel):
    inspection_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    profile_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    selections: list[GroupSelection] = Field(min_length=1, max_length=100)


class FrozenDocument(StrictModel):
    schema_version: int
    inspection_revision: str
    profile: NamingProfile
    plan: ImportPlan
    groups: list[ImportGroup]
    source: dict[str, Any]
    files: list[InspectedFile]
    unselected_groups: list[str]
    publication_available: bool
    pending_checks: list[str]
    initial_sidecars: dict[str, dict[str, str]] = Field(default_factory=dict)


class FrozenPlanView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    inspection_id: UUID
    revision: str
    created_at: datetime
    document: FrozenDocument


@router.get("/download-roots", response_model=list[str])
async def download_roots(admin: Admin):
    return sorted(get_settings().import_sources)


async def assert_admin(db, user_id):
    actor = await db.get(User, user_id, populate_existing=True)
    if not actor or not actor.active or actor.role != "admin":
        raise HTTPException(403, "Administrator access is required")


@router.post("/inspections", status_code=202, response_model=InspectionView)
async def create_inspection(
    body: InspectInput,
    admin: Admin,
    db: Database,
    idempotency_key: str = Header(min_length=8, max_length=200),
):
    if get_settings().recovery_mode:
        raise HTTPException(409, "Inspection is paused for recovery")
    root = get_settings().import_sources.get(body.source_key)
    if not root:
        raise HTTPException(422, "Select a download root configured on the worker")
    await transaction_lock(db, f"operation:{admin.id}:{idempotency_key}")
    await assert_admin(db, admin.id)
    payload = {**body.model_dump(), "source_path": str(root)}
    operation = await db.scalar(
        select(Operation).where(
            Operation.owner_id == admin.id, Operation.idempotency_key == idempotency_key
        )
    )
    if operation:
        if operation.kind != "organization.inspect" or operation.payload != payload:
            raise HTTPException(409, "This operation key was already used for another command")
        return await db.scalar(
            select(DownloadInspection).where(DownloadInspection.operation_id == operation.id)
        )
    operation = Operation(
        owner_id=admin.id,
        kind="organization.inspect",
        idempotency_key=idempotency_key,
        payload=payload,
    )
    db.add(operation)
    await db.flush()
    row = DownloadInspection(
        owner_id=admin.id,
        operation_id=operation.id,
        source_key=body.source_key,
        source_path=str(root),
        relative_path=body.relative_path,
    )
    db.add(row)
    operation.job_id = await enqueue(db, "organization.inspect", operation_id=str(operation.id))
    await db.commit()
    await db.refresh(row)
    return row


@router.get("/inspections", response_model=list[InspectionView])
async def inspections(admin: Admin, db: Database, offset: int = Query(0, ge=0)):
    # Summary list does not load potentially large file snapshots.
    rows = (
        (
            await db.execute(
                select(
                    DownloadInspection.id,
                    DownloadInspection.created_at,
                    DownloadInspection.operation_id,
                    DownloadInspection.source_key,
                    DownloadInspection.relative_path,
                    DownloadInspection.state,
                    DownloadInspection.message,
                )
                .where(DownloadInspection.owner_id == admin.id)
                .order_by(DownloadInspection.created_at.desc(), DownloadInspection.id)
                .offset(offset)
                .limit(25)
            )
        )
        .mappings()
        .all()
    )
    return [InspectionView.model_validate(row) for row in rows]


async def owned_inspection(db, actor_id, inspection_id):
    row = await db.scalar(
        select(DownloadInspection).where(
            DownloadInspection.id == inspection_id, DownloadInspection.owner_id == actor_id
        )
    )
    if not row:
        raise HTTPException(404, "Inspection not found")
    return row


@router.get("/inspections/{inspection_id}", response_model=InspectionView)
async def inspection(inspection_id: UUID, admin: Admin, db: Database):
    return await owned_inspection(db, admin.id, inspection_id)


@router.post("/inspections/{inspection_id}/plans", response_model=FrozenPlanView, status_code=201)
async def freeze_plan(inspection_id: UUID, body: FreezeInput, admin: Admin, db: Database):
    await transaction_lock(db, f"inspection-plan:{inspection_id}")
    await assert_admin(db, admin.id)
    row = await owned_inspection(db, admin.id, inspection_id)
    if row.state != "ready" or not row.snapshot or not source_matches(row):
        raise HTTPException(
            409, "A completed inspection of the configured download root is required"
        )
    if row.snapshot["revision"] != body.inspection_revision:
        raise HTTPException(409, "Inspection changed; review the current files")
    profile = await current_profile(db)
    if fingerprint(profile.model_dump()) != body.profile_revision:
        raise HTTPException(409, "Naming settings changed; preview the current profile")
    if len({selection.group_key for selection in body.selections}) != len(body.selections):
        raise HTTPException(422, "Choose each inspected group once")
    observed = {group["key"]: group for group in row.snapshot["groups"]}
    files = {file["path"]: file for file in row.snapshot["files"]}
    groups, sidecars = [], {}
    await graph_lock(db)
    for selection in body.selections:
        group = observed.get(selection.group_key)
        if not group:
            raise HTTPException(422, "Selected group is not in this inspection")
        work = await canonical_work(db, selection.work_id)
        version = await db.get(Version, selection.version_id)
        if not version or (await canonical_work(db, version.work_id)).id != work.id:
            raise HTTPException(422, "Choose a catalog version belonging to the selected book")
        if version.medium != group["medium"]:
            raise HTTPException(422, "Catalog version and inspected medium differ")
        pending = await db.scalar(
            select(ProviderObject.id)
            .where(
                ProviderObject.version_id == version.id,
                ProviderObject.match_status == "needs-review",
            )
            .limit(1)
        )
        if pending:
            raise HTTPException(
                409, "Resolve this version's metadata conflict before mapping files"
            )
        # Preserve version's origin work for correction/merge undo provenance.
        groups.append(
            ImportGroup(
                id=uuid5(row.id, selection.group_key),
                work_id=version.work_id,
                version_id=version.id,
                medium=version.medium,
                full_content=selection.full_content,
                metadata=NamingMetadata(
                    title=version.title or work.title,
                    authors=work.authors,
                    language=version.language or work.language,
                    narrators=version.narrators,
                    abridged=version.abridged,
                    original_year=work.publication_year,
                    edition_year=version.publication_year if version.medium == "ebook" else None,
                    recording_year=version.publication_year if version.medium == "audio" else None,
                    isbn=next(
                        (
                            version.identifiers[key]
                            for key in ("isbn13", "isbn10", "isbn")
                            if isinstance(version.identifiers.get(key), str)
                        ),
                        None,
                    ),
                    asin=version.identifiers.get("asin")
                    if isinstance(version.identifiers.get("asin"), str)
                    else None,
                ),
                files=[PlannedSourceFile(**file) for file in group["files"]],
            )
        )
        try:
            sidecars[str(groups[-1].id)] = initial_sidecars(
                ExportMetadata(
                    medium=version.medium,
                    naming=groups[-1].metadata,
                    description=work.description,
                )
            )
        except ValueError as error:
            raise HTTPException(
                422,
                "Resolved book metadata cannot be exported; correct invalid or oversized fields",
            ) from error
    plan = plan_import(groups, profile)
    selected_files = sorted({file.path for group in groups for file in group.files})
    document = {
        "schema_version": 2,
        "initial_sidecars": sidecars,
        "inspection_revision": row.snapshot["revision"],
        "profile": profile.model_dump(),
        "plan": plan.model_dump(mode="json"),
        "groups": [group.model_dump(mode="json") for group in groups],
        "source": {
            "key": row.source_key,
            "path": row.source_path,
            "relative_path": row.relative_path,
            "directory_identity": row.snapshot["directory_identity"],
        },
        "files": [files[path] for path in selected_files],
        "unselected_groups": sorted(
            set(observed) - {selection.group_key for selection in body.selections}
        ),
        "publication_available": False,
        "pending_checks": [
            "source revalidation",
            "destination configuration",
            "hardlink/copy probe",
            "current ownership and permissions",
            "ABS layout certification",
        ],
    }
    revision = fingerprint(document)
    existing = await db.scalar(
        select(FrozenImportPlan).where(
            FrozenImportPlan.inspection_id == row.id, FrozenImportPlan.revision == revision
        )
    )
    if existing:
        return existing
    frozen = FrozenImportPlan(
        inspection_id=row.id, owner_id=admin.id, revision=revision, document=document
    )
    db.add(frozen)
    await db.flush()
    db.add(
        AuditEvent(
            actor_id=admin.id,
            action="organization.plan.frozen",
            entity_id=frozen.id,
            detail={"revision": revision},
        )
    )
    await db.commit()
    await db.refresh(frozen)
    return frozen


@router.get("/plans/{plan_id}", response_model=FrozenPlanView)
async def frozen_plan(plan_id: UUID, admin: Admin, db: Database):
    row = await db.scalar(
        select(FrozenImportPlan).where(
            FrozenImportPlan.id == plan_id, FrozenImportPlan.owner_id == admin.id
        )
    )
    if not row:
        raise HTTPException(404, "Import plan not found")
    return row
