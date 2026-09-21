import httpx
import pytest
from fastapi import HTTPException

from app.domain import library_covers


@pytest.mark.parametrize(
    "status,kind", [(302, "image/jpeg"), (200, "text/html"), (401, "image/png")]
)
async def test_cover_proxy_rejects_redirects_and_non_images(monkeypatch, status, kind):
    client_type = httpx.AsyncClient
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, headers={"content-type": kind}, content=b"data")

    monkeypatch.setattr(
        library_covers.httpx,
        "AsyncClient",
        lambda **kwargs: client_type(**kwargs, transport=httpx.MockTransport(respond)),
    )
    with pytest.raises(HTTPException) as caught:
        await library_covers.fetch_cover("http://library.invalid/base", "private", "item_1")
    assert caught.value.status_code == 404
    assert len(requests) == 1
    assert requests[0].url.path == "/base/api/items/item_1/cover"
    assert requests[0].headers["authorization"] == "Bearer private"


async def test_cover_proxy_returns_image_and_rejects_path_traversal(monkeypatch):
    client_type = httpx.AsyncClient
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, headers={"content-type": "image/jpeg"}, content=b"cover")

    monkeypatch.setattr(
        library_covers.httpx,
        "AsyncClient",
        lambda **kwargs: client_type(**kwargs, transport=httpx.MockTransport(respond)),
    )
    assert await library_covers.fetch_cover("http://library.invalid", "private", "item_1") == (
        b"cover",
        "image/jpeg",
    )
    with pytest.raises(HTTPException):
        await library_covers.fetch_cover("http://library.invalid", "private", "../secrets")
    assert len(requests) == 1
