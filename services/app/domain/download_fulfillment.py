"""Close request reservations from scoped inventory, preserving external identity."""

from sqlalchemy import or_, select

from app.config import get_settings
from app.db.models import (
    AcquisitionIntent,
    AcquisitionReservation,
    AcquisitionSelection,
    AcquisitionTarget,
    AuditEvent,
    DownloadAttempt,
    DownloadFulfillment,
    FrozenImportPlan,
    ImportEntry,
    ImportRun,
    LibraryAsset,
    User,
)
from app.domain.work_graph import acquisition_lock, family_ids


async def record_satisfaction(db, intent, target, previous_reservation_id):
    """Caller holds the work lock and has just evaluated current grants/inventory."""
    if target.state != "satisfied" or not target.satisfied_asset_id:
        return
    # The original target also repairs pre-migration detached reservations. Never
    # infer historical membership for unrelated requests with similar requirements.
    predicates = [AcquisitionSelection.target_id == target.id]
    if previous_reservation_id:
        predicates.append(AcquisitionSelection.reservation_id == previous_reservation_id)
    pairs = (
        await db.execute(
            select(DownloadAttempt, AcquisitionSelection)
            .join(AcquisitionSelection, DownloadAttempt.selection_id == AcquisitionSelection.id)
            .where(
                AcquisitionSelection.state == "committed",
                DownloadAttempt.external_may_exist.is_(True),
                or_(*predicates),
            )
        )
    ).all()
    for attempt, selection in pairs:
        if await db.scalar(
            select(DownloadFulfillment.id).where(
                DownloadFulfillment.attempt_id == attempt.id,
                DownloadFulfillment.target_id == target.id,
            )
        ):
            continue
        asset = await db.get(LibraryAsset, target.satisfied_asset_id)
        entry_id = None
        if attempt.inspection_id:
            entry_id = await db.scalar(
                select(ImportEntry.id)
                .join(ImportRun, ImportEntry.run_id == ImportRun.id)
                .join(FrozenImportPlan, ImportRun.plan_id == FrozenImportPlan.id)
                .where(
                    FrozenImportPlan.inspection_id == attempt.inspection_id,
                    ImportEntry.asset_id == asset.id,
                    ImportEntry.state == "confirmed",
                )
                .order_by(ImportEntry.created_at, ImportEntry.id)
                .limit(1)
            )
        db.add(
            DownloadFulfillment(
                attempt_id=attempt.id,
                target_id=target.id,
                asset_id=asset.id,
                import_entry_id=entry_id,
                evidence={
                    "reservation_id": str(selection.reservation_id),
                    "intent_id": str(intent.id),
                    "owner_id": str(intent.owner_id),
                    "work_id": str(intent.work_id),
                    "slot": target.slot,
                    "specification": intent.specification,
                    "library_id": str(asset.library_id),
                    "version_id": str(asset.version_id) if asset.version_id else None,
                    "medium": asset.medium,
                    "basis": "imported" if entry_id else "existing-library",
                },
            )
        )
    await db.flush()


async def retire_satisfied(db, work_id):
    """Release only completed, currently satisfied work; torrent claims stay active."""
    from app.domain.acquisition import RequestSpec, assess

    await db.flush()
    pairs = (
        await db.execute(
            select(AcquisitionSelection, DownloadAttempt)
            .join(DownloadAttempt, DownloadAttempt.selection_id == AcquisitionSelection.id)
            .join(AcquisitionReservation)
            .where(
                AcquisitionReservation.work_id.in_(family_ids(work_id)),
                AcquisitionReservation.state == "committed",
                AcquisitionSelection.state == "committed",
                DownloadAttempt.state == "complete",
            )
        )
    ).all()
    for selection, attempt in pairs:
        target = await db.get(AcquisitionTarget, selection.target_id)
        fulfillment = await db.scalar(
            select(DownloadFulfillment).where(
                DownloadFulfillment.attempt_id == attempt.id,
                DownloadFulfillment.target_id == target.id,
            )
        )
        if not fulfillment or target.state != "satisfied":
            continue
        # Another compatible request must finish its own scoped evaluation first.
        if await db.scalar(
            select(AcquisitionTarget.id)
            .where(AcquisitionTarget.reservation_id == selection.reservation_id)
            .limit(1)
        ):
            continue
        intent = await db.get(AcquisitionIntent, selection.intent_id)
        user = await db.get(User, intent.owner_id)
        if not user or not user.active or user.role == "viewer":
            continue
        outcomes = await assess(
            db, user, intent.work_id, RequestSpec.model_validate(intent.specification)
        )
        if not any(
            item["slot"] == target.slot and item["state"] == "satisfied" for item in outcomes
        ):
            continue
        reservation = await db.get(AcquisitionReservation, selection.reservation_id)
        reservation.state = "released"
        selection.state = "fulfilled"
        selection.message = (
            "Request fulfilled from confirmed library inventory; transfer history retained"
        )
        db.add(
            AuditEvent(
                actor_id=user.id,
                action="acquisition.fulfilled",
                entity_id=attempt.id,
                detail={"fulfillment_id": str(fulfillment.id)},
            )
        )
    await db.flush()


async def reconcile_work(db, work_id):
    from app.domain.acquisition import evaluate

    if get_settings().recovery_mode:
        return
    await acquisition_lock(db, work_id)
    intents = (
        await db.scalars(
            select(AcquisitionIntent)
            .where(AcquisitionIntent.work_id.in_(family_ids(work_id)))
            .order_by(AcquisitionIntent.id)
        )
    ).all()
    for intent in intents:
        await evaluate(db, await db.get(User, intent.owner_id), intent)
