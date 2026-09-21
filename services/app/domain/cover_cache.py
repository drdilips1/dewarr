"""Durable, content-validated artwork cache, shared across browser sessions."""

import base64
import hashlib
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Response

from app.db.models import ProviderCache
from app.domain.operations import transaction_lock
from app.importing.covers import CoverError, fetch_cover, validated_url


async def cached_cover(db, url):
    try:
        validated_url(url)
    except CoverError as error:
        raise HTTPException(422, "Unsupported cover URL") from error
    key = hashlib.sha256(f"cover-image:v1:{url}".encode()).hexdigest()
    # The transaction lock also coalesces simultaneous requests across API workers.
    await transaction_lock(db, f"cover-image:{key}")
    cached = await db.get(ProviderCache, key)
    if cached:
        data = base64.b64decode(cached.value["jpeg"])
    else:
        try:
            data = await fetch_cover(url)
        except CoverError as error:
            # Never persist a transient upstream failure as an empty cover.
            raise HTTPException(404, "Cover temporarily unavailable") from error
        now = datetime.now(UTC)
        db.add(
            ProviderCache(
                key=key,
                value={"jpeg": base64.b64encode(data).decode("ascii")},
                fetched_at=now,
                expires_at=now + timedelta(days=365),
            )
        )
    await db.commit()
    return Response(
        data,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "private, max-age=86400",
            "X-Content-Type-Options": "nosniff",
        },
    )
