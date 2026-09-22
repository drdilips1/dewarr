"""Optional Plex sign-in. Off until an administrator links one server."""

import logging
from types import SimpleNamespace
from uuid import uuid4

from cryptography.fernet import InvalidToken
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError

from app.api.auth import FINISH, enforce_auth_budget, start_session, write_handoff
from app.api.dependencies import Admin, Database, client_host
from app.config import get_settings
from app.db.models import PlexLogin
from app.domain.plex import (
    MACHINE_ID,
    PICKER_LIMIT,
    PlexRejected,
    authorization_url,
    create_pin,
    exchange,
    identity,
    resolve_user,
)
from app.security import decrypt_secrets, encrypt_secrets, token_hash

router = APIRouter(prefix="/auth", tags=["authentication"])
logger = logging.getLogger(__name__)
PLEX_COOKIE = "book_plex"
PLEX_PATH = "/api/auth/plex"
ERRORS = {
    "denied": "Plex did not sign you in.",
    "mismatch": "That sign-in attempt expired. Try again.",
    "rejected": "This Plex account cannot sign in.",
    "unavailable": "Plex could not be reached.",
    "paused": "Sign-in is paused during recovery review.",
    "limited": "Too many sign-in attempts. Try again in ten minutes.",
}


class PlexPublicView(BaseModel):
    enabled: bool


class PlexSettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    machine_id: str = Field(default="", max_length=80)
    auto_register: bool = False
    default_role: str = "member"


class PlexSettingsView(BaseModel):
    enabled: bool
    machine_id: str
    server_name: str
    auto_register: bool
    default_role: str


class PlexServerView(BaseModel):
    name: str
    machine_id: str


class PlexPendingView(BaseModel):
    servers: list[PlexServerView]


def settings_view(row: PlexLogin | None) -> PlexSettingsView:
    return PlexSettingsView(
        enabled=bool(row and row.enabled),
        machine_id=row.machine_id if row else "",
        server_name=row.server_name if row else "",
        auto_register=bool(row and row.auto_register),
        default_role=row.default_role if row else "member",
    )


def client_address(request: Request) -> str:
    return token_hash(client_host(request))


