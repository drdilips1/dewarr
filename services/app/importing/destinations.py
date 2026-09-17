import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select

from app.config import get_settings
from app.db.models import AuditEvent, ImportDestination, Integration, Library, Operation, User
from app.db.session import session_factory
from app.importing.filesystem import InspectionError
from app.importing.naming import fingerprint
from app.importing.publication import PublishFile, probe_destination


def destination_configuration(destination):
    settings = get_settings()
    root = settings.import_destinations.get(destination.root_key)
    return {
        "root_key": destination.root_key,
        "root_path": str(root) if root else None,
        "staging_path": str(settings.import_staging_root) if settings.import_staging_root else None,
        "library_id": str(destination.library_id),
        "medium": destination.medium,
        "backend_path": destination.backend_path,
        "mode": destination.mode,
        "enabled": destination.enabled,
        "watched_paths": sorted(str(path) for path in settings.import_destinations.values()),
    }


async def permitted(db, operation, destination):
    actor = await db.get(User, operation.owner_id, populate_existing=True)
    library = await db.get(Library, destination.library_id, populate_existing=True)
    integration = (
        await db.get(Integration, library.integration_id, populate_existing=True)
        if library
        else None
    )
    return bool(
        actor
        and actor.active
        and actor.role == "admin"
        and library
        and library.accessible
        and integration
        and integration.enabled
        and destination.enabled
        and not get_settings().recovery_mode
    )


def route_unchanged(destination, payload):
    return (
        destination_configuration(destination) == payload["configuration"]
        and str(get_settings().import_sources.get(payload["source_key"])) == payload["source_path"]
    )


async def probe_route(operation_id: UUID):
    token = uuid4()
    async with session_factory()() as db, db.begin():
        operation = await db.get(Operation, operation_id)
        if not operation or operation.status in {"completed", "failed"}:
            return
        destination = await db.scalar(
            select(ImportDestination)
            .where(ImportDestination.id == UUID(operation.payload["destination_id"]))
            .with_for_update()
        )
        if not destination or destination.probe_operation_id != operation.id:
            operation.status, operation.message = (
                "failed",
                "A newer destination probe replaced this attempt",
            )
            return
        if not await permitted(db, operation, destination) or not route_unchanged(
            destination, operation.payload
        ):
            operation.status, operation.message = (
                "failed",
                "Destination access or configuration changed",
            )
            destination.probe = None
            return
        destination.probe_token = token
        operation.status, operation.message = (
            "running",
            "Checking hardlink and no-replace behavior on worker mounts",
        )
        payload = operation.payload
    try:
        configuration = payload["configuration"]
        for watched in get_settings().import_destinations.values():
            for external in (Path(payload["source_path"]), Path(configuration["staging_path"])):
                if external.is_relative_to(watched) or watched.is_relative_to(external):
                    raise InspectionError(
                        "Download and staging roots must be outside all library roots"
                    )
        report = await asyncio.to_thread(
            probe_destination,
            Path(payload["source_path"]),
            payload["source_relative"],
            PublishFile.model_validate(payload["file"]),
            Path(configuration["root_path"]),
            Path(configuration["staging_path"]),
        )
        ok = report["no_replace"] and report[configuration["mode"]]
        message = (
            "Filesystem route verified; ABS compatibility is still required"
            if ok
            else ("Hardlink route unavailable; correct the mounts or explicitly choose copy mode")
        )
    except (OSError, ValueError) as error:
        report, ok = {}, False
        message = (
            str(error)[:300]
            if isinstance(error, InspectionError)
            else ("Destination probe failed; check paths, permissions and filesystem support")
        )
    async with session_factory()() as db, db.begin():
        operation = await db.get(Operation, operation_id)
        destination = await db.scalar(
            select(ImportDestination)
            .where(ImportDestination.id == UUID(payload["destination_id"]))
            .with_for_update()
        )
        if not destination or destination.probe_operation_id != operation.id:
            operation.status, operation.message = "failed", "A newer probe replaced this result"
            return
        if destination.probe_token != token:
            return
        if not await permitted(db, operation, destination) or not route_unchanged(
            destination, payload
        ):
            operation.status, operation.message = (
                "failed",
                "Destination access changed; result discarded",
            )
            destination.probe_token, destination.probe = None, None
            return
        destination.probe = {
            "status": "verified" if ok else "failed",
            "message": message,
            "source_key": payload["source_key"],
            "source_path": payload["source_path"],
            "configuration_revision": fingerprint(configuration),
            "checked_at": datetime.now(UTC).isoformat(),
            **report,
        }
        destination.probe_token = None
        operation.status, operation.message = "completed" if ok else "failed", message
        db.add(
            AuditEvent(
                actor_id=operation.owner_id,
                action="organization.destination.probed",
                entity_id=destination.id,
                detail={"verified": bool(ok)},
            )
        )
