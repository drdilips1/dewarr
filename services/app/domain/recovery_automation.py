"""Explicitly pause saved automation without claiming its external effects ended."""

from uuid import UUID

from fastapi import HTTPException

from app.db.models import (
    AuditEvent,
    AutomaticImportPolicy,
    ListSubscription,
    ListWritebackPolicy,
)

MODELS = {
    "import-policy": AutomaticImportPolicy,
    "subscription": ListSubscription,
    "writeback-policy": ListWritebackPolicy,
}
DESCRIPTIONS = {
    "import-policy": ("organization.automatic-policy", "pause-imports", "Automatic imports"),
    "subscription": ("lists.subscription", "pause-subscription", "List synchronization"),
    "writeback-policy": ("lists.writeback-policy", "pause-writeback", "Hardcover write-back"),
}


async def observe(inputs, writer):
    lists = {str(row["id"]): row for row in inputs["book_lists"]}
    destinations = {str(row["id"]): row for row in inputs["import_destinations"]}
    for category, model in MODELS.items():
        kind, action, label = DESCRIPTIONS[category]
        for row in inputs[model.__tablename__]:
            if not row["enabled"]:
                continue
            if category == "import-policy":
                name = destinations.get(str(row["destination_id"]), {}).get(
                    "root_key", "Unavailable route"
                )
            else:
                name = lists.get(str(row["list_id"]), {}).get("name", "Unavailable list")
            await writer.add(
                "review",
                "automation-ready",
                f"{label} · {name}",
                "Pause this saved setting; keep existing books, requests and external evidence",
                entity_id=row["list_id"] if category == "writeback-policy" else row["id"],
                evidence={
                    "command_schema": 1,
                    "entity_type": category,
                    "kind": kind,
                    "saved_state": "enabled",
                    "action": action,
                },
            )


async def current(db, category, identifier, *, lock=False):
    row = await db.get(MODELS[category], identifier, with_for_update=lock, populate_existing=True)
    if not row or not row.enabled:
        raise HTTPException(409, "The saved automation setting changed; observe again")
    return row


async def pause(db, review, item):
    category = item["entity_type"]
    row = await current(db, category, UUID(item["entity_id"]), lock=True)
    before = {"enabled": row.enabled, "generation": row.generation}
    row.enabled = False
    row.generation += 1
    if category == "subscription":
        before.update(
            state=row.state,
            operation_id=str(row.operation_id) if row.operation_id else None,
            run_token=str(row.run_token) if row.run_token else None,
            lease_until=row.lease_until.isoformat() if row.lease_until else None,
            next_sync_at=row.next_sync_at.isoformat() if row.next_sync_at else None,
        )
        row.run_token = row.lease_until = row.next_sync_at = row.operation_id = None
        row.state = "idle"
        row.message = (
            "Paused during recovery; review the current list before enabling synchronization"
        )
    elif category == "writeback-policy":
        before["confirmed_at"] = row.confirmed_at.isoformat() if row.confirmed_at else None
        row.confirmed_at = None
    result = {
        "entity_id": item["entity_id"],
        "entity_type": category,
        "state": "paused",
        "generation": row.generation,
    }
    db.add(
        AuditEvent(
            actor_id=review.owner_id,
            action="recovery.automation.paused",
            entity_id=UUID(item["entity_id"]),
            detail={"review_id": str(review.id), "before": before, **result},
        )
    )
    return result
