from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text

from app.api.dependencies import Admin, Database
from app.api.destinations import view as destination_view
from app.api.imports import assert_admin
from app.config import get_settings
from app.db.models import (
    AuditEvent,
    DownloadInspection,
    FrozenImportPlan,
    ImportDestination,
    ImportEntry,
    ImportRun,
    Operation,
    Version,
)
from app.domain.operations import transaction_lock
from app.importing.destinations import destination_configuration
from app.importing.grouping import current_grouping
from app.importing.naming import StrictModel
from app.importing.ownership import already_owned
from app.importing.publication import PublicationSpec, PublishFile
from app.importing.versioning import version_revision
from app.jobs.queue import enqueue

router = APIRouter(prefix="/organization", tags=["organization"])


class DestinationChoice(StrictModel):
    id: UUID
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")


class ImportInput(StrictModel):
    plan_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    destinations: dict[Literal["ebook", "audio"], DestinationChoice]


class CoverExportView(BaseModel):
    state: Literal["prepared", "unavailable"]
    message: str
    sha256: str | None = None
    backend_selected: bool | None = None
    unchanged: bool | None = None


class EntryView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    group_id: UUID
    version_id: UUID
    destination_id: UUID | None
    operation_id: UUID | None
    state: str
    message: str
    published_at: datetime | None
    confirmed_at: datetime | None
    asset_id: UUID | None
    can_retry: bool = False
    can_cancel: bool = False
    cover_export: CoverExportView | None = None


class RunView(BaseModel):
    id: UUID
    plan_id: UUID
    created_at: datetime
    entries: list[EntryView]


async def view(db, run):
    entries = (
        await db.scalars(
            select(ImportEntry)
            .where(ImportEntry.run_id == run.id)
            .order_by(ImportEntry.created_at, ImportEntry.id)
        )
    ).all()
    return RunView(
        id=run.id,
        plan_id=run.plan_id,
        created_at=run.created_at,
        entries=[
            EntryView.model_validate(entry).model_copy(
                update={
                    "can_retry": bool(
                        entry.reserved
                        and entry.specification
                        and entry.state in {"held", "awaiting-library"}
                    ),
                    "can_cancel": not entry.published_at
                    and entry.state in {"queued", "publishing", "held", "cancel-held"},
                }
            )
            for entry in entries
        ],
    )


