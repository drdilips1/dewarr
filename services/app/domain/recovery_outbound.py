"""Review saved Hardcover intents against current membership, without sending writes."""

import json
from datetime import UTC, datetime
from functools import partial
from uuid import UUID, uuid4

from fastapi import HTTPException

from app.adapters.hardcover_writeback import Observation, positive
from app.db.models import (
    AuditEvent,
    ListWritebackLease,
    ListWritebackPolicy,
    Operation,
    RecoveryFinding,
)
from app.db.session import session_factory
from app.domain import list_writeback as writes
from app.domain import recovery_reconciliation as reviews
from app.domain.operations import transaction_lock
from app.domain.recovery_scans import ScanHeld, context, digest
from app.security import decrypt_secrets

KIND = reviews.OUTBOUND_KIND


def target(payload):
    """Use the original command target, never a newly configured subscription."""
    try:
        for key in ("remote_owner_id", "external_list_id", "book_id"):
            positive(payload[key])
        UUID(payload["list_id"])
        if type(payload["desired"]) is not bool:
            raise ValueError
        base = Observation.model_validate_json(json.dumps(payload["base"]))
        if (base.owner_id, base.list_id, base.book_id) != (
            payload["remote_owner_id"],
            payload["external_list_id"],
            payload["book_id"],
        ):
            raise ValueError
        attempt = payload.get("pending_attempt")
        if attempt is not None:
            if not isinstance(attempt, dict):
                raise ValueError
            if attempt["action"] != ("add" if payload["desired"] else "remove"):
                raise ValueError
            if attempt["action"] == "remove":
                positive(attempt["entry_id"])
                if attempt["entry_id"] not in {entry.id for entry in base.memberships}:
                    raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ScanHeld(
            "Saved outbound target or attempt is incomplete; retain it for review"
        ) from None
    return payload["remote_owner_id"], payload["external_list_id"], payload["book_id"]


def resolution(payload, current):
    if target(payload) != (current.owner_id, current.list_id, current.book_id):
        raise ScanHeld("Current Hardcover account or list differs from the original command")
    attempt = payload.get("pending_attempt")
    if payload["desired"] == bool(current.memberships):
        return {
            "outcome": "desired-observed",
            "clear_attempt": True,
            "message": "Desired membership is currently visible; "
            "this does not prove which actor changed it",
        }
    if (
        attempt
        and attempt["action"] == "remove"
        and attempt["entry_id"] not in {entry.id for entry in current.memberships}
    ):
        return {
            "outcome": "attempt-observed",
            "clear_attempt": True,
            "message": "The exact attempted membership is absent; "
            "other memberships remain and need owner review",
        }
    return {
        "outcome": "uncertain" if attempt else "difference-held",
        "clear_attempt": False,
        "message": "The sent change remains unconfirmed; preserve its attempt and do not replay it"
        if attempt
        else "Current membership differs; no restored command can authorize replay",
    }


async def read_membership(inputs, operation, pulse):
    p = operation["payload"]
    target(p)
    owner = next((r for r in inputs["users"] if r["id"] == operation["owner_id"]), None)
    account = next(
        (r for r in inputs["catalog_accounts"] if r["user_id"] == operation["owner_id"]), None
    )
    if (
        not owner
        or not owner["active"]
        or owner["role"] == "viewer"
        or not account
        or not account["enabled"]
    ):
        raise ScanHeld("The original list owner's current Hardcover access is unavailable")
    await pulse()
    current = await writes.fetch_membership(
        operation["owner_id"],
        account["generation"],
        decrypt_secrets(account["encrypted_token"])["token"],
        p["external_list_id"],
        p["book_id"],
    )
    resolution(p, current)  # Enforce original remote owner even after credential rotation.
    return current


async def observe(inputs, writer, operation):
    p = operation["payload"]
    try:
        target(p)
    except ScanHeld as error:
        await writer.add(
            "lists",
            "needs-review",
            "Saved outbound list change",
            str(error),
            entity_id=operation["id"],
            evidence={"saved_status": operation["status"]},
        )
        return
    current = await read_membership(inputs, operation, writer.pulse)
    result = resolution(p, current)
    await writer.add(
        "lists",
        "outbound-ready",
        f"Hardcover book {p['book_id']} · list {p['external_list_id']}",
        result["message"],
        entity_id=operation["id"],
        evidence={
            "outbound_schema": 1,
            "observation": current.model_dump(mode="json"),
            "saved_status": operation["status"],
            **result,
        },
    )


