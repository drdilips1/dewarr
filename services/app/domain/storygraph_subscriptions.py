"""StoryGraph shelf and tag observation. A page is never proof a book was removed."""

import asyncio
import contextlib
import secrets
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.adapters.contracts import AdapterError, FailureKind
from app.adapters.storygraph import open_session, read_list, stored_target
from app.config import get_settings
from app.db.models import Operation, RateLimit, StorygraphAccount
from app.db.session import session_factory
from app.domain.list_subscriptions import apply_records, context, next_due, storygraph_budget
from app.domain.operations import transaction_lock
from app.jobs.retry import ShelfRetry
from app.security import decrypt_secrets, encrypt_secrets

RECONNECT = "Reconnect StoryGraph to keep this list updated"
BUSY = "StoryGraph is already being checked. Try again in a moment."
LIMITED = "StoryGraph is limiting requests. Try again in a moment."
FETCH_LEASE = 120
FETCH_BEAT = 30


def _fetch_key(user_id):
    return f"storygraph-fetch:{user_id}"


async def _claim_fetch(user_id, token):
    key = _fetch_key(user_id)
    now = datetime.now(UTC)
    async with session_factory()() as db, db.begin():
        await transaction_lock(db, key)
        row = await db.get(RateLimit, key)
        if row and row.resets_at > now:
            return False
        until = now + timedelta(seconds=FETCH_LEASE)
        if row:
            row.count, row.resets_at = token, until
        else:
            db.add(RateLimit(key=key, count=token, resets_at=until))
    return True


async def _extend_fetch(user_id, token):
    key = _fetch_key(user_id)
    async with session_factory()() as db, db.begin():
        await transaction_lock(db, key)
        row = await db.get(RateLimit, key)
        if not row or row.count != token:
            return False
        row.resets_at = datetime.now(UTC) + timedelta(seconds=FETCH_LEASE)
    return True


async def _release_fetch(user_id, token):
    key = _fetch_key(user_id)
    async with session_factory()() as db, db.begin():
        await transaction_lock(db, key)
        row = await db.get(RateLimit, key)
        if row and row.count == token:
            row.resets_at = datetime.now(UTC)


async def _beat_fetch(user_id, token):
    try:
        while True:
            await asyncio.sleep(FETCH_BEAT)
            try:
                held = await _extend_fetch(user_id, token)
            except asyncio.CancelledError:
                raise
            except Exception:
                continue
            if not held:
                return
    except asyncio.CancelledError:
        raise


@asynccontextmanager
async def fetch_lock(user_id, *, wait=True):
    """Serialize this user's StoryGraph HTTP so a rotated session is not overwritten."""
    token = secrets.randbelow(2_147_483_646) + 1
    while True:
        if await _claim_fetch(user_id, token):
            beat = asyncio.create_task(_beat_fetch(user_id, token))
            try:
                yield True
            finally:
                beat.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await beat
                await _release_fetch(user_id, token)
            return
        if not wait:
            yield False
            return
        await asyncio.sleep(2)


async def save_rotation(db, user_id, sent_cookie, rotated):
    if not rotated or rotated == sent_cookie:
        return
    account = await db.get(StorygraphAccount, user_id)
    if not account:
        return
    current = decrypt_secrets(account.encrypted_config)
    if current.get("session_cookie") != sent_cookie:
        return
    current["session_cookie"] = rotated
    account.encrypted_config = encrypt_secrets(current)


async def _claim(db, operation_id):
    operation = await db.get(Operation, operation_id)
    if operation:
        await transaction_lock(db, f"storygraph-account:{operation.owner_id}")
    return await context(db, operation_id)


