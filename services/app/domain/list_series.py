"""List-derived finite series requests preserve the originating membership episode."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.db.models import (
    AcquisitionReason,
    CatalogSeries,
    ListAcquisitionBook,
    ListAcquisitionPolicy,
    ListEntry,
    Operation,
    SeriesMembership,
)
from app.domain import list_policies, series_acquisition, series_scopes
from app.domain.acquisition import RequestSpec
from app.domain.operations import try_transaction_lock
from app.domain.pack_coverage import MAX_ADDITIONAL_BOOKS
from app.domain.release_profiles import ProfileSnapshot
from app.domain.work_graph import family_ids
from app.importing.naming import fingerprint
from app.jobs.queue import enqueue


class SeriesPlanView(BaseModel):
    state: Literal["single", "ready", "review", "busy"]
    message: str
    external_id: str | None = None
    series_name: str | None = None
    records: list[series_scopes.ScopeBook] = []


def origin(parent):
    return parent.payload.get("list_origin") if parent else None


async def lock_origin(db, saved):
    if saved:
        await list_policies.lock_authority(db, saved["authority"])


async def removed(db, saved):
    """Permanent episode withdrawal, separate from temporary pause; no late row locks."""
    if not saved:
        return False
    proof = saved["authority"]
    policy = await db.get(ListAcquisitionPolicy, UUID(proof["policy_id"]), populate_existing=True)
    book = await db.get(ListAcquisitionBook, UUID(proof["book_id"]), populate_existing=True)
    if (
        not policy
        or not policy.list_id
        or str(policy.list_id) != proof["list_id"]
        or policy.generation != proof["generation"]
        or not book
        or book.policy_id != policy.id
        or book.generation != policy.generation
        or book.state in {"removed", "baseline"}
        or str(book.intent_id) != saved["root_intent_id"]
        or book.progress.get("activation") != saved["activation"]
    ):
        return True
    if not await db.scalar(
        select(ListEntry.id)
        .where(
            ListEntry.list_id == policy.list_id,
            ListEntry.work_id.in_(family_ids(book.work_id)),
        )
        .limit(1)
    ):
        return True
    return not bool(
        await db.scalar(
            select(AcquisitionReason.id)
            .where(
                AcquisitionReason.intent_id == book.intent_id,
                AcquisitionReason.reference == list_policies.reason_reference(policy),
                AcquisitionReason.active.is_(True),
            )
            .limit(1)
        )
    )


async def require_origin(db, owner_id, saved):
    if not saved:
        return
    await list_policies.require_authority(
        db,
        owner_id,
        saved["authority"],
        intent_id=UUID(saved["root_intent_id"]),
    )
    if await removed(db, saved):
        raise HTTPException(409, "The originating list membership episode changed")
    policy = await db.get(ListAcquisitionPolicy, UUID(saved["authority"]["policy_id"]))
    if fingerprint(policy.configuration) != saved["configuration_revision"]:
        raise HTTPException(409, "The originating list policy changed; review it again")


async def lock_import_reasons(db, selections):
    intent_ids = set()
    for selection in selections:
        authority = (selection.frozen.get("automatic_selection") or {}).get("series_authority")
        if authority and (saved := authority.get("list_origin")):
            intent_ids.update((selection.intent_id, UUID(saved["root_intent_id"])))
    if intent_ids:
        await db.scalars(
            select(AcquisitionReason)
            .where(AcquisitionReason.intent_id.in_(intent_ids))
            .order_by(AcquisitionReason.id)
            .with_for_update(read=True)
        )


async def require_import_authority(db, selection):
    """Fence new publications; a pause preserves already-submitted lifecycle work.

    The publisher locks these origins before users/library rows. Do not acquire
    late locks here, and never substitute a different generic request reason.
    """
    authority = (selection.frozen.get("automatic_selection") or {}).get("series_authority")
    if not authority or not authority.get("list_origin"):
        return
    parent = await db.get(Operation, UUID(authority["operation_id"]), populate_existing=True)
    if (
        not parent
        or parent.owner_id != selection.owner_id
        or parent.kind != "series.requests"
        or parent.status != "completed"
        or origin(parent) != authority["list_origin"]
        or series_acquisition.scope_revision(parent) != authority["scope_revision"]
        or await removed(db, authority["list_origin"])
        or not await db.scalar(
            select(AcquisitionReason.id).where(
                AcquisitionReason.intent_id == selection.intent_id,
                AcquisitionReason.kind == "series",
                AcquisitionReason.reference == str(parent.id),
                AcquisitionReason.active.is_(True),
            )
        )
    ):
        raise HTTPException(
            409, "The originating series/list authority was withdrawn before import"
        )


async def plan(db, user, work_id):
    rows = list(
        await db.scalars(
            select(CatalogSeries)
            .where(
                CatalogSeries.owner_id == user.id,
                CatalogSeries.provider == "hardcover",
                select(SeriesMembership.id)
                .where(
                    SeriesMembership.series_id == CatalogSeries.id,
                    SeriesMembership.present.is_(True),
                    SeriesMembership.work_id.in_(family_ids(work_id)),
                )
                .exists(),
            )
            .order_by(CatalogSeries.id)
            .limit(4)
        )
    )
    if not rows:
        return {"state": "single", "message": "No known series membership; requests this book only"}
    if len(rows) > 3:
        return {
            "state": "review",
            "message": "Several series contain this book; request a reviewed series explicitly",
        }
    valid, issues = [], []
    for row in rows:
        # List planning already holds graph/list locks. Never wait here behind a
        # catalog publisher or review mutation that may need those locks.
        for key in (
            f"series-scope:{user.id}:{row.external_id}",
            f"series-catalog:{user.id}:{row.external_id}",
        ):
            if not await try_transaction_lock(db, key):
                return {
                    "state": "busy",
                    "message": "Series metadata is changing; another check is scheduled",
                }
        await db.refresh(row)
        review = await series_scopes.latest(db, user, row)
        state, message = await series_scopes.state(db, user, row, review)
        if state == "current" and str(work_id) in {r["work_id"] for r in review.payload["records"]}:
            if len(review.payload["records"]) > MAX_ADDITIONAL_BOOKS + 1:
                issues.append(
                    (row, "The reviewed set exceeds the 20-additional-book automation limit")
                )
            else:
                valid.append((row, review))
        else:
            issues.append(
                (
                    row,
                    message
                    if state != "current"
                    else "The trigger book is outside the reviewed main-book set",
                )
            )
    if len(valid) != 1:
        return {
            "state": "review",
            "message": "Several reviewed series contain this book; choose one explicitly"
            if valid
            else issues[0][1],
            "external_id": rows[0].external_id if len(rows) == 1 else None,
        }
    row, review = valid[0]
    return {
        "state": "ready",
        "message": f"Complete {len(review.payload['records'])} reviewed main books",
        "external_id": row.external_id,
        "series_id": str(row.id),
        "series_name": row.name,
        "catalog_generation": row.generation,
        "fetched_at": row.fetched_at.isoformat(),
        "scope_review": {
            "id": str(review.id),
            "revision": review.payload["revision"],
            "fingerprint": review.payload["fingerprint"],
        },
        "records": deepcopy(review.payload["records"]),
        "omitted": deepcopy(review.payload["omitted"]),
    }


async def create(db, user, policy, book, planned):
    from app.domain.list_automation import proof

    config = policy.configuration
    automatic = await series_acquisition.configuration(
        db,
        user,
        RequestSpec.model_validate(config["specification"]),
        ProfileSnapshot.model_validate(config["profile"]),
        series_acquisition.automatic_routes.AutomaticRoutes.model_validate(
            {key: config[key] for key in ("downloader_id", "downloader_generation", "routes")}
        ),
    )
    # Series route labels describe presentation; all inherited list settings and
    # their immutable values remain in the profile/parent evidence.
    now = datetime.now(UTC)
    ids = sorted(r["work_id"] for r in planned["records"])
    parent = Operation(
        owner_id=user.id,
        kind="series.requests",
        status="queued",
        idempotency_key=f"list-series:{book.id}:{policy.generation}:{book.progress['activation']}",
        message="Creating finite series requests from this list membership",
        payload={
            "command": {
                "external_id": planned["external_id"],
                "work_ids": ids,
                "scope": "complete_series",
                "confirm_main_membership": False,
                "scope_review_id": planned["scope_review"]["id"],
                "expected_generation": planned["catalog_generation"],
                "specification": automatic["specification"],
            },
            "series": {
                "id": planned["series_id"],
                "name": planned["series_name"],
                "external_id": planned["external_id"],
                "generation": planned["catalog_generation"],
                "fetched_at": planned["fetched_at"],
            },
            "records": planned["records"],
            "omitted": planned["omitted"],
            "scope_review": planned["scope_review"],
            "main_membership": "user-confirmed",
            "effective_specification": automatic["specification"],
            "release_policy": automatic["profile"],
            "automatic_configuration": automatic,
            "accepted_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=24)).isoformat(),
            "list_origin": {
                "authority": proof(policy, book),
                "activation": book.progress["activation"],
                "root_intent_id": str(book.intent_id),
                "configuration_revision": fingerprint(config),
            },
        },
    )
    db.add(parent)
    await db.flush()
    parent.job_id = await enqueue(db, "series.requests", operation_id=str(parent.id))
    book.progress = {
        **book.progress,
        "series_request_id": str(parent.id),
        "series_external_id": planned["external_id"],
    }
    return parent


async def advance(db, user, policy, book, planned, now):
    from app.domain.list_automation import next_tick

    parent_id = book.progress.get("series_request_id")
    parent = (
        await db.get(Operation, UUID(parent_id))
        if parent_id
        else await create(db, user, policy, book, planned)
    )
    await require_origin(db, user.id, origin(parent))
    if parent.status == "failed" and parent.payload.get("upstream_hold"):
        from app.domain.series_requests import start

        await start(db, user, parent)
    controller = (
        await db.get(Operation, UUID(parent.payload["acquisition_id"]))
        if parent.payload.get("acquisition_id")
        else None
    )
    if controller:
        # An explicit list resume preserves its episode and may resume only a
        # controller held by upstream authority, not arbitrary child failures.
        if controller.status == "held" and controller.payload.get("upstream_hold"):
            await series_acquisition.retry(db, user, parent)
        book.state = (
            "available"
            if controller.status == "completed"
            else "held"
            if controller.status in {"held", "cancelled"}
            else "pending"
        )
        book.message = controller.message
        if controller.status == "completed":
            from app.domain.series_requests import status_records

            records = await status_records(db, user, parent)
            if any(
                r["issue"] or any(t["state"] != "satisfied" for t in r["targets"]) for r in records
            ):
                book.state, book.message = (
                    "held",
                    "Series availability changed; review the saved request before replacing files",
                )
    else:
        book.state = "held" if parent.status in {"failed", "cancelled"} else "pending"
        book.message = parent.message
    book.next_check_at = (
        next_tick(now)
        if book.state == "pending"
        else now + timedelta(hours=24)
        if book.state == "available"
        else None
    )
