"""Reviewed authoritative ABS inventory refresh while restore effects stay fenced."""

import asyncio
from datetime import UTC, datetime
from functools import partial
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, update

from app.adapters.audiobookshelf import Audiobookshelf
from app.db.models import (
    AuditEvent,
    Integration,
    InventoryRun,
    Library,
    LibraryAsset,
    RecoveryFinding,
)
from app.db.session import session_factory
from app.domain import inventory
from app.domain import recovery_observers as observers
from app.domain import recovery_reconciliation as reviews
from app.domain.identity import normalized
from app.domain.recovery_scans import ScanHeld
from app.security import decrypt_secrets

KIND = reviews.INVENTORY_KIND


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
            or finding.domain != "library"
            or finding.state != "inventory-ready"
            or not finding.entity_id
            or finding.evidence.get("inventory_schema") != 1
        ):
            raise HTTPException(409, "Choose a completed backend inventory observation")
        integration = await db.get(Integration, finding.entity_id)
        if (
            not integration
            or integration.kind != "audiobookshelf"
            or not integration.enabled
            or integration.id in seen
            or str(integration.id) != finding.evidence.get("integration_id")
        ):
            raise HTTPException(409, "Each enabled backend must appear exactly once")
        seen.add(integration.id)
        items.append(
            {
                "finding_id": str(finding.id),
                "finding_digest": reviews.finding_signature(finding),
                "integration_id": str(integration.id),
                "title": integration.name,
                "connection_signature": reviews.connection_signature(integration),
                "inventory_digest": finding.evidence["inventory_digest"],
                "summary": finding.evidence["summary"],
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
        message="Review refreshing current library evidence; grants and automation stay unchanged",
    )


async def fresh_inventory(identifier, token, payload):
    observed = {}
    for item in payload["items"]:
        await reviews.pulse(identifier, token)
        async with session_factory()() as db:
            integration = await db.get(Integration, UUID(item["integration_id"]))
            if (
                not integration
                or not integration.enabled
                or reviews.connection_signature(integration) != item["connection_signature"]
            ):
                raise ScanHeld("The reviewed media connection changed")
            endpoint = integration.base_url
            secret = decrypt_secrets(integration.encrypted_secrets)["token"]
        async with asyncio.timeout(600), Audiobookshelf(endpoint, secret) as client:
            current = await observers.read_inventory(
                client, partial(reviews.pulse, identifier, token)
            )
        if observers.inventory_signature(current) != item["inventory_digest"]:
            raise ScanHeld("Backend inventory or permissions changed; observe and review again")
        observed[item["finding_id"]] = current
    return observed


async def apply_inventory(db, operation, item, observed):
    integration_id = UUID(item["integration_id"])
    integration = await db.get(Integration, integration_id, with_for_update=True)
    now = datetime.now(UTC)
    libraries = {
        row.external_id: row
        for row in await db.scalars(
            select(Library).where(Library.integration_id == integration_id).with_for_update()
        )
    }
    scope, current = observed["scope"], observed["items"]
    locations = {
        (record.id, medium): library_id
        for library_id, records in current.items()
        for record in records
        for medium in ("ebook", "audio")
        if getattr(record, medium)
    }
    all_ids = {record.id for records in current.values() for record in records}
    affected = []
    for info in sorted(observed["libraries"], key=lambda row: row["id"]):
        library = libraries.get(info["id"])
        if not library:
            library = Library(
                integration_id=integration_id,
                external_id=info["id"],
                name=info["name"],
                accessible=False,
                generation=0,
            )
            db.add(library)
            await db.flush()
        same_scope = library.scope_fingerprint == scope
        library.generation += 1
        library.name = info["name"]
        # Preserve explicit local suppression even when ABS still returns that item.
        suppressed = set(
            await db.scalars(
                select(LibraryAsset.id).where(
                    LibraryAsset.library_id == library.id,
                    LibraryAsset.state == "intentionally-removed",
                )
            )
        )
        for record in sorted(current[info["id"]], key=lambda row: (normalized(row.title), row.id)):
            await inventory.apply_item(
                db, library, record, library.generation, integration_id, all_ids
            )
        await db.flush()
        for asset in await db.scalars(
            select(LibraryAsset).where(LibraryAsset.library_id == library.id)
        ):
            if asset.id in suppressed:
                asset.state = "intentionally-removed"
            elif asset.seen_generation != library.generation:
                destination = locations.get((asset.external_id, asset.medium))
                if destination and destination != library.external_id:
                    asset.state, asset.missing_since = "moved", None
                elif not same_scope:
                    asset.state = "scope-unavailable"
                else:
                    # Missing media is not an instruction to replace it. Ordinary
                    # acquisition holds suspected/previously confirmed absence.
                    if asset.state != "missing-confirmed":
                        asset.state = "missing-suspected"
                    asset.missing_since = asset.missing_since or now
        library.scope_fingerprint, library.accessible = scope, True
        library.last_complete_sync = now
        affected.append(str(library.id))
    for external, library in libraries.items():
        if external in current:
            continue
        library.accessible = False
        await db.execute(
            update(LibraryAsset)
            .where(
                LibraryAsset.library_id == library.id,
                LibraryAsset.state != "intentionally-removed",
            )
            .values(state="scope-unavailable")
        )
        affected.append(str(library.id))
    # A restored collecting run/lease cannot publish its earlier staged snapshot.
    await db.execute(
        update(InventoryRun)
        .where(InventoryRun.integration_id == integration_id, InventoryRun.status == "collecting")
        .values(status="interrupted", completed_at=now)
    )
    db.add(
        InventoryRun(
            integration_id=integration_id,
            operation_id=operation.id,
            credential_generation=integration.credential_generation,
            status="completed",
            completed_at=now,
        )
    )
    integration.lease_token, integration.lease_until, integration.next_sync_at = None, None, None
    integration.status, integration.last_error = "connected", None
    integration.last_success_at = now
    integration.capabilities = observed["capabilities"].model_dump(mode="json")
    db.add(
        AuditEvent(
            actor_id=operation.owner_id,
            action="recovery.inventory.reconciled",
            entity_id=integration_id,
            detail={
                "review_id": str(operation.id),
                "finding_id": item["finding_id"],
                "library_ids": affected,
                "summary": item["summary"],
                "scope_fingerprint": scope,
            },
        )
    )
    return {
        "integration_id": str(integration_id),
        "library_ids": affected,
        "summary": item["summary"],
    }


async def run(identifier):
    await reviews.run_review(
        identifier,
        kind=KIND,
        read=fresh_inventory,
        apply=apply_inventory,
        message="Current inventory recorded. Run fresh observations before further review; "
        "downloads, imports, lists and automation remain paused",
    )
