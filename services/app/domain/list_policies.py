"""Reviewed standing list authority. Activation never silently authorizes a backlog."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from app.config import get_settings
from app.db.models import (
    AcquisitionIntent,
    AcquisitionReason,
    BookList,
    ImportDestination,
    ListAcquisitionBook,
    ListAcquisitionPolicy,
    ListEntry,
    ListSubscription,
    Operation,
    User,
    Work,
)
from app.domain.acquisition import RequestSpec, assess, evaluate, validate_request
from app.domain.acquisition_selection import verified_probe
from app.domain.automatic_dispatch import approve_route
from app.domain.downloaders import connection_or_404, mapped_path
from app.domain.list_requests import owner_context, pending_targets
from app.domain.operations import transaction_lock
from app.domain.release_profiles import PreferenceOverrides, overlay_profile, profile_snapshot
from app.domain.request_constraints import combine
from app.domain.visibility import visible_work
from app.domain.work_graph import acquisition_lock, canonical_map, family_ids, graph_lock
from app.importing.destinations import destination_configuration

KIND = "lists.policy-preview"


class PolicyRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")
    destination_id: UUID
    destination_revision: str = Field(pattern=r"^[a-f0-9]{64}$")


class ListPolicyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["browse", "manual", "automatic"] = "browse"
    specification: RequestSpec
    profile_id: UUID | None = None
    profile_generation: int | None = Field(default=None, ge=0)
    profile_effective_revision: str | None = Field(
        default=None, pattern=r"^[a-f0-9]{64}$", exclude_if=lambda value: value is None
    )
    preference_overrides: PreferenceOverrides = Field(default_factory=PreferenceOverrides)
    downloader_id: UUID | None = None
    downloader_generation: int | None = Field(default=None, ge=1)
    routes: dict[Literal["ebook", "audio"], PolicyRoute] = Field(default_factory=dict)
    include_work_ids: list[UUID] = Field(default_factory=list, max_length=25)
    expected_revision: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def valid_scope(self):
        if self.specification.ebook_version_id or self.specification.audio_version_id:
            raise ValueError("Choose exact versions from their book pages")
        if len(set(self.include_work_ids)) != len(self.include_work_ids):
            raise ValueError("Select each backlog book once")
        if self.mode != "automatic" and self.include_work_ids:
            raise ValueError("Use reviewed list requests for manual backlog selection")
        return self


def permitted(user):
    if (
        not user
        or not user.active
        or user.role == "viewer"
        or (user.role != "admin" and not user.can_automate)
    ):
        raise HTTPException(403, "An administrator must grant list automation permission")


async def current_policy(db, list_id):
    return await db.scalar(
        select(ListAcquisitionPolicy)
        .where(ListAcquisitionPolicy.list_id == list_id)
        .execution_options(populate_existing=True)
    )


async def members(db, user, list_id):
    await graph_lock(db)
    mapping = canonical_map()
    rows = (
        await db.execute(
            select(ListEntry.id, Work.id, Work.title, Work.authors, ListEntry.created_at)
            .join(mapping, mapping.c.origin_id == ListEntry.work_id)
            .join(Work, Work.id == mapping.c.work_id)
            .where(ListEntry.list_id == list_id, visible_work(user))
            .order_by(Work.id, ListEntry.id)
            .limit(10001)
        )
    ).all()
    if len(rows) > 10000:
        raise HTTPException(
            422, "Split this list before activating automation (10,000-entry limit)"
        )
    grouped = {}
    for entry, work, title, authors, added_at in rows:
        item = grouped.setdefault(
            str(work),
            {
                "work_id": str(work),
                "title": title,
                "authors": authors,
                "entry_ids": [],
                "added_at": added_at.isoformat(),
            },
        )
        item["entry_ids"].append(str(entry))
        item["added_at"] = min(item["added_at"], added_at.isoformat())
    return list(grouped.values())


async def configuration(db, user, list_id, body):
    spec = body.specification
    profile = await profile_snapshot(
        db, user.id, body.profile_id, body.profile_generation, body.profile_effective_revision
    )
    profile = overlay_profile(profile, list_overrides=body.preference_overrides)
    constraints = combine(
        spec.download_constraints.model_dump() if spec.download_constraints else None,
        profile.preferences.model_dump(include={"blocked_formats", "maximum_bytes"}),
    )
    values = spec.model_dump(mode="json")
    values["download_constraints"] = constraints
    approvals = {}
    subscription = await db.scalar(
        select(ListSubscription).where(ListSubscription.list_id == list_id)
    )
    if body.mode == "automatic":
        permitted(user)
        if subscription and not subscription.baseline_at:
            raise HTTPException(409, "Complete a successful list sync before activating automation")
        if not body.downloader_id or body.downloader_generation is None:
            raise HTTPException(422, "Choose a tested downloader")
        downloader = await connection_or_404(db, body.downloader_id)
        if (
            not downloader.enabled
            or downloader.status != "connected"
            or (downloader.credential_generation != body.downloader_generation)
        ):
            raise HTTPException(409, "Downloader settings changed; test and preview again")
        mapping = mapped_path(downloader, downloader.config["save_path"])
        media = {spec.mode} if spec.mode in {"ebook", "audio"} else {"ebook", "audio"}
        if set(body.routes) != media:
            raise HTTPException(422, "Choose an import destination for each requested medium")
        for medium in sorted(media):
            route = body.routes[medium]
            approval = await approve_route(
                db, user.id, route.destination_id, route.destination_revision
            )
            destination = await db.get(ImportDestination, route.destination_id)
            config = await destination_configuration(db, destination)
            if destination.medium != medium or not verified_probe(destination, config, mapping):
                raise HTTPException(409, "Verify each download-to-library route before activation")
            expected_library = getattr(spec, medium + "_library_id")
            if expected_library and expected_library != destination.library_id:
                raise HTTPException(422, "Destination conflicts with the requested library")
            values[medium + "_library_id"] = str(destination.library_id)
            approvals[medium] = approval
    return {
        "mode": body.mode,
        "request_constraints": spec.download_constraints.model_dump()
        if spec.download_constraints
        else None,
        "specification": RequestSpec.model_validate(values).model_dump(mode="json"),
        "profile": profile.model_dump(mode="json"),
        "downloader_id": str(body.downloader_id) if body.downloader_id else None,
        "downloader_generation": body.downloader_generation,
        "routes": {medium: route.model_dump(mode="json") for medium, route in body.routes.items()},
        "approvals": approvals,
        "subscription": {"id": str(subscription.id), "generation": subscription.generation}
        if subscription
        else None,
    }


async def preview(db, user, list_id, body, key):
    await transaction_lock(db, f"operation:{user.id}:{key}")
    _, user = await owner_context(db, user.id, list_id)
    command = {"list_id": str(list_id), **body.model_dump(mode="json")}
    existing = await db.scalar(
        select(Operation).where(Operation.owner_id == user.id, Operation.idempotency_key == key)
    )
    if existing:
        if existing.kind != KIND or existing.payload["command"] != command:
            raise HTTPException(409, "This preview key was already used for different settings")
        return existing
    policy = await current_policy(db, list_id)
    if body.expected_revision != (policy.revision if policy else 0):
        raise HTTPException(409, "List policy changed; reload before previewing")
    config = await configuration(db, user, list_id, body)
    records = await members(db, user, list_id)
    if not set(map(str, body.include_work_ids)) <= {r["work_id"] for r in records}:
        raise HTTPException(409, "Backlog selection is no longer in this list")
    spec = RequestSpec.model_validate(config["specification"])
    projected = []
    for record in records:
        await validate_request(db, user, UUID(record["work_id"]), spec)
        outcomes = await assess(db, user, UUID(record["work_id"]), spec)
        projected.append(
            {
                **record,
                "targets": await pending_targets(db, user, UUID(record["work_id"]), spec, outcomes),
                "selected": record["work_id"] in set(map(str, body.include_work_ids)),
            }
        )
    operation = Operation(
        owner_id=user.id,
        kind=KIND,
        idempotency_key=key,
        status="preview",
        message="Review future additions and the explicitly selected current books",
        payload={
            "command": command,
            "configuration": config,
            "members": records,
            "records": projected,
            "expires_at": (datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
        },
    )
    db.add(operation)
    await db.flush()
    return operation


async def owned_preview(db, user, list_id, identifier):
    await owner_context(db, user.id, list_id)
    operation = await db.get(Operation, identifier, with_for_update=True)
    if (
        not operation
        or operation.owner_id != user.id
        or operation.kind != KIND
        or (operation.payload["command"]["list_id"] != str(list_id))
    ):
        raise HTTPException(404, "List activation preview not found")
    return operation


def reason_reference(policy):
    return f"policy:{policy.list_id}:{policy.id}:{policy.generation}"


async def withdraw_generation(db, user, policy):
    rows = (
        await db.execute(
            select(AcquisitionIntent, AcquisitionReason)
            .join(AcquisitionReason)
            .where(
                AcquisitionReason.reference == reason_reference(policy),
                AcquisitionReason.active.is_(True),
            )
            .order_by(AcquisitionIntent.work_id, AcquisitionIntent.id)
        )
    ).all()
    for intent, reason in rows:
        await acquisition_lock(db, intent.work_id)
        reason.active = False
        await db.flush()
        await evaluate(db, user, intent)


async def activate(db, user, operation):
    if get_settings().recovery_mode:
        raise HTTPException(409, "List activation is paused for recovery")
    if operation.status == "completed":
        return await db.get(ListAcquisitionPolicy, UUID(operation.payload["policy_id"]))
    payload = operation.payload
    body = ListPolicyInput.model_validate(
        {k: v for k, v in payload["command"].items() if k != "list_id"}
    )
    list_id = UUID(payload["command"]["list_id"])
    if datetime.fromisoformat(payload["expires_at"]) <= datetime.now(UTC):
        raise HTTPException(409, "Activation preview expired; preview the list again")
    _, user = await owner_context(db, user.id, list_id)
    policy = await current_policy(db, list_id)
    if body.expected_revision != (policy.revision if policy else 0):
        raise HTTPException(409, "List policy changed; preview again")
    config = await configuration(db, user, list_id, body)
    records = await members(db, user, list_id)
    if config != payload["configuration"] or records != payload["members"]:
        raise HTTPException(
            409, "List membership, book identity or settings changed; preview again"
        )
    now = datetime.now(UTC)
    if policy:
        policy.revision += 1
        if policy.configuration != config:
            await withdraw_generation(db, user, policy)
            policy.generation += 1
    else:
        policy = ListAcquisitionPolicy(list_id=list_id, owner_id=user.id, revision=1, generation=1)
        db.add(policy)
    policy.configuration, policy.active = deepcopy(config), True
    policy.baseline_at, policy.next_check_at = now, now
    policy.message = (
        "Monitoring future additions" if body.mode == "automatic" else f"{body.mode.title()} mode"
    )
    await db.flush()
    from app.domain.list_monitoring import reconcile

    await reconcile(
        db, policy, records, now, activation=True, selected=set(map(str, body.include_work_ids))
    )
    operation.status, operation.message = "completed", "List policy saved"
    operation.payload = {**payload, "policy_id": str(policy.id), "policy_revision": policy.revision}
    return policy


async def pause(db, user, list_id, expected_revision):
    await owner_context(db, user.id, list_id)
    policy = await current_policy(db, list_id)
    if not policy or policy.revision != expected_revision:
        raise HTTPException(409, "List policy changed; reload before pausing")
    policy.active = False
    policy.revision += 1
    policy.message = "Acquisition paused; list synchronization continues"
    return policy


async def lock_authority(db, proof):
    if proof:
        await db.scalar(
            select(BookList.id)
            .where(BookList.id == UUID(proof["list_id"]))
            .with_for_update(read=True)
        )


async def require_authority(db, owner_id, proof, *, intent_id=None):
    if not proof:
        return
    await lock_authority(db, proof)
    policy = await db.get(ListAcquisitionPolicy, UUID(proof["policy_id"]), populate_existing=True)
    user = await db.get(User, owner_id, populate_existing=True)
    permitted(user)
    if (
        not policy
        or policy.owner_id != owner_id
        or str(policy.list_id) != proof["list_id"]
        or (
            not policy.active
            or policy.generation != proof["generation"]
            or policy.configuration["mode"] != "automatic"
        )
    ):
        raise HTTPException(409, "List acquisition is paused or its policy changed")
    book = await db.get(ListAcquisitionBook, UUID(proof["book_id"]), populate_existing=True)
    if (
        not book
        or book.policy_id != policy.id
        or book.generation != policy.generation
        or (book.state in {"baseline", "removed"} or (intent_id and book.intent_id != intent_id))
    ):
        raise HTTPException(409, "This book no longer has list acquisition authority")
    if not await db.scalar(
        select(ListEntry.id).where(
            ListEntry.list_id == policy.list_id, ListEntry.work_id.in_(family_ids(book.work_id))
        )
    ):
        raise HTTPException(409, "The book is no longer in this list")
    if book.intent_id and not await db.scalar(
        select(AcquisitionReason.id).where(
            AcquisitionReason.intent_id == book.intent_id,
            AcquisitionReason.reference == reason_reference(policy),
            AcquisitionReason.active.is_(True),
        )
    ):
        raise HTTPException(409, "This list's request reason was withdrawn")
