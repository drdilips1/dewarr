"""Owner-scoped defaults, with separate administrator-owned installation defaults."""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.dependencies import Database, Member
from app.db.models import AcquisitionDefaults, AuditEvent, User
from app.domain.operations import transaction_lock
from app.domain.release_profiles import (
    DEFAULTS_LOCK,
    PreferenceOverrides,
    ReleasePreferences,
    default_layers,
    resolve_preferences,
)
from app.importing.naming import fingerprint

router = APIRouter(prefix="/acquisition/preferences", tags=["acquisition-preferences"])
Scope = Literal["personal", "installation"]


class DefaultsView(BaseModel):
    overrides: PreferenceOverrides
    effective: ReleasePreferences
    inherited: ReleasePreferences
    inherited_origins: dict[str, str]
    origins: dict[str, str]
    revision: str


class SaveDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")
    overrides: PreferenceOverrides
    expected_revision: str = Field(pattern=r"^[a-f0-9]{64}$")


async def context(db, user, scope):
    actor = await db.get(User, user.id, with_for_update={"read": True}, populate_existing=True)
    if not actor or not actor.active or actor.role not in {"admin", "member"}:
        raise HTTPException(403, "Member access is required")
    if scope == "installation" and actor.role != "admin":
        raise HTTPException(403, "Administrator access is required")
    await transaction_lock(db, DEFAULTS_LOCK)
    key = "installation" if scope == "installation" else f"user:{user.id}"
    row = await db.scalar(select(AcquisitionDefaults).where(AcquisitionDefaults.key == key))
    return key, row


async def view(db, user, scope, row):
    effective, origins = resolve_preferences(
        await default_layers(db, user.id if scope == "personal" else None)
    )
    layers = await default_layers(db) if scope == "personal" else []
    inherited, inherited_origins = resolve_preferences(layers)
    overrides = row.preferences if row else {}
    return DefaultsView(
        overrides=overrides,
        effective=effective,
        inherited=inherited,
        inherited_origins=inherited_origins,
        origins=origins,
        revision=fingerprint(
            {
                "generation": row.generation if row else 0,
                "overrides": overrides,
                "effective": effective.model_dump(),
                "origins": origins,
            }
        ),
    )


@router.get("/{scope}", response_model=DefaultsView)
async def read(scope: Scope, user: Member, db: Database):
    _, row = await context(db, user, scope)
    return await view(db, user, scope, row)


@router.put("/{scope}", response_model=DefaultsView)
async def save(scope: Scope, body: SaveDefaults, user: Member, db: Database):
    key, row = await context(db, user, scope)
    previous = await view(db, user, scope, row)
    if previous.revision != body.expected_revision:
        raise HTTPException(409, "Download defaults changed; reload before saving")
    if not row:
        row = AcquisitionDefaults(
            key=key, owner_id=user.id if scope == "personal" else None, generation=0
        )
        db.add(row)
    row.preferences = body.overrides.model_dump()
    row.generation += 1
    db.add(
        AuditEvent(
            actor_id=user.id,
            action="acquisition.defaults.updated",
            detail={"scope": scope, "generation": row.generation},
        )
    )
    await db.flush()
    current = await view(db, user, scope, row)
    await db.commit()
    return current
