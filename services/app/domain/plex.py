"""Plex PIN sign-in. The Plex token is used for one membership check and is not stored."""

import asyncio
import re
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
from sqlalchemy import select, text

from app.config import get_settings
from app.db.models import AuditEvent, PlexIdentity, User
from app.domain.oidc import sanitize_username

MACHINE_ID = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
PIN_CODE = re.compile(r"^[A-Za-z0-9]{4,64}$")
MAX_BODY = 1_000_000
PICKER_LIMIT = 30
PIN_ATTEMPTS = 10
PIN_WAIT = 0.5


class PlexRejected(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def api_origin() -> str:
    return get_settings().plex_api_origin


def auth_origin() -> str:
    return get_settings().plex_auth_origin


def authorization_url(client_id: str, code: str) -> str:
    forward = get_settings().public_url + "/api/auth/plex/callback"
    query = urlencode(
        [
            ("clientID", client_id),
            ("code", code),
            ("context[device][product]", "Dewarr"),
            ("context[device][platform]", "Web"),
            ("forwardUrl", forward),
        ]
    )
    return auth_origin() + "/auth#?" + query


def servers_from(resources: object) -> list[dict[str, str]]:
    if not isinstance(resources, list):
        raise PlexRejected("unavailable")
    owned, shared = [], []
    seen = set()
    for item in resources:
        if not isinstance(item, dict):
            continue
        provides = item.get("provides")
        machine_id = item.get("clientIdentifier")
        if not isinstance(provides, str) or "server" not in provides.split(","):
            continue
        if not isinstance(machine_id, str) or not MACHINE_ID.fullmatch(machine_id):
            continue
        if machine_id in seen:
            continue
        seen.add(machine_id)
        name = item.get("name")
        label = " ".join(name.split()) if isinstance(name, str) else ""
        server = {"name": (label or "Plex")[:120], "machine_id": machine_id}
        if item.get("owned") is True:
            owned.append(server)
        else:
            shared.append(server)
    return owned + shared


def _same_origin(url: str, origin: str) -> bool:
    parts, root = urlsplit(url), urlsplit(origin)
    return (
        parts.scheme == root.scheme
        and parts.netloc == root.netloc
        and not parts.username
        and not parts.password
    )


async def fetch(method: str, url: str, client_id: str, *, token: str | None = None) -> Any:
    if not _same_origin(url, api_origin()):
        raise PlexRejected("rejected")
    headers = {
        "Accept": "application/json",
        "X-Plex-Product": "Dewarr",
        "X-Plex-Client-Identifier": client_id,
        "X-Plex-Version": "1",
        "X-Plex-Platform": "Web",
        "X-Plex-Device": "Dewarr",
    }
    if token:
        headers["X-Plex-Token"] = token
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            response = await client.request(method, url, headers=headers)
    except httpx.HTTPError:
        raise PlexRejected("unavailable") from None
    if response.is_redirect or response.status_code >= 500 or response.status_code == 429:
        raise PlexRejected("unavailable")
    if response.status_code >= 400 or len(response.content) > MAX_BODY:
        raise PlexRejected("rejected")
    try:
        return response.json()
    except ValueError:
        raise PlexRejected("unavailable") from None


async def create_pin(client_id: str) -> tuple[int, str]:
    body = await fetch("POST", api_origin() + "/api/v2/pins?strong=true", client_id)
    if not isinstance(body, dict):
        raise PlexRejected("unavailable")
    pin_id, code = body.get("id"), body.get("code")
    if (
        type(pin_id) is not int
        or pin_id < 1
        or not isinstance(code, str)
        or not PIN_CODE.fullmatch(code)
    ):
        raise PlexRejected("unavailable")
    return pin_id, code


async def exchange(client_id: str, pin_id: int) -> str:
    url = api_origin() + f"/api/v2/pins/{pin_id}"
    for attempt in range(PIN_ATTEMPTS):
        body = await fetch("GET", url, client_id)
        token = body.get("authToken") if isinstance(body, dict) else None
        if isinstance(token, str) and token.strip() and len(token) <= 512 and " " not in token:
            return token
        if attempt + 1 < PIN_ATTEMPTS:
            await asyncio.sleep(PIN_WAIT)
    raise PlexRejected("denied")


async def identity(client_id: str, token: str) -> dict[str, Any]:
    user = await fetch("GET", api_origin() + "/api/v2/user", client_id, token=token)
    resources = await fetch(
        "GET",
        api_origin() + "/api/v2/resources?includeHttps=1",
        client_id,
        token=token,
    )
    if not isinstance(user, dict):
        raise PlexRejected("rejected")
    user_id = user.get("id")
    if type(user_id) is not int or user_id < 1 or len(str(user_id)) > 20:
        raise PlexRejected("rejected")
    username = user.get("username") if isinstance(user.get("username"), str) else ""
    title = user.get("title") if isinstance(user.get("title"), str) else ""
    display = " ".join(title.split())[:120]
    return {
        "plex_user_id": str(user_id),
        "username": username,
        "display_name": display,
        "servers": servers_from(resources),
    }


def can_access(profile: dict[str, Any], machine_id: str) -> bool:
    return any(server["machine_id"] == machine_id for server in profile["servers"])


async def _unused_username(db, preferred: str, plex_user_id: str) -> str:
    base = sanitize_username(preferred, plex_user_id)
    candidate = base
    for count in range(2, 51):
        if not await db.scalar(select(User.id).where(User.username == candidate)):
            return candidate
        suffix = f"-{count}"
        candidate = base[: 100 - len(suffix)] + suffix
    raise PlexRejected("rejected")


async def resolve_user(db, login, profile: dict[str, Any]) -> User:
    plex_user_id = profile["plex_user_id"]
    if not can_access(profile, login.machine_id):
        raise PlexRejected("rejected")
    await db.execute(text("SELECT pg_advisory_xact_lock(720002)"))
    await db.execute(text("SELECT pg_advisory_xact_lock(720004)"))
    identity_row = await db.scalar(
        select(PlexIdentity).where(PlexIdentity.plex_user_id == plex_user_id)
    )
    if identity_row:
        user = await db.get(User, identity_row.user_id)
        if not user or not user.active:
            raise PlexRejected("rejected")
        return user
    if not login.auto_register:
        raise PlexRejected("rejected")
    username = await _unused_username(db, profile["username"], plex_user_id)
    user = User(
        username=username,
        display_name=profile["display_name"] or username,
        password_hash=None,
        role=login.default_role,
        can_automate=False,
    )
    db.add(user)
    await db.flush()
    db.add(PlexIdentity(user_id=user.id, plex_user_id=plex_user_id))
    db.add(
        AuditEvent(
            actor_id=user.id,
            action="plex.registered",
            entity_id=user.id,
        )
    )
    return user
