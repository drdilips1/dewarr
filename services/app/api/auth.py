import asyncio
import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert

from app.api.dependencies import COOKIE, Admin, CurrentUser, Database, require_origin
from app.config import get_settings
from app.db.models import AuditEvent, LoginSession, RateLimit, User
from app.recovery import active_restore, restore_pending
from app.security import csrf_token, hash_password, token_hash, verify_password

router = APIRouter(prefix="/auth", tags=["authentication"])


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=100, pattern=r"^[A-Za-z0-9_.@-]+$")
    password: str = Field(min_length=12, max_length=256)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.lower()


class BootstrapInput(Credentials):
    display_name: str = Field(min_length=1, max_length=120)


class UserInput(Credentials):
    display_name: str = Field(min_length=1, max_length=120)
    role: Literal["admin", "member", "viewer"] = "member"


class UserView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    username: str
    display_name: str
    role: str
    can_automate: bool
    onboarding_status: str = "pending"


class AuthView(BaseModel):
    user: UserView
    csrf_token: str
    recovery: bool = False


class SetupView(BaseModel):
    needs_setup: bool


def user_view(user: User) -> UserView:
    return UserView(
        id=str(user.id),
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        can_automate=user.can_automate,
        onboarding_status=(user.onboarding or {}).get("status", "pending"),
    )


async def enforce_auth_budget(db: Database, key: str) -> None:
    now = datetime.now(UTC)
    # Persist failures independently of the later authentication transaction.
    await db.execute(
        insert(RateLimit)
        .values(key=key, count=0, resets_at=now + timedelta(minutes=10))
        .on_conflict_do_nothing(index_elements=[RateLimit.key])
    )
    rate = await db.scalar(select(RateLimit).where(RateLimit.key == key).with_for_update())
    assert rate
    if rate.resets_at <= now:
        rate.count, rate.resets_at = 0, now + timedelta(minutes=10)
    rate.count += 1
    blocked = rate.count > 15
    await db.commit()
    if blocked:
        raise HTTPException(429, "Too many sign-in attempts. Try again in ten minutes")


async def establish_session(user: User, db: Database, response: Response) -> AuthView:
    settings = get_settings()
    checkpoint = await active_restore(db)
    recovering = await restore_pending(db)
    if recovering and (user.role != "admin" or (checkpoint and checkpoint.operator_id != user.id)):
        raise HTTPException(
            423, "Only the designated recovery operator can sign in during restore review"
        )
    token = secrets.token_urlsafe(48)
    db.add(
        LoginSession(
            token_hash=token_hash(token),
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(hours=settings.session_hours),
        )
    )
    await db.commit()
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        max_age=settings.session_hours * 3600,
        path="/",
    )
    return AuthView(user=user_view(user), csrf_token=csrf_token(token), recovery=recovering)


@router.get("/setup", response_model=SetupView)
async def setup_status(db: Database) -> SetupView:
    return SetupView(needs_setup=not bool(await db.scalar(select(func.count()).select_from(User))))


@router.post("/bootstrap", response_model=AuthView, status_code=201)
async def bootstrap(body: BootstrapInput, request: Request, response: Response, db: Database):
    require_origin(request)
    await enforce_auth_budget(db, "bootstrap")
    encoded = await asyncio.to_thread(hash_password, body.password)
    await db.execute(text("SELECT pg_advisory_xact_lock(720001)"))
    if await db.scalar(select(func.count()).select_from(User)):
        raise HTTPException(409, "Setup is already complete")
    user = User(
        username=body.username,
        display_name=body.display_name,
        password_hash=encoded,
        role="admin",
        can_automate=True,
    )
    db.add(user)
    await db.flush()
    db.add(AuditEvent(actor_id=user.id, action="admin.bootstrapped", entity_id=user.id))
    return await establish_session(user, db, response)


@router.post("/login", response_model=AuthView)
async def login(body: Credentials, request: Request, response: Response, db: Database):
    require_origin(request)
    await enforce_auth_budget(
        db, "ip:" + token_hash(request.client.host if request.client else "local")
    )
    await enforce_auth_budget(db, "login:" + token_hash(body.username))
    user = await db.scalar(select(User).where(User.username == body.username))
    encoded = user.password_hash if user and user.active else None
    await db.rollback()  # Password hashing must not hold a connection/transaction open.
    if not await asyncio.to_thread(verify_password, body.password, encoded):
        raise HTTPException(401, "Username or password is incorrect")
    user = await db.scalar(
        select(User).where(User.username == body.username, User.active.is_(True))
    )
    if not user or user.password_hash != encoded:
        raise HTTPException(401, "Username or password is incorrect")
    return await establish_session(user, db, response)


@router.get("/me", response_model=AuthView)
async def me(request: Request, user: CurrentUser, db: Database):
    return AuthView(
        user=user_view(user),
        csrf_token=csrf_token(request.cookies[COOKIE]),
        recovery=await restore_pending(db),
    )


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, user: CurrentUser, db: Database):
    await db.execute(
        delete(LoginSession).where(LoginSession.token_hash == token_hash(request.cookies[COOKIE]))
    )
    await db.commit()
    response.delete_cookie(COOKIE, path="/", secure=get_settings().cookie_secure, samesite="strict")


@router.get("/users", response_model=list[UserView])
async def users(admin: Admin, db: Database):
    return [
        user_view(user) for user in (await db.scalars(select(User).order_by(User.username))).all()
    ]


@router.post("/users", response_model=UserView, status_code=201)
async def create_user(body: UserInput, admin: Admin, db: Database):
    admin_id = admin.id
    await db.rollback()
    encoded = await asyncio.to_thread(hash_password, body.password)
    # Serialize account creation to turn a duplicate into a stable API conflict.
    await db.execute(text("SELECT pg_advisory_xact_lock(720002)"))
    if await db.scalar(select(User.id).where(User.username == body.username)):
        raise HTTPException(409, "That username is already in use")
    user = User(
        username=body.username,
        display_name=body.display_name,
        password_hash=encoded,
        role=body.role,
    )
    db.add(user)
    await db.flush()
    db.add(AuditEvent(actor_id=admin_id, action="user.created", entity_id=user.id))
    await db.commit()
    return user_view(user)


class AutomationPermissionInput(BaseModel):
    allowed: bool
    expected_allowed: bool


@router.put("/users/{user_id}/automation", response_model=UserView)
async def automation_permission(
    user_id: UUID, body: AutomationPermissionInput, admin: Admin, db: Database
):
    rows = {
        u.id: u
        for u in await db.scalars(
            select(User)
            .where(User.id.in_([admin.id, user_id]))
            .order_by(User.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    }
    actor = rows.get(admin.id)
    if not actor or not actor.active or actor.role != "admin":
        raise HTTPException(403, "Administrator access changed")
    user = rows.get(user_id)
    if not user:
        raise HTTPException(404, "Account not found")
    if user.role != "member":
        raise HTTPException(422, "List automation grants apply to member accounts")
    if user.can_automate != body.expected_allowed:
        raise HTTPException(409, "This permission changed; reload the account")
    user.can_automate = body.allowed
    db.add(
        AuditEvent(
            actor_id=admin.id,
            action="user.automation.changed",
            entity_id=user.id,
            detail={"allowed": body.allowed},
        )
    )
    await db.commit()
    return user_view(user)