def read_transaction(request: Request) -> dict | None:
    raw = request.cookies.get(PLEX_COOKIE)
    if not raw:
        return None
    try:
        payload = decrypt_secrets(raw)
    except (InvalidToken, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def write_cookie(response: Response, payload: dict) -> None:
    response.set_cookie(
        PLEX_COOKIE,
        encrypt_secrets(payload),
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="lax",
        max_age=600,
        path=PLEX_PATH,
    )


def clear_cookie(response: Response) -> None:
    response.delete_cookie(
        PLEX_COOKIE, path=PLEX_PATH, secure=get_settings().cookie_secure, samesite="lax"
    )


def fail(code: str, *, settings_page: bool = False) -> RedirectResponse:
    if settings_page:
        target = f"/settings?plex_error={code}#accounts"
    else:
        target = f"/?plex_error={code}"
    response = RedirectResponse(target, status_code=303)
    clear_cookie(response)
    logger.info("Plex sign-in did not complete (%s)", code)
    return response


async def login_row(db: Database) -> PlexLogin | None:
    return await db.get(PlexLogin, 1)


def login_config(row: PlexLogin | None):
    if row is None:
        return None
    return SimpleNamespace(
        client_id=row.client_id,
        machine_id=row.machine_id,
        server_name=row.server_name,
        auto_register=row.auto_register,
        default_role=row.default_role,
        enabled=row.enabled,
    )


async def ensure_row(db: Database) -> PlexLogin:
    row = await login_row(db)
    if row is None:
        row = PlexLogin(
            id=1,
            enabled=False,
            client_id=str(uuid4()),
            machine_id="",
            server_name="",
            auto_register=False,
            default_role="member",
        )
        db.add(row)
        await db.commit()
    return row


def pending_servers(request: Request, admin_id: str) -> list[dict]:
    saved = read_transaction(request)
    if not saved or saved.get("purpose") != "choose" or saved.get("admin_id") != admin_id:
        return []
    servers = saved.get("servers")
    if not isinstance(servers, list):
        return []
    chosen = []
    for server in servers:
        if not isinstance(server, dict):
            continue
        machine_id = server.get("machine_id")
        name = server.get("name")
        if (
            isinstance(machine_id, str)
            and MACHINE_ID.fullmatch(machine_id)
            and isinstance(name, str)
            and name
        ):
            chosen.append({"name": name[:120], "machine_id": machine_id})
    return chosen


async def limited(
    request: Request, db: Database, key: str, *, settings_page: bool
) -> RedirectResponse | None:
    try:
        await enforce_auth_budget(db, key + client_address(request))
    except HTTPException as error:
        if error.status_code == 429:
            return fail("limited", settings_page=settings_page)
        raise
    return None


@router.get("/plex", response_model=PlexPublicView)
async def plex_status(db: Database) -> PlexPublicView:
    row = await login_row(db)
    return PlexPublicView(enabled=bool(row and row.enabled and row.machine_id))


@router.get("/plex/settings", response_model=PlexSettingsView)
async def plex_settings(admin: Admin, db: Database) -> PlexSettingsView:
    return settings_view(await login_row(db))


@router.put("/plex/settings", response_model=PlexSettingsView)
async def save_plex_settings(
    body: PlexSettingsInput, request: Request, response: Response, admin: Admin, db: Database
):
    if body.default_role not in {"member", "viewer"}:
        raise HTTPException(422, "New accounts start as members or viewers")
    machine_id = body.machine_id.strip()
    if machine_id and not MACHINE_ID.fullmatch(machine_id):
        raise HTTPException(422, "Choose a Plex server")
    row = await login_row(db)
    offered = pending_servers(request, str(admin.id))
    if machine_id and (row is None or machine_id != row.machine_id):
        match = next((server for server in offered if server["machine_id"] == machine_id), None)
        if match is None:
            raise HTTPException(422, "Link a Plex server again before choosing it")
        server_name = match["name"]
    else:
        machine_id = row.machine_id if row else ""
        server_name = row.server_name if row else ""
    if body.enabled and not machine_id:
        raise HTTPException(422, "Link a Plex server before enabling sign-in")
    if row is None:
        row = PlexLogin(id=1, client_id=str(uuid4()))
        db.add(row)
    row.enabled = body.enabled
    row.machine_id = machine_id
    row.server_name = server_name
    row.auto_register = body.auto_register
    row.default_role = body.default_role
    await db.commit()
    clear_cookie(response)
    return settings_view(row)


@router.get("/plex/pending", response_model=PlexPendingView)
async def plex_pending(request: Request, admin: Admin) -> PlexPendingView:
    return PlexPendingView(
        servers=[PlexServerView(**server) for server in pending_servers(request, str(admin.id))]
    )


@router.get("/plex/link")
async def link(request: Request, admin: Admin, db: Database):
    blocked = await limited(request, db, "plex-link:", settings_page=True)
    if blocked:
        return blocked
    row = await ensure_row(db)
    client_id, admin_id = row.client_id, str(admin.id)
    await db.rollback()
    try:
        pin_id, code = await create_pin(client_id)
    except PlexRejected as error:
        return fail(error.code if error.code in ERRORS else "unavailable", settings_page=True)
    response = RedirectResponse(authorization_url(client_id, code), status_code=302)
    write_cookie(response, {"purpose": "link", "pin_id": pin_id, "admin_id": admin_id})
    return response


@router.get("/plex/start")
async def start(request: Request, db: Database):
    blocked = await limited(request, db, "plex-start:", settings_page=False)
    if blocked:
        return blocked
    row = login_config(await login_row(db))
    await db.rollback()
    if not row or not row.enabled or not row.machine_id:
        raise HTTPException(404, "Plex sign-in is not enabled")
    try:
        pin_id, code = await create_pin(row.client_id)
    except PlexRejected as error:
        return fail(error.code if error.code in ERRORS else "unavailable")
    response = RedirectResponse(authorization_url(row.client_id, code), status_code=302)
    write_cookie(response, {"purpose": "login", "pin_id": pin_id})
    return response


@router.get("/plex/callback")
async def callback(request: Request, db: Database):
    saved = read_transaction(request)
    purpose = saved.get("purpose") if saved else None
    settings_page = purpose == "link"
    blocked = await limited(request, db, "plex-callback:", settings_page=settings_page)
    if blocked:
        return blocked
    if request.query_params.get("error"):
        return fail("denied", settings_page=settings_page)
    pin_id = saved.get("pin_id") if saved else None
    if purpose not in {"login", "link"} or type(pin_id) is not int or pin_id < 1:
        return fail("mismatch", settings_page=settings_page)
    row = login_config(await login_row(db))
    await db.rollback()
    client_id = row.client_id if row else ""
    if not client_id:
        return fail("denied", settings_page=settings_page)
    try:
        token = await exchange(client_id, pin_id)
        profile = await identity(client_id, token)
    except PlexRejected as error:
        return fail(
            error.code if error.code in ERRORS else "unavailable", settings_page=settings_page
        )
    if purpose == "link":
        if not profile["servers"]:
            return fail("rejected", settings_page=True)
        response = RedirectResponse("/settings#accounts", status_code=303)
        write_cookie(
            response,
            {
                "purpose": "choose",
                "admin_id": saved.get("admin_id"),
                "servers": profile["servers"][:PICKER_LIMIT],
            },
        )
        return response
    if not row or not row.enabled or not row.machine_id:
        return fail("denied")
    try:
        user = await resolve_user(db, row, profile)
    except PlexRejected as error:
        await db.rollback()
        return fail(error.code if error.code in ERRORS else "rejected")
    except IntegrityError:
        await db.rollback()
        return fail("rejected")
    try:
        token = await start_session(user, db)
    except HTTPException as error:
        if error.status_code == 423:
            return fail("paused")
        raise
    response = RedirectResponse(FINISH, status_code=303)
    clear_cookie(response)
    write_handoff(response, token)
    return response
