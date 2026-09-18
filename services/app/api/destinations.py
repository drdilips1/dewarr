from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from pydantic import Field, model_validator
from sqlalchemy import select

from app.api.dependencies import Admin, Database
from app.api.imports import assert_admin
from app.api.operations import OperationView
from app.config import get_settings
from app.db.models import (
    AuditEvent,
    FrozenImportPlan,
    ImportDestination,
    Integration,
    Library,
    Operation,
)
from app.domain.operations import transaction_lock
from app.importing.destinations import destination_configuration, permitted
from app.importing.filesystem import relative_parts
from app.importing.naming import StrictModel, fingerprint
from app.jobs.queue import enqueue

router = APIRouter(prefix="/organization", tags=["organization"])


class DestinationInput(StrictModel):
    library_id: UUID
    medium: Literal["ebook", "audio"]
    backend_path: str = Field(min_length=2, max_length=1024)
    mode: Literal["hardlink", "copy"] = "hardlink"
    enabled: bool = True
    expected_revision: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def backend_root(self):
        if not self.backend_path.startswith("/"):
            raise ValueError("Enter the absolute library root as Audiobookshelf sees it")
        relative_parts(self.backend_path[1:])
        return self


class DestinationView(StrictModel):
    id: UUID
    root_key: str
    library_id: UUID
    medium: str
    backend_path: str
    mode: str
    enabled: bool
    revision: str
    configured: bool
    probe: dict[str, Any] | None
    publication_available: bool = False


async def view(db, row):
    configuration = await destination_configuration(db, row)
    revision = fingerprint(configuration)
    probe = row.probe if row.probe and row.probe.get("configuration_revision") == revision else None
    if probe and str(get_settings().import_sources.get(probe.get("source_key"))) != probe.get(
        "source_path"
    ):
        probe = None
    return DestinationView(
        id=row.id,
        root_key=row.root_key,
        library_id=row.library_id,
        medium=row.medium,
        backend_path=row.backend_path,
        mode=row.mode,
        enabled=row.enabled,
        revision=revision,
        configured=bool(configuration["root_path"] and configuration["staging_path"]),
        probe=probe,
        publication_available=bool(
            probe
            and probe.get("status") == "verified"
            and probe.get("backend", {}).get("root_mapping")
            and row.enabled
        ),
    )


@router.get("/destination-roots", response_model=list[str])
async def destination_roots(admin: Admin):
    return sorted(get_settings().import_destinations)


@router.get("/destinations", response_model=list[DestinationView])
async def destinations(admin: Admin, db: Database):
    return [
        await view(db, row)
        for row in (
            await db.scalars(select(ImportDestination).order_by(ImportDestination.root_key))
        ).all()
    ]


@router.put("/destinations/{root_key}", response_model=DestinationView)
async def save_destination(root_key: str, body: DestinationInput, admin: Admin, db: Database):
    if root_key not in get_settings().import_destinations:
        raise HTTPException(422, "Select a library root configured on the worker")
    await transaction_lock(db, f"destination:{root_key}")
    await assert_admin(db, admin.id)
    library = await db.get(Library, body.library_id)
    integration = await db.get(Integration, library.integration_id) if library else None
    if not library or not library.accessible or not integration or not integration.enabled:
        raise HTTPException(422, "Select an accessible library from an enabled connection")
    row = await db.scalar(
        select(ImportDestination).where(ImportDestination.root_key == root_key).with_for_update()
    )
    if row and (await view(db, row)).revision != body.expected_revision:
        raise HTTPException(409, "Destination settings changed; reload before saving")
    if not row:
        if body.expected_revision:
            raise HTTPException(409, "Destination no longer matches the edited settings")
        row = ImportDestination(root_key=root_key)
        db.add(row)
    for key, value in body.model_dump(exclude={"expected_revision"}).items():
        setattr(row, key, value)
    row.probe, row.probe_token, row.probe_operation_id = None, None, None
    await db.flush()
    db.add(AuditEvent(actor_id=admin.id, action="organization.destination.saved", entity_id=row.id))
    await db.commit()
    return await view(db, row)


class ProbeInput(StrictModel):
    plan_id: UUID
    expected_revision: str = Field(pattern=r"^[a-f0-9]{64}$")


@router.post("/destinations/{destination_id}/probe", response_model=OperationView, status_code=202)
async def probe_destination(
    destination_id: UUID,
    body: ProbeInput,
    admin: Admin,
    db: Database,
    idempotency_key: str = Header(min_length=8, max_length=200),
):
    await transaction_lock(db, f"operation:{admin.id}:{idempotency_key}")
    row = await db.scalar(
        select(ImportDestination).where(ImportDestination.id == destination_id).with_for_update()
    )
    if not row or not (await view(db, row)).configured:
        raise HTTPException(422, "Configure destination and private staging roots first")
    if (await view(db, row)).revision != body.expected_revision:
        raise HTTPException(409, "Destination settings changed; review them before probing")
    frozen = await db.scalar(
        select(FrozenImportPlan).where(
            FrozenImportPlan.id == body.plan_id, FrozenImportPlan.owner_id == admin.id
        )
    )
    if not frozen:
        raise HTTPException(404, "Import plan not found")
    document = frozen.document
    configuration = await destination_configuration(db, row)
    source = document["source"]
    if str(get_settings().import_sources.get(source["key"])) != source["path"]:
        raise HTTPException(409, "Download root changed; inspect the files again")
    selected = next(
        (
            item
            for item in document["plan"]["items"]
            if item["state"] == "ready" and item["medium"] == row.medium
        ),
        None,
    )
    if not selected:
        raise HTTPException(
            422, "The plan needs a resolved item matching this destination's medium"
        )
    source_file = selected["files"][0]["source"]
    evidence = next(file for file in document["files"] if file["path"] == source_file)
    payload = {
        "destination_id": str(row.id),
        "plan_id": str(frozen.id),
        "configuration": configuration,
        "source_key": source["key"],
        "source_path": source["path"],
        "source_relative": source["relative_path"],
        **({"source_kind": "file"} if source.get("source_kind") == "file" else {}),
        "file": {
            "source": source_file,
            "name": "probe",
            "sha256": evidence["sha256"],
            "identity": evidence["identity"],
        },
    }
    existing = await db.scalar(
        select(Operation).where(
            Operation.owner_id == admin.id, Operation.idempotency_key == idempotency_key
        )
    )
    if existing:
        if existing.kind != "organization.probe" or existing.payload != payload:
            raise HTTPException(409, "This operation key was already used for another command")
        return existing
    operation = Operation(
        owner_id=admin.id,
        kind="organization.probe",
        idempotency_key=idempotency_key,
        payload=payload,
        message="Waiting to check the destination on the worker",
    )
    if not await permitted(db, operation, row):
        raise HTTPException(409, "Destination access or recovery mode prevents probing")
    db.add(operation)
    await db.flush()
    row.probe_operation_id, row.probe_token, row.probe = operation.id, None, None
    operation.job_id = await enqueue(db, "organization.probe", operation_id=str(operation.id))
    await db.commit()
    await db.refresh(operation)
    return operation