@router.post("/plans/{plan_id}/imports", response_model=RunView, status_code=202)
async def start_import(
    plan_id: UUID,
    body: ImportInput,
    admin: Admin,
    db: Database,
    idempotency_key: str = Header(min_length=8, max_length=200),
):
    if get_settings().recovery_mode:
        raise HTTPException(409, "Publication is paused for recovery")
    await transaction_lock(db, f"import-command:{admin.id}:{idempotency_key}")
    await assert_admin(db, admin.id)
    request = {"plan_id": str(plan_id), **body.model_dump(mode="json")}
    existing = await db.scalar(
        select(ImportRun).where(
            ImportRun.owner_id == admin.id, ImportRun.command_key == idempotency_key
        )
    )
    if existing:
        if existing.request != request:
            raise HTTPException(409, "This import command key was used for another request")
        return await view(db, existing)
    plan = await db.scalar(
        select(FrozenImportPlan).where(
            FrozenImportPlan.id == plan_id, FrozenImportPlan.owner_id == admin.id
        )
    )
    if not plan:
        raise HTTPException(404, "Import plan not found")
    await transaction_lock(db, f"inspection-plan:{plan.inspection_id}")
    inspection = await db.get(DownloadInspection, plan.inspection_id)
    grouping_revision, _ = await current_grouping(db, inspection)
    document = plan.document
    if (document.get("grouping_revision") or document["inspection_revision"]) != grouping_revision:
        raise HTTPException(409, "File groups changed after this plan; save a new reviewed plan")
    if plan.revision != body.plan_revision:
        raise HTTPException(409, "Review the current frozen import plan")
    if document["profile"]["layout"] != "conventional":
        raise HTTPException(409, "Nested publication awaits the complete compatibility gate")
    if not document.get("initial_sidecars") or not document.get("version_revisions"):
        raise HTTPException(409, "Create a fresh plan with frozen metadata and version evidence")
    source = document["source"]
    if str(get_settings().import_sources.get(source["key"])) != source["path"]:
        raise HTTPException(409, "Download mapping changed; inspect and plan again")
    destinations = {}
    for medium, choice in body.destinations.items():
        row = await db.get(ImportDestination, choice.id)
        if not row or row.medium != medium or not row.enabled:
            raise HTTPException(422, "Choose an enabled destination for each medium")
        current = await destination_view(db, row)
        if (
            current.revision != choice.revision
            or not current.probe
            or current.probe.get("status") != "verified"
            or not current.probe.get("backend", {}).get("root_mapping")
        ):
            raise HTTPException(
                409, "Verify the current destination and ABS mapping before importing"
            )
        destinations[medium] = row
    # Short transaction serializes reservation decisions, not filesystem work.
    await transaction_lock(db, "import:reservations")
    run = ImportRun(
        owner_id=admin.id, plan_id=plan.id, command_key=idempotency_key, request=request
    )
    db.add(run)
    await db.flush()
    groups = {group["id"]: group for group in document["groups"]}
    files = {file["path"]: file for file in document["files"]}
    for item in document["plan"]["items"]:
        group = groups[item["group_id"]]
        destination = destinations.get(item["medium"])
        entry = ImportEntry(
            id=uuid4(),
            run_id=run.id,
            group_id=UUID(item["group_id"]),
            version_id=UUID(item["version_id"]),
            destination_id=destination.id if destination else None,
            state="held",
            reserved=False,
            message=item["reason"] or "Choose a destination for this book",
        )
        db.add(entry)
        if item["state"] != "ready" or not destination:
            continue
        version = await db.get(Version, entry.version_id)
        if version_revision(version) != document["version_revisions"].get(str(version.id)):
            entry.message = "Catalog version changed; inspect its identity and create a fresh plan"
            continue
        if await already_owned(db, version.id, destination.library_id):
            entry.state, entry.message = (
                "skipped",
                "This version is already confirmed in the destination library",
            )
            continue
        reserved = await db.scalar(
            select(ImportEntry.id)
            .where(
                ImportEntry.configuration["destination"]["library_id"].astext
                == str(destination.library_id),
                ImportEntry.version_id == version.id,
                ImportEntry.reserved.is_(True),
            )
            .limit(1)
        )
        if reserved:
            entry.message = "Another import already reserves this version; review that import first"
            continue
        same_files = await db.scalar(
            select(ImportEntry.id)
            .join(ImportRun)
            .join(FrozenImportPlan)
            .where(
                FrozenImportPlan.inspection_id == plan.inspection_id,
                ImportEntry.group_id == entry.group_id,
                ImportEntry.reserved.is_(True),
            )
            .limit(1)
        )
        if same_files:
            entry.message = (
                "These files already belong to a reserved import; review that import first"
            )
            continue
        configuration = await destination_configuration(db, destination)
        specification = PublicationSpec(
            entry_id=entry.id,
            plan_revision=plan.revision,
            source_root=Path(source["path"]),
            source_relative=source["relative_path"],
            source_directory=source["directory_identity"],
            destination_root=Path(configuration["root_path"]),
            staging_root=Path(configuration["staging_path"]),
            folder=item["folder"].split("/", 1)[1],
            mode=destination.mode,
            files=[
                PublishFile(
                    source=mapping["source"],
                    name=PurePosixPath(mapping["destination"]).name,
                    sha256=files[mapping["source"]]["sha256"],
                    identity=files[mapping["source"]]["identity"],
                )
                for mapping in item["files"]
            ],
            sidecars=document["initial_sidecars"][item["group_id"]],
        )
        entry.specification = specification.model_dump(mode="json")
        entry.configuration = {
            "destination": configuration,
            "source_key": source["key"],
            "source_path": source["path"],
        }
        entry.expected_metadata = {
            **group["metadata"],
            "medium": item["medium"],
            "version_revision": version_revision(version),
            "cover_source": document.get("cover_sources", {}).get(item["group_id"]),
        }
        if item["medium"] == "audio" and len(specification.files) > 1:
            names = {file.source: file.name for file in specification.files}
            entry.expected_metadata["audio_order"] = [
                str(
                    PurePosixPath(configuration["backend_path"])
                    / specification.folder
                    / names[file["path"]]
                )
                for file in sorted(
                    group["files"],
                    key=lambda file: (file.get("disc") or 1, file.get("track") or 1, file["path"]),
                )
                if file.get("role", "media") == "media"
            ]
        entry.state, entry.message, entry.reserved = "queued", "Waiting to publish this book", True
        operation = Operation(
            owner_id=admin.id,
            kind="organization.publish",
            idempotency_key=f"import:{entry.id}",
            payload={"entry_id": str(entry.id)},
        )
        db.add(operation)
        await db.flush()
        entry.operation_id = operation.id
        operation.job_id = await enqueue(db, "organization.publish", operation_id=str(operation.id))
    db.add(AuditEvent(actor_id=admin.id, action="organization.import.requested", entity_id=run.id))
    await db.commit()
    return await view(db, run)


