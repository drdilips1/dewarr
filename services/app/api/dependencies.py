import hmac
import re
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import LoginSession, User
from app.db.session import database
from app.recovery import active_restore, restore_pending
from app.security import csrf_token, token_hash

Database = Annotated[AsyncSession, Depends(database)]
COOKIE = "book_session"


def require_origin(request: Request) -> None:
    if request.headers.get("origin") != get_settings().public_url:
        raise HTTPException(403, "The request origin is not allowed")


async def current_user(request: Request, db: Database) -> User:
    raw = request.cookies.get(COOKIE)
    if not raw:
        raise HTTPException(401, "Sign in to continue")
    user = await db.scalar(
        select(User)
        .join(LoginSession, User.id == LoginSession.user_id)
        .where(
            LoginSession.token_hash == token_hash(raw),
            LoginSession.expires_at > datetime.now(UTC),
            User.active.is_(True),
        )
    )
    if not user:
        raise HTTPException(401, "Your session has expired. Sign in again")
    checkpoint = await active_restore(db)
    if checkpoint and user.id != checkpoint.operator_id:
        raise HTTPException(401, "Sign in as the designated recovery operator")
    if await restore_pending(db):
        allowed = {
            ("GET", "/api/auth/me"),
            ("POST", "/api/auth/logout"),
            ("GET", "/api/recovery"),
            ("POST", "/api/recovery/scans"),
            ("POST", "/api/recovery/reconciliations"),
            ("POST", "/api/recovery/inventory-reconciliations"),
            ("POST", "/api/recovery/publication-reconciliations"),
            ("POST", "/api/recovery/list-reconciliations"),
            ("POST", "/api/recovery/outbound-reconciliations"),
            ("POST", "/api/recovery/command-reconciliations"),
            ("POST", "/api/recovery/access-reconciliations"),
        }
        report_read = request.method == "GET" and bool(
            re.fullmatch(
                r"/api/recovery/scans/[0-9a-f-]{36}(?:/findings/[0-9a-f-]{36})?", request.url.path
            )
        )
        review_action = bool(
            re.fullmatch(
                r"/api/recovery/(?:reconciliations|inventory-reconciliations|publication-reconciliations|list-reconciliations|outbound-reconciliations|command-reconciliations|access-reconciliations)/[0-9a-f-]{36}",
                request.url.path,
            )
            and request.method == "GET"
            or re.fullmatch(
                r"/api/recovery/(?:reconciliations|inventory-reconciliations|publication-reconciliations|list-reconciliations|outbound-reconciliations|command-reconciliations|access-reconciliations)/[0-9a-f-]{36}/accept",
                request.url.path,
            )
            and request.method == "POST"
        )
        if user.role != "admin" or (
            (request.method, request.url.path) not in allowed
            and not report_read
            and not review_action
        ):
            raise HTTPException(423, "Recovery review is active; application actions are paused")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_origin(request)
        if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), csrf_token(raw)):
            raise HTTPException(403, "Refresh this page before trying again")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require_admin(user: CurrentUser) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Administrator access is required")
    return user


Admin = Annotated[User, Depends(require_admin)]


def require_member(user: CurrentUser) -> User:
    if user.role == "viewer":
        raise HTTPException(403, "This account has read-only access")
    return user


Member = Annotated[User, Depends(require_member)]
