"""Approve or decline a book request, optionally starting the approver's download."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from app.db.models import AcquisitionIntent, AcquisitionReason, AuditEvent, Operation, User
from app.domain.acquisition import RequestSpec, evaluate
from app.domain.operations import transaction_lock
from app.domain.permissions import MANAGE_REQUESTS, has
from app.domain.work_graph import acquisition_lock

KIND = "request.decision"


def _apply(reasons, status, actor, note):
    now = datetime.now(UTC)
    for reason in reasons:
        reason.approval_status = status
        reason.decided_by = actor.id
        reason.decided_at = now
        reason.decision_note = note


async def approval_download_started(db, work_id) -> bool:
    """True once an approver's download was accepted for this book."""
    return bool(
        await db.scalar(
            select(Operation.id)
            .where(
                Operation.kind == "acquisition.quick-add",
                Operation.status.in_(["queued", "running", "completed"]),
                Operation.payload["approval_dispatch"].astext == "true",
                Operation.payload["command"]["work_id"].astext == str(work_id),
            )
            .limit(1)
        )
    )


async def decide(db, actor, intent_id, status, note, download, expected_status, key):
    if not has(actor, MANAGE_REQUESTS):
        raise HTTPException(403, "You cannot approve or decline requests")
    if status == "declined" and download:
        raise HTTPException(422, "A declined request cannot start a download")
    note = (note or "").strip() or None
    command = {
        "intent_id": str(intent_id),
        "status": status,
        "note": note,
        "download": download,
        "expected_status": expected_status,
    }
    await transaction_lock(db, f"operation:{actor.id}:{key}")
    existing = await db.scalar(
        select(Operation).where(Operation.owner_id == actor.id, Operation.idempotency_key == key)
    )
    if existing:
        if existing.kind != KIND or existing.payload.get("command") != command:
            raise HTTPException(409, "This decision key was already used for another command")
        intent = await db.get(AcquisitionIntent, UUID(existing.payload["intent_id"]))
        return intent, existing.payload["download_started"], existing.payload["download_message"]
    intent = await db.get(AcquisitionIntent, intent_id)
    if not intent:
        raise HTTPException(404, "Request not found")
    await acquisition_lock(db, intent.work_id)
    await db.refresh(actor)
    if not actor.active or not has(actor, MANAGE_REQUESTS):
        raise HTTPException(403, "You cannot approve or decline requests")
    reasons = list(
        await db.scalars(
            select(AcquisitionReason)
            .where(
                AcquisitionReason.intent_id == intent.id,
                AcquisitionReason.active.is_(True),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    matching = [reason for reason in reasons if reason.approval_status == expected_status]
    if not matching:
        raise HTTPException(
            409 if reasons else 404,
            "This request changed; reload it before deciding"
            if reasons
            else "This request is not waiting for a decision",
        )
    owner = await db.get(User, intent.owner_id)
    started, message = False, None
    if status == "approved" and download:
        from app.domain.quick_add import begin

        try:
            async with db.begin_nested():
                _apply(matching, status, actor, note)
                await evaluate(db, owner, intent)
                await db.flush()
                operation = await begin(
                    db,
                    actor,
                    intent.work_id,
                    RequestSpec.model_validate(intent.specification),
                    f"approval-download:{key}",
                    dispatch=True,
                )
            started = operation.status in {"queued", "running"}
            message = operation.message
        except HTTPException as exc:
            # The savepoint restores the request, so a failed download can be tried again.
            message = exc.detail if isinstance(exc.detail, str) else "Download could not start"
            for reason in matching:
                await db.refresh(reason)
    else:
        _apply(matching, status, actor, note)
        await evaluate(db, owner, intent)
        await db.flush()
    recorded = matching[0].approval_status
    db.add(
        AuditEvent(
            actor_id=actor.id,
            action=f"request.{recorded}" if recorded == status else "request.download_failed",
            entity_id=intent.id,
            detail={"note": note, "download_started": started, "owner_id": str(intent.owner_id)},
        )
    )
    db.add(
        Operation(
            owner_id=actor.id,
            kind=KIND,
            idempotency_key=key,
            status="completed",
            payload={
                "command": command,
                "intent_id": str(intent.id),
                "download_started": started,
                "download_message": message,
            },
            message=message or ("Request approved" if status == "approved" else "Request declined"),
        )
    )
    await db.flush()
    return intent, started, message
