"""Reviewed retirement of historical request approvals and acquisition controllers."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from app.db.models import (
    AuditEvent,
    ListAcquisitionBook,
    ListAcquisitionPolicy,
    Operation,
    RecoveryFinding,
)
from app.domain import recovery_automation as automation
from app.domain import recovery_reconciliation as reviews

KIND = reviews.COMMAND_KIND
COMMAND_KINDS = {
    "lists.requests",
    "series.requests",
    "series.acquire",
    "lists.acquire",
    "lists.policy-preview",
}


def eligible(row):
    if row["kind"] not in COMMAND_KINDS or row["payload"].get("recovery_retirement"):
        return False
    if row["kind"] == "series.acquire":
        return bool(row["payload"].get("enabled")) or row["status"] in {"queued", "running"}
    return row["status"] not in {"completed", "cancelled"}


def command_summary(row):
    return {
        "kind": row["kind"],
        "saved_state": row["status"],
        "action": "pause-controller" if row["kind"] == "series.acquire" else "retire-command",
    }


async def observe(inputs, writer):
    await automation.observe(inputs, writer)
    lists = {str(row["id"]): row for row in inputs["book_lists"]}
    labels = {
        "lists.requests": "List request batch",
        "series.requests": "Series request batch",
        "series.acquire": "Series acquisition",
        "lists.acquire": "List acquisition check",
        "lists.policy-preview": "List activation preview",
    }
    for row in inputs["list_operations"]:
        if eligible(row):
            list_id = row["payload"].get("command", {}).get("list_id")
            name = lists.get(list_id, {}).get("name") or row["payload"].get("series", {}).get(
                "name"
            )
            title = labels[row["kind"]] + (" · " + name if name else "")
            await writer.add(
                "review",
                "command-ready",
                title,
                "Retire this saved approval or controller; existing wanted books stay intact",
                entity_id=row["id"],
                evidence={"command_schema": 1, "entity_type": "operation", **command_summary(row)},
            )
    for policy in inputs["list_acquisition_policies"]:
        if policy["active"]:
            title = lists.get(str(policy["list_id"]), {}).get("name", "Detached acquisition policy")
            await writer.add(
                "review",
                "command-ready",
                title,
                "Pause this acquisition policy; existing wanted books and reservations stay intact",
                entity_id=policy["id"],
                evidence={
                    "command_schema": 1,
                    "entity_type": "policy",
                    "kind": "lists.acquisition-policy",
                    "saved_state": "active",
                    "action": "pause-policy",
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
            or finding.domain != "review"
            or finding.state not in {"command-ready", "automation-ready"}
            or finding.evidence.get("command_schema") != 1
            or not finding.entity_id
            or (finding.evidence.get("entity_type"), finding.entity_id) in seen
        ):
            raise HTTPException(409, "Choose each eligible historical command or policy once")
        category = finding.evidence.get("entity_type")
        if category == "operation":
            row = await db.get(Operation, finding.entity_id)
            if not row or not eligible(
                {"kind": row.kind, "status": row.status, "payload": row.payload}
            ):
                raise HTTPException(409, "The historical command changed; observe again")
        elif category == "policy":
            row = await db.get(ListAcquisitionPolicy, finding.entity_id)
            if not row or not row.active:
                raise HTTPException(409, "The acquisition policy changed; observe again")
        elif category in automation.MODELS:
            await automation.current(db, category, finding.entity_id)
            kind, action, _ = automation.DESCRIPTIONS[category]
            if finding.evidence.get("kind") != kind or finding.evidence.get("action") != action:
                raise HTTPException(409, "The automation review changed; observe again")
        else:
            raise HTTPException(409, "Unsupported command recovery target")
        seen.add((category, finding.entity_id))
        items.append(
            {
                "finding_id": str(finding.id),
                "finding_digest": reviews.finding_signature(finding),
                "entity_id": str(finding.entity_id),
                "title": finding.title,
                **{
                    k: finding.evidence[k] for k in ("entity_type", "kind", "saved_state", "action")
                },
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
        message="Review pausing saved automation or retiring commands; "
        "books and reservations are preserved",
    )


async def read_current(identifier, token, payload):
    # This action only removes authority. The shared final context check binds
    # all selected commands and policies; no external observation is invented.
    await reviews.pulse(identifier, token)
    return {item["finding_id"]: None for item in payload["items"]}


async def record_retirement(db, review, item, unused):
    if item["entity_type"] in automation.MODELS:
        return await automation.pause(db, review, item)
    now = datetime.now(UTC)
    if item["entity_type"] == "policy":
        row = await db.get(ListAcquisitionPolicy, UUID(item["entity_id"]), with_for_update=True)
        before = {
            "active": row.active,
            "revision": row.revision,
            "next_check_at": str(row.next_check_at),
        }
        row.active = False
        row.revision += 1
        # Preserve the required historical due time; the scheduler requires active=True.
        row.message = "Paused during restore review; preview acquisition before reactivating"
        for book in await db.scalars(
            select(ListAcquisitionBook).where(ListAcquisitionBook.policy_id == row.id)
        ):
            book.next_check_at = None
        result = {"entity_id": str(row.id), "state": "paused", "revision": row.revision}
    else:
        row = await db.get(Operation, UUID(item["entity_id"]), with_for_update=True)
        before = {
            "status": row.status,
            "enabled": row.payload.get("enabled"),
            "revision": row.payload.get("revision"),
        }
        payload = dict(row.payload)
        if row.kind == "series.acquire":
            before["next_at"] = payload.get("next_at")
            before["book_schedule"] = {
                key: book.get("next_at") for key, book in payload.get("books", {}).items()
            }
            payload.update(enabled=False, revision=payload.get("revision", 0) + 1, next_at=None)
            payload["books"] = {
                key: {**book, "next_at": None} for key, book in payload.get("books", {}).items()
            }
            row.status = "held"
        else:
            row.status = "cancelled"
        row.message = (
            "Retired during restore review; create a fresh preview. "
            "Existing wanted books remain unchanged"
        )
        row.payload = {
            **payload,
            "recovery_retirement": {
                "review_id": str(review.id),
                "checkpoint_id": review.payload["checkpoint_id"],
                "at": now.isoformat(),
                "before": before,
            },
        }
        result = {"entity_id": str(row.id), "state": row.status}
    db.add(
        AuditEvent(
            actor_id=review.owner_id,
            action="recovery.command.retired",
            entity_id=row.id,
            detail={
                "review_id": str(review.id),
                "entity_type": item["entity_type"],
                "before": before,
                **result,
            },
        )
    )
    return result


async def run(identifier):
    await reviews.run_review(
        identifier,
        kind=KIND,
        read=read_current,
        apply=record_retirement,
        message="Selected commands retired or automation paused. "
        "Existing wanted books and reservations remain; "
        "automation stays paused.",
    )
