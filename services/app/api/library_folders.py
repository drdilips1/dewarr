"""Choose an ABS folder, persist its local mount, and activate a verified route."""

import asyncio
from pathlib import Path
from typing import Literal
from uuid import UUID

from cryptography.fernet import InvalidToken
from fastapi import APIRouter, HTTPException
from pydantic import Field, field_validator
from sqlalchemy import select

from app.adapters.audiobookshelf import Audiobookshelf
from app.adapters.contracts import AdapterError
from app.api.automatic_imports import view as policy_view
from app.api.dependencies import Admin, Database
from app.db.models import (
    AcquisitionDefaults,
    AuditEvent,
    AutomaticImportPolicy,
    ImportDestination,
    ImportStorageSettings,
    Integration,
    Library,
)
from app.domain.operations import transaction_lock
from app.domain.release_profiles import DEFAULTS_LOCK
from app.importing.destination_view import DestinationView, view
from app.importing.naming import StrictModel
from app.importing.planning import assert_admin
from app.importing.storage import storage_settings
from app.security import decrypt_secrets

router = APIRouter(prefix="/organization/library-folders", tags=["organization"])


class FolderOption(StrictModel):
    library_id: UUID
    library_name: str
    server_name: str
    folders: list[str] = []
    ebooks_allowed: bool = True
    error: str | None = None


async def configuration(db, library_id):
    library = await db.get(Library, library_id)
    integration = await db.get(Integration, library.integration_id) if library else None
    if not library or not library.accessible or not integration or not integration.enabled:
        raise HTTPException(422, "Choose a library from a connected Audiobookshelf server")
    async with Audiobookshelf(
        integration.base_url, decrypt_secrets(integration.encrypted_secrets)["token"]
    ) as adapter:
        config = await adapter.import_configuration(library.external_id)
    return library, config


@router.get("", response_model=list[FolderOption])
async def folders(admin: Admin, db: Database):
    rows = (
        await db.execute(
            select(Library, Integration)
            .join(Integration, Library.integration_id == Integration.id)
            .where(
                Library.accessible.is_(True),
                Integration.enabled.is_(True),
                Integration.kind == "audiobookshelf",
            )
            .order_by(Library.name)
        )
    ).all()

    async def option(library, integration):
        row = FolderOption(
            library_id=library.id, library_name=library.name, server_name=integration.name
        )
        try:
            async with Audiobookshelf(
                integration.base_url, decrypt_secrets(integration.encrypted_secrets)["token"]
            ) as adapter:
                config = await adapter.import_configuration(library.external_id)
            row.folders, row.ebooks_allowed = config.folders, not config.audiobooks_only
        except (AdapterError, InvalidToken, ValueError, KeyError):
            row.error = (
                "Could not read this library's folders. Check its connection and permissions."
            )
        return row

    return await asyncio.gather(*(option(library, integration) for library, integration in rows))


class FolderInput(StrictModel):
    library_id: UUID
    backend_path: str = Field(max_length=1024)
    local_path: str = Field(max_length=1024)
    destination_id: UUID | None = None
    expected_revision: str | None = None

    @field_validator("backend_path", "local_path")
    @classmethod
    def absolute_folder(cls, value):
        path = Path(value)
        if not value.startswith("/") or str(path) == "/" or ".." in path.parts or "\x00" in value:
            raise ValueError("Choose an absolute folder path below /")
        return str(path)


