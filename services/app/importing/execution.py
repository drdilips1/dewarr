"""Durable item publication and independent ABS confirmation.

The final rename holds permission/configuration/attempt rows until it finishes.
Bulk file work happens outside database transactions in private staging.
"""

import asyncio
import base64
import hashlib
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from uuid import UUID, uuid4

from cryptography.fernet import InvalidToken
from fastapi import HTTPException
from sqlalchemy import select

from app.adapters.audiobookshelf import Audiobookshelf
from app.adapters.contracts import AdapterError, FailureKind
from app.config import get_settings
from app.db.models import (
    AuditEvent,
    FrozenImportPlan,
    ImportDestination,
    ImportEntry,
    ImportRun,
    Integration,
    Library,
    LibraryAsset,
    Operation,
    ProviderObject,
    User,
    Version,
)
from app.db.session import session_factory
from app.domain import download_reviews
from app.domain.identity import normalized
from app.domain.inventory import apply_item
from app.importing.backend import verify_backend
from app.importing.covers import CoverError, fetch_cover
from app.importing.destinations import destination_configuration
from app.importing.filesystem import beneath, digest, directory
from app.importing.naming import AUDIO, EBOOK
from app.importing.ownership import already_owned
from app.importing.publication import (
    PublicationBusy,
    PublicationError,
    PublicationSpec,
    publish_item,
)
from app.importing.versioning import version_revision
from app.security import decrypt_secrets


class Superseded(PublicationError):
    pass


class AlreadyOwned(PublicationError):
    pass


async def context(db, entry, token, *, lock=False):
    run = await db.get(ImportRun, entry.run_id)
    plan = await db.get(FrozenImportPlan, run.plan_id)
    if lock:
        await download_reviews.lock_principals(db, plan.inspection_id)
    destination = await db.get(ImportDestination, entry.destination_id)
    backend = entry.configuration["destination"]["backend"]
    actor = await db.get(
        User, run.owner_id, with_for_update={"read": True} if lock else None, populate_existing=True
    )
    integration = await db.get(
        Integration, UUID(backend["integration_id"]), with_for_update=lock, populate_existing=True
    )
    library = await db.get(
        Library, destination.library_id, with_for_update=lock, populate_existing=True
    )
    if lock:
        await db.refresh(destination, with_for_update=True)
        await db.refresh(entry, with_for_update=True)
    if entry.run_token != token or entry.state not in {"publishing", "awaiting-library"}:
        raise Superseded("A newer import attempt owns this entry")
    if (
        get_settings().recovery_mode
        or not actor
        or not actor.active
        or actor.role != "admin"
        or not integration.enabled
        or not library.accessible
        or not destination.enabled
    ):
        raise PublicationError("Import access changed or recovery mode is active")
    if await destination_configuration(db, destination) != entry.configuration["destination"]:
        raise PublicationError("Destination or connection changed; review it before retrying")
    if (
        str(get_settings().import_sources.get(entry.configuration["source_key"]))
        != entry.configuration["source_path"]
    ):
        raise PublicationError("Source mapping changed; do not publish this frozen plan")
    version = await db.get(
        Version,
        entry.version_id,
        with_for_update={"read": True} if lock else None,
        populate_existing=True,
    )
    if version_revision(version) != entry.expected_metadata["version_revision"]:
        raise PublicationError("Catalog version identity changed; this import needs review")
    conflicts = await db.scalar(
        select(ProviderObject.id)
        .where(
            ProviderObject.version_id == version.id, ProviderObject.match_status == "needs-review"
        )
        .limit(1)
    )
    if conflicts:
        raise PublicationError("Resolve this catalog version's metadata conflict first")
    try:
        from app.importing.automatic import publication_authority

        if not entry.published_at:
            await publication_authority(db, run.id, lock=lock)
        await download_reviews.validate_inspection(
            db, plan.inspection_id, destination_id=destination.id, version=version, lock=lock
        )
    except HTTPException as error:
        raise PublicationError(str(error.detail)) from error
    return run, destination, integration, library


class RenameGuard:
    def __init__(self, loop, entry_id, token):
        self.loop, self.entry_id, self.token = loop, entry_id, token
        self.db = None

    async def enter(self):
        self.db = session_factory()()
        try:
            await self.db.begin()
            entry = await self.db.get(ImportEntry, self.entry_id)
            _, _, _, library = await context(self.db, entry, self.token, lock=True)
            if await already_owned(self.db, entry.version_id, library.id):
                raise AlreadyOwned("This version became available before publication")
        except BaseException:
            await self.db.rollback()
            await self.db.close()
            self.db = None
            raise

    async def leave(self):
        if self.db:
            try:
                await self.db.rollback()  # Guard carries locks, never optimistic state writes.
            finally:
                await self.db.close()
                self.db = None

    @contextmanager
    def hold(self):
        # The event loop stays alive while the shielded filesystem thread finishes.
        asyncio.run_coroutine_threadsafe(self.enter(), self.loop).result()
        try:
            yield
        finally:
            asyncio.run_coroutine_threadsafe(self.leave(), self.loop).result()


