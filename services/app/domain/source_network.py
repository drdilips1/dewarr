"""Shared source sessions: short database transactions surround bounded HTTP calls."""

import asyncio
import math
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException

from app.adapters.contracts import AdapterError, FailureKind
from app.adapters.mam import MAMClient, stored_automation
from app.db.models import SourceConnection, User
from app.db.session import session_factory
from app.domain.operations import transaction_lock
from app.security import decrypt_secrets, encrypt_secrets

REQUEST_INTERVAL = 2.0
LEASE_SECONDS = 90


async def check_actor(db, user_id, *, admin=False):
    user = await db.get(User, user_id, populate_existing=True)
    if not user or not user.active:
        raise HTTPException(401, "Your account is no longer active")
    if admin and user.role != "admin":
        raise HTTPException(403, "Administrator access is required")


async def source_call(
    user_id,
    operation,
    argument=None,
    *,
    with_generation=False,
    expected_generation=None,
    recovery_guard=None,
):
    token = uuid4()
    async with session_factory()() as db, db.begin():
        await check_actor(db, user_id, admin=operation in {"test", "maintain"})
        await transaction_lock(db, "source:mam")
        if recovery_guard is not None:
            await recovery_guard(db)
        row = await db.get(SourceConnection, "mam")
        if not row or not row.enabled:
            raise HTTPException(409, "An administrator must connect and enable MAM first")
        if expected_generation is not None and row.generation != expected_generation:
            raise HTTPException(409, "MAM settings changed. Search again.")
        now = datetime.now(UTC)
        if row.lease_token:
            if row.lease_until and row.lease_until > now:
                raise AdapterError(
                    FailureKind.RATE_LIMIT,
                    "MAM is handling another request. Retry shortly.",
                    retry_after=2,
                )
            raise HTTPException(
                409,
                "MAM session recovery is required after an interrupted request. "
                "Enter a current mam_id to reconnect.",
            )
        due = max(row.next_request_at or now, row.blocked_until or now, now)
        wait = (due - now).total_seconds()
        if wait > 5:
            raise AdapterError(
                FailureKind.RATE_LIMIT,
                "MAM is cooling down. Wait before retrying.",
                retry_after=math.ceil(wait),
            )
        lease_for = {"resolve": 120, "maintain": 180}.get(operation, LEASE_SECONDS)
        row.lease_token, row.lease_until = token, now + timedelta(seconds=lease_for)
        row.next_request_at = due + timedelta(seconds=REQUEST_INTERVAL)
        generation, endpoint, proxy = row.generation, row.base_url, row.proxy_url
        automation = stored_automation(row.automation)
        secrets = decrypt_secrets(row.encrypted_secrets)
    client = None
    failure = None
    value = None
    try:
        if wait:
            await asyncio.sleep(wait)
        client = MAMClient(
            endpoint,
            secrets["mam_id"],
            proxy_url=proxy,
            proxy_username=secrets.get("proxy_username"),
            proxy_password=secrets.get("proxy_password"),
            request_interval=REQUEST_INTERVAL,
        )
        client.automation = automation
        async with client:
            value = (
                await getattr(client, operation)(argument)
                if argument is not None
                else await client.test()
            )
    except AdapterError as error:
        failure = error
    except BaseException:
        # A process/task interrupted before reconciliation may have lost a rotated
        # session. Leave the lease for explicit credential recovery, not a blind replay.
        raise
    async with session_factory()() as db, db.begin():
        await transaction_lock(db, "source:mam")
        row = await db.get(SourceConnection, "mam")
        if not row or row.lease_token != token:
            raise HTTPException(409, "MAM connection changed during this request")
        row.lease_token, row.lease_until = None, None
        interval_deadline = datetime.now(UTC) + timedelta(seconds=REQUEST_INTERVAL)
        row.next_request_at = max(row.next_request_at or interval_deadline, interval_deadline)
        changed = row.generation != generation or not row.enabled
        current_secrets = decrypt_secrets(row.encrypted_secrets)
        same_session = (
            current_secrets.get("mam_id") == secrets["mam_id"]
            and row.base_url == endpoint
            and row.proxy_url == proxy
        )
        if same_session and client and client.rotated_cookie:
            row.encrypted_secrets = encrypt_secrets(
                {**current_secrets, "mam_id": client.rotated_cookie}
            )
        if client and client.cooldown:
            deadline = datetime.now(UTC) + timedelta(seconds=client.cooldown)
            row.blocked_until = max(row.blocked_until or deadline, deadline)
        if operation != "maintain" and not changed:
            row.status = failure.kind.value if failure else "connected"
            row.last_error = str(failure) if failure else None
            if not failure:
                row.last_success_at = datetime.now(UTC)
        if operation == "maintain" and argument is not None and same_session and not changed:
            from app.domain.account_automation import next_automation_state

            row.automation_state = next_automation_state(
                row.automation_state, argument, None if failure else value, datetime.now(UTC)
            )
        # Persist session rotation even if this request's reader lost access.
    if changed:
        raise HTTPException(
            409, "MAM connection changed during this request; retry with the current settings"
        )
    async with session_factory()() as db:
        await check_actor(db, user_id, admin=operation in {"test", "maintain"})
    if failure:
        raise failure
    return (value, generation) if with_generation else value
