from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.dependencies import CurrentUser, Database, Member
from app.db.models import AcquisitionProfile, AuditEvent
from app.domain.operations import transaction_lock
from app.domain.release_profiles import ProfileSnapshot, ReleasePreferences

router = APIRouter(prefix="/acquisition/profiles", tags=["acquisition-profiles"])


class ProfileInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    preferences: ReleasePreferences = Field(default_factory=ReleasePreferences)
    expected_generation: int = Field(default=0, ge=0)


def view(row):
    return ProfileSnapshot(
        id=row.id, generation=row.generation, name=row.name, preferences=row.preferences
    )


@router.get("", response_model=list[ProfileSnapshot])
async def profiles(user: CurrentUser, db: Database):
    return [
        ProfileSnapshot(preferences=ReleasePreferences()),
        *(
            view(row)
            for row in await db.scalars(
                select(AcquisitionProfile)
                .where(AcquisitionProfile.owner_id == user.id)
                .order_by(AcquisitionProfile.name, AcquisitionProfile.id)
            )
        ),
    ]


@router.post("", response_model=ProfileSnapshot, status_code=201)
async def create(body: ProfileInput, user: Member, db: Database):
    if body.expected_generation != 0 or not body.name.strip():
        raise HTTPException(422, "Use a nonempty name and revision zero for a new profile")
    row = AcquisitionProfile(
        owner_id=user.id,
        name=body.name.strip(),
        generation=1,
        preferences=body.preferences.model_dump(mode="json"),
    )
    db.add(row)
    await db.flush()
    db.add(AuditEvent(actor_id=user.id, action="acquisition.profile.created", entity_id=row.id))
    await db.commit()
    return view(row)


@router.put("/{profile_id}", response_model=ProfileSnapshot)
async def update(profile_id: UUID, body: ProfileInput, user: Member, db: Database):
    await transaction_lock(db, f"profile:{profile_id}")
    row = await db.get(AcquisitionProfile, profile_id, populate_existing=True)
    if not row or row.owner_id != user.id:
        raise HTTPException(404, "Acquisition profile not found")
    if row.generation != body.expected_generation:
        raise HTTPException(409, "Profile changed. Reload before saving.")
    if not body.name.strip():
        raise HTTPException(422, "Enter a profile name")
    row.name, row.preferences = body.name.strip(), body.preferences.model_dump(mode="json")
    row.generation += 1
    db.add(AuditEvent(actor_id=user.id, action="acquisition.profile.updated", entity_id=row.id))
    await db.commit()
    return view(row)