def verify_published_media(spec):
    with directory(spec.destination_root) as root, beneath(root, spec.folder, folder=True) as item:
        for file in spec.files:
            with beneath(item, file.name) as media:
                if digest(media, time.monotonic() + 300) != file.sha256:
                    raise PublicationError("Published media changed; library confirmation is held")


def matches(entry, item):
    config, metadata = entry.configuration["destination"], entry.expected_metadata
    folder = str(PurePosixPath(config["backend_path"]) / entry.specification["folder"])
    if item.path != folder:
        return False
    spec = PublicationSpec.model_validate(entry.specification)
    selected = {
        str(PurePosixPath(folder) / file.name): file.identity["size"] for file in spec.files
    }
    media = {file.path: file.size for file in item.library_files if file.format in AUDIO | EBOOK}
    if (
        media != selected
        or item.missing
        or item.invalid
        or not getattr(item, "full_" + metadata["medium"])
    ):
        raise PublicationError("ABS item boundaries or media files differ from the frozen import")
    if normalized(item.title) != normalized(metadata["title"]):
        raise PublicationError("ABS title differs from the exported title")
    if expected_order := metadata.get("audio_order"):
        indices = [file.playback_index for file in item.audio]
        if (
            any(index is None for index in indices)
            or len(set(indices)) != len(indices)
            or [file.path for file in sorted(item.audio, key=lambda file: file.playback_index)]
            != expected_order
        ):
            raise PublicationError(
                "ABS playback order differs from the reviewed disc and track order"
            )
    for key in ("authors", "narrators"):
        expected = metadata[key] if key == "authors" or metadata["medium"] == "audio" else []
        if expected and sorted(map(normalized, expected)) != sorted(
            map(normalized, getattr(item, key))
        ):
            raise PublicationError(f"ABS {key} differ from the exported metadata")
    year = metadata["edition_year" if metadata["medium"] == "ebook" else "recording_year"]
    if year and year != item.year:
        raise PublicationError("ABS publication year differs from the exported version")
    if metadata.get("language") and normalized(metadata["language"]) != normalized(
        item.language or ""
    ):
        raise PublicationError("ABS language differs from the exported version")
    if metadata.get("series") and not any(
        series.get("name") == metadata["series"]
        and (not metadata.get("sequence") or str(series.get("sequence")) == metadata["sequence"])
        for series in item.series
    ):
        raise PublicationError("ABS series metadata differs from the export")
    return True


