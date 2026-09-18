"""Bounded automatic release preparation through the shared acquisition selector."""

import asyncio
import math
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text

from app.adapters.contracts import AdapterError, FailureKind
from app.adapters.mam import MAMRelease
from app.adapters.prowlarr import ProwlarrRelease
from app.adapters.torrent_descriptor import TorrentDescriptor
from app.config import get_settings
from app.db.models import (
    AcquisitionIntent,
    AcquisitionReservation,
    AcquisitionTarget,
    ListCatalogBinding,
    Operation,
    SourceArtifact,
    SourceConnection,
    SourceResult,
    User,
    Version,
    Work,
    WorkMetadataSource,
)
from app.db.session import session_factory
from app.domain.acquisition import evaluate
from app.domain.acquisition_selection import SelectionInput, prepare
from app.domain.automatic_eligibility import AUDIO, EBOOKS, eligibility, limit_bytes
from app.domain.book_sources import checked
from app.domain.operations import transaction_lock
from app.domain.prowlarr_network import prowlarr_call
from app.domain.release_profiles import (
    ProfileSnapshot,
    assess_release,
    normalized,
    profile_snapshot,
    ranking_key,
)
from app.domain.source_artifacts import persist_artifact
from app.domain.source_network import source_call
from app.domain.visibility import visible_origin_work
from app.domain.work_graph import acquisition_lock, family_ids
from app.jobs.queue import enqueue
from app.jobs.retry import SourceSearchRetry
from app.security import decrypt_secrets

KIND = "acquisition.auto-select"
MAX_INSPECTIONS = 5
TERMINAL = {"completed", "held", "failed", "cancelled"}


class AlreadyAvailable(HTTPException):
    def __init__(self):
        super().__init__(
            409, "Requested media is already available; no release selection is needed"
        )


class AutomaticSelectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent_id: UUID
    slot: str = Field(pattern="^(ebook|audio|either)$")
    search_id: UUID
    downloader_id: UUID
    downloader_generation: int = Field(ge=1)
    destination_id: UUID
    destination_revision: str = Field(pattern=r"^[a-f0-9]{64}$")


def release_value(row):
    return (MAMRelease if row.source_key == "mam" else ProwlarrRelease).model_validate(
        row.release_snapshot
    )


async def context(db, user_id, body):
    user = await db.get(User, user_id, populate_existing=True)
    if not user or not user.active or user.role == "viewer":
        raise HTTPException(403, "Request account access changed")
    intent = await db.get(AcquisitionIntent, body.intent_id, populate_existing=True)
    if not intent or intent.owner_id != user_id:
        raise HTTPException(404, "Request not found")
    work = await acquisition_lock(db, intent.work_id)
    await evaluate(db, user, intent)
    await db.flush()
    target = await db.scalar(
        select(AcquisitionTarget).where(
            AcquisitionTarget.intent_id == intent.id,
            AcquisitionTarget.slot == body.slot,
        )
    )
    if target and target.state == "satisfied":
        raise AlreadyAvailable()
    if not target or target.state != "wanted" or not target.reservation_id:
        raise HTTPException(
            409, "This target is no longer wanted; check current library availability"
        )
    reservation = await db.get(AcquisitionReservation, target.reservation_id)
    if reservation.state != "planned":
        raise HTTPException(409, "A compatible request already has an acquisition in progress")
    search, changed = await checked(db, body.search_id, user_id)
    if changed or UUID(search.payload["work"]["id"]) != work.id:
        raise HTTPException(409, "The source search no longer matches this request")
    if search.status != "completed":
        raise HTTPException(409, "Wait for the source search to finish")
    if datetime.fromisoformat(search.payload["expires_at"]) <= datetime.now(UTC):
        raise HTTPException(409, "Source results expired; refresh the source search")
    profile = ProfileSnapshot.model_validate(search.payload["profile"])
    current = await profile_snapshot(db, user_id, profile.id, profile.generation)
    if current.model_dump(mode="json") != profile.model_dump(mode="json"):
        raise HTTPException(409, "Download preferences changed; refresh the source search")
    # A matched source/provider identity is required; manually typed titles alone
    # remain usable in the reviewed flow rather than silently acquiring namesakes.
    anchor = await db.scalar(
        select(WorkMetadataSource.id)
        .join(Work)
        .where(
            visible_origin_work(user),
            WorkMetadataSource.work_id.in_(family_ids(work.id)),
            WorkMetadataSource.accepted.is_(True),
        )
        .limit(1)
    )
    if not anchor:
        bindings = await db.scalars(
            select(ListCatalogBinding).where(
                ListCatalogBinding.owner_id == user_id,
                ListCatalogBinding.work_id.in_(family_ids(work.id)),
            )
        )
        anchor = any(
            b.identity_key.startswith(("hardcover:", "goodreads:"))
            and normalized(b.assertion.get("title", "")) == normalized(work.title)
            and {normalized(a) for a in b.assertion.get("authors", [])}.intersection(
                normalized(a) for a in work.authors
            )
            for b in bindings
        )
    if not anchor:
        raise HTTPException(
            409, "Match this title to a catalog provider before automatic selection"
        )
    rule = dict(reservation.requirements)
    version = await db.get(Version, UUID(rule["version_id"])) if rule["version_id"] else None
    return user, work, search, profile, rule, version


