"""Durable, one-submission download attempts. Redelivery observes, never re-adds."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select, update

from app.adapters.contracts import AdapterError, FailureKind
from app.adapters.qbittorrent import QbitClient, verify_association
from app.adapters.torrent_descriptor import TorrentDescriptor
from app.config import get_settings
from app.db.models import (
    AcquisitionIntent,
    AcquisitionReservation,
    AcquisitionSelection,
    AcquisitionTarget,
    AuditEvent,
    DownloadAttempt,
    DownloadIdentityClaim,
    DownloadInspection,
    ImportDestination,
    Integration,
    Operation,
    SourceArtifact,
    User,
)
from app.db.session import session_factory
from app.domain.acquisition import RequestSpec, evaluate, validate_request
from app.domain.acquisition_selection import configuration_current, owned_selection
from app.domain.downloaders import SETTINGS_LOCK
from app.domain.operations import transaction_lock
from app.domain.source_artifacts import artifact_bytes, member
from app.domain.work_graph import acquisition_lock
from app.importing.naming import fingerprint
from app.jobs.queue import enqueue
from app.security import decrypt_secrets

LEASE_SECONDS = 240
NETWORK_SECONDS = 180
TERMINAL = {"complete", "cancelled"}


def hashes(selection):
    descriptor = TorrentDescriptor.model_validate(selection.frozen["descriptor"])
    return {value for value in (descriptor.infohash_v1, descriptor.infohash_v2) if value}


def attempt_tag(attempt):
    return "book-search:" + str(attempt.id)


def inspection_path(selection):
    descriptor = selection.frozen["descriptor"]
    paths = [item["path"] for item in descriptor["files"]]
    if len(paths) == 1 and "/" not in paths[0]:
        name = paths[0]
    elif all(path.startswith(descriptor["name"] + "/") for path in paths):
        name = descriptor["name"]
    else:
        raise HTTPException(409, "Torrent files do not have one supported inspection root")
    relative = "/".join(
        part
        for part in (selection.frozen["mapping"]["relative_path"], name)
        if part not in {"", "."}
    )
    if len(relative) > 1024:
        raise HTTPException(409, "Completed download path exceeds the inspection limit")
    return relative


async def locked(db, identifier):
    attempt = await db.get(DownloadAttempt, identifier)
    if not attempt:
        return None, None
    selection = await db.get(AcquisitionSelection, attempt.selection_id)
    await acquisition_lock(db, UUID(selection.frozen["origin_work_id"]))
    await db.refresh(attempt, with_for_update=True)
    await db.refresh(selection)
    return attempt, selection


async def owned_attempt(db, user, identifier):
    row = await db.get(DownloadAttempt, identifier, populate_existing=True)
    if not row or row.owner_id != user.id:
        raise HTTPException(404, "Download attempt not found")
    return row


async def authority(db, selection, *, wanted):
    """Recheck current grants and frozen configuration at the side-effect boundary."""
    if get_settings().recovery_mode:
        raise HTTPException(409, "Downloads are paused for recovery")
    if wanted and not get_settings().download_dispatch_enabled:
        raise HTTPException(409, "New download dispatch is disabled")
    await member(db, selection.owner_id)
    user = await db.get(User, selection.owner_id)
    intent = await db.get(AcquisitionIntent, selection.intent_id)
    if wanted:
        await evaluate(db, user, intent)
        await db.flush()
        target = await db.get(AcquisitionTarget, selection.target_id, populate_existing=True)
        if target.state != "wanted" or target.reservation_id != selection.reservation_id:
            raise HTTPException(409, "The selected target is no longer wanted")
    await transaction_lock(db, "source:mam")
    await transaction_lock(db, SETTINGS_LOCK)
    destination = await db.get(ImportDestination, selection.destination_id, with_for_update=True)
    spec = RequestSpec.model_validate(intent.specification)
    medium = selection.frozen["requirements"]["medium"]
    await validate_request(
        db,
        user,
        intent.work_id,
        spec.model_copy(
            update={
                medium + "_library_id": destination.library_id,
            }
        ),
    )
    if not await configuration_current(db, selection, committed=True):
        raise HTTPException(409, "Saved acquisition settings changed; review the download route")
    artifact = await db.get(SourceArtifact, selection.artifact_id)
    content = artifact_bytes(artifact)
    if (
        artifact.sha256 != selection.frozen["artifact_sha256"]
        or artifact.descriptor != selection.frozen["descriptor"]
    ):
        raise HTTPException(409, "Saved torrent identity changed; inspect the release again")
    if wanted:
        inspection_path(selection)
    return await db.get(Integration, selection.downloader_id), content


async def start(db, user, selection_id, key):
    await transaction_lock(db, f"operation:{user.id}:{key}")
    await member(db, user.id)
    receipt = await db.scalar(
        select(Operation).where(
            Operation.owner_id == user.id,
            Operation.idempotency_key == key,
        )
    )
    if receipt:
        if receipt.kind != "acquisition.download" or receipt.payload.get("selection_id") != str(
            selection_id
        ):
            raise HTTPException(409, "This command key was already used for another operation")
        return await owned_attempt(db, user, UUID(receipt.payload["attempt_id"]))
    if not get_settings().download_dispatch_enabled:
        raise HTTPException(409, "Download dispatch is not enabled for this installation")
    selection = await owned_selection(db, user, selection_id)
    await acquisition_lock(db, UUID(selection.frozen["origin_work_id"]))
    await db.refresh(selection)
    existing = await db.scalar(
        select(DownloadAttempt).where(DownloadAttempt.selection_id == selection.id)
    )
    if existing:
        # Every accepted command key gets its own durable receipt, including aliases.
        db.add(
            Operation(
                owner_id=user.id,
                kind="acquisition.download",
                idempotency_key=key,
                status="completed",
                message="Existing download attempt returned",
                payload={"selection_id": str(selection.id), "attempt_id": str(existing.id)},
            )
        )
        return existing
    if selection.state != "prepared":
        raise HTTPException(409, "Select a current source release before downloading")
    downloader, _ = await authority(db, selection, wanted=True)
    endpoint_key = fingerprint({"url": downloader.base_url.rstrip("/")})
    identities = hashes(selection)
    if not identities:
        raise HTTPException(409, "Torrent identity is required before dispatch")
    # Endpoint-scoped claims also catch two saved connections to the same URL.
    for digest in sorted(identities):
        await transaction_lock(db, f"download-identity:{endpoint_key}:{digest}")
    if await db.scalar(
        select(DownloadIdentityClaim.id)
        .where(
            DownloadIdentityClaim.endpoint_key == endpoint_key,
            DownloadIdentityClaim.torrent_hash.in_(identities),
            DownloadIdentityClaim.active.is_(True),
        )
        .limit(1)
    ):
        raise HTTPException(
            409, "This transfer already has a pending acquisition; resolve it in Activity"
        )
    attempt_id, operation_id = uuid4(), uuid4()
    operation = Operation(
        id=operation_id,
        owner_id=user.id,
        kind="acquisition.download",
        integration_id=downloader.id,
        idempotency_key=key,
        payload={"selection_id": str(selection.id), "attempt_id": str(attempt_id)},
    )
    db.add(operation)
    await db.flush()
    attempt = DownloadAttempt(
        id=attempt_id,
        owner_id=user.id,
        selection_id=selection.id,
        operation_id=operation.id,
        endpoint_key=endpoint_key,
        next_check_at=datetime.now(UTC),
    )
    db.add(attempt)
    await db.flush()
    db.add_all(
        [
            DownloadIdentityClaim(
                attempt_id=attempt.id, endpoint_key=endpoint_key, torrent_hash=digest
            )
            for digest in sorted(identities)
        ]
    )
    reservation = await db.get(AcquisitionReservation, selection.reservation_id)
    reservation.state, selection.state = "committed", "committed"
    selection.message = "Download queued; follow its progress in Activity"
    operation.job_id = await enqueue(db, "acquisition.download", attempt_id=str(attempt.id))
    db.add(AuditEvent(actor_id=user.id, action="acquisition.download.queued", entity_id=attempt.id))
    return attempt


async def record(db, attempt, state, message, *, poll=False):
    attempt.state, attempt.message = state, message
    attempt.run_token, attempt.lease_until = None, None
    attempt.next_check_at = datetime.now(UTC) + timedelta(seconds=60) if poll else None
    operation = await db.get(Operation, attempt.operation_id)
    operation.status = (
        "completed"
        if state in TERMINAL
        else "held"
        if state in {"held", "uncertain"}
        else "running"
    )
    operation.message = message


async def cancel(db, user, identifier):
    await owned_attempt(db, user, identifier)
    attempt, selection = await locked(db, identifier)
    await member(db, user.id)
    if attempt.state == "cancelled":
        return attempt
    if attempt.external_may_exist:
        raise HTTPException(
            409, "Submission may have reached the downloader; reconcile it instead of cancelling"
        )
    await record(db, attempt, "cancelled", "Cancelled before submission; no torrent was removed")
    selection.state, selection.message = "cancelled", attempt.message
    reservation = await db.get(AcquisitionReservation, selection.reservation_id)
    reservation.state = "planned"
    await db.execute(
        update(DownloadIdentityClaim)
        .where(
            DownloadIdentityClaim.attempt_id == attempt.id,
        )
        .values(active=False)
    )
    intent = await db.get(AcquisitionIntent, selection.intent_id)
    await evaluate(db, user, intent)
    db.add(
        AuditEvent(actor_id=user.id, action="acquisition.download.cancelled", entity_id=attempt.id)
    )
    return attempt


async def recheck(db, user, identifier):
    await owned_attempt(db, user, identifier)
    attempt, _ = await locked(db, identifier)
    await member(db, user.id)
    if get_settings().recovery_mode:
        raise HTTPException(409, "Downloads are paused for recovery")
    if attempt.state in TERMINAL:
        return attempt
    now = datetime.now(UTC)
    if (attempt.lease_until and attempt.lease_until > now) or (
        attempt.next_check_at and attempt.next_check_at > now
    ):
        raise HTTPException(409, "A download check is running or cooling down")
    from sqlalchemy import text

    operation = await db.get(Operation, attempt.operation_id)
    status = await db.scalar(
        text("SELECT status::text FROM book_queue.procrastinate_jobs WHERE id=:id"),
        {"id": operation.job_id},
    )
    if status not in {"todo", "doing"}:
        operation.job_id = await enqueue(db, "acquisition.download", attempt_id=str(attempt.id))
    attempt.next_check_at = now + timedelta(seconds=60)
    return attempt


async def find(client, selection, tag):
    found = {}
    for digest in sorted(hashes(selection)):
        for state in await client.find(attempt_tag=tag, torrent_hash=digest):
            found[state.external_id] = state
    return list(found.values())


async def finish_observation(db, attempt, selection, state):
    if not state:
        await record(
            db,
            attempt,
            "uncertain",
            "Submission is not yet visible; only checking for the existing transfer",
            poll=True,
        )
        return
    attempt.observation = state.model_dump(mode="json")
    if not state.completed and not state.reported_complete:
        await record(
            db, attempt, "downloading", "Transfer associated; waiting for complete files", poll=True
        )
        return
    expected = {
        item["path"]: item["size_bytes"] for item in selection.frozen["descriptor"]["files"]
    }
    actual = {item.relative_path: item.size_bytes for item in state.files}
    if expected != actual or state.total_bytes != selection.frozen["descriptor"]["torrent_bytes"]:
        await record(
            db,
            attempt,
            "held",
            "Completed files differ from the inspected torrent; review the downloader",
        )
        return
    await record(
        db,
        attempt,
        "complete",
        "Download complete; file inspection and library confirmation are still required",
    )
    # Existing reviewed import UI is administrator-only. Do not silently elevate
    # a member's source-directory access or manufacture library availability.
    user = await db.get(User, attempt.owner_id)
    if user.role != "admin":
        attempt.message = (
            "Download complete; administrator inspection is required before library import"
        )
        (await db.get(Operation, attempt.operation_id)).message = attempt.message
        return
    await authority(db, selection, wanted=True)
    mapping = selection.frozen["mapping"]
    relative = inspection_path(selection)
    operation = Operation(
        owner_id=user.id,
        kind="organization.inspect",
        idempotency_key="download-inspection:" + str(attempt.id),
    )
    db.add(operation)
    await db.flush()
    inspection = DownloadInspection(
        owner_id=user.id,
        operation_id=operation.id,
        source_key=mapping["source_key"],
        source_path=str(get_settings().import_sources[mapping["source_key"]]),
        relative_path=relative,
    )
    db.add(inspection)
    await db.flush()
    attempt.inspection_id = inspection.id
    operation.job_id = await enqueue(db, "organization.inspect", operation_id=str(operation.id))


async def run(identifier):
    """Persist the irreversible boundary before add; all subsequent runs only find."""
    token = uuid4()
    async with session_factory()() as db, db.begin():
        attempt, selection = await locked(db, identifier)
        if not attempt or attempt.state in TERMINAL:
            return
        now = datetime.now(UTC)
        if attempt.lease_until and attempt.lease_until > now:
            return
        try:
            downloader, content = await authority(
                db, selection, wanted=not attempt.external_may_exist
            )
        except (HTTPException, AdapterError):
            await record(
                db, attempt, "held", "Download access, request or saved settings need review"
            )
            return
        if fingerprint({"url": downloader.base_url.rstrip("/")}) != attempt.endpoint_key:
            await record(
                db,
                attempt,
                "held",
                "Downloader identity changed; existing transfer needs reconciliation",
            )
            return
        credentials, endpoint = decrypt_secrets(downloader.encrypted_secrets), downloader.base_url
        already_submitted = attempt.external_may_exist
        attempt.run_token, attempt.lease_until = token, now + timedelta(seconds=LEASE_SECONDS)
        attempt.state = "uncertain" if already_submitted else "preflight"
        tag = attempt_tag(attempt)
        frozen = dict(selection.frozen)
    # Detached selection contains only frozen metadata; no DB connection over I/O.
    try:
        async with (
            asyncio.timeout(NETWORK_SECONDS),
            QbitClient(endpoint, credentials["username"], credentials["password"]) as client,
        ):
            await client.capabilities()
            states = await find(client, selection, tag)
            if not already_submitted:
                if states:
                    raise AdapterError(
                        FailureKind.UNCERTAIN,
                        "An existing transfer conflicts with this new attempt; it was not adopted",
                    )
                async with session_factory()() as db, db.begin():
                    attempt, current = await locked(db, identifier)
                    if (
                        attempt.run_token != token
                        or attempt.state != "preflight"
                        or attempt.lease_until <= datetime.now(UTC)
                    ):
                        return
                    await authority(db, current, wanted=True)
                    # This sticky marker commits before any mutating request.
                    attempt.external_may_exist, attempt.state = True, "submitting"
                    attempt.message = (
                        "Submission recorded; uncertain outcomes will only be reconciled"
                    )
                    (await db.get(Operation, attempt.operation_id)).message = attempt.message
                receipt = await client.submit(
                    content,
                    attempt_tag=tag,
                    save_path=frozen["downloader"]["save_path"],
                    category=frozen["downloader"]["category"],
                )
                async with session_factory()() as db, db.begin():
                    attempt, _ = await locked(db, identifier)
                    if attempt.run_token != token:
                        return
                    attempt.receipt = receipt.model_dump(mode="json")
                states = await find(client, selection, tag)
            observed = verify_association(
                states,
                tag=tag,
                hashes=hashes(selection),
                save_path=frozen["downloader"]["save_path"],
                category=frozen["downloader"]["category"],
            )
            async with session_factory()() as db, db.begin():
                attempt, current = await locked(db, identifier)
                if attempt.run_token != token:
                    return
                await authority(db, current, wanted=False)
                await finish_observation(db, attempt, current, observed)
                db.add(
                    AuditEvent(
                        actor_id=attempt.owner_id,
                        action="acquisition.download.observed",
                        entity_id=attempt.id,
                        detail={"state": attempt.state},
                    )
                )
    except (AdapterError, HTTPException, TimeoutError) as error:
        async with session_factory()() as db, db.begin():
            attempt, _ = await locked(db, identifier)
            if attempt.run_token != token:
                return
            transient = isinstance(error, TimeoutError) or (
                isinstance(error, AdapterError)
                and error.kind
                in {
                    FailureKind.TIMEOUT,
                    FailureKind.UNAVAILABLE,
                    FailureKind.RATE_LIMIT,
                }
            )
            unknown = attempt.external_may_exist and (
                transient or isinstance(error, AdapterError) and error.kind == FailureKind.UNCERTAIN
            )
            message = (
                str(error)
                if isinstance(error, AdapterError)
                else "Download check timed out"
                if transient
                else "Download access, request or saved settings changed"
            )
            await record(
                db,
                attempt,
                "uncertain" if unknown else "queued" if transient else "held",
                message[:300],
                poll=transient or unknown,
            )
