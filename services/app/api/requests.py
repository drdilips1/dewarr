from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.api.dependencies import CurrentUser, Database, Member
from app.api.operations import OperationView
from app.db.models import (
    AcquisitionIntent,
    AcquisitionReason,
    AcquisitionSelection,
    AcquisitionTarget,
    AuditEvent,
    BookList,
    Operation,
    Version,
)
from app.domain.acquisition import (
    RequestOptions,
    RequestReason,
    RequestSpec,
    assess,
    evaluate,
    submit,
    validate_request,
)
from app.domain.release_profiles import ProfileSnapshot
from app.domain.request_preferences import PreferenceChoice, resolve
from app.domain.work_graph import acquisition_lock, canonical_work, family_ids

router = APIRouter(prefix="/requests", tags=["requests"])


class RequestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    work_id: UUID
    specification: RequestOptions
    reason: RequestReason = Field(default_factory=RequestReason)
    release_preferences: PreferenceChoice | None = None
    expected_preference_revision: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class TargetView(BaseModel):
    slot: str
    state: str
    message: str
    source_artifact_id: UUID | None = None


class ReasonView(BaseModel):
    label: str
    id: UUID
    kind: str
    active: bool
    list_id: UUID | None
    release_policy: ProfileSnapshot | None = None


class RequestView(BaseModel):
    id: UUID
    work_id: UUID
    work_title: str
    specification: RequestSpec
    targets: list[TargetView]
    reasons: list[ReasonView]
    description: str
    release_policy: ProfileSnapshot | None = None


class PreviewView(BaseModel):
    specification: RequestSpec
    targets: list[TargetView]
    download_available: bool = False
    release_policy: ProfileSnapshot | None = None


class SubmittedView(BaseModel):
    request: RequestView
    operation: OperationView


class RequestPage(BaseModel):
    items: list[RequestView]
    total: int
    offset: int
    limit: int


async def owned_intent(db, user, intent_id):
    intent = await db.scalar(
        select(AcquisitionIntent).where(
            AcquisitionIntent.id == intent_id,
            AcquisitionIntent.owner_id == user.id,
        )
    )
    if not intent:
        raise HTTPException(404, "Request not found")
    return intent


async def view(db, user, intent):
    # Refresh only the display projection here; dispatch must evaluate under the work lock.
    spec = RequestSpec.model_validate(intent.specification)
    reasons = (
        await db.scalars(
            select(AcquisitionReason)
            .where(
                AcquisitionReason.intent_id == intent.id,
            )
            .order_by(AcquisitionReason.created_at, AcquisitionReason.id)
        )
    ).all()
    active = any(reason.active for reason in reasons)
    descriptions = []
    work_title = "Unavailable book"
    try:
        if user.role == "viewer":
            raise HTTPException(403, "Read-only account")
        work_title = (await validate_request(db, user, intent.work_id, spec)).title
        for medium in ("ebook", "audio"):
            version_id = getattr(spec, medium + "_version_id")
            if version_id:
                version = await db.get(Version, version_id)
                descriptors = [
                    version.title,
                    ", ".join(version.narrators),
                    str(version.publication_year) if version.publication_year else None,
                ]
                descriptions.append(
                    " · ".join(value for value in descriptors if value) or "Selected version"
                )
        targets = [TargetView(**item) for item in await assess(db, user, intent.work_id, spec)]
        for target in targets:
            if not active:
                target.state, target.message = "cancelled", "No active request reasons"
            elif target.state == "wanted":
                target.message = "Saved to wanted; choose a source release to continue"
                selection = await db.scalar(
                    select(AcquisitionSelection)
                    .join(
                        AcquisitionTarget,
                        AcquisitionTarget.reservation_id == AcquisitionSelection.reservation_id,
                    )
                    .where(
                        AcquisitionTarget.intent_id == intent.id,
                        AcquisitionTarget.slot == target.slot,
                        AcquisitionSelection.state.in_(["prepared", "committed"]),
                    )
                )
                if selection:
                    target.message = (
                        "Acquisition pending; check download activity"
                        if selection.state == "committed"
                        else "Release selected; download has not started"
                    )
                    if selection.owner_id == user.id:
                        target.source_artifact_id = selection.artifact_id
    except HTTPException:
        targets = [
            TargetView(slot=slot, state="paused", message="Request access needs attention")
            for slot in spec.slots()
        ]
    return RequestView(
        id=intent.id,
        work_id=(await canonical_work(db, intent.work_id)).id,
        work_title=work_title,
        specification=spec,
        release_policy=intent.release_policy,
        description="; ".join(
            descriptions
            + (["Language: " + spec.language] if spec.language else [])
            + (["Standalone copy"] if spec.standalone else [])
        )
        or "Any acceptable version",
        targets=targets,
        reasons=[
            ReasonView(
                id=reason.id,
                kind=reason.kind,
                active=reason.active,
                list_id=reason.list_id,
                release_policy=reason.release_policy,
                label="Series: "
                + ((await db.get(Operation, UUID(reason.reference))).payload["series"]["name"])
                if reason.kind == "series"
                else "Your request"
                if reason.kind == "manual"
                else (
                    await db.scalar(select(BookList.name).where(BookList.id == reason.list_id))
                    or "Former list"
                ),
            )
            for reason in reasons
        ],
    )


