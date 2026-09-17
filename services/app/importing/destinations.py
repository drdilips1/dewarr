import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from cryptography.fernet import InvalidToken
from sqlalchemy import select

from app.adapters.audiobookshelf import Audiobookshelf
from app.adapters.contracts import AdapterError
from app.config import get_settings
from app.db.models import AuditEvent, ImportDestination, Integration, Library, Operation, User
from app.db.session import session_factory
from app.importing.backend import verify_backend
from app.importing.filesystem import InspectionError
from app.importing.naming import fingerprint
from app.importing.publication import PublishFile, probe_destination
from app.security import decrypt_secrets


async def destination_configuration(db, destination):
    library = await db.get(Library, destination.library_id, populate_existing=True)
    integration = (
        await db.get(Integration, library.integration_id, populate_existing=True)
        if library
        else None
    )
    settings = get_settings()
    root = settings.import_destinations.get(destination.root_key)
    return {
        "backend": {
            "integration_id": str(integration.id),
            "generation": integration.credential_generation,
            "base_url": integration.base_url,
            "enabled": integration.enabled,
            "library_external_id": library.external_id,
            "accessible": library.accessible,
        }
        if integration and library
        else None,
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
        and integration.kind == "audiobookshelf"
        and integration.enabled
        and destination.enabled
        and not get_settings().recovery_mode
    )


async def route_unchanged(db, destination, payload):
    return (
        await destination_configuration(db, destination) == payload["configuration"]
        and str(get_settings().import_sources.get(payload["source_key"])) == payload["source_path"]
    )


async def probe_route(operation_id: UUID, *, client_factory=None):
    client_factory = client_factory or Audiobookshelf
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
        if not await permitted(db, operation, destination) or not await route_unchanged(
            db, destination, operation.payload
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
        integration = await db.get(
            Integration, UUID(payload["configuration"]["backend"]["integration_id"])
        )
        try:
            secret = decrypt_secrets(integration.encrypted_secrets)["token"]
            if not isinstance(secret, str) or not secret:
                raise ValueError("Missing token")
        except (InvalidToken, KeyError, TypeError, ValueError):
            operation.status, operation.message = (
                "failed",
                "ABS credentials could not be read; save the connection token again",
            )
            destination.probe_token, destination.probe = None, None
            return
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
        if ok:
            backend = configuration["backend"]
            async with client_factory(backend["base_url"], secret) as adapter:
                report["backend"] = await verify_backend(
                    adapter,
                    backend["library_external_id"],
                    configuration["backend_path"],
                    Path(configuration["root_path"]),
                    configuration["medium"],
                )

        message = (
            "Filesystem and ABS folder mapping verified; ready for a reviewed import plan"
            if ok
            else ("Hardlink route unavailable; correct the mounts or explicitly choose copy mode")
        )
    except (OSError, ValueError, AdapterError) as error:
        report, ok = {}, False
        message = (
            str(error)[:300]
            if isinstance(error, (InspectionError, AdapterError))
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
        if not await permitted(db, operation, destination) or not await route_unchanged(
            db, destination, payload
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
