"""Serve library artwork without disclosing backend credentials or filesystem paths."""

import asyncio
from uuid import UUID

import httpx
from fastapi import HTTPException, Response
from sqlalchemy import select

from app.adapters.audiobookshelf import external_id
from app.adapters.contracts import AdapterError
from app.adapters.grimmory import Grimmory
from app.adapters.http import configured_url
from app.db.models import Integration, LibraryAsset, Version
from app.domain.availability import availability_rows
from app.domain.catalog_display import display_map
from app.domain.primary_editions import asset_narrators, edition_order, primary_choices
from app.security import decrypt_secrets


async def fetch_cover(
    base_url: str,
    token: str,
    item_id: str,
    *,
    kind: str = "audiobookshelf",
    secrets: dict | None = None,
) -> tuple[bytes, str]:
    if kind == "grimmory":
        try:
            async with Grimmory(base_url, secrets or {}) as client:
                return await client.cover(item_id)
        except AdapterError as error:
            raise HTTPException(404, "Cover unavailable") from error
    try:
        item_id = external_id(item_id)
        async with (
            asyncio.timeout(15),
            httpx.AsyncClient(
                base_url=configured_url(base_url) + "/",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
                follow_redirects=False,
                trust_env=False,
            ) as client,
            client.stream("GET", f"api/items/{item_id}/cover", params={"width": 480}) as response,
        ):
            kind = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if response.status_code != 200 or kind not in {
                "image/jpeg",
                "image/png",
                "image/webp",
                "image/avif",
                "image/gif",
            }:
                raise HTTPException(404, "Cover unavailable")
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > 8 * 1024 * 1024:
                    raise HTTPException(404, "Cover unavailable")
            return bytes(content), kind
    except (httpx.HTTPError, TimeoutError, AdapterError, ValueError) as error:
        raise HTTPException(404, "Cover unavailable") from error


async def library_cover(db, user, work_id: UUID, medium: str):
    mapping = display_map(user)
    root = select(mapping.c.work_id).where(mapping.c.origin_id == work_id).scalar_subquery()
    root_id = await db.scalar(select(mapping.c.work_id).where(mapping.c.origin_id == work_id))
    choices = await primary_choices(db, user, mapping, [root_id] if root_id else [])
    rows = await db.execute(
        availability_rows(user, mapping)
        .with_only_columns(LibraryAsset, Integration, Version.narrators)
        .outerjoin(Version, Version.id == LibraryAsset.version_id)
        .where(
            mapping.c.work_id == root,
            Integration.kind.in_(["audiobookshelf", "grimmory"]),
        )
        .order_by((LibraryAsset.medium == medium).desc(), LibraryAsset.created_at.desc())
    )
    rows = sorted(
        rows.all(),
        key=lambda row: (
            row[0].medium != medium,
            *edition_order(
                row[0], choices.get(root_id, {}).get(row[0].medium), asset_narrators(row[0], row[2])
            ),
        ),
    )
    for asset, integration, _ in rows:
        if not asset.metadata_snapshot.get("cover_path"):
            continue
        try:
            secrets = decrypt_secrets(integration.encrypted_secrets)
            data, kind = await fetch_cover(
                integration.base_url,
                secrets.get("token", ""),
                asset.external_id,
                kind=integration.kind,
                secrets=secrets,
            )
        except HTTPException:
            continue
        return Response(
            data,
            media_type=kind,
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )
    raise HTTPException(404, "Cover unavailable")
