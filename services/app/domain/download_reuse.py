"""A fresh authorization joins a known transfer; hash equality never adopts a torrent."""

from fastapi import HTTPException
from sqlalchemy import select

from app.db.models import (
    AcquisitionReservation,
    AcquisitionSelection,
    AuditEvent,
    DownloadAttempt,
    DownloadIdentityClaim,
    DownloadMembership,
    Operation,
)
from app.domain import download_memberships
from app.domain.operations import transaction_lock
from app.jobs.queue import enqueue

STATES = {"queued", "preflight", "downloading", "complete"}


async def candidates(db, selections):
    """Called before any principal/work locks; stabilize membership before reading it."""
    if not selections:
        return []
    rows = list(
        await db.scalars(
            select(DownloadAttempt)
            .join(AcquisitionSelection, AcquisitionSelection.id == DownloadAttempt.selection_id)
            .where(
                DownloadAttempt.owner_id == selections[0].owner_id,
                AcquisitionSelection.artifact_id == selections[0].artifact_id,
                DownloadAttempt.state != "cancelled",
                DownloadAttempt.id.in_(
                    select(DownloadIdentityClaim.attempt_id).where(
                        DownloadIdentityClaim.active.is_(True)
                    )
                ),
            )
            .order_by(DownloadAttempt.id)
        )
    )
    matches = []
    for attempt in rows:
        prior = await db.get(AcquisitionSelection, attempt.selection_id)
        for item in selections:
            try:
                download_memberships.require_same_transfer([prior, item])
                break
            except HTTPException:
                continue
        else:
            continue
        await transaction_lock(db, f"download-members:{attempt.id}")
        await db.refresh(attempt)
        matches.append((attempt, await download_memberships.for_attempt(db, attempt.id)))
    return matches


async def join(db, user, selections, available, key):
    from app.domain import download_attempts

    matching = []
    for attempt, prior in available:
        try:
            download_memberships.require_same_transfer([prior[0], *selections])
            matching.append((attempt, prior))
        except HTTPException:
            continue
    if not matching:
        return None
    if len(matching) != 1:
        raise HTTPException(
            409, "Several saved transfers match this route; review their identities"
        )
    attempt, prior = matching[0]
    await db.refresh(attempt, with_for_update=True)
    if attempt.state not in STATES:
        raise HTTPException(409, "Reconcile the existing transfer before attaching another book")
    if len(prior) + len(selections) > 100:
        raise HTTPException(409, "The saved transfer has reached its 100-book request limit")
    # The original operation is historical. This separate receipt is the authority
    # for every appended association and its continuation.
    ids = sorted(str(item.id) for item in selections)
    receipt = await db.scalar(
        select(Operation).where(Operation.owner_id == user.id, Operation.idempotency_key == key)
    )
    if receipt:
        if (
            receipt.kind != "acquisition.download.join"
            or receipt.payload.get("selection_ids") != ids
            or receipt.payload.get("attempt_id") != str(attempt.id)
        ):
            raise HTTPException(409, "This transfer-join command has a different scope")
        return attempt
    for item in selections:
        if item.state != "prepared" or await download_memberships.attempt_for(db, item.id):
            raise HTTPException(409, "This book already has an acquisition in progress")
        await download_attempts.selection_authority(db, item, wanted=True)
    receipt = Operation(
        owner_id=user.id,
        kind="acquisition.download.join",
        idempotency_key=key,
        status="completed",
        message="Authorized books joined the saved transfer; no torrent was added",
        payload={
            "attempt_id": str(attempt.id),
            "selection_ids": ids,
            "prior_selection_ids": sorted(str(item.id) for item in prior),
            "artifact_id": str(selections[0].artifact_id),
            "automatic_operation_ids": [
                item.frozen["automatic_selection"]["operation_id"] for item in selections
            ],
            "external_may_exist": attempt.external_may_exist,
        },
    )
    db.add(receipt)
    await db.flush()
    for item in selections:
        db.add(
            DownloadMembership(
                attempt_id=attempt.id, selection_id=item.id, join_operation_id=receipt.id
            )
        )
        (await db.get(AcquisitionReservation, item.reservation_id)).state = "committed"
        item.state, item.message = (
            "committed",
            "Joined an existing transfer; awaiting library confirmation",
        )
        await enqueue(db, "acquisition.fulfillment", work_id=item.frozen["origin_work_id"])
    await db.flush()
    if attempt.state == "complete":
        from app.importing.reuse import schedule

        await schedule(db, attempt, receipt, selections)
    db.add(
        AuditEvent(
            actor_id=user.id,
            action="acquisition.download.joined",
            entity_id=attempt.id,
            detail={"join_operation_id": str(receipt.id), "selection_ids": ids},
        )
    )
    return attempt