async def prepare(db, checkpoint, owner_id, scan_id, finding_ids, key):
    old, scan, command = await reviews.review_inputs(
        db, checkpoint, owner_id, scan_id, finding_ids, key, kind=KIND
    )
    if old:
        return old
    items, seen = [], set()
    for finding_id in sorted(finding_ids):
        finding = await db.get(RecoveryFinding, finding_id)
        if (
            not finding
            or finding.scan_id != scan.id
            or finding.domain != "lists"
            or finding.state != "outbound-ready"
            or finding.evidence.get("outbound_schema") != 1
            or not finding.entity_id
            or finding.entity_id in seen
        ):
            raise HTTPException(409, "Choose each verified outbound observation once")
        saved = await db.get(Operation, finding.entity_id)
        if not saved or saved.kind != writes.KIND:
            raise HTTPException(409, "Saved outbound operation is unavailable")
        try:
            current = Observation.model_validate_json(json.dumps(finding.evidence["observation"]))
            decision = resolution(saved.payload, current)
        except (KeyError, ValueError, ScanHeld):
            raise HTTPException(409, "Outbound evidence is invalid; observe again") from None
        seen.add(saved.id)
        items.append(
            {
                "finding_id": str(finding.id),
                "finding_digest": reviews.finding_signature(finding),
                "operation_id": str(saved.id),
                "title": finding.title,
                "observation_digest": digest(current.model_dump(mode="json")),
                "desired": saved.payload["desired"],
                "saved_status": saved.status,
                "pending_attempt": bool(saved.payload.get("pending_attempt")),
                **decision,
            }
        )
    return await reviews.save_review(
        db,
        checkpoint,
        owner_id,
        scan,
        command,
        items,
        key,
        kind=KIND,
        message="Review current outbound outcomes; old commands will not be replayed",
    )


async def fresh_outbound(identifier, token, payload):
    observed = {}
    for item in payload["items"]:
        await reviews.pulse(identifier, token)
        async with session_factory()() as db:
            inputs = await context(db)
        saved = next(
            (row for row in inputs["outbound"] if str(row["id"]) == item["operation_id"]), None
        )
        if not saved:
            raise ScanHeld("The saved outbound operation changed")
        current = await read_membership(inputs, saved, partial(reviews.pulse, identifier, token))
        if digest(current.model_dump(mode="json")) != item["observation_digest"]:
            raise ScanHeld("Hardcover membership changed since review; observe again")
        observed[item["finding_id"]] = current
    return observed


async def record_outcome(db, operation, item, current):
    saved = await db.get(Operation, UUID(item["operation_id"]), with_for_update=True)
    p = dict(saved.payload)
    decision = resolution(p, current)
    before = {"status": saved.status, "pending_attempt": p.get("pending_attempt")}
    now = datetime.now(UTC)
    # Terminal even if ordinary jobs are later recovered. A new owner command is required.
    saved.status = "completed" if decision["outcome"] == "desired-observed" else "attention"
    saved.message = decision["message"]
    saved.payload = {
        **p,
        "reconcile_only": True,
        "pending_attempt": None if decision["clear_attempt"] else p.get("pending_attempt"),
        "last_observation": current.model_dump(mode="json"),
        "recovery_receipt": {
            "review_id": str(operation.id),
            "observed_at": now.isoformat(),
            "outcome": decision["outcome"],
            "before": before,
        },
        **({"confirmed_at": now.isoformat()} if saved.status == "completed" else {}),
    }
    policy = await db.get(ListWritebackPolicy, UUID(p["list_id"]), with_for_update=True)
    if policy:
        policy.enabled = False
        policy.generation += 1
        policy.confirmed_at = None
    key = writes.target(p)
    await transaction_lock(db, f"list-writeback:{key}")
    lease = await db.get(ListWritebackLease, key, with_for_update=True)
    if lease and lease.operation_id == saved.id:
        lease.token, lease.lease_until = uuid4(), now
    db.add(
        AuditEvent(
            actor_id=operation.owner_id,
            action="recovery.outbound.reconciled",
            entity_id=saved.id,
            detail={
                "review_id": str(operation.id),
                "before": before,
                "outcome": decision["outcome"],
                "observation": current.model_dump(mode="json"),
            },
        )
    )
    return {"operation_id": str(saved.id), "outcome": decision["outcome"], "status": saved.status}


async def run(identifier):
    await reviews.run_review(
        identifier,
        kind=KIND,
        read=fresh_outbound,
        apply=record_outcome,
        message="Outbound evidence recorded without sending list changes. "
        "Uncertain outcomes remain held; automation stays paused.",
    )
