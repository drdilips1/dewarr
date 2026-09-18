from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.api.dependencies import Admin, Database
from app.db.models import AuditEvent, CapacitySettings, DownloadCapacity, User
from app.domain import capacity
from app.domain.operations import transaction_lock
from app.importing.naming import fingerprint

router = APIRouter(prefix="/acquisition/capacity", tags=["capacity"])


class CapacityView(BaseModel):
    limits: capacity.Limits
    revision: str
    occupied_slots: int
    reserved_bytes: int


class SaveCapacity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limits: capacity.Limits
    expected_revision: str = Field(pattern=r"^[a-f0-9]{64}$")


async def current(db):
    limits = await capacity.settings(db)
    occupied = await db.scalar(
        select(func.count())
        .select_from(DownloadCapacity)
        .where(DownloadCapacity.slot_active.is_(True))
    )
    return CapacityView(
        limits=limits,
        revision=fingerprint(limits.model_dump()),
        occupied_slots=occupied,
        reserved_bytes=sum((await capacity.reserved_bytes(db)).values()),
    )


@router.get("", response_model=CapacityView)
async def settings(admin: Admin, db: Database):
    return await current(db)


@router.put("", response_model=CapacityView)
async def save(body: SaveCapacity, admin: Admin, db: Database):
    actor = await db.get(User, admin.id, with_for_update={"read": True}, populate_existing=True)
    if not actor or not actor.active or actor.role != "admin":
        raise HTTPException(403, "Administrator access is required")
    await transaction_lock(db, capacity.LOCK)
    previous = await capacity.settings(db)
    if fingerprint(previous.model_dump()) != body.expected_revision:
        raise HTTPException(409, "Capacity settings changed; reload before saving")
    row = await db.get(CapacitySettings, 1)
    if not row:
        row = CapacitySettings(id=1)
        db.add(row)
    row.configuration = body.limits.model_dump()
    db.add(
        AuditEvent(
            actor_id=admin.id,
            action="acquisition.capacity.updated",
            detail={"revision": fingerprint(row.configuration)},
        )
    )
    await db.commit()
    return await current(db)
