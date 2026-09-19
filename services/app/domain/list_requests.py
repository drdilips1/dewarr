"""Reviewed list batches reuse the ordinary request engine and its independent reasons."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import delete, select, text

from app.config import get_settings
from app.db.models import (
    AcquisitionIntent,
    AcquisitionReason,
    AcquisitionReservation,
    AcquisitionTarget,
    AuditEvent,
    BookList,
    ListEntry,
    Operation,
    User,
    Work,
)
from app.db.session import session_factory
from app.domain.acquisition import (
    RequestOptions,
    RequestReason,
    RequestSpec,
    assess,
    compatible_reservation,
    submit,
    validate_request,
)
from app.domain.operations import require_live_command, transaction_lock
from app.domain.request_preferences import PreferenceChoice, resolve
from app.domain.request_scope import same_command
from app.domain.visibility import visible_work
from app.domain.work_graph import acquisition_lock, canonical_map, graph_lock
from app.jobs.queue import enqueue

KIND = "lists.requests"
MAX_BOOKS = 100


class BatchInput(BaseModel):
    expected_content_revision: str | None = Field(
        default=None, min_length=64, max_length=64, exclude_if=lambda value: value is None
    )
    model_config = ConfigDict(extra="forbid")
    work_ids: list[UUID] = Field(min_length=1, max_length=MAX_BOOKS)
    specification: RequestOptions
    release_preferences: PreferenceChoice | None = None

    @model_validator(mode="after")
    def book_specific_versions(self):
        if self.specification.ebook_version_id or self.specification.audio_version_id:
            raise ValueError("Choose a specific edition or recording from its book page")
        if len(set(self.work_ids)) != len(self.work_ids):
            raise ValueError("Select each book only once")
        return self


async def owner_context(db, user_id, list_id):
    item = await db.scalar(
        select(BookList)
        .where(BookList.id == list_id, BookList.owner_id == user_id)
        .with_for_update()
    )
    if not item:
        raise HTTPException(404, "List not found")
    user = await db.scalar(
        select(User)
        .where(User.id == user_id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    if not user or not user.active or user.role == "viewer":
        raise HTTPException(403, "Your account can no longer request books")
    return item, user


async def selected_works(db, user, list_id, work_ids):
    mapping = canonical_map()
    works = list(
        await db.scalars(
            select(Work)
            .join(mapping, mapping.c.work_id == Work.id)
            .join(ListEntry, ListEntry.work_id == mapping.c.origin_id)
            .where(ListEntry.list_id == list_id, Work.id.in_(work_ids), visible_work(user))
            .distinct()
            .order_by(Work.id)
        )
    )
    if {w.id for w in works} != set(work_ids):
        raise HTTPException(409, "Selected books or list access changed; create a new preview")
    return works


def identity(work):
    return {"work_id": str(work.id), "title": work.title, "authors": work.authors}


async def repair(db, operation):
    if operation.status in {"queued", "running"}:
        state = await db.scalar(
            text("SELECT status::text FROM book_queue.procrastinate_jobs WHERE id=:id"),
            {"id": operation.job_id},
        )
        if state not in {"todo", "doing"}:
            operation.status = "failed"
            operation.message = "The batch worker stopped; retry this saved selection"


async def preview(db, user, list_id, body, key):
    _, user = await owner_context(db, user.id, list_id)
    await transaction_lock(db, f"operation:{user.id}:{key}")
    command = {
        "list_id": str(list_id),
        "work_ids": sorted(map(str, body.work_ids)),
        "specification": body.specification.model_dump(mode="json"),
        "scope_inheritance": 1,
    }
    if body.expected_content_revision is not None:
        command["expected_content_revision"] = body.expected_content_revision
    if body.release_preferences is not None:
        command["release_preferences"] = body.release_preferences.model_dump(
            mode="json", exclude_unset=True
        )
    existing = await db.scalar(
        select(Operation).where(Operation.owner_id == user.id, Operation.idempotency_key == key)
    )
    if existing:
        if existing.kind != KIND or not same_command(existing.payload["command"], command):
            raise HTTPException(409, "This preview key was already used for different options")
        return existing
    specification, profile = await resolve(
        db, user, body.specification, RequestReason(list_id=list_id), body.release_preferences
    )
    await graph_lock(db)
    from app.domain.list_curation import check_revision

    await graph_lock(db)
    await check_revision(db, list_id, body.expected_content_revision)
    works = await selected_works(db, user, list_id, body.work_ids)
    records = []
    for work in works:
        await validate_request(db, user, work.id, specification, RequestReason(list_id=list_id))
        records.append(identity(work))
    # Only abandoned, unsubmitted previews expire; accepted receipts are durable.
    old = list(
        await db.scalars(
            select(Operation.id)
            .where(
                Operation.owner_id == user.id, Operation.kind == KIND, Operation.status == "preview"
            )
            .order_by(Operation.created_at.desc(), Operation.id)
            .offset(9)
        )
    )
    if old:
        await db.execute(delete(Operation).where(Operation.id.in_(old)))
    operation = Operation(
        owner_id=user.id,
        kind=KIND,
        idempotency_key=key,
        status="preview",
        message="Review the selected books before saving wanted media",
        payload={
            "command": command,
            "records": records,
            "effective_specification": specification.model_dump(mode="json"),
            "release_policy": profile.model_dump(mode="json"),
            "expires_at": (datetime.now(UTC) + timedelta(hours=24)).isoformat(),
        },
    )
    db.add(operation)
    await db.flush()
    return operation


async def owned(db, user, list_id, operation_id):
    await owner_context(db, user.id, list_id)
    operation = await db.scalar(
        select(Operation)
        .where(Operation.id == operation_id, Operation.owner_id == user.id, Operation.kind == KIND)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not operation or operation.payload["command"]["list_id"] != str(list_id):
        raise HTTPException(404, "List request preview not found")
    await repair(db, operation)
    return operation


async def validate_plan(db, user, operation):
    command = operation.payload["command"]
    if datetime.fromisoformat(operation.payload["expires_at"]) <= datetime.now(UTC):
        raise HTTPException(409, "This request preview expired; create a new preview")
    await graph_lock(db)
    works = await selected_works(
        db, user, UUID(command["list_id"]), list(map(UUID, command["work_ids"]))
    )
    if [identity(w) for w in works] != operation.payload["records"]:
        raise HTTPException(409, "Book identity changed since preview; create a new preview")
    spec = RequestOptions.model_validate(command["specification"])
    if operation.payload.get("release_policy"):
        spec, _ = await resolve(
            db,
            user,
            spec,
            RequestReason(list_id=UUID(command["list_id"])),
            PreferenceChoice.model_validate(command["release_preferences"])
            if command.get("release_preferences") is not None
            else None,
            expected=operation.payload["release_policy"]["effective_revision"],
        )
    for work in works:
        await validate_request(
            db, user, work.id, spec, RequestReason(list_id=UUID(command["list_id"]))
        )
    return works, spec


async def start(db, user, operation):
    await require_live_command(db, operation)
    if get_settings().recovery_mode:
        raise HTTPException(409, "List requests are paused for recovery")
    if operation.status in {"completed", "queued", "running"}:
        return operation
    if operation.status == "cancelled":
        raise HTTPException(409, "This batch was cancelled; create a new preview")
    await validate_plan(db, user, operation)
    operation.status = "queued"
    operation.message = "Waiting to save this list's wanted media"
    operation.job_id = await enqueue(db, KIND, operation_id=str(operation.id))
    return operation


async def cancel(db, user, operation):
    if operation.status == "cancelled":
        return
    if operation.status == "completed":
        raise HTTPException(
            409, "These requests were saved; remove their list reasons individually"
        )
    operation.status, operation.message = (
        "cancelled",
        "Batch cancelled; no wanted requests were saved",
    )
    db.add(AuditEvent(actor_id=user.id, action="lists.requests.cancelled", entity_id=operation.id))


async def pending_targets(db, user, work_id, spec, outcomes):
    """Add owner-visible compatible requests without changing ownership or reserving work."""
    # Never disclose another account's pending targets or private list reasons.
    pending = list(
        await db.scalars(
            select(AcquisitionReservation)
            .join(AcquisitionTarget, AcquisitionTarget.reservation_id == AcquisitionReservation.id)
            .join(AcquisitionIntent)
            .where(
                AcquisitionIntent.owner_id == user.id,
                AcquisitionIntent.work_id == work_id,
                AcquisitionReservation.state.in_(["planned", "selected", "committed"]),
                AcquisitionTarget.state == "wanted",
                select(AcquisitionReason.id)
                .where(
                    AcquisitionReason.intent_id == AcquisitionIntent.id,
                    AcquisitionReason.active.is_(True),
                )
                .exists(),
            )
        )
    )
    targets = []
    for outcome in outcomes:
        value = {k: outcome[k] for k in ("slot", "state", "message")}
        compatible = False
        for candidate in pending:
            for medium in spec.media(outcome["slot"]):
                scope = str(getattr(spec, medium + "_library_id") or "unconfigured:" + str(user.id))
                if candidate.scope == scope and await compatible_reservation(
                    db, candidate, spec.rule(medium)
                ):
                    compatible = True
        if value["state"] == "wanted" and compatible:
            value.update(
                state="pending",
                message="An active compatible request already exists",
            )
        targets.append(value)
    return targets


async def status_records(db, user, operation):
    """Current, owner-visible projection, distinct from the immutable completion receipt."""
    records = []
    spec = RequestSpec.model_validate(
        operation.payload.get("effective_specification")
        or operation.payload["command"]["specification"]
    )
    for snapshot in operation.payload["records"]:
        work_id = UUID(snapshot["work_id"])
        work = await db.scalar(select(Work).where(Work.id == work_id, visible_work(user)))
        if not work or work.redirect_to:
            records.append(
                {
                    "work_id": work_id,
                    "title": "Book needs review",
                    "targets": [],
                    "issue": "Book identity or access changed",
                }
            )
            continue
        try:
            await validate_request(
                db,
                user,
                work_id,
                spec,
                RequestReason(list_id=UUID(operation.payload["command"]["list_id"]))
                if operation.status not in {"completed", "cancelled"}
                else None,
            )
            outcomes = await assess(db, user, work_id, spec)
        except HTTPException:
            records.append(
                {
                    "work_id": work_id,
                    "title": work.title,
                    "targets": [],
                    "issue": "List membership or request access needs attention",
                }
            )
            continue
        targets = await pending_targets(db, user, work_id, spec, outcomes)
        records.append({"work_id": work_id, "title": work.title, "targets": targets, "issue": None})
    return records


async def run(operation_id):
    if get_settings().recovery_mode:
        raise RuntimeError("List requests are paused for recovery")
    async with session_factory()() as db, db.begin():
        operation = await db.get(Operation, operation_id)
        if not operation or operation.kind != KIND or operation.payload.get("recovery_retirement"):
            return
        command = operation.payload["command"]
        # Ordinary requests lock their command before the list. Reserve child
        # command locks in that same order, before taking any list/work locks.
        for work_id in command["work_ids"]:
            await transaction_lock(
                db, f"operation:{operation.owner_id}:list-request:{operation.id}:{work_id}"
            )
        try:
            _, user = await owner_context(db, operation.owner_id, UUID(command["list_id"]))
        except HTTPException:
            await db.refresh(operation, with_for_update=True)
            if operation.status in {"queued", "running"}:
                operation.status, operation.message = (
                    "failed",
                    "List or account access changed before requests were saved",
                )
            return
        await db.refresh(operation, with_for_update=True)
        if operation.status not in {"queued", "running"}:
            return
        try:
            works, spec = await validate_plan(db, user, operation)
        except HTTPException as error:
            operation.status, operation.message = "failed", str(error.detail)
            return
        # All batch locks use canonical UUID order, matching list-reason withdrawal.
        for work in works:
            await acquisition_lock(db, work.id)
        receipts = []
        for work in works:
            intent, _ = await submit(
                db,
                user,
                work.id,
                spec,
                RequestReason(list_id=UUID(command["list_id"])),
                f"list-request:{operation.id}:{work.id}",
                frozen_preferences=operation.payload.get("release_policy"),
            )
            receipts.append({"work_id": str(work.id), "request_id": str(intent.id)})
        operation.payload = {**operation.payload, "receipt": receipts}
        operation.status, operation.message = (
            "completed",
            f"Saved wanted media for {len(receipts)} "
            f"{'book' if len(receipts) == 1 else 'books'}; downloads have not been started",
        )
        db.add(
            AuditEvent(actor_id=user.id, action="lists.requests.completed", entity_id=operation.id)
        )