async def run(operation_id):
    if get_settings().recovery_mode:
        raise ShelfRetry(60)
    token = uuid4()
    config = None
    owner_id = None
    wait = 0
    async with session_factory()() as db, db.begin():
        operation = await db.get(Operation, operation_id)
        if not operation:
            return
        owner_id = operation.owner_id
        await transaction_lock(db, f"storygraph-account:{owner_id}")
        ctx = await context(db, operation_id)
        if not ctx:
            return
        operation, row, _ = ctx
        if operation.status in {"completed", "failed"}:
            return
        now = datetime.now(UTC)
        if operation.created_at < now - timedelta(days=7):
            row.state, row.message, row.run_token = (
                "failed",
                "Shelf observation expired; retry with a new observation",
                None,
            )
            row.next_sync_at = next_due(row, now, failed=True)
            operation.status, operation.message = "failed", row.message
            return
        if row.run_token and row.lease_until and row.lease_until > now:
            raise ShelfRetry((row.lease_until - now).total_seconds() + 1)
        wait = await storygraph_budget(db, owner_id)
        if wait:
            row.run_token, row.state = None, "queued"
            operation.status = "queued"
            row.message = operation.message = "Waiting for the StoryGraph request budget"
        else:
            account = await db.get(StorygraphAccount, owner_id)
            if not account:
                row.state, row.message, row.run_token = "failed", RECONNECT, None
                row.failures += 1
                row.next_sync_at = next_due(row, now, failed=True)
                operation.status, operation.message = "failed", row.message
                return
            config = decrypt_secrets(row.encrypted_config)
            row.run_token, row.lease_until, row.state = (
                token,
                now + timedelta(minutes=2),
                "running",
            )
            operation.status = "running"
            row.message = operation.message = "Observing StoryGraph list additions"
    if wait:
        raise ShelfRetry(wait)
    if config is None or owner_id is None:
        return
    async with fetch_lock(owner_id, wait=False) as acquired:
        if not acquired:
            async with session_factory()() as db, db.begin():
                ctx = await _claim(db, operation_id)
                if ctx and ctx[1].run_token == token:
                    operation, row, _ = ctx
                    row.run_token, row.state = None, "queued"
                    operation.status = "queued"
                    row.message = operation.message = BUSY
            raise ShelfRetry(2)
        async with session_factory()() as db, db.begin():
            await transaction_lock(db, f"storygraph-account:{owner_id}")
            account = await db.get(StorygraphAccount, owner_id)
            if not account:
                ctx = await context(db, operation_id)
                if ctx and ctx[1].run_token == token:
                    operation, row, _ = ctx
                    row.state, row.message, row.run_token = "failed", RECONNECT, None
                    row.failures += 1
                    row.next_sync_at = next_due(row, datetime.now(UTC), failed=True)
                    operation.status, operation.message = "failed", row.message
                await storygraph_budget(db, owner_id, block=2, replace=True)
                return
            sent = decrypt_secrets(account.encrypted_config)
        sent_cookie = sent.get("session_cookie") if isinstance(sent, dict) else None
        live = {}
        try:
            page = await read_list(open_session(sent), stored_target(config), session_out=live)
        except AdapterError as error:
            spacing = (error.retry_after or 60) if error.kind == FailureKind.RATE_LIMIT else 2
            async with session_factory()() as db, db.begin():
                ctx = await _claim(db, operation_id)
                await save_rotation(db, owner_id, sent_cookie, live.get("session_cookie"))
                await storygraph_budget(db, owner_id, block=spacing, replace=True)
                if not ctx or ctx[1].run_token != token:
                    return
                operation, row, _ = ctx
                row.state, row.message, row.run_token = "failed", str(error), None
                row.failures += 1
                row.next_sync_at = next_due(
                    row, datetime.now(UTC), failed=True, retry_after=error.retry_after or 0
                )
                operation.status, operation.message = "failed", row.message
            return
        async with session_factory()() as db, db.begin():
            ctx = await _claim(db, operation_id)
            await save_rotation(db, owner_id, sent_cookie, page.session_cookie)
            await storygraph_budget(db, owner_id, block=2, replace=True)
            if not ctx or ctx[1].run_token != token:
                return
            operation, row, owner = ctx
            added = await apply_records(db, row, owner, page.items)
            now = datetime.now(UTC)
            note = (
                "This check did not reach the end of the list, so older entries may be missing."
                if page.partial
                else "Books left off a later check stay on this list."
            )
            row.baseline_at = row.baseline_at or now
            row.last_success_at, row.next_sync_at = now, next_due(row, now)
            row.state, row.failures, row.run_token = "idle", 0, None
            row.message = f"Observed {len(page.items)} books; {added} new. {note}"
            operation.status, operation.message = "completed", row.message
