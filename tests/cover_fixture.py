"""Synthetic HTTP image service; production URL, stream and decoder checks still run."""

import httpx

from app.importing.covers import CoverError, download_cover, normalize_cover
from tests.media_fixtures import cover_bytes

COVER_URL = "https://assets.hardcover.app/book-search-fixture/cover.png"


class CoverServiceFixture:
    def __init__(self):
        self.content = cover_bytes()
        self.calls = []
        self.fail = False

    async def fetch(self, url):
        self.calls.append(url)
        assert url == COVER_URL
        if self.fail:
            raise CoverError("Synthetic cover service unavailable")
        content = self.content

        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield content

        async def handle(request):
            assert (
                request.url.host == "1.1.1.1" and request.headers["host"] == "assets.hardcover.app"
            )
            return httpx.Response(200, headers={"content-type": "image/png"}, stream=Stream())

        async def resolve(host):
            return ["1.1.1.1"]

        data = await download_cover(url, transport=httpx.MockTransport(handle), resolver=resolve)
        return await normalize_cover(data)
