import logging

import httpx
import pytest

from app.adapters.contracts import AdapterError, FailureKind
from app.adapters.goodreads import FeedResult, feed_url, fetch_feed, parse_feed

URL = "https://www.goodreads.com/review/list_rss/123?key=private-feed-key&shelf=to-read"
FEED = b"""<rss version="2.0"><channel><title>Reading shelf</title>
<link>https://www.goodreads.com/review/list/123</link><item><book_id>42</book_id>
<title><![CDATA[Harbor &amp; Roads]]></title><author_name>Alex Morgan</author_name>
<isbn>0-306-40615-2</isbn><description>private user review</description>
<book_image_url>http://127.0.0.1/private</book_image_url></item></channel></rss>"""


@pytest.mark.parametrize(
    "url",
    [
        "http://www.goodreads.com/review/list_rss/123",
        "https://goodreads.com.evil.test/review/list_rss/123",
        "https://user:pass@www.goodreads.com/review/list_rss/123",
        "https://www.goodreads.com:444/review/list_rss/123",
        "https://www.goodreads.com/review/list/123",
        "https://www.goodreads.com/review/list_rss/0",
        "https://www.goodreads.com/review/list_rss/123?shelf=a&shelf=b",
        "https://www.goodreads.com/review/list_rss/123?redirect=http://localhost",
        "https://www.goodreads.com/review/list_rss/123#secret",
        "https://www.goodreads.com/review/list_rss/123\n",
    ],
)
def test_rejects_nonfeed_routes(url):
    with pytest.raises(ValueError, match="Goodreads HTTPS"):
        feed_url(url)


def test_normalized_minimal_records_do_not_keep_reviews_or_arbitrary_urls():
    assert feed_url(URL.replace("www.", "")) == URL
    result = parse_feed(FEED)
    assert result == [
        {
            "external_id": "42",
            "title": "Harbor & Roads",
            "authors": ["Alex Morgan"],
            "isbn": "9780306406157",
            "isbn13": None,
        }
    ]
    assert (
        len(
            parse_feed(
                FEED.replace(
                    b"</channel>",
                    FEED[FEED.index(b"<item>") : FEED.index(b"</item>") + 7] + b"</channel>",
                )
            )
        )
        == 1
    )


@pytest.mark.parametrize(
    "body",
    [
        b"<html>login</html>",
        b"<rss><channel/></rss>",
        b"<rss>",
        b'<!DOCTYPE rss [<!ENTITY x "expanded">]><rss><channel><title>&x;</title></channel></rss>',
        FEED.replace(b"<book_id>42</book_id>", b""),
        FEED.replace(
            b"</channel>", b"<item><book_id>42</book_id><title>Conflict</title></item></channel>"
        ),
    ],
)
def test_malformed_or_conflicting_feeds_are_not_empty_shelves(body):
    with pytest.raises(AdapterError):
        parse_feed(body)


async def public(host):
    assert host == "www.goodreads.com"
    return ["1.1.1.1"]


async def test_pins_public_dns_preserves_tls_host_and_redacts_private_feed_key(caplog):
    def handler(request):
        assert request.url.host == "1.1.1.1"
        assert request.headers["host"] == "www.goodreads.com"
        assert request.extensions["sni_hostname"] == "www.goodreads.com"
        assert request.headers["if-none-match"] == '"first"'
        assert "authorization" not in request.headers
        return httpx.Response(200, stream=httpx.ByteStream(FEED), headers={"ETag": '"second"'})

    caplog.set_level(logging.INFO)
    page = await fetch_feed(
        URL, etag='"first"', resolver=public, transport=httpx.MockTransport(handler)
    )
    assert page.etag == '"second"' and page.items[0]["external_id"] == "42"
    assert "private-feed-key" not in caplog.text


async def test_304_preserves_validator_and_does_not_claim_empty_feed():
    page = await fetch_feed(
        URL,
        etag='"first"',
        resolver=public,
        transport=httpx.MockTransport(lambda r: httpx.Response(304)),
    )
    assert page == FeedResult([], True, '"first"', None)
    with pytest.raises(AdapterError, match="unsolicited"):
        await fetch_feed(
            URL, resolver=public, transport=httpx.MockTransport(lambda r: httpx.Response(304))
        )


@pytest.mark.parametrize(
    "status,kind",
    [
        (302, FailureKind.UNAVAILABLE),
        (429, FailureKind.RATE_LIMIT),
        (403, FailureKind.AUTHENTICATION),
        (503, FailureKind.UNAVAILABLE),
    ],
)
async def test_failures_are_typed_and_never_follow_redirects(status, kind):
    with pytest.raises(AdapterError) as caught:
        await fetch_feed(
            URL,
            resolver=public,
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    status, headers={"Location": "http://localhost", "Retry-After": "2400"}
                )
            ),
        )
    assert caught.value.kind == kind
    if status == 429:
        assert caught.value.retry_after == 2400


async def test_private_or_mixed_dns_never_opens_connection():
    async def resolver(host):
        return ["1.1.1.1", "127.0.0.1"]

    def forbidden(request):
        pytest.fail("Private DNS must fail before making a request")

    with pytest.raises(AdapterError, match="public addresses"):
        await fetch_feed(URL, resolver=resolver, transport=httpx.MockTransport(forbidden))


def test_shelf_budget_wait_does_not_exhaust_failure_retries():
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from app.jobs.retry import ShelfRetry, ShelfRetryStrategy

    strategy = ShelfRetryStrategy(max_attempts=5, wait=60)
    job = SimpleNamespace(attempts=50)
    before = datetime.now(UTC) + timedelta(seconds=5)
    decision = strategy.get_retry_decision(exception=ShelfRetry(5), job=job)
    after = datetime.now(UTC) + timedelta(seconds=5)
    assert before <= decision.retry_at <= after
    assert strategy.get_retry_decision(exception=RuntimeError("unexpected"), job=job) is None