async def begin(db, user, body, key):
    if get_settings().recovery_mode:
        raise HTTPException(409, "Automatic selection is paused for recovery")
    await transaction_lock(db, f"operation:{user.id}:{key}")
    command = body.model_dump(mode="json")
    previous = await db.scalar(
        select(Operation).where(Operation.owner_id == user.id, Operation.idempotency_key == key)
    )
    if previous:
        if previous.kind != KIND or previous.payload["command"] != command:
            raise HTTPException(409, "This command key was already used for another selection")
        return previous
    _, work, search, profile, rule, _ = await context(db, user.id, body)
    active = await db.scalar(
        select(Operation)
        .where(
            Operation.owner_id == user.id,
            Operation.kind == KIND,
            Operation.payload["command"]["intent_id"].astext == str(body.intent_id),
            Operation.payload["command"]["slot"].astext == body.slot,
            Operation.status.in_(["queued", "running"]),
        )
        .order_by(Operation.created_at.desc())
        .limit(1)
    )
    if active:
        await repair(db, active)
        if active.status in {"queued", "running"}:
            if active.payload["command"] != command:
                raise HTTPException(409, "Cancel the active selection before changing its options")
            raise HTTPException(
                409, "A selection is already running for this target; open its current status"
            )
    operation = Operation(
        owner_id=user.id,
        kind=KIND,
        idempotency_key=key,
        message="Waiting to assess source candidates",
        payload={
            "command": command,
            "work": deepcopy(search.payload["work"]),
            "profile": profile.model_dump(mode="json"),
            "requirements": rule,
            "maximum_bytes": limit_bytes(profile.preferences, rule["medium"]),
            "inspected": [],
            "verified": {},
            "decisions": [],
            "selection_id": None,
            "token": None,
        },
    )
    db.add(operation)
    await db.flush()
    operation.job_id = await enqueue(db, KIND, operation_id=str(operation.id))
    return operation


async def owned(db, user, identifier):
    await transaction_lock(db, f"auto-select:{identifier}")
    operation = await db.get(Operation, identifier, populate_existing=True)
    if not operation or operation.owner_id != user.id or operation.kind != KIND:
        raise HTTPException(404, "Automatic selection not found")
    await repair(db, operation)
    return operation


async def repair(db, operation):
    if operation.status in {"queued", "running"}:
        status = await db.scalar(
            text("SELECT status::text FROM book_queue.procrastinate_jobs WHERE id=:id"),
            {"id": operation.job_id},
        )
        if status not in {"todo", "doing"}:
            operation.status, operation.message = (
                "failed",
                "Selection worker stopped; start a new selection from fresh results",
            )


