import asyncio
import hashlib
import hmac
import json as json_module
import math
import re
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

from sqlalchemy import delete, select

from app.adapters.contracts import AdapterError, FailureKind
from app.adapters.http import JsonEndpoint
from app.config import get_settings
from app.db.models import ProviderBudget, ProviderCache
from app.db.session import session_factory
from app.domain.operations import transaction_lock

REQUEST_INTERVAL = 1.1


def retry_delay(headers, now):
    delays = []
    retry = headers.get("retry-after", "")
    if retry.isdigit():
        delays.append(int(retry))
    elif retry:
        try:
            delays.append(max(0, (parsedate_to_datetime(retry) - now).total_seconds()))
        except (TypeError, ValueError):
            pass
    for bucket in headers.get("ratelimit", "").split(","):
        remaining = re.search(r"(?:^|;)\s*r=(\d+)", bucket)
        reset = re.search(r"(?:^|;)\s*t=(\d+)", bucket)
        if remaining and reset and int(remaining[1]) == 0:
            delays.append(int(reset[1]))
    if headers.get("x-ratelimit-remaining") == "0":
        try:
            delays.append(max(0, float(headers["x-ratelimit-reset"]) - now.timestamp()))
        except (KeyError, ValueError):
            pass
    return min(max(delays, default=0), 7 * 86400)


class CatalogGateway:
    """Persisted HTTP cache and credential-wide budget; never hold a transaction over I/O."""

    def __init__(self, provider, scope, token=None, *, force=False, transport=None, cache=True):
        settings = get_settings()
        endpoint = settings.hardcover_url if provider == "hardcover" else settings.openlibrary_url
        self.http = JsonEndpoint(endpoint, token, transport=transport)
        self.provider, self.scope, self.force = provider, scope, force
        digest = hmac.new(
            settings.encryption_key(), (token or provider).encode(), hashlib.sha256
        ).hexdigest()
        self.budget_key = f"{provider}:{digest}"
        self.stale, self.warning, self.used_keys = False, None, []
        self.endpoint = endpoint
        self.cache = cache

    async def __aenter__(self):
        await self.http.__aenter__()
        return self

    async def __aexit__(self, *args):
        await self.http.__aexit__(*args)

    async def reserve(self):
        async with session_factory()() as db, db.begin():
            await transaction_lock(db, self.budget_key)
            budget = await db.get(ProviderBudget, self.budget_key)
            now = datetime.now(UTC)
            if not budget:
                budget = ProviderBudget(key=self.budget_key, next_request_at=now)
                db.add(budget)
            due = max(now, budget.next_request_at, budget.blocked_until or now)
            wait = (due - now).total_seconds()
            if wait > 5:
                raise AdapterError(
                    FailureKind.RATE_LIMIT,
                    "This provider is cooling down. Try again later.",
                    retry_after=math.ceil(wait),
                )
            budget.next_request_at = due + timedelta(seconds=REQUEST_INTERVAL)
        if wait > 0:
            await asyncio.sleep(wait)

    async def cooldown(self, delay):
        if not delay:
            return
        async with session_factory()() as db, db.begin():
            await transaction_lock(db, self.budget_key)
            record = await db.get(ProviderBudget, self.budget_key)
            deadline = datetime.now(UTC) + timedelta(seconds=delay)
            if record:
                record.blocked_until = max(record.blocked_until or deadline, deadline)

    async def request(self, method, path, *, params=None, json=None):
        material = [self.provider, self.endpoint, self.scope, method, path, params, json]
        key = hashlib.sha256(json_module.dumps(material, sort_keys=True).encode()).hexdigest()
        self.used_keys.append(key)
        now = datetime.now(UTC)
        async with session_factory()() as db:
            cached = await db.get(ProviderCache, key) if self.cache else None
            cached_value = cached.value if cached else None
            cached_at = cached.fetched_at if cached else None
            if cached and cached.expires_at > now and not self.force:
                return cached_value
        try:
            await self.reserve()
            try:
                response = await self.http.request(method, path, params=params, json=json)
            except AdapterError as error:
                delay = retry_delay(self.http.response_headers, datetime.now(UTC))
                if error.kind == FailureKind.RATE_LIMIT:
                    delay = max(delay, 60)
                await self.cooldown(delay)
                if delay:
                    error.retry_after = max(error.retry_after or 0, math.ceil(delay))
                raise
            await self.cooldown(retry_delay(self.http.response_headers, datetime.now(UTC)))
        except AdapterError as error:
            if (
                cached_value
                and cached_at > now - timedelta(days=7)
                and error.kind
                in {
                    FailureKind.TIMEOUT,
                    FailureKind.ROUTE,
                    FailureKind.UNAVAILABLE,
                    FailureKind.RATE_LIMIT,
                }
            ):
                self.stale = True
                self.warning = "Provider unavailable; showing previously cached catalog data."
                return cached_value
            raise
        if not self.cache:
            return response
        data = response.get("data")
        search = data.get("search") if isinstance(data, dict) else None
        if (
            response.get("errors")
            or response.get("error")
            or (isinstance(search, dict) and search.get("error"))
            or ("data" in response and not isinstance(data, dict))
        ):
            return response
        is_search = path == "search.json" or (json and "CatalogSearch" in json.get("query", ""))
        async with session_factory()() as db, db.begin():
            await transaction_lock(db, "cache:" + key)
            record = await db.get(ProviderCache, key)
            if not record:
                record = ProviderCache(key=key)
                db.add(record)
            record.value, record.fetched_at = response, now
            record.expires_at = now + timedelta(seconds=300 if is_search else 3600)
            expired = (
                select(ProviderCache.key)
                .where(ProviderCache.expires_at < now - timedelta(days=7))
                .limit(100)
            )
            await db.execute(delete(ProviderCache).where(ProviderCache.key.in_(expired)))
        return response

    async def invalidate(self):
        async with session_factory()() as db, db.begin():
            await db.execute(delete(ProviderCache).where(ProviderCache.key.in_(self.used_keys)))