@router.put("/{medium}", response_model=DestinationView)
async def choose(medium: Literal["ebook", "audio"], body: FolderInput, admin: Admin, db: Database):
    await transaction_lock(db, "library-storage")
    await assert_admin(db, admin.id)
    try:
        _, config = await configuration(db, body.library_id)
    except (AdapterError, InvalidToken, ValueError, KeyError) as error:
        raise HTTPException(
            422, "Could not read Audiobookshelf folders. Check the connection and token."
        ) from error
    if body.backend_path not in config.folders:
        raise HTTPException(422, "Choose a current folder from the selected Audiobookshelf library")
    if medium == "ebook" and config.audiobooks_only:
        raise HTTPException(
            422,
            "This library only accepts audiobooks. "
            "Enable ebooks in Audiobookshelf or choose another library.",
        )
    root_key = f"library-{medium}"
    destination = (
        await db.get(ImportDestination, body.destination_id)
        if body.destination_id
        else await db.scalar(
            select(ImportDestination).where(ImportDestination.root_key == root_key)
        )
    )
    if body.destination_id and not destination:
        raise HTTPException(404, "Destination no longer exists")
    if destination:
        await db.refresh(destination, with_for_update=True)
        if (
            destination.medium != medium
            or body.expected_revision != (await view(db, destination)).revision
        ):
            raise HTTPException(
                409, "Folder settings changed. Reopen the folder picker and try again."
            )
        root_key = destination.root_key
    settings = await storage_settings(db)
    local = Path(body.local_path)
    if not settings.import_staging_root and local.parent == Path("/"):
        raise HTTPException(
            422,
            "Use a library folder inside a shared media mount, such as /data/ebooks. "
            "Choose Other path to enter the folder path used by Dewarr.",
        )
    stage = settings.import_staging_root or local.parent / ".book-search-staging"
    # All media and publication journals remain outside watched roots.
    roots = {**settings.import_destinations, root_key: local}
    for root in roots.values():
        for external in [*settings.import_sources.values(), stage]:
            if root.is_relative_to(external) or external.is_relative_to(root):
                raise HTTPException(
                    422,
                    "Library folders must be separate from download and staging folders. "
                    "Use sibling folders on the same mounted filesystem.",
                )
    storage = await db.get(ImportStorageSettings, 1)
    if not storage:
        storage = ImportStorageSettings(id=1, destinations={})
        db.add(storage)
    storage.destinations = {**storage.destinations, root_key: str(local)}
    storage.staging_root = str(stage)
    if not destination:
        destination = ImportDestination(root_key=root_key)
        db.add(destination)
    destination.library_id, destination.medium = body.library_id, medium
    destination.backend_path, destination.mode, destination.enabled = (
        body.backend_path,
        "hardlink",
        True,
    )
    destination.probe = destination.probe_token = destination.probe_operation_id = None
    await db.flush()
    db.add(
        AuditEvent(
            actor_id=admin.id,
            action="organization.folder.selected",
            entity_id=destination.id,
            detail={"medium": medium},
        )
    )
    await db.commit()
    return await view(db, destination)


class ActivateInput(StrictModel):
    expected_revision: str
    automatic: bool = True


@router.post("/{destination_id}/activate", response_model=DestinationView)
async def activate(destination_id: UUID, body: ActivateInput, admin: Admin, db: Database):
    await transaction_lock(db, DEFAULTS_LOCK)
    await transaction_lock(db, f"automatic-policy:{destination_id}")
    await assert_admin(db, admin.id)
    destination = await db.get(ImportDestination, destination_id, with_for_update=True)
    if not destination:
        raise HTTPException(404, "Destination not found")
    current = await view(db, destination)
    if (
        current.revision != body.expected_revision
        or not current.publication_available
        or destination.mode != "hardlink"
    ):
        raise HTTPException(409, "The current folder must pass its hardlink test before use")
    if body.automatic and not (await policy_view(db, destination)).can_enable:
        raise HTTPException(
            409, "Automatic import requires a verified folder and supported naming layout"
        )
    policy = await db.scalar(
        select(AutomaticImportPolicy)
        .where(AutomaticImportPolicy.destination_id == destination.id)
        .with_for_update()
    )
    if not policy:
        policy = AutomaticImportPolicy(
            destination_id=destination.id, generation=0, configuration={}, approved_by=admin.id
        )
        db.add(policy)
    policy.enabled, policy.approved_by = body.automatic, admin.id
    policy.generation += 1
    policy.configuration = {
        "destination_revision": current.revision,
        "source_key": current.probe["source_key"],
        "source_path": current.probe["source_path"],
    }
    # One choice sets library identity and physical route together. Preserve unrelated preferences.
    for key, owner in [("installation", None), (f"user:{admin.id}", admin.id)]:
        defaults = await db.scalar(
            select(AcquisitionDefaults).where(AcquisitionDefaults.key == key)
        )
        if not defaults:
            defaults = AcquisitionDefaults(key=key, owner_id=owner, generation=0, preferences={})
            db.add(defaults)
        defaults.preferences = {
            **defaults.preferences,
            f"{destination.medium}_library_id": str(destination.library_id),
            f"{destination.medium}_destination_id": str(destination.id),
        }
        binding = current.probe.get("setup_downloader")
        if binding:
            defaults.preferences = {**defaults.preferences, "downloader_id": binding["id"]}
        defaults.generation += 1
    db.add(
        AuditEvent(
            actor_id=admin.id,
            action="organization.folder.activated",
            entity_id=destination.id,
            detail={"medium": destination.medium, "automatic": body.automatic},
        )
    )
    await db.commit()
    return await view(db, destination)