@router.post("/imports/{run_id}/entries/{entry_id}/cancel", response_model=RunView, status_code=202)
async def cancel_entry(run_id: UUID, entry_id: UUID, admin: Admin, db: Database):
    await assert_admin(db, admin.id)
    if get_settings().recovery_mode:
        raise HTTPException(409, "Import changes are paused for recovery")
    run = await db.scalar(
        select(ImportRun).where(ImportRun.id == run_id, ImportRun.owner_id == admin.id)
    )
    entry = await db.get(ImportEntry, entry_id, with_for_update=True)
    if not run or not entry or entry.run_id != run.id:
        raise HTTPException(404, "Import entry not found")
    if entry.state == "cancelled":
        return await view(db, run)
    if entry.published_at or entry.state in {"confirmed", "skipped", "awaiting-library"}:
        raise HTTPException(
            409, "This book was already published or satisfied; its files are preserved"
        )
    if entry.state == "cancelling":
        return await view(db, run)  # Periodic recovery handles failed/expired queue attempts.
    entry.run_token, entry.next_check_at = None, None
    if not entry.specification and not entry.reserved:
        entry.state = "cancelled"
        entry.message = "Unstarted import stopped; you can review a new plan"
    else:
        operation = await db.get(Operation, entry.operation_id)
        status = await db.scalar(
            text("SELECT status::text FROM book_queue.procrastinate_jobs WHERE id=:id"),
            {"id": operation.job_id},
        )
        entry.state = "cancelling"
        entry.message = "Stopping import after checking whether any files were already published"
        entry.next_check_at = datetime.now(UTC) + timedelta(minutes=1)
        operation.status, operation.message = "queued", entry.message
        if status != "todo":
            operation.job_id = await enqueue(
                db, "organization.publish", operation_id=str(operation.id)
            )
    db.add(
        AuditEvent(
            actor_id=admin.id, action="organization.import.cancel-requested", entity_id=entry.id
        )
    )
    await db.commit()
    return await view(db, run)


@router.get("/plans/{plan_id}/imports", response_model=list[RunView])
async def plan_imports(plan_id: UUID, admin: Admin, db: Database):
    rows = (
        await db.scalars(
            select(ImportRun)
            .where(ImportRun.plan_id == plan_id, ImportRun.owner_id == admin.id)
            .order_by(ImportRun.created_at.desc())
            .limit(25)
        )
    ).all()
    return [await view(db, row) for row in rows]


@router.get("/imports/{run_id}", response_model=RunView)
async def import_run(run_id: UUID, admin: Admin, db: Database):
    row = await db.scalar(
        select(ImportRun).where(ImportRun.id == run_id, ImportRun.owner_id == admin.id)
    )
    if not row:
        raise HTTPException(404, "Import not found")
    return await view(db, row)


@router.post("/imports/{run_id}/entries/{entry_id}/retry", response_model=RunView, status_code=202)
async def retry_entry(run_id: UUID, entry_id: UUID, admin: Admin, db: Database):
    await assert_admin(db, admin.id)
    if get_settings().recovery_mode:
        raise HTTPException(409, "Publication is paused for recovery")
    run = await db.scalar(
        select(ImportRun).where(ImportRun.id == run_id, ImportRun.owner_id == admin.id)
    )
    entry = await db.get(ImportEntry, entry_id, with_for_update=True)
    if not run or not entry or entry.run_id != run.id:
        raise HTTPException(404, "Import entry not found")
    if (
        entry.state not in {"held", "awaiting-library"}
        or not entry.reserved
        or not entry.specification
    ):
        raise HTTPException(409, "This entry cannot be retried; review or create a fresh plan")
    operation = await db.get(Operation, entry.operation_id)
    # Never restart a live job solely because its observation is delayed.
    from sqlalchemy import text

    status = await db.scalar(
        text("SELECT status::text FROM book_queue.procrastinate_jobs WHERE id=:id"),
        {"id": operation.job_id},
    )
    if status in {"todo", "doing"}:
        return await view(db, run)
    destination = await db.get(ImportDestination, entry.destination_id)
    current = await destination_configuration(db, destination)
    previous = entry.configuration["destination"]

    # Explicit retry may use a rotated token for the same server/library/paths.
    def without_generation(value):
        return {
            **value,
            "backend": {key: item for key, item in value["backend"].items() if key != "generation"},
        }

    if without_generation(previous) != without_generation(current):
        raise HTTPException(
            409, "The frozen server, library or paths changed; resolve the mapping before retrying"
        )
    entry.configuration = {**entry.configuration, "destination": current}
    entry.state = "awaiting-library" if entry.published_at else "queued"
    entry.message = "Import retry requested"
    operation.status = "queued"
    operation.job_id = await enqueue(db, "organization.publish", operation_id=str(operation.id))
    db.add(AuditEvent(actor_id=admin.id, action="organization.import.retry", entity_id=entry.id))
    await db.commit()
    return await view(db, run)
