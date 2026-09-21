"""Downloader settings and read-only diagnostics; dispatch has a separate lifecycle."""

import asyncio
import math
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.adapters.contracts import AdapterError, FailureKind
from app.adapters.qbittorrent import QbitClient, absolute_path
from app.config import get_settings
from app.db.models import Integration
from app.db.session import session_factory
from app.domain.operations import transaction_lock
from app.domain.source_network import check_actor
from app.security import decrypt_secrets

SETTINGS_LOCK = "downloaders:settings"
TEST_INTERVAL = 2
TEST_TIMEOUT = 60
TEST_LEASE_SECONDS = 90


class DownloadMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    download_root: str = Field(max_length=2000)
    source_key: str = Field(pattern=r"^[a-z0-9_-]{1,60}$")

    @field_validator("download_root")
    @classmethod
    def root(cls, value):
        return absolute_path(value)


def relative_to(path, root):
    try:
        relative = PurePosixPath(path).relative_to(root)
        return "" if str(relative) == "." else str(relative)
    except ValueError:
        return None


def bind_mappings(mappings: list[DownloadMapping], save_path: str) -> list[dict]:
    bound = []
    sources = get_settings().import_sources
    for mapping in mappings:
        root = sources.get(mapping.source_key)
        if not root:
            raise HTTPException(422, "Select a download root configured on the worker")
        if any(
            relative_to(mapping.download_root, previous["download_root"]) is not None
            or relative_to(previous["download_root"], mapping.download_root) is not None
            for previous in bound
        ):
            raise HTTPException(422, "Download path mappings must not overlap")
        bound.append({**mapping.model_dump(), "source_path": str(root)})
    if not any(relative_to(save_path, mapping["download_root"]) is not None for mapping in bound):
        raise HTTPException(422, "The save path must be inside a mapped download root")
    return bound


def mappings_current(row):
    mappings = row.config.get("mappings", [])
    if row.config.get("client_managed") and not any(
        relative_to(row.config.get("save_path", ""), mapping["download_root"]) is not None
        for mapping in mappings
    ):
        return False
    return bool(mappings) and all(
        str(get_settings().import_sources.get(mapping["source_key"])) == mapping["source_path"]
        for mapping in mappings
    )


def mapped_path(row, path):
    path = absolute_path(path)
    if not mappings_current(row):
        raise HTTPException(
            409, "Worker download roots changed. Review and save the path mappings."
        )
    matches = []
    for mapping in row.config["mappings"]:
        relative = relative_to(path, mapping["download_root"])
        if relative is not None:
            matches.append(
                {
                    "download_path": path,
                    "source_key": mapping["source_key"],
                    "relative_path": relative,
                    "worker_path": str(PurePosixPath(mapping["source_path"]) / relative),
                }
            )
    if len(matches) != 1:
        raise HTTPException(422, "The download path does not match one configured root")
    return matches[0]


async def connection_or_404(db, connection_id):
    row = await db.get(Integration, connection_id, populate_existing=True)
    if not row or row.kind != "qbittorrent" or row.owner_id is not None:
        raise HTTPException(404, "Downloader connection not found")
    return row