async def candidates(db, operation, work, profile, rule, version):
    search_id = UUID(operation.payload["command"]["search_id"])
    rows = list(
        await db.scalars(
            select(SourceResult).where(
                SourceResult.operation_id == search_id,
                SourceResult.owner_id == operation.owner_id,
            )
        )
    )
    sources = {s.key: s for s in await db.scalars(select(SourceConnection))}
    ranked = []
    for row in rows:
        release = release_value(row)
        verified = operation.payload.get("verified", {}).get(str(row.id))
        if verified:
            release = type(release).model_validate(verified["release"])
        problems = eligibility(
            release, operation.payload["work"], rule, profile.preferences, version=version
        )
        source = sources.get(row.source_key)
        if (
            not source
            or not source.enabled
            or source.generation != row.source_generation
            or row.expires_at <= datetime.now(UTC)
        ):
            problems.append("Source connection changed or this observation expired")
        ranked_release = (
            release.model_copy(update={"formats": verified["formats"]}) if verified else release
        )
        assessment = assess_release(
            ranked_release, operation.payload["work"], profile.preferences, rule["medium"]
        )
        ranked.append(
            (ranking_key(ranked_release, assessment, profile.preferences), row, release, problems)
        )
    ranked.sort(key=lambda value: value[0])
    return ranked


async def resolve_candidate(owner_id, row):
    if row.source_key == "mam":
        artifact, generation = await source_call(
            owner_id,
            "resolve",
            row.release_snapshot["source_id"],
            with_generation=True,
            expected_generation=row.source_generation,
        )
    else:
        release = release_value(row)
        reference = decrypt_secrets(row.encrypted_reference).get("link")
        if not reference:
            raise HTTPException(422, "This result has no supported torrent file")
        artifact, generation = await prowlarr_call(
            owner_id, "resolve", (release, reference), expected_generation=row.source_generation
        )
    identifier = await persist_artifact(
        owner_id, artifact.release.source_id, artifact, generation, row.source_key
    )
    return identifier, artifact.release


def finish(operation, state, message):
    operation.status, operation.message = state, message
    operation.payload = {**operation.payload, "token": None}


async def reject_candidate(db, operation, result_id, reasons):
    payload = deepcopy(operation.payload)
    if str(result_id) not in payload["inspected"]:
        payload["inspected"].append(str(result_id))
    payload.get("verified", {}).pop(str(result_id), None)
    payload["token"] = None
    for decision in payload["decisions"]:
        if decision["result_id"] == str(result_id):
            decision["reasons"] = reasons
            decision["inspected"] = True
    operation.payload = payload
    operation.status, operation.message = (
        "queued",
        "This torrent needs review; checking the next candidate",
    )
    operation.job_id = await enqueue(db, KIND, operation_id=str(operation.id))


def eligible_candidates(ranked, payload):
    inspected = set(payload["inspected"])
    verified = payload.get("verified", {})
    return [
        item
        for item in ranked
        if not item[3]
        and (
            str(item[1].id) in verified
            or (str(item[1].id) not in inspected and len(inspected) < MAX_INSPECTIONS)
        )
    ]


