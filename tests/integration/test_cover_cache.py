import pytest
from sqlalchemy import func, select

from app.db.models import ProviderCache
from app.importing.covers import CoverError

pytestmark = pytest.mark.integration
URL = "https://i.gr-assets.com/books/123.jpg"


async def test_cover_is_durable_and_browser_cacheable(client, admin, database, monkeypatch):
    from app.domain import cover_cache

    calls = []

    async def fetch(url):
        calls.append(url)
        return b"normalized-jpeg"

    monkeypatch.setattr(cover_cache, "fetch_cover", fetch)
    for _ in range(2):
        response = await client.get("/api/catalog/cover-image", params={"url": URL})
        assert response.status_code == 200
        assert response.content == b"normalized-jpeg"
        assert response.headers["content-type"] == "image/jpeg"
        assert response.headers["cache-control"] == "private, max-age=86400"
    assert calls == [URL]
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(ProviderCache)) == 1


async def test_failed_cover_is_retried_not_saved(client, admin, database, monkeypatch):
    from app.domain import cover_cache

    async def fail(url):
        raise CoverError("Temporary outage")

    monkeypatch.setattr(cover_cache, "fetch_cover", fail)
    response = await client.get("/api/catalog/cover-image", params={"url": URL})
    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(ProviderCache)) == 0

    async def recover(url):
        return b"recovered-jpeg"

    monkeypatch.setattr(cover_cache, "fetch_cover", recover)
    assert (await client.get("/api/catalog/cover-image", params={"url": URL})).status_code == 200
    assert (
        await client.get("/api/catalog/cover-image", params={"url": "https://localhost/x"})
    ).status_code == 422
