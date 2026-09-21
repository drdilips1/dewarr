import json

import httpx
import pytest
from sqlalchemy import func, select

from app.adapters.hardcover_authors import HC_AUTHOR
from app.db.models import Work
from app.domain.catalog_network import CatalogGateway

pytestmark = pytest.mark.integration


async def test_author_browsing_authenticated_cached_and_read_only(
    client, admin, database, monkeypatch
):
    from app.api import metadata

    url = "/api/metadata/authors/hardcover/9"
    assert (await client.get(url)).status_code == 409
    await client.put("/api/metadata/account", json={"token": "author-test-token"})
    calls = []

    def respond(request):
        payload = json.loads(request.content)
        calls.append(payload)
        assert payload["query"] == HC_AUTHOR
        return httpx.Response(
            200,
            json={
                "data": {
                    "authors": [{"id": 9, "name": "Writer"}],
                    "books": [{"id": 42, "title": "A book"}],
                }
            },
        )

    class Gateway(CatalogGateway):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs, transport=httpx.MockTransport(respond))

        async def reserve(self):
            pass

    monkeypatch.setattr(metadata, "CatalogGateway", Gateway)
    response = await client.get(url)
    assert response.status_code == 200, response.text
    assert response.json()["author"]["external_id"] == "9"
    assert response.json()["known_works"] == {}
    assert "author-test-token" not in response.text
    assert (await client.get(url)).status_code == 200
    assert len(calls) == 1
    assert (await client.get(url + "?page=0")).status_code == 422
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(Work)) == 0


async def test_author_requires_login(client):
    assert (await client.get("/api/metadata/authors/hardcover/9")).status_code == 401
