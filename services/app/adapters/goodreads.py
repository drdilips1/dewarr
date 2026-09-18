"""Bounded Goodreads shelf RSS observation. A feed is never a complete shelf snapshot."""

import asyncio
import contextvars
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from app.adapters.contracts import AdapterError, FailureKind
from app.adapters.mam import plain
from app.importing.covers import CoverError, public_address, public_addresses
from app.importing.match_evidence import isbn_key

MAX_BYTES = 4 * 1024 * 1024
MAX_ITEMS = 500
_request = contextvars.ContextVar("goodreads_feed_request", default=False)


class FeedLogFilter(logging.Filter):
    def filter(self, record):
        # RSS URLs can contain the user's private feed key.
        return not _request.get()


logging.getLogger("httpx").addFilter(FeedLogFilter())
logging.getLogger("httpcore").addFilter(FeedLogFilter())


def feed_url(value):
    try:
        parts = urlsplit(value.strip())
        if (
            parts.scheme != "https"
            or parts.hostname not in {"goodreads.com", "www.goodreads.com"}
            or parts.port not in {None, 443}
            or parts.username is not None
            or parts.password is not None
            or parts.fragment
            or "\\" in value
            or len(value) > 2000
            or any(ord(c) < 33 for c in value)
            or not re.fullmatch(r"/review/list_rss/[1-9][0-9]{0,19}", parts.path)
        ):
            raise ValueError
        query = parse_qsl(parts.query, keep_blank_values=True, max_num_fields=10)
        if len({k for k, _ in query}) != len(query) or any(
            k not in {"key", "shelf", "sort", "order", "per_page"} or len(v) > 300 for k, v in query
        ):
            raise ValueError
        return urlunsplit(("https", "www.goodreads.com", parts.path, urlencode(sorted(query)), ""))
    except (ValueError, TypeError):
        raise ValueError("Use a Goodreads HTTPS shelf RSS URL, copied from its RSS link") from None


def feed_identity(value):
    url = urlsplit(feed_url(value))
    return url.path, dict(parse_qsl(url.query)).get("shelf", "all")


def parse_feed(content):
    if len(content) > MAX_BYTES:
        raise AdapterError(FailureKind.PARSER, "The Goodreads feed exceeds the supported size")
    try:
        root = ElementTree.fromstring(content, forbid_dtd=True)
        if root.tag != "rss" or len(root.findall("channel")) != 1:
            raise ValueError
        channel = root.find("channel")
        if not channel.findtext("title") or not channel.findtext("link"):
            raise ValueError
        items = channel.findall("item")
        if len(items) > MAX_ITEMS or sum(1 for _ in root.iter()) > 20000:
            raise ValueError
        records = {}
        for item in items:
            external_id = (item.findtext("book_id") or "").strip()
            if not external_id:
                link = urlsplit(item.findtext("link") or "")
                match = re.match(r"^/book/show/([1-9][0-9]*)", link.path)
                if link.hostname in {"goodreads.com", "www.goodreads.com"} and match:
                    external_id = match[1]
            title = plain(item.findtext("book_title") or item.findtext("title"), 600)
            author = plain(item.findtext("author_name"), 300)
            if not re.fullmatch(r"[1-9][0-9]{0,19}", external_id) or not title:
                raise ValueError
            record = {
                "external_id": external_id,
                "title": title,
                "authors": [author] if author else [],
                "isbn": isbn_key(item.findtext("isbn") or ""),
                "isbn13": isbn_key(item.findtext("isbn13") or ""),
            }
            # Never retain reviews, private notes, ratings or arbitrary HTML/image URLs.
            if external_id in records and records[external_id] != record:
                raise ValueError
            records[external_id] = record
        return list(records.values())
    except (ElementTree.ParseError, DefusedXmlException, ValueError, TypeError):
        raise AdapterError(
            FailureKind.PARSER,
            "Goodreads returned an unrecognized or conflicting shelf feed; "
            "existing entries are preserved",
        ) from None


@dataclass
class FeedResult:
    items: list[dict]
    not_modified: bool = False
    etag: str | None = None
    modified: str | None = None


def validator(value):
    return value if value and len(value) <= 500 and not any(ord(c) < 32 for c in value) else None


def retry_delay(value):
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        try:
            seconds = int((parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            seconds = 1800
    return max(60, min(seconds, 7 * 86400))


async def fetch_feed(url, *, etag=None, modified=None, transport=None, resolver=public_addresses):
    url = feed_url(url)
    host = urlsplit(url).hostname
    marker = _request.set(True)
    try:
        async with asyncio.timeout(30):
            addresses = await resolver(host)
            if not addresses or any(not public_address(address) for address in addresses):
                raise AdapterError(
                    FailureKind.ROUTE, "The Goodreads host did not resolve to public addresses"
                )
            headers = {
                "Host": host,
                "Accept": "application/rss+xml, application/xml, text/xml",
                "Accept-Encoding": "identity",
            }
            if validator(etag):
                headers["If-None-Match"] = etag
            if validator(modified):
                headers["If-Modified-Since"] = modified
            async with httpx.AsyncClient(
                transport=transport,
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(15, connect=5),
                headers=headers,
            ) as client:
                target = httpx.URL(url).copy_with(host=addresses[0])
                async with client.stream(
                    "GET", target, extensions={"sni_hostname": host}
                ) as response:
                    status = response.status_code
                    if status == 304:
                        if not etag and not modified:
                            raise AdapterError(
                                FailureKind.PARSER,
                                "Goodreads returned an unsolicited unchanged response",
                            )
                        return FeedResult(
                            [],
                            True,
                            validator(response.headers.get("etag")) or etag,
                            validator(response.headers.get("last-modified")) or modified,
                        )
                    if status == 429:
                        raise AdapterError(
                            FailureKind.RATE_LIMIT,
                            "Goodreads is limiting requests; observation will retry later",
                            retry_after=retry_delay(response.headers.get("retry-after")),
                        )
                    if status in {401, 403}:
                        raise AdapterError(
                            FailureKind.AUTHENTICATION,
                            "Goodreads denied this feed; check its URL and visibility",
                        )
                    if status != 200:
                        raise AdapterError(
                            FailureKind.UNAVAILABLE,
                            "Goodreads did not return the shelf feed; check the final RSS URL",
                        )
                    if response.headers.get("content-encoding", "identity").lower() not in {
                        "identity",
                        "",
                    }:
                        raise AdapterError(
                            FailureKind.PARSER, "Compressed Goodreads feeds are unsupported"
                        )
                    content = bytearray()
                    async for chunk in response.aiter_raw():
                        content.extend(chunk)
                        if len(content) > MAX_BYTES:
                            raise AdapterError(
                                FailureKind.PARSER, "The Goodreads feed exceeds the supported size"
                            )
                    return FeedResult(
                        parse_feed(bytes(content)),
                        False,
                        validator(response.headers.get("etag")),
                        validator(response.headers.get("last-modified")),
                    )
    except (httpx.HTTPError, TimeoutError, OSError, CoverError):
        raise AdapterError(
            FailureKind.ROUTE, "Goodreads could not be reached within its time limit"
        ) from None
    finally:
        _request.reset(marker)