async def run(identifier):
    if get_settings().recovery_mode:
        raise SourceSearchRetry(60)
    token = str(uuid4())
    async with session_factory()() as db, db.begin():
        await transaction_lock(db, f"auto-select:{identifier}")
        operation = await db.get(Operation, identifier, populate_existing=True)
        if not operation or operation.kind != KIND or operation.status in TERMINAL:
            return
        if operation.payload.get("token") and datetime.fromisoformat(
            operation.payload["lease_until"]
        ) > datetime.now(UTC):
            raise SourceSearchRetry(
                max(
                    1,
                    math.ceil(
                        (
                            datetime.fromisoformat(operation.payload["lease_until"])
                            - datetime.now(UTC)
                        ).total_seconds()
                    ),
                )
            )
        body = AutomaticSelectionInput.model_validate(operation.payload["command"])
        try:
            user, work, search, profile, rule, version = await context(db, operation.owner_id, body)
            if (
                rule != operation.payload["requirements"]
                or search.payload["work"] != operation.payload["work"]
            ):
                raise HTTPException(
                    409, "Request or catalog evidence changed; start a fresh selection"
                )
        except (HTTPException, AdapterError) as error:
            finish(
                operation,
                "completed" if isinstance(error, AlreadyAvailable) else "held",
                str(error.detail) if isinstance(error, HTTPException) else str(error),
            )
            return
        ranked = await candidates(db, operation, work, profile, rule, version)
        inspected = set(operation.payload["inspected"])
        possible = eligible_candidates(ranked, operation.payload)
        payload = deepcopy(operation.payload)
        previous_decisions = {v["result_id"]: v for v in payload["decisions"] if v.get("inspected")}
        payload["decisions"] = [
            {
                "result_id": str(row.id),
                "source": release.source,
                "title": release.raw_title,
                "reasons": list(
                    dict.fromkeys(
                        [*issues, *previous_decisions.get(str(row.id), {}).get("reasons", [])]
                    )
                ),
                "inspected": str(row.id) in inspected,
            }
            for _, row, release, issues in ranked
        ]
        operation.payload = payload
        if not possible:
            finish(
                operation,
                "held",
                "No eligible release found within this page and inspection budget; "
                "review candidate reasons or refresh results",
            )
            return
        row = possible[0][1]
        cached = payload.get("verified", {}).get(str(row.id))
        payload.update(
            token=token, lease_until=(datetime.now(UTC) + timedelta(minutes=4)).isoformat()
        )
        operation.payload = payload
        operation.status, operation.message = (
            "running",
            "Inspecting the highest ranked eligible torrent",
        )
        owner_id = operation.owner_id
    try:
        if cached:
            artifact_id = UUID(cached["artifact_id"])
            fresh = type(release_value(row)).model_validate(cached["release"])
        else:
            async with asyncio.timeout(180):
                artifact_id, fresh = await resolve_candidate(owner_id, row)
    except (AdapterError, HTTPException, TimeoutError) as error:
        async with session_factory()() as db, db.begin():
            await transaction_lock(db, f"auto-select:{identifier}")
            operation = await db.get(Operation, identifier, populate_existing=True)
            if operation.status in TERMINAL or operation.payload.get("token") != token:
                return
            retry = (
                isinstance(error, TimeoutError)
                or isinstance(error, AdapterError)
                and error.kind
                in {
                    FailureKind.RATE_LIMIT,
                    FailureKind.UNAVAILABLE,
                    FailureKind.TIMEOUT,
                }
            )
            rejected = (
                isinstance(error, AdapterError)
                and error.kind
                in {FailureKind.PARSER, FailureKind.UNSUPPORTED, FailureKind.NOT_FOUND}
                or isinstance(error, HTTPException)
                and error.status_code in {404, 422}
            )
            if rejected:
                await reject_candidate(
                    db,
                    operation,
                    row.id,
                    ["Torrent could not be inspected or is unsupported; review this source result"],
                )
                return
            finish(
                operation,
                "queued" if retry else "held",
                "Source access is temporarily unavailable"
                if retry
                else "Torrent inspection needs review; inspect the source result manually",
            )
        if retry:
            raise SourceSearchRetry(getattr(error, "retry_after", None) or 60) from None
        return
    async with session_factory()() as db, db.begin():
        # Selection commands take their key before the acquisition lock. Match
        # that order even when a user races the internally generated command.
        child_key = f"auto-selected:{identifier}"
        await transaction_lock(db, f"operation:{owner_id}:{child_key}")
        await transaction_lock(db, f"auto-select:{identifier}")
        operation = await db.get(Operation, identifier, populate_existing=True)
        if operation.status in TERMINAL or operation.payload.get("token") != token:
            return
        try:
            user, work, search, profile, rule, version = await context(db, owner_id, body)
            if (
                rule != operation.payload["requirements"]
                or search.payload["work"] != operation.payload["work"]
            ):
                raise HTTPException(
                    409, "Request or catalog evidence changed; start a fresh selection"
                )
            result = await db.get(SourceResult, row.id, populate_existing=True)
            source = await db.get(SourceConnection, row.source_key, populate_existing=True)
            if (
                not result
                or result.expires_at <= datetime.now(UTC)
                or not source
                or not source.enabled
                or source.generation != row.source_generation
            ):
                raise HTTPException(
                    409, "Source observation changed during inspection; refresh results"
                )
            artifact = await db.get(SourceArtifact, artifact_id)
            if (
                not artifact
                or artifact.owner_id != owner_id
                or artifact.source_key != row.source_key
                or artifact.source_generation != row.source_generation
                or artifact.source_id != fresh.source_id
                or fresh.source_id != release_value(row).source_id
            ):
                raise HTTPException(
                    409, "Resolved torrent does not match the selected source result"
                )
            descriptor = TorrentDescriptor.model_validate(artifact.descriptor)
            reasons = eligibility(
                fresh,
                operation.payload["work"],
                rule,
                profile.preferences,
                version=version,
                descriptor=descriptor,
            )
            # Existing artifact snapshots are immutable. Metadata changes require
            # review; fluctuating counts/timestamps cannot change book identity.
            excluded = {
                "observed_at",
                "seeders",
                "leechers",
                "snatches",
                "uploaded_at",
                "description",
                "media_info",
            }
            if release_value(artifact).model_dump(exclude=excluded) != fresh.model_dump(
                exclude=excluded
            ):
                reasons.append(
                    "Source metadata differs from the saved artifact; review this release"
                )
            if reasons:
                await reject_candidate(db, operation, row.id, reasons)
                return
            payload = deepcopy(operation.payload)
            if str(row.id) not in payload["inspected"]:
                payload["inspected"].append(str(row.id))
            payload["token"] = None
            primary_formats = EBOOKS if rule["medium"] == "ebook" else AUDIO
            payload.setdefault("verified", {})[str(row.id)] = {
                "artifact_id": str(artifact.id),
                "release": fresh.model_dump(mode="json"),
                "formats": sorted(
                    {PurePosixPath(f.path).suffix.lower().lstrip(".") for f in descriptor.files}
                    & primary_formats
                ),
            }
            for decision in payload["decisions"]:
                if decision["result_id"] == str(row.id):
                    decision["reasons"] = []
                    decision["inspected"] = True
            operation.payload = payload
            remaining = eligible_candidates(
                await candidates(db, operation, work, profile, rule, version), payload
            )
            if remaining and remaining[0][1].id != row.id:
                operation.status, operation.message = (
                    "queued",
                    "Inspected formats changed the ranking; checking the next candidate",
                )
                operation.job_id = await enqueue(db, KIND, operation_id=str(identifier))
                return
            async with db.begin_nested():
                selected = await prepare(
                    db,
                    user,
                    SelectionInput(
                        intent_id=body.intent_id,
                        slot=body.slot,
                        artifact_id=artifact_id,
                        downloader_id=body.downloader_id,
                        downloader_generation=body.downloader_generation,
                        destination_id=body.destination_id,
                        destination_revision=body.destination_revision,
                        confirmed_work_id=work.id,
                        profile_id=profile.id,
                        profile_generation=profile.generation,
                    ),
                    child_key,
                    automatic_evidence={
                        "operation_id": str(identifier),
                        "search_id": str(body.search_id),
                        "result_id": str(row.id),
                        "maximum_bytes": operation.payload["maximum_bytes"],
                        "inspections": len(payload["inspected"]),
                        "reported_seeders": fresh.seeders,
                        "source_observed_at": fresh.observed_at.isoformat(),
                        "inspected_formats": payload["verified"][str(row.id)]["formats"],
                        "scope": "Fetched source page; single-book manifest; "
                        "actual file identity checked after downloading",
                    },
                )
            operation.payload = {**operation.payload, "selection_id": str(selected.id)}
            finish(
                operation, "completed", "Best eligible release prepared; download has not started"
            )
        except (HTTPException, AdapterError) as error:
            finish(
                operation,
                "completed" if isinstance(error, AlreadyAvailable) else "held",
                str(error.detail) if isinstance(error, HTTPException) else str(error),
            )
