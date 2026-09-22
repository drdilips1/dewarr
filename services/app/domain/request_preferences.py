"""Resolve ordinary preferences while retaining independent, frozen request restrictions."""

from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select

from app.db.models import AcquisitionIntent, BookList, ListAcquisitionPolicy, Operation
from app.domain import request_scope
from app.domain.release_profiles import (
    PreferenceOverrides,
    ProfileSnapshot,
    ReleasePreferences,
    overlay_profile,
    profile_snapshot,
    refresh_profile,
    same_profile,
)
from app.domain.request_constraints import combine
from app.domain.work_graph import canonical_work


class PreferenceChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_id: UUID | None = None
    profile_generation: int | None = Field(default=None, ge=0)
    profile_effective_revision: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    overrides: PreferenceOverrides = Field(default_factory=PreferenceOverrides)


async def resolve(db, user, specification, reason, choice=None, *, frozen=None, expected=None):
    from app.domain.acquisition import RequestSpec

    if frozen is not None:
        profile = ProfileSnapshot.model_validate(frozen)
    else:
        choice = choice or PreferenceChoice()
        inherited = None
        if reason and reason.list_id:
            item = await db.scalar(
                select(BookList)
                .where(BookList.id == reason.list_id, BookList.owner_id == user.id)
                .with_for_update()
            )
            if not item:
                raise HTTPException(404, "List not found")
            policy = await db.scalar(
                select(ListAcquisitionPolicy).where(ListAcquisitionPolicy.list_id == item.id)
            )
            if policy:
                inherited = ProfileSnapshot.model_validate(policy.configuration["profile"])
        explicit = "profile_id" in choice.model_fields_set
        base = await profile_snapshot(
            db,
            user.id,
            choice.profile_id if explicit or not inherited else inherited.id,
            choice.profile_generation if explicit or not inherited else inherited.generation,
            choice.profile_effective_revision
            if explicit or not inherited
            else (inherited.base_effective_revision or inherited.effective_revision),
        )
        profile = overlay_profile(
            base,
            list_overrides=inherited.list_overrides if inherited else None,
            request_overrides={
                **choice.overrides.model_dump(mode="json"),
                **request_scope.overrides(specification),
            },
        )
    if expected is not None and profile.effective_revision != expected:
        raise HTTPException(409, "Request preferences changed; preview this request again")
    if frozen is None:
        specification, origins = request_scope.specification(specification, profile)
        profile = profile.model_copy(update={"scope_origins": origins})
    values = specification.model_dump(mode="json")
    values["download_constraints"] = combine(
        values.get("download_constraints"),
        profile.preferences.model_dump(include={"blocked_formats", "maximum_bytes"}),
    )
    try:
        resolved = RequestSpec.model_validate(values)
    except ValidationError:
        raise HTTPException(
            422, "Preferences must allow a format for every requested medium"
        ) from None
    return resolved, profile


def policy_identity(profile):
    # Preserve legacy built-in request deduplication, while separate non-equivalent
    # policies retain their own intents/reasons and may share eligible reservations.
    values = profile.preferences.model_dump(
        exclude=set(request_scope.SCOPE_FIELDS.values()), mode="json"
    )
    defaults = ReleasePreferences().model_dump(
        exclude=set(request_scope.SCOPE_FIELDS.values()), mode="json"
    )
    if profile.id is None and values == defaults:
        return None
    return {
        "profile_id": str(profile.id) if profile.id else None,
        "generation": profile.generation,
        "preferences": values,
    }


async def owned_request(db, user, request_id, work_id):
    intent = await db.get(AcquisitionIntent, request_id)
    if not intent or intent.owner_id != user.id:
        raise HTTPException(404, "Request not found")
    if (await canonical_work(db, intent.work_id)).id != (await canonical_work(db, work_id)).id:
        raise HTTPException(409, "Request does not match this book")
    from app.domain.permissions import require_download_allowed

    await require_download_allowed(db, user, intent)
    return intent


async def for_intent(db, user, intent, body):
    inherited = (
        ProfileSnapshot.model_validate(intent.release_policy)
        if intent and intent.release_policy
        else None
    )
    explicit = "profile_id" in body.model_fields_set
    base = await profile_snapshot(
        db,
        user.id,
        body.profile_id if explicit or not inherited else inherited.id,
        body.profile_generation if explicit or not inherited else inherited.generation,
        body.profile_effective_revision,
    )
    overrides = (
        inherited.request_overrides.model_dump()
        if inherited and inherited.request_overrides
        else {}
    )
    if getattr(body, "preference_overrides", None):
        overrides.update(body.preference_overrides.model_dump())
    profile = overlay_profile(
        base,
        list_overrides=inherited.list_overrides if inherited else None,
        request_overrides=overrides,
    )
    return profile.model_copy(
        update={"scope_origins": inherited.scope_origins if inherited else {}}
    )


async def for_selection(db, user, intent, body):
    if not body.search_id:
        return await for_intent(db, user, intent, body)
    search = await db.get(Operation, body.search_id)
    if not search or search.kind != "sources.search" or search.owner_id != user.id:
        raise HTTPException(404, "Source search not found")
    if (await canonical_work(db, UUID(search.payload["work"]["id"]))).id != (
        await canonical_work(db, intent.work_id)
    ).id:
        raise HTTPException(409, "Source search does not match this request")
    bound = search.payload.get("command", {}).get("request_id")
    if bound and bound != str(intent.id):
        raise HTTPException(409, "Source search belongs to a different request")
    frozen = ProfileSnapshot.model_validate(search.payload["profile"])
    if body.profile_id is not None and body.profile_id != frozen.id:
        raise HTTPException(409, "Selected profile does not match the saved source search")
    if body.profile_generation is not None and body.profile_generation != frozen.generation:
        raise HTTPException(409, "Profile revision does not match the saved source search")
    if body.profile_effective_revision is not None and body.profile_effective_revision not in {
        frozen.base_effective_revision,
        frozen.effective_revision,
    }:
        raise HTTPException(409, "Preferences do not match the saved source search")
    current = await refresh_profile(db, user.id, frozen)
    if not same_profile(current, frozen):
        raise HTTPException(409, "Download preferences changed; refresh the source search")
    return frozen
