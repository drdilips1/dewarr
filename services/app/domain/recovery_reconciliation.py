"""Reviewed, freshly verified recovery of existing transfer associations.

Only the local ledger changes. No submit/import/fulfillment job is created, and the
persistent restore checkpoint remains active. Future resume rechecks all authority.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select, text

from app.adapters.contracts import AdapterError
from app.adapters.qbittorrent import QbitClient, QbitState, verify_association
from app.db.models import (
    AcquisitionSelection,
    AuditEvent,
    DownloadAttempt,
    DownloadCapacity,
    DownloadIdentityClaim,
    Integration,
    Operation,
    RecoveryFinding,
    RecoveryScan,
)
from app.db.session import session_factory
from app.domain import capacity, download_attempts
from app.domain.operations import transaction_lock
from app.domain.recovery_scans import ScanHeld, context, digest
from app.domain.recovery_scans import require_checkpoint as scan_checkpoint
from app.jobs.queue import enqueue
from app.jobs.retry import ShelfRetry
from app.security import decrypt_secrets

KIND = "recovery.reconcile"
INVENTORY_KIND = "recovery.inventory"
PUBLICATION_KIND = "recovery.publication"
LIST_KIND = "recovery.lists"
REVIEW_KINDS = (KIND, INVENTORY_KIND, PUBLICATION_KIND, LIST_KIND)
logger = logging.getLogger(__name__)


async def require_checkpoint(db, checkpoint_id, actor_id):
    try:
        return await scan_checkpoint(db, checkpoint_id, actor_id)
    except ScanHeld as error:
        raise HTTPException(409, str(error)) from None


def connection_signature(integration):
    return digest(
        {
            "url": integration.base_url,
            "credentials": integration.encrypted_secrets,
            "generation": integration.credential_generation,
            "configuration": integration.config,
            "enabled": integration.enabled,
        }
    )


def identity_signature(state):
    return digest(
        {
            "external_id": state.external_id,
            "identities": sorted(state.identities),
            "tags": sorted(state.tags),
            "save_path": state.save_path,
            "category": state.category,
            "auto_managed": state.auto_managed,
            "total_bytes": state.total_bytes,
            "files": sorted((f.relative_path, f.size_bytes) for f in state.files),
        }
    )


def finding_signature(finding):
    return digest(
        {
            "scan_id": finding.scan_id,
            "entity_id": finding.entity_id,
            "domain": finding.domain,
            "state": finding.state,
            "title": finding.title,
            "evidence": finding.evidence,
        }
    )


async def require_idle(db, checkpoint_id, *, excluding=None):
    running = list(
        await db.scalars(
            select(Operation).where(
                Operation.kind.in_(REVIEW_KINDS),
                Operation.payload["checkpoint_id"].astext == str(checkpoint_id),
                Operation.status.in_(["queued", "running"]),
            )
        )
    )
    for operation in running:
        if operation.id == excluding:
            continue
        job_status = await db.scalar(
            text("SELECT status::text FROM book_queue.procrastinate_jobs WHERE id=:id"),
            {"id": operation.job_id},
        )
        if job_status in {"todo", "doing"}:
            raise HTTPException(409, "A reviewed recovery action is queued or running")
        operation.status = "held"
        operation.message = "The recovery action stopped; create a fresh observation and review"
        operation.payload = {**operation.payload, "run_token": None, "lease_until": None}


async def load(db, identifier, checkpoint, actor_id, *, lock=False, kind=KIND):
    await require_checkpoint(db, checkpoint.id, actor_id)
    operation = await db.get(Operation, identifier, populate_existing=True, with_for_update=lock)
    if (
        not operation
        or operation.kind != kind
        or operation.owner_id != actor_id
        or operation.payload.get("checkpoint_id") != str(checkpoint.id)
    ):
        raise HTTPException(404, "Recovery review not found")
    return operation


async def current_scan(db, scan_id, checkpoint_id, owner_id):
    await require_checkpoint(db, checkpoint_id, owner_id)
    scan = await db.get(RecoveryScan, scan_id, populate_existing=True)
    newest = await db.scalar(
        select(RecoveryScan.id)
        .where(RecoveryScan.checkpoint_id == checkpoint_id)
        .order_by(RecoveryScan.created_at.desc(), RecoveryScan.id.desc())
        .limit(1)
    )
    if not scan or scan.checkpoint_id != checkpoint_id:
        raise HTTPException(404, "Recovery observation not found")
    if (
        scan.id != newest
        or scan.state != "completed"
        or not scan.finished_at
        or scan.finished_at < datetime.now(UTC) - timedelta(minutes=15)
    ):
        raise HTTPException(409, "Complete a fresh observation before preparing recovery actions")
    try:
        current_context = digest(await context(db))
    except ScanHeld as error:
        raise HTTPException(409, str(error)) from None
    if scan.context_digest != current_context:
        raise HTTPException(409, "Saved context changed; run fresh recovery observations")
    return scan


async def review_inputs(db, checkpoint, owner_id, scan_id, finding_ids, key, *, kind=KIND):
    await transaction_lock(db, f"recovery:{checkpoint.id}")
    await require_checkpoint(db, checkpoint.id, owner_id)
    ordered = sorted(set(finding_ids))
    if len(ordered) != len(finding_ids) or not 1 <= len(ordered) <= 100:
        raise HTTPException(422, "Choose 1 to 100 distinct eligible findings")
    command = {"scan_id": str(scan_id), "finding_ids": [str(i) for i in ordered]}
    old = await db.scalar(
        select(Operation).where(Operation.owner_id == owner_id, Operation.idempotency_key == key)
    )
    if old:
        if (
            old.kind != kind
            or old.payload.get("checkpoint_id") != str(checkpoint.id)
            or old.payload.get("command") != command
        ):
            raise HTTPException(409, "This command key belongs to another operation")
        return old, None, command
    await require_idle(db, checkpoint.id)
    scan = await current_scan(db, scan_id, checkpoint.id, owner_id)
    return None, scan, command


async def prepare(db, checkpoint, owner_id, scan_id, finding_ids, key):
    old, scan, command = await review_inputs(db, checkpoint, owner_id, scan_id, finding_ids, key)
    if old:
        return old
    ordered = sorted(finding_ids)
    items, seen = [], set()
    for finding_id in ordered:
        finding = await db.get(RecoveryFinding, finding_id)
        if (
            not finding
            or finding.scan_id != scan.id
            or finding.domain != "downloads"
            or finding.state != "matched"
            or not finding.entity_id
        ):
            raise HTTPException(409, "Only verified matching saved transfers can be recorded")
        attempt = await db.get(DownloadAttempt, finding.entity_id)
        if not attempt or attempt.id in seen:
            raise HTTPException(409, "Each transfer must appear exactly once in the review")
        selection = await db.get(AcquisitionSelection, attempt.selection_id)
        try:
            integration_id = UUID(finding.evidence["integration_id"])
            states = [QbitState.model_validate(row) for row in finding.evidence["states"]]
        except (KeyError, ValueError, TypeError, AttributeError):
            raise HTTPException(409, "Observation evidence is invalid; run fresh checks") from None
        integration = await db.get(Integration, integration_id)
        if (
            not integration
            or not integration.enabled
            or integration.kind != "qbittorrent"
            or digest({"url": integration.base_url.rstrip("/")}) != attempt.endpoint_key
        ):
            raise HTTPException(409, "The saved downloader connection changed")
        try:
            state = verify_association(
                states,
                tag=download_attempts.attempt_tag(attempt),
                hashes=download_attempts.hashes(selection),
                save_path=selection.frozen["downloader"]["save_path"],
                category=selection.frozen["downloader"]["category"],
            )
        except AdapterError:
            raise HTTPException(
                409, "Observation identity is inconsistent; run fresh checks"
            ) from None
        if not state:
            raise HTTPException(409, "The finding has no current transfer identity")
        seen.add(attempt.id)
        items.append(
            {
                "finding_id": str(finding.id),
                "finding_digest": finding_signature(finding),
                "attempt_id": str(attempt.id),
                "integration_id": str(integration.id),
                "connection_signature": connection_signature(integration),
                "selection_digest": digest(selection.frozen),
                "title": finding.title,
                "saved_state": attempt.state,
                "saved_external_may_exist": attempt.external_may_exist,
                "observed_state": download_attempts.transfer_stage(selection, state)[0],
                "identity_signature": identity_signature(state),
                "external_id": state.external_id,
            }
        )
    return await save_review(
        db,
        checkpoint,
        owner_id,
        scan,
        command,
        items,
        key,
        kind=KIND,
        message="Review recording these existing transfers; automation remains paused",
    )


async def save_review(db, checkpoint, owner_id, scan, command, items, key, *, kind, message):
    plan = {
        "checkpoint_id": str(checkpoint.id),
        "command": command,
        "context_digest": scan.context_digest,
        "expires_at": (scan.finished_at + timedelta(minutes=15)).isoformat(),
        "items": items,
    }
    operation = Operation(
        owner_id=owner_id,
        kind=kind,
        idempotency_key=key,
        status="prepared",
        message=message,
        payload={**plan, "revision": digest(plan)},
    )
    db.add(operation)
    await db.flush()
    return operation


async def require_current_plan(db, operation):
    payload = operation.payload
    reviewed = {
        key: payload[key]
        for key in ("checkpoint_id", "command", "context_digest", "expires_at", "items")
    }
    if digest(reviewed) != payload["revision"]:
        raise HTTPException(409, "The review specification changed; prepare it again")
    if datetime.fromisoformat(payload["expires_at"]) < datetime.now(UTC):
        raise HTTPException(409, "Recovery review expired; observe and review again")
    scan = await current_scan(
        db,
        UUID(payload["command"]["scan_id"]),
        UUID(payload["checkpoint_id"]),
        operation.owner_id,
    )
    if payload["context_digest"] != scan.context_digest:
        raise HTTPException(409, "The reviewed observation context changed")
    for item in payload["items"]:
        for reference in [item, *item.get("additional_findings", [])]:
            finding = await db.get(RecoveryFinding, UUID(reference["finding_id"]))
            if (
                not finding
                or finding.scan_id != scan.id
                or finding_signature(finding) != reference["finding_digest"]
            ):
                raise HTTPException(409, "Observation evidence changed; create a fresh review")


async def accept(db, checkpoint, owner_id, identifier, revision, key, *, kind=KIND):
    await transaction_lock(db, f"recovery:{checkpoint.id}")
    operation = await load(db, identifier, checkpoint, owner_id, lock=True, kind=kind)
    command = {"review_id": str(identifier), "revision": revision}
    receipt = await db.scalar(
        select(Operation).where(Operation.owner_id == owner_id, Operation.idempotency_key == key)
    )
    if receipt:
        if receipt.kind != kind + ".accept" or receipt.payload != command:
            raise HTTPException(409, "This command key belongs to another operation")
        return operation
    if operation.status != "prepared" or operation.payload["revision"] != revision:
        raise HTTPException(409, "This exact review is no longer awaiting approval")
    await require_idle(db, checkpoint.id)
    await require_current_plan(db, operation)
    operation.status = "queued"
    operation.message = "Rechecking current evidence before applying the reviewed recovery action"
    operation.job_id = await enqueue(db, kind, operation_id=str(operation.id))
    db.add(
        Operation(
            owner_id=owner_id,
            kind=kind + ".accept",
            idempotency_key=key,
            status="completed",
            message="Exact recovery review accepted; automation remains paused",
            payload=command,
        )
    )
    db.add(
        AuditEvent(
            actor_id=owner_id,
            action="recovery.reconciliation.accepted",
            entity_id=operation.id,
            detail={"revision": revision},
        )
    )
    return operation


async def pulse(identifier, token):
    async with session_factory()() as db, db.begin():
        operation = await db.get(Operation, identifier, with_for_update=True)
        await require_checkpoint(db, UUID(operation.payload["checkpoint_id"]), operation.owner_id)
        if operation.status != "running" or operation.payload.get("run_token") != str(token):
            raise ScanHeld("The recovery action lease changed")
        operation.payload = {
            **operation.payload,
            "lease_until": (datetime.now(UTC) + timedelta(minutes=2)).isoformat(),
        }


async def fresh_transfers(identifier, token, payload):
    observed = {}
    for item in payload["items"]:
        await pulse(identifier, token)
        async with session_factory()() as db:
            selection = await db.get(
                AcquisitionSelection,
                (await db.get(DownloadAttempt, UUID(item["attempt_id"]))).selection_id,
            )
            attempt = await db.get(DownloadAttempt, UUID(item["attempt_id"]))
            integration = await db.get(Integration, UUID(item["integration_id"]))
            if not integration or not integration.enabled:
                raise ScanHeld("The reviewed downloader connection is unavailable")
            if (
                connection_signature(integration) != item["connection_signature"]
                or digest(selection.frozen) != item["selection_digest"]
                or digest({"url": integration.base_url.rstrip("/")}) != attempt.endpoint_key
            ):
                raise ScanHeld("The reviewed connection or transfer selection changed")
            secrets = decrypt_secrets(integration.encrypted_secrets)
            endpoint = integration.base_url
        async with (
            asyncio.timeout(90),
            QbitClient(endpoint, secrets["username"], secrets["password"]) as client,
        ):
            await client.capabilities()
            found = verify_association(
                await download_attempts.find(
                    client, selection, download_attempts.attempt_tag(attempt)
                ),
                tag=download_attempts.attempt_tag(attempt),
                hashes=download_attempts.hashes(selection),
                save_path=selection.frozen["downloader"]["save_path"],
                category=selection.frozen["downloader"]["category"],
            )
        if not found or identity_signature(found) != item["identity_signature"]:
            raise ScanHeld("Transfer identity, routing or file membership changed since review")
        observed[item["finding_id"]] = found
    return observed


async def record_transfer(db, operation, item, observed):
    attempt, selection = await download_attempts.locked(db, UUID(item["attempt_id"]))
    # Restore a withdrawn identity claim only when no other attempt owns it.
    for identity in sorted(download_attempts.hashes(selection)):
        await transaction_lock(db, f"download-identity:{attempt.endpoint_key}:{identity}")
        claims = list(
            await db.scalars(
                select(DownloadIdentityClaim).where(
                    DownloadIdentityClaim.endpoint_key == attempt.endpoint_key,
                    DownloadIdentityClaim.torrent_hash == identity,
                )
            )
        )
        if any(claim.active and claim.attempt_id != attempt.id for claim in claims):
            raise ScanHeld("Another saved attempt already owns this transfer identity")
        owned = next((claim for claim in claims if claim.attempt_id == attempt.id), None)
        if owned:
            owned.active = True
        else:
            db.add(
                DownloadIdentityClaim(
                    attempt_id=attempt.id,
                    endpoint_key=attempt.endpoint_key,
                    torrent_hash=identity,
                    active=True,
                )
            )
    before = {"state": attempt.state, "external_may_exist": attempt.external_may_exist}
    attempt.external_may_exist = True
    attempt.observation = observed.model_dump(mode="json")
    state, message = download_attempts.transfer_stage(selection, observed)
    if attempt.state == "cancelled" or selection.state == "cancelled":
        state, message = "held", "Existing transfer found for a withdrawn request; keep it held"
    await download_attempts.record(db, attempt, state, message, poll=False)
    await transaction_lock(db, capacity.LOCK)
    reservation = await db.get(DownloadCapacity, attempt.id)
    if not reservation:
        old_operation = await db.get(Operation, attempt.operation_id)
        reservation = DownloadCapacity(
            attempt_id=attempt.id, automatic=bool(old_operation.payload.get("automatic"))
        )
        db.add(reservation)
    # Conservative recovery debit; this does not invent a historical submission timestamp.
    reservation.submitted_at = reservation.submitted_at or datetime.now(UTC)
    reservation.slot_active = state != "complete"
    # Preserve storage reservations until the ordinary capacity/import reconciliation.
    db.add(
        AuditEvent(
            actor_id=operation.owner_id,
            action="recovery.download.reconciled",
            entity_id=attempt.id,
            detail={
                "review_id": str(operation.id),
                "finding_id": item["finding_id"],
                "before": before,
                "after": {"state": state, "external_may_exist": True},
                "capacity_debit_observed_at": datetime.now(UTC).isoformat(),
            },
        )
    )
    return {"attempt_id": str(attempt.id), "state": state, "external_id": observed.external_id}


async def run(identifier):
    await run_review(
        identifier,
        kind=KIND,
        read=fresh_transfers,
        apply=record_transfer,
        message="Selected transfers recorded. Run fresh observations before further review; "
        "imports, lists and automation remain paused",
    )


async def run_review(identifier, *, kind, read, apply, message):
    token = uuid4()
    async with session_factory()() as db, db.begin():
        operation = await db.get(Operation, identifier)
        if not operation or operation.kind != kind or operation.status not in {"queued", "running"}:
            return
        await transaction_lock(db, "recovery:" + operation.payload["checkpoint_id"])
        await db.refresh(operation, with_for_update=True)
        if operation.status not in {"queued", "running"}:
            return
        until = operation.payload.get("lease_until")
        if until and datetime.fromisoformat(until) > datetime.now(UTC):
            raise ShelfRetry(30)
        try:
            await require_current_plan(db, operation)
        except (HTTPException, ScanHeld) as error:
            operation.status = "held"
            operation.message = (
                str(error.detail) if isinstance(error, HTTPException) else str(error)
            )
            return
        operation.status = "running"
        operation.payload = {
            **operation.payload,
            "run_token": str(token),
            "lease_until": (datetime.now(UTC) + timedelta(minutes=2)).isoformat(),
        }
        payload = dict(operation.payload)
    try:
        async with asyncio.timeout(900):
            observed = await read(identifier, token, payload)
        async with session_factory()() as db, db.begin():
            await transaction_lock(db, "recovery:" + payload["checkpoint_id"])
            operation = await db.get(Operation, identifier, with_for_update=True)
            if operation.status != "running" or operation.payload.get("run_token") != str(token):
                return
            await require_current_plan(db, operation)
            results = [
                await apply(db, operation, item, observed[item["finding_id"]])
                for item in payload["items"]
            ]
            operation.status = "completed"
            operation.message = message
            operation.payload = {
                **payload,
                "results": results,
                "applied_at": datetime.now(UTC).isoformat(),
                "run_token": None,
                "lease_until": None,
            }
    except Exception as error:
        if isinstance(error, (HTTPException, ScanHeld, AdapterError)):
            message = str(error.detail) if isinstance(error, HTTPException) else str(error)
        elif isinstance(error, TimeoutError):
            message = "Current evidence verification timed out; no corrections were applied"
        else:
            logger.error("Recovery reconciliation %s failed (%s)", identifier, type(error).__name__)
            message = "Recovery verification failed; no corrections were applied"
        async with session_factory()() as db, db.begin():
            operation = await db.get(Operation, identifier, with_for_update=True)
            if operation.payload.get("run_token") == str(token):
                operation.status, operation.message = "held", message
                operation.payload = {**operation.payload, "run_token": None, "lease_until": None}
