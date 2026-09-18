"""Finite, owner-reviewed main-book evidence, separate from acquisition permission."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Integer, select

from app.config import get_settings
from app.db.models import AuditEvent, Operation
from app.domain.corrections import revision
from app.domain.operations import transaction_lock
from app.domain.pack_coverage import CATALOG_FRESH_FOR

KIND = "series.scope-review"


class ScopeReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    work_ids: list[UUID] = Field(min_length=1, max_length=100)
    expected_generation: int = Field(ge=1)
    expected_review_id: UUID | None
    confirm_main_membership: Literal[True]

    @model_validator(mode="after")
    def unique_books(self):
        if len(set(self.work_ids)) != len(self.work_ids):
            raise ValueError("Select each book only once")
        return self


class ScopeBook(BaseModel):
    work_id: UUID
    title: str
    authors: list[str]
    position: str | None
    warnings: list[str]


class ScopeReviewView(BaseModel):
    id: UUID | None = None
    revision: int = 0
    state: Literal["not-reviewed", "current", "changed", "needs-refresh", "withdrawn", "superseded"]
    message: str
    catalog_generation: int | None = None
    reviewed_at: datetime | None = None
    books: list[ScopeBook] = []


async def lock(db, user_id, external_id):
    # All series request/review mutations acquire this before user, series and graph locks.
    await transaction_lock(db, f"series-scope:{user_id}:{external_id}")


async def latest(db, user, series):
    # Do not filter cancelled reviews: withdrawal must never resurrect an older revision.
    return await db.scalar(
        select(Operation)
        .where(
            Operation.owner_id == user.id,
            Operation.kind == KIND,
            Operation.payload["series_id"].astext == str(series.id),
        )
        .order_by(Operation.payload["revision"].astext.cast(Integer).desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )


def evidence(series, records):
    """Ignore decorative metadata/generation changes, retain identity and membership facts."""
    return revision(
        {
            "series_id": str(series.id),
            "provider": series.provider,
            "external_id": series.external_id,
            "books": [
                {
                    **{key: record[key] for key in ("work_id", "title", "authors")},
                    "members": [
                        {
                            **{
                                key: member[key]
                                for key in (
                                    "entry_id",
                                    "position",
                                    "compilation",
                                    "partial",
                                    "canonical_id",
                                    "release_date",
                                )
                            },
                            "provider": member["book"]["provider"],
                            "external_id": member["book"]["external_id"],
                            "source_title": member["book"]["title"],
                            "source_authors": member["book"]["authors"],
                            "details": member.get("details"),
                        }
                        for member in sorted(record["members"], key=lambda m: m["entry_id"])
                    ],
                }
                for record in sorted(records, key=lambda r: r["work_id"])
            ],
        }
    )


async def selected(db, user, series, work_ids):
    from app.domain.series_requests import membership

    return await membership(
        db, user, series, SimpleNamespace(work_ids=work_ids, scope="complete_series")
    )


async def state(db, user, series, review):
    if not review:
        return "not-reviewed", "No reusable main-book selection has been reviewed"
    current = await latest(db, user, series)
    if not current or current.id != review.id:
        return "superseded", "A newer main-book review replaced this selection"
    if review.status == "cancelled":
        return "withdrawn", "Main-book review withdrawn; existing accepted requests are unchanged"
    try:
        records, _ = await selected(
            db, user, series, [UUID(r["work_id"]) for r in review.payload["records"]]
        )
    except HTTPException as error:
        if error.status_code != 409:
            raise
        return "changed", "Selected membership or book identity changed; review the selection again"
    if evidence(series, records) != review.payload["fingerprint"]:
        return "changed", "Selected catalog evidence changed; review the selection again"
    if series.fetched_at < datetime.now(UTC) - CATALOG_FRESH_FOR:
        return "needs-refresh", "Refresh the series catalog before reusing this review"
    return "current", "Reviewed main books are unchanged; new catalog members are not included"


async def view(db, user, series, review):
    status, message = await state(db, user, series, review)
    return ScopeReviewView(
        state=status,
        message=message,
        **(
            {
                "id": review.id,
                "revision": review.payload["revision"],
                "catalog_generation": review.payload["catalog_generation"],
                "reviewed_at": review.created_at,
                "books": review.payload["records"],
            }
            if review
            else {}
        ),
    )


async def save(db, user, external_id, body, key):
    from app.domain.series_requests import context

    if get_settings().recovery_mode:
        raise HTTPException(409, "Series scope changes are paused for recovery")
    await transaction_lock(db, f"operation:{user.id}:{key}")
    series, user = await context(db, user.id, external_id)
    command = {
        **body.model_dump(mode="json"),
        "external_id": external_id,
        "work_ids": sorted(map(str, body.work_ids)),
    }
    old = await db.scalar(
        select(Operation).where(
            Operation.owner_id == user.id,
            Operation.idempotency_key == key,
        )
    )
    if old:
        if old.kind != KIND or old.payload["command"] != command:
            raise HTTPException(409, "This review key was used for different options")
        return series, user, old
    previous = await latest(db, user, series)
    if (previous.id if previous else None) != body.expected_review_id:
        raise HTTPException(409, "The saved main-book review changed; reload before replacing it")
    if series.generation != body.expected_generation:
        raise HTTPException(409, "Series catalog changed; reload and review your selection")
    if series.fetched_at < datetime.now(UTC) - CATALOG_FRESH_FOR:
        raise HTTPException(409, "Refresh the series catalog before saving a main-book review")
    records, omitted = await selected(db, user, series, body.work_ids)
    review = Operation(
        owner_id=user.id,
        kind=KIND,
        idempotency_key=key,
        status="completed",
        message="Saved a finite main-book review; no acquisition was requested",
        payload={
            "command": command,
            "series_id": str(series.id),
            "revision": previous.payload["revision"] + 1 if previous else 1,
            "catalog_generation": series.generation,
            "observed_at": series.fetched_at.isoformat(),
            "evidence_kind": "user-reviewed-main-books",
            "records": records,
            "omitted": omitted,
            "fingerprint": evidence(series, records),
        },
    )
    db.add(review)
    await db.flush()
    db.add(
        AuditEvent(
            actor_id=user.id,
            action=KIND,
            entity_id=review.id,
            detail={"revision": review.payload["revision"], "books": len(records)},
        )
    )
    return series, user, review


async def require_current(db, user, series, review_id, work_ids):
    review = await latest(db, user, series)
    if not review or review.id != review_id:
        raise HTTPException(409, "Main-book review changed; create a new preview")
    status, message = await state(db, user, series, review)
    if status != "current":
        raise HTTPException(409, message)
    if set(map(str, work_ids)) != {r["work_id"] for r in review.payload["records"]}:
        raise HTTPException(409, "Select the entire saved main-book set or review a new selection")
    return {
        "id": str(review.id),
        "revision": review.payload["revision"],
        "fingerprint": review.payload["fingerprint"],
    }


async def withdraw(db, user, external_id, review_id):
    from app.domain.series_requests import context

    if get_settings().recovery_mode:
        raise HTTPException(409, "Series scope changes are paused for recovery")
    series, user = await context(db, user.id, external_id)
    review = await latest(db, user, series)
    if not review or review.id != review_id:
        raise HTTPException(409, "Main-book review changed; reload before withdrawing it")
    if review.status != "cancelled":
        review.status, review.message = "cancelled", "Main-book review withdrawn"
        review.payload = {**review.payload, "withdrawn_at": datetime.now(UTC).isoformat()}
        db.add(AuditEvent(actor_id=user.id, action="series.scope-withdraw", entity_id=review.id))
    return series, user, review
