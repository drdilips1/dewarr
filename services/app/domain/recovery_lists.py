"""Reviewed inbound membership baselines; no acquisition or outbound replay."""

from datetime import UTC, datetime
from functools import partial
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, select

from app.db.models import (
    AuditEvent,
    BookList,
    ListAcquisitionBook,
    ListAcquisitionPolicy,
    ListEntry,
    ListObservation,
    ListSubscription,
    ListWritebackPolicy,
    Operation,
    RecoveryFinding,
    User,
)
from app.db.session import session_factory
from app.domain import list_monitoring, list_policies, list_subscriptions
from app.domain import recovery_observers as observers
from app.domain import recovery_reconciliation as reviews
from app.domain.acquisition import deactivate_list_reasons
from app.domain.recovery_scans import ScanHeld, context
from app.domain.work_graph import family_ids
from app.security import decrypt_secrets, encrypt_secrets

KIND = reviews.LIST_KIND


async def current_subscription(db, identifier):
    subscription = await db.get(ListSubscription, identifier)
    item = await db.get(BookList, subscription.list_id) if subscription else None
    owner = await db.get(User, item.owner_id) if item else None
    if (
        not subscription
        or not subscription.enabled
        or subscription.provider not in {"hardcover", "goodreads"}
        or not owner
        or not owner.active
        or owner.role == "viewer"
    ):
        raise HTTPException(409, "The current list subscription or owner's access changed")
    return subscription, item, owner


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
            or finding.state != "list-ready"
            or finding.evidence.get("list_schema") != 1
            or not finding.entity_id
            or finding.entity_id in seen
        ):
            raise HTTPException(409, "Choose each verified list baseline observation once")
        row, item, owner = await current_subscription(db, finding.entity_id)
        if row.provider != finding.evidence["provider"]:
            raise HTTPException(409, "The observed list provider changed")
        seen.add(row.id)
        policy = await db.scalar(
            select(ListAcquisitionPolicy).where(ListAcquisitionPolicy.list_id == item.id)
        )
        writeback = await db.get(ListWritebackPolicy, item.id)
        items.append(
            {
                "finding_id": str(finding.id),
                "finding_digest": reviews.finding_signature(finding),
                "subscription_id": str(row.id),
                "list_id": str(item.id),
                "owner_id": str(owner.id),
                "title": item.name,
                "provider": row.provider,
                "complete": finding.evidence["complete"],
                "membership_digest": finding.evidence["membership_digest"],
                "summary": finding.evidence["summary"],
                "pause_acquisition": bool(policy and policy.active),
                "pause_writeback": bool(writeback and writeback.enabled),
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
        message="Review list membership as a baseline; no catch-up downloads or list writes",
    )


async def fresh_lists(identifier, token, payload):
    observed = {}
    for item in payload["items"]:
        await reviews.pulse(identifier, token)
        async with session_factory()() as db:
            row, _, _ = await current_subscription(db, UUID(item["subscription_id"]))
            inputs = await context(db)
            subscription = observers.keyed(inputs["list_subscriptions"])[row.id]
        current = await observers.read_shelf(
            inputs, subscription, partial(reviews.pulse, identifier, token)
        )
        if observers.shelf_signature(current) != item["membership_digest"]:
            raise ScanHeld("Current list membership or owner changed; observe and review again")
        observed[item["finding_id"]] = current
    return observed


async def remove_absent_membership(db, owner, subscription, work_id):
    """Preserve local additions and other reasons; defer reservation/availability evaluation."""
    family = family_ids(work_id)
    kept = await db.scalar(
        select(ListObservation.id)
        .where(
            ListObservation.subscription_id == subscription.id,
            ListObservation.work_id.in_(family),
            ListObservation.present.is_(True),
            ListObservation.excluded.is_(False),
        )
        .limit(1)
    )
    if kept:
        return
    await db.execute(
        delete(ListEntry).where(
            ListEntry.list_id == subscription.list_id,
            ListEntry.work_id.in_(family),
            ListEntry.locally_added.is_(False),
        )
    )
    remaining = await db.scalar(
        select(ListEntry.id)
        .where(
            ListEntry.list_id == subscription.list_id,
            ListEntry.work_id.in_(family),
        )
        .limit(1)
    )
    if not remaining:
        await deactivate_list_reasons(db, owner, subscription.list_id, work_id)


async def record_baseline(db, operation, item, observed):
    row, book_list, owner = await current_subscription(db, UUID(item["subscription_id"]))
    await db.refresh(book_list, with_for_update=True)
    await db.refresh(row, with_for_update=True)
    before = {"generation": row.generation, "state": row.state}
    added = await list_subscriptions.apply_records(db, row, owner, observed["records"])
    removed = []
    if observed["complete"]:
        present = {record["external_id"] for record in observed["records"]}
        for observation in await db.scalars(
            select(ListObservation).where(
                ListObservation.subscription_id == row.id,
                ListObservation.present.is_(True),
            )
        ):
            if observation.external_id not in present:
                observation.present = False
                removed.append(observation.work_id)
        await db.flush()
        for work_id in sorted(set(removed)):
            await remove_absent_membership(db, owner, row, work_id)
    now = datetime.now(UTC)
    policy = await db.scalar(
        select(ListAcquisitionPolicy)
        .where(
            ListAcquisitionPolicy.list_id == book_list.id,
        )
        .with_for_update()
    )
    if policy:
        policy.active = False
        policy.revision += 1
        policy.baseline_at = now
        policy.message = "Restored list baseline recorded; preview acquisition before reactivating"
        records = await list_policies.members(db, owner, book_list.id)
        await list_monitoring.reconcile(db, policy, records, now, activation=True)
        for book in await db.scalars(
            select(ListAcquisitionBook).where(
                ListAcquisitionBook.policy_id == policy.id,
            )
        ):
            book.next_check_at = None
            if book.state == "baseline":
                book.message = "Recovered list member; preview acquisition first"
        if policy.operation_id:
            pending = await db.get(Operation, policy.operation_id, with_for_update=True)
            if pending and pending.status in {"queued", "running"}:
                pending.status, pending.message = "attention", policy.message
        policy.operation_id = None
    writeback = await db.get(ListWritebackPolicy, book_list.id, with_for_update=True)
    if writeback:
        writeback.enabled = False
        writeback.generation += 1
        writeback.confirmed_at = None
        # Pending outbound attempts and their original evidence remain untouched.
    if row.operation_id:
        pending = await db.get(Operation, row.operation_id, with_for_update=True)
        if pending and pending.status in {"queued", "running"}:
            pending.status = "attention"
            pending.message = "Membership was rebaselined during recovery; old sync is fenced"
    config = decrypt_secrets(row.encrypted_config)
    if row.provider == "hardcover":
        config.update(
            name=observed["info"]["name"], complete=True, last_count=len(observed["records"])
        )
    else:
        # The next sync must not reuse validators from before the restored baseline.
        config.pop("etag", None)
        config.pop("modified", None)
    row.encrypted_config = encrypt_secrets(config)
    row.generation += 1
    row.state, row.failures = "idle", 0
    row.baseline_at = row.last_success_at = now
    row.run_token = row.lease_until = row.next_sync_at = row.operation_id = None
    row.message = "Recovery baseline recorded; synchronization and acquisition await review"
    result = {
        "list_id": str(book_list.id),
        "new_observations": added,
        "absent_observations": len(removed),
        "complete": observed["complete"],
    }
    db.add(
        AuditEvent(
            actor_id=operation.owner_id,
            action="recovery.list.rebaselined",
            entity_id=book_list.id,
            detail={
                "review_id": str(operation.id),
                "finding_id": item["finding_id"],
                "before": before,
                "generation": row.generation,
                **result,
            },
        )
    )
    return result


async def run(identifier):
    await reviews.run_review(
        identifier,
        kind=KIND,
        read=fresh_lists,
        apply=record_baseline,
        message="List baselines recorded. Recovered additions need explicit acquisition review; "
        "automation and outbound writes remain paused.",
    )
