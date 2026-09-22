from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.config import get_settings
from app.db.models import RestoreCheckpoint
from app.domain.recovery_approvals import denial
from app.importing.destinations import destination_configuration, setup_route_current
from app.importing.naming import StrictModel, fingerprint


class DestinationView(StrictModel):
    id: UUID
    root_key: str
    library_id: UUID
    medium: str
    backend_path: str
    local_path: str | None = None
    mode: str
    enabled: bool
    revision: str
    configured: bool
    probe: dict[str, Any] | None
    publication_available: bool = False
    server_kind: str


async def view(db, row):
    configuration = await destination_configuration(db, row)
    revision = fingerprint(configuration)
    probe = row.probe if row.probe and row.probe.get("configuration_revision") == revision else None
    if probe and str(get_settings().import_sources.get(probe.get("source_key"))) != probe.get(
        "source_path"
    ):
        probe = None
    if probe:
        if not await setup_route_current(db, probe):
            probe = None
    if probe:
        historical = (
            await denial(db, "operation", row.probe_operation_id)
            if row.probe_operation_id
            else await db.scalar(select(RestoreCheckpoint.id).limit(1))
        )
        if historical:
            # Preserve the receipt on disk/in the ledger, but require a new route test.
            probe = None
    return DestinationView(
        id=row.id,
        root_key=row.root_key,
        library_id=row.library_id,
        medium=row.medium,
        backend_path=row.backend_path,
        local_path=configuration["root_path"],
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
        server_kind=(configuration["backend"] or {}).get("kind") or "audiobookshelf",
    )