async def prepare_cover(entry_id, token):
    async with session_factory()() as db:
        entry = await db.get(ImportEntry, entry_id)
        await context(db, entry, token)
        source = entry.expected_metadata.get("cover_source")
        if entry.cover_export is not None or not source or entry.published_at:
            return PublicationSpec.model_validate(entry.specification)
    try:
        content = await fetch_cover(source)
        cover = {
            "state": "prepared",
            "message": "Selected catalog cover prepared for initial export",
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    except CoverError as error:
        content = None
        cover = {"state": "unavailable", "message": f"No cover exported: {error}"}
    async with session_factory()() as db, db.begin():
        current = await db.get(ImportEntry, entry_id)
        run, _, _, _ = await context(db, current, token, lock=True)
        spec = PublicationSpec.model_validate(current.specification)
        if current.cover_export is None:
            if content:
                spec = PublicationSpec.model_validate(
                    {
                        **spec.model_dump(mode="json"),
                        "binary_sidecars": {"cover.jpg": base64.b64encode(content).decode("ascii")},
                    }
                )
            current.specification = spec.model_dump(mode="json")
            current.cover_export = cover
            db.add(
                AuditEvent(
                    actor_id=run.owner_id,
                    action="organization.cover.prepared",
                    entity_id=current.id,
                    detail={"state": cover["state"], "sha256": cover.get("sha256")},
                )
            )
        return spec


def observe_cover(spec):
    if not spec.binary_sidecars:
        return None
    try:
        with (
            directory(spec.destination_root) as root,
            beneath(root, spec.folder, folder=True) as item,
            beneath(item, "cover.jpg") as file,
        ):
            return digest(file, time.monotonic() + 15)
    except (OSError, ValueError):
        return None  # External artwork changes do not invalidate the book's media.


async def find_item(adapter, entry, library_external_id):
    page, expected_total, found = 0, None, []
    while True:
        rows, total = await adapter.page(library_external_id, page)
        if expected_total is not None and total != expected_total:
            raise PublicationError("ABS inventory changed during confirmation; retry detection")
        expected_total = total
        for item in await adapter.expanded([row["id"] for row in rows]) if rows else []:
            if item.library_id != library_external_id:
                raise PublicationError("ABS item moved during confirmation")
            if matches(entry, item):
                found.append(item)
        if (page + 1) * adapter.page_size >= total:
            break
        page += 1
    if len(found) > 1:
        raise PublicationError("ABS reports duplicate items for this import folder")
    if not found:
        return None
    current = await adapter.item(found[0].id)
    if current.library_id != library_external_id or not matches(entry, current):
        raise PublicationError("ABS item changed during confirmation")
    return current


async def finish_state(entry_id, token, state, message, *, receipt=None):
    async with session_factory()() as db, db.begin():
        entry = await db.get(ImportEntry, entry_id, with_for_update=True)
        if entry.run_token != token:
            return
        operation = await db.get(Operation, entry.operation_id)
        entry.state, entry.message, entry.run_token = state, message, None
        if receipt:
            entry.receipt = receipt
        if state == "skipped":
            entry.reserved = False
        entry.next_check_at = (
            datetime.now(UTC) + timedelta(minutes=1) if state == "awaiting-library" else None
        )
        operation.status = (
            "completed" if state in {"confirmed", "skipped", "awaiting-library"} else "failed"
        )
        operation.message = message


async def execute(operation_id: UUID, *, client_factory=None, checkpoint=lambda _: None):
    client_factory = client_factory or Audiobookshelf
    token = uuid4()
    async with session_factory()() as db, db.begin():
        operation = await db.get(Operation, operation_id)
        if not operation or operation.kind != "organization.publish":
            return
        entry = await db.get(ImportEntry, UUID(operation.payload["entry_id"]), with_for_update=True)
        if entry.state in {"confirmed", "skipped", "held", "cancel-held", "cancelled"}:
            return
        cancelling = entry.state == "cancelling"
        entry_id = entry.id
        if not cancelling:
            entry.run_token = token
            entry.state = "awaiting-library" if entry.published_at else "publishing"
            operation.status, operation.message = "running", "Checking this book's import state"
    if cancelling:
        from app.importing.cancellation import execute as cancel

        await cancel(operation_id, checkpoint=checkpoint)
        return
    try:
        async with session_factory()() as db:
            entry = await db.get(ImportEntry, entry_id)
            _, _, integration, library = await context(db, entry, token)
            secret = decrypt_secrets(integration.encrypted_secrets)["token"]
            url, external_library = integration.base_url, library.external_id
            spec = PublicationSpec.model_validate(entry.specification)
        async with client_factory(url, secret) as adapter:
            capabilities = await verify_backend(
                adapter,
                external_library,
                entry.configuration["destination"]["backend_path"],
                spec.destination_root,
                entry.expected_metadata["medium"],
            )
            if not entry.published_at:
                spec = await prepare_cover(entry_id, token)
                entry.specification = spec.model_dump(mode="json")
                guard = RenameGuard(asyncio.get_running_loop(), entry_id, token)
                task = asyncio.create_task(
                    asyncio.to_thread(
                        publish_item, spec, checkpoint=checkpoint, publication_guard=guard.hold
                    )
                )
                try:
                    receipt = await asyncio.shield(task)
                except asyncio.CancelledError:
                    await task
                    raise
                checkpoint("published-before-database")
                async with session_factory()() as db, db.begin():
                    current = await db.get(ImportEntry, entry_id, with_for_update=True)
                    if current.run_token != token:
                        return
                    current.receipt, current.published_at = receipt, datetime.now(UTC)
                    current.state, current.message = (
                        "awaiting-library",
                        "Published; awaiting ABS item confirmation",
                    )
                    current.next_check_at = datetime.now(UTC) + timedelta(minutes=1)
                    db.add(
                        AuditEvent(
                            actor_id=operation.owner_id,
                            action="organization.item.published",
                            entity_id=current.id,
                        )
                    )
            if capabilities["scan_capable"]:
                await adapter.scan(external_library)
            await asyncio.to_thread(verify_published_media, spec)
            item = await find_item(adapter, entry, external_library)
            if item is None:
                async with session_factory()() as db:
                    current = await db.get(ImportEntry, entry_id)
                    overdue = current.published_at and datetime.now(
                        UTC
                    ) - current.published_at > timedelta(minutes=30)
                await finish_state(
                    entry_id,
                    token,
                    "held" if overdue else "awaiting-library",
                    "ABS has not detected the expected item; check the library and retry detection"
                    if overdue
                    else "Published; waiting for Audiobookshelf to detect the complete item",
                )
                return
            observed_cover = await asyncio.to_thread(observe_cover, spec)
            async with session_factory()() as db, db.begin():
                current = await db.get(ImportEntry, entry_id)
                _, _, integration, library = await context(db, current, token, lock=True)
                version = await db.get(Version, current.version_id)
                namespace = f"abs:{integration.id}"
                link = await db.scalar(
                    select(ProviderObject)
                    .where(
                        ProviderObject.provider == namespace,
                        ProviderObject.kind == f"item:{version.medium}",
                        ProviderObject.external_id == item.id,
                    )
                    .with_for_update()
                )
                if link and link.manual_lock and link.version_id != version.id:
                    raise PublicationError(
                        "A manual library match conflicts with this imported version"
                    )
                if not link:
                    link = ProviderObject(
                        provider=namespace, kind=f"item:{version.medium}", external_id=item.id
                    )
                    db.add(link)
                link.work_id, link.version_id, link.manual_lock, link.match_status = (
                    version.work_id,
                    version.id,
                    True,
                    "matched",
                )
                link.snapshot = item.model_dump(mode="json")
                await db.flush()
                await apply_item(db, library, item, library.generation, integration.id, {item.id})
                await db.flush()
                asset = await db.scalar(
                    select(LibraryAsset).where(
                        LibraryAsset.library_id == library.id,
                        LibraryAsset.external_id == item.id,
                        LibraryAsset.medium == version.medium,
                    )
                )
                if not asset or not asset.full_content or asset.version_id != version.id:
                    raise PublicationError(
                        "ABS observation did not produce the intended full library asset"
                    )
                if version.medium == "ebook":
                    # A reviewed ebook group may contain several complete formats.
                    # The exact file set was checked by matches; ABS exposes only
                    # one of those as its primary ebookFile.
                    selected_paths = set(
                        current.expected_metadata.get("ebook_media_paths")
                        or [file.path for file in item.ebook]
                    )
                    asset.files = [
                        {**file.model_dump(), "import_verified": True}
                        for file in item.library_files
                        if file.path in selected_paths and file.format in EBOOK
                    ]
                current.asset_id, current.confirmed_at = asset.id, datetime.now(UTC)
                if current.cover_export and current.cover_export["state"] == "prepared":
                    selected = item.cover_path == str(
                        PurePosixPath(current.configuration["destination"]["backend_path"])
                        / spec.folder
                        / "cover.jpg"
                    )
                    unchanged = observed_cover == current.cover_export["sha256"]
                    current.cover_export = {
                        **current.cover_export,
                        "backend_selected": selected,
                        "unchanged": unchanged,
                        "message": "Selected cover detected in Audiobookshelf"
                        if selected and unchanged
                        else (
                            "Artwork changed or ABS selected another cover; "
                            "the initial export will not overwrite it"
                        ),
                    }
                current.state, current.message, current.run_token, current.next_check_at = (
                    "confirmed",
                    "Available in Audiobookshelf",
                    None,
                    None,
                )
                stored_operation = await db.get(Operation, operation_id)
                stored_operation.status, stored_operation.message = "completed", current.message
                # Enqueue in this transaction; the reconciler acquires work locks
                # afterward, never in reverse order under import publication locks.
                from app.jobs.queue import enqueue

                await enqueue(db, "acquisition.fulfillment", work_id=str(version.work_id))
                db.add(
                    AuditEvent(
                        actor_id=operation.owner_id,
                        action="organization.item.confirmed",
                        entity_id=current.id,
                        detail={"asset_id": str(asset.id)},
                    )
                )
    except Superseded:
        return
    except AlreadyOwned as error:
        await finish_state(entry_id, token, "skipped", str(error))
    except PublicationBusy:
        raise
    except (PublicationError, AdapterError, OSError, ValueError, InvalidToken, KeyError) as error:
        message = (
            str(error)[:500]
            if isinstance(error, (PublicationError, AdapterError))
            else "Import failed; check source, mounts, credentials and permissions before retrying"
        )
        transient = isinstance(error, AdapterError) and error.kind in {
            FailureKind.UNAVAILABLE,
            FailureKind.TIMEOUT,
            FailureKind.RATE_LIMIT,
            FailureKind.UNCERTAIN,
        }
        async with session_factory()() as db:
            current = await db.get(ImportEntry, entry_id)
            waiting = bool(
                transient
                and current.published_at
                and datetime.now(UTC) - current.published_at < timedelta(minutes=30)
            )
        await finish_state(entry_id, token, "awaiting-library" if waiting else "held", message)
