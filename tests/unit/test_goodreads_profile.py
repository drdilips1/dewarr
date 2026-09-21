import pytest

from app.adapters import goodreads_profile as profile
from app.adapters.contracts import AdapterError, FailureKind
from app.adapters.goodreads import DocumentResult


@pytest.mark.parametrize(
    "value",
    [
        "153017922",
        "https://www.goodreads.com/user/show/153017922-logan-abell",
        "https://www.goodreads.com/review/list/153017922?page=1&shelf=%23ALL%23",
    ],
)
def test_profile_variants(value):
    assert profile.profile_input(value) == {"user_id": "153017922", "key": None, "selected": None}


@pytest.mark.parametrize(
    "value",
    [
        "https://goodreads.com.evil.test/user/show/123",
        "https://user:password@goodreads.com/user/show/123",
        "http://www.goodreads.com/user/show/123",
        "https://www.goodreads.com:444/user/show/123",
        "https://www.goodreads.com/user/show/123?shelf=a&shelf=b",
        "https://www.goodreads.com/user/show/123?shelf=../../private",
        "https://www.goodreads.com/user/show/0",
        "https://www.goodreads.com/user/show/123#token",
        "https://www.goodreads.com/user/show/123\nsecret",
        "https://localhost/review/list_rss/123",
    ],
)
def test_invalid_profile_links(value):
    with pytest.raises(ValueError):
        profile.profile_input(value)


HTML = b"""<html><title>Reader (36 books)</title><div id="shelves">
<a href="/review/list/123?shelf=read">read (2)</a>
<a href="/review/list/123?tag=alternative-history">alternative-history (1)</a>
<a href="/review/list/123?shelf=did-not-finish">did-not-finish (0)</a>
<a href="https://evil.test/review/list/123?shelf=bad">bad (99)</a>
<a href="/review/list/999?shelf=wrong">wrong (99)</a>
</div></html>"""
FEED = b"""<rss><channel><title>Reader's bookshelf: all</title>
<link>https://www.goodreads.com/review/list/123</link>
<item><book_id>42</book_id><title>Book</title><user_shelves>to-read, fantasy</user_shelves></item>
</channel></rss>"""


def test_profile_discovery_includes_tags_empty_shelves_and_only_target_account():
    name, shelves = profile.parse_profile(HTML, "123")
    assert name == "Reader"
    assert {s["external_id"]: s["count"] for s in shelves} == {
        "read": 2,
        "alternative-history": 1,
        "did-not-finish": 0,
    }


async def test_feed_fallback_and_private_key_reuse(monkeypatch):
    calls = []

    async def fetch(url, **kwargs):
        calls.append(url)
        if "/user/show/" in url:
            raise AdapterError(FailureKind.AUTHENTICATION, "Sign in required")
        return DocumentResult(FEED)

    monkeypatch.setattr(profile, "fetch_document", fetch)
    config = profile.profile_input(
        "https://www.goodreads.com/review/list_rss/123?key=secret&shelf=to-read"
    )
    result = await profile.discover(config)
    assert result["name"] == "Reader" and result["warning"]
    assert {s["external_id"] for s in result["shelves"]} == {"to-read", "fantasy"}
    assert "key=secret" in calls[0]
    assert "key=secret" not in calls[1]
    assert (
        profile.shelf_url(result, "fantasy")
        == "https://www.goodreads.com/review/list_rss/123?key=secret&shelf=fantasy"
    )


async def test_profile_and_feed_discovery_are_combined(monkeypatch):
    async def fetch(url, **kwargs):
        return DocumentResult(HTML if "/user/show/" in url else FEED)

    monkeypatch.setattr(profile, "fetch_document", fetch)
    result = await profile.discover(profile.profile_input("123"))
    assert not result["warning"]
    assert {s["external_id"] for s in result["shelves"]} == {
        "read",
        "did-not-finish",
        "alternative-history",
        "to-read",
        "fantasy",
    }


async def test_canonical_profile_redirect_is_bounded_and_uses_html():
    import httpx

    from app.adapters.goodreads import fetch_document

    calls = []

    async def resolver(host):
        assert host == "www.goodreads.com"
        return ["93.184.216.34"]

    async def handle(request):
        calls.append(request.url.path)
        assert request.headers["accept"] == "text/html"
        if len(calls) == 1:
            return httpx.Response(
                302, headers={"location": "https://www.goodreads.com/user/show/123-reader"}
            )

        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield HTML

        return httpx.Response(200, stream=Stream())

    result = await fetch_document(
        "https://www.goodreads.com/user/show/123",
        profile_id="123",
        resolver=resolver,
        transport=httpx.MockTransport(handle),
    )
    assert result.content == HTML
    assert calls == ["/user/show/123", "/user/show/123-reader"]


@pytest.mark.parametrize(
    "target",
    [
        "http://www.goodreads.com/user/show/123-reader",
        "https://evil.test/user/show/123-reader",
        "https://www.goodreads.com/user/show/999-reader",
        "https://www.goodreads.com/user/sign_in",
        "https://www.goodreads.com/user/show/123-reader?redirect=http://localhost",
    ],
)
async def test_profile_redirect_rejects_unrelated_destinations(target):
    import httpx

    from app.adapters.goodreads import fetch_document

    calls = []

    async def resolver(host):
        return ["93.184.216.34"]

    async def handle(request):
        calls.append(request.url)
        return httpx.Response(302, headers={"location": target})

    with pytest.raises(AdapterError):
        await fetch_document(
            "https://www.goodreads.com/user/show/123",
            profile_id="123",
            resolver=resolver,
            transport=httpx.MockTransport(handle),
        )
    assert len(calls) == 1