async def test_connection(user_id, connection_id):
    token = uuid4()
    async with session_factory()() as db, db.begin():
        await transaction_lock(db, SETTINGS_LOCK)
        await check_actor(db, user_id, admin=True)
        row = await connection_or_404(db, connection_id)
        if not row.enabled:
            raise HTTPException(409, "Enable the downloader before testing it")
        now = datetime.now(UTC)
        if row.lease_until and row.lease_until > now:
            raise AdapterError(
                FailureKind.RATE_LIMIT, "A connection test is running.", retry_after=2
            )
        if row.next_sync_at and row.next_sync_at > now:
            raise AdapterError(
                FailureKind.RATE_LIMIT,
                "Wait before testing this downloader again.",
                retry_after=math.ceil((row.next_sync_at - now).total_seconds()),
            )
        generation, endpoint = row.credential_generation, row.base_url
        client_managed, category = row.config.get("client_managed", False), row.config["category"]
        credentials = decrypt_secrets(row.encrypted_secrets)
        row.lease_token, row.lease_until = token, now + timedelta(seconds=TEST_LEASE_SECONDS)
        row.next_sync_at = now + timedelta(seconds=TEST_INTERVAL)
    failure = None
    capabilities = None
    observed_path = None
    try:
        async with (
            asyncio.timeout(TEST_TIMEOUT),
            QbitClient(endpoint, credentials["username"], credentials["password"]) as client,
        ):
            capabilities = await client.capabilities()
            if client_managed:
                observed_path = await client.download_location(category)
    except AdapterError as error:
        failure = error
    except TimeoutError:
        failure = AdapterError(FailureKind.TIMEOUT, "The downloader connection test timed out.")
    # Cancellation/crash leaves a bounded lease. Unlike rotating MAM sessions,
    # a read-only qBit test can be retried after it expires using a fresh login.
    async with session_factory()() as db, db.begin():
        await transaction_lock(db, SETTINGS_LOCK)
        row = await connection_or_404(db, connection_id)
        if row.lease_token != token:
            raise HTTPException(409, "A newer downloader test superseded this result")
        row.lease_token, row.lease_until = None, None
        changed = row.credential_generation != generation or not row.enabled
        if not changed:
            row.status = failure.kind.value if failure else "connected"
            row.last_error = str(failure) if failure else None
            row.capabilities = capabilities.model_dump(mode="json") if capabilities else {}
            if not failure:
                row.last_success_at = datetime.now(UTC)
                if observed_path is not None:
                    # Existing mount bindings remain import evidence, never torrent overrides.
                    mappings = row.config.get("mappings", [])
                    if not mappings:
                        candidates = [
                            (key, str(root))
                            for key, root in get_settings().import_sources.items()
                            if relative_to(observed_path, str(root)) is not None
                        ]
                        if candidates:
                            key, root = max(candidates, key=lambda item: len(item[1]))
                            mappings = [
                                {
                                    "download_root": root,
                                    "source_key": key,
                                    "source_path": root,
                                }
                            ]
                    row.config = {**row.config, "save_path": observed_path, "mappings": mappings}
        if failure:
            row.next_sync_at = datetime.now(UTC) + timedelta(
                seconds=max(60, failure.retry_after or 0)
            )
    async with session_factory()() as db:
        await check_actor(db, user_id, admin=True)
    if changed:
        raise HTTPException(
            409, "Downloader settings changed during the test; test the saved settings"
        )
    if failure:
        raise failure


async def resolve_metadata(user_id, connection_id, magnet, *, expected_generation=None):
    """Bounded read-only metadata inspection sharing the diagnostic connection lease."""
    from app.domain.source_artifacts import member

    token = uuid4()
    async with session_factory()() as db, db.begin():
        await transaction_lock(db, SETTINGS_LOCK)
        await member(db, user_id)
        row = await connection_or_404(db, connection_id)
        if not row.enabled or (
            expected_generation is not None and row.credential_generation != expected_generation
        ):
            raise HTTPException(409, "Downloader settings changed; select its current connection")
        now = datetime.now(UTC)
        if row.lease_until and row.lease_until > now:
            raise AdapterError(
                FailureKind.RATE_LIMIT, "Downloader inspection is busy.", retry_after=2
            )
        if row.next_sync_at and row.next_sync_at > now:
            raise AdapterError(
                FailureKind.RATE_LIMIT,
                "Downloader inspection is cooling down.",
                retry_after=math.ceil((row.next_sync_at - now).total_seconds()),
            )
        generation, endpoint = row.credential_generation, row.base_url
        credentials = decrypt_secrets(row.encrypted_secrets)
        row.lease_token, row.lease_until = token, now + timedelta(seconds=90)
        row.next_sync_at = now + timedelta(seconds=TEST_INTERVAL)
    failure, content = None, None
    try:
        async with (
            asyncio.timeout(60),
            QbitClient(endpoint, credentials["username"], credentials["password"]) as client,
        ):
            content = await client.resolve_magnet(magnet)
    except AdapterError as error:
        failure = error
    except TimeoutError:
        failure = AdapterError(FailureKind.TIMEOUT, "Torrent metadata inspection timed out.")
    async with session_factory()() as db, db.begin():
        await transaction_lock(db, SETTINGS_LOCK)
        row = await connection_or_404(db, connection_id)
        if row.lease_token != token:
            raise HTTPException(409, "Downloader inspection expired; retry current settings")
        row.lease_token, row.lease_until = None, None
        changed = row.credential_generation != generation or not row.enabled
        row.next_sync_at = datetime.now(UTC) + timedelta(
            seconds=max(TEST_INTERVAL, failure.retry_after or 0) if failure else TEST_INTERVAL
        )
        # A torrent lacking peers does not imply the entire downloader is broken.
    async with session_factory()() as db:
        await member(db, user_id)
    if changed:
        raise HTTPException(409, "Downloader changed during metadata inspection; retry")
    if failure:
        raise failure
    return content, generation