@router.post("/preview", response_model=PreviewView)
async def preview(body: RequestInput, user: CurrentUser, db: Database):
    specification, profile = await resolve(
        db, user, body.specification, body.reason, body.release_preferences
    )
    await validate_request(db, user, body.work_id, specification, body.reason)
    return PreviewView(
        specification=specification,
        release_policy=profile,
        targets=[
            TargetView(**item)
            for item in await assess(
                db,
                user,
                body.work_id,
                specification,
            )
        ],
    )


@router.post("", response_model=SubmittedView, status_code=202)
async def create(
    body: RequestInput,
    user: Member,
    db: Database,
    idempotency_key: str = Header(min_length=8, max_length=200),
):
    intent, operation = await submit(
        db,
        user,
        body.work_id,
        body.specification,
        body.reason,
        idempotency_key,
        preference_choice=body.release_preferences,
        expected_preference_revision=body.expected_preference_revision,
    )
    response = SubmittedView(
        request=await view(db, user, intent), operation=OperationView.model_validate(operation)
    )
    await db.commit()
    return response


@router.get("", response_model=RequestPage)
async def all_requests(
    user: CurrentUser,
    db: Database,
    work_id: UUID | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
):
    where = [AcquisitionIntent.owner_id == user.id]
    if work_id:
        where.append(AcquisitionIntent.work_id.in_(family_ids(work_id)))
    intents = (
        await db.scalars(
            select(AcquisitionIntent)
            .where(*where)
            .order_by(AcquisitionIntent.created_at.desc(), AcquisitionIntent.id)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    total = await db.scalar(select(func.count()).select_from(AcquisitionIntent).where(*where))
    return RequestPage(
        items=[await view(db, user, intent) for intent in intents],
        total=total or 0,
        offset=offset,
        limit=limit,
    )


@router.get("/{intent_id}", response_model=RequestView)
async def request_detail(intent_id: UUID, user: CurrentUser, db: Database):
    return await view(db, user, await owned_intent(db, user, intent_id))


@router.delete("/{intent_id}/reasons/{reason_id}", response_model=RequestView)
async def cancel_reason(intent_id: UUID, reason_id: UUID, user: Member, db: Database):
    intent = await owned_intent(db, user, intent_id)
    await acquisition_lock(db, intent.work_id)
    reason = await db.scalar(
        select(AcquisitionReason)
        .where(
            AcquisitionReason.id == reason_id,
            AcquisitionReason.intent_id == intent_id,
        )
        .execution_options(populate_existing=True)
    )
    if not reason:
        raise HTTPException(404, "Request reason not found")
    reason.active = False
    await db.flush()
    await evaluate(db, user, intent)
    db.add(AuditEvent(actor_id=user.id, action="acquisition.reason.cancelled", entity_id=reason.id))
    response = await view(db, user, intent)
    await db.commit()
    return response
