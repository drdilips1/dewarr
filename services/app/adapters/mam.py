"""Native MAM read API.

Request-field adaptations reference MouseSearch (c) 2026 sevenlayercookie and
myanonamouse-mcp (c) 2026 Sandy McArthur, Jr. MIT notices ship in app/notices
and docs/notices; exact upstream revisions are in docs/REUSE-LEDGER.md.
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit

import httpx
from pydantic import BaseModel, Field, field_validator

from app.adapters.contracts import AdapterError, FailureKind, Release
from app.adapters.http import configured_url
from app.domain.catalog_network import retry_delay

MAX_RESPONSE_BYTES = 8 * 1024 * 1024
SEARCH_PATH = "tor/js/loadSearchJSONbasic.php"


class PrivateDownloadLogFilter(logging.Filter):
    def filter(self, record):
        # httpx logs complete request URLs at INFO, including MAM passkeys.
        return not any(
            isinstance(value, httpx.URL) and "/tor/download.php/" in value.path
            for value in (record.args if isinstance(record.args, tuple) else ())
        )


logging.getLogger("httpx").addFilter(PrivateDownloadLogFilter())


def download_path(value, source_id):
    if not isinstance(value, str) or not 0 < len(value) <= 4096:
        raise AdapterError(FailureKind.PARSER, "MAM did not provide a usable download reference.")
    try:
        parts = urlsplit(value)
    except ValueError as error:
        raise AdapterError(
            FailureKind.PARSER, "MAM returned an invalid download reference."
        ) from error
    segments = [unquote(segment) for segment in parts.path.split("/")]
    if (
        parts.scheme
        or parts.netloc
        or parts.fragment
        or any(ord(c) < 33 or ord(c) == 127 for c in value)
        or any(
            segment in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9._~=-]+", segment)
            for segment in segments
        )
    ):
        raise AdapterError(FailureKind.PARSER, "MAM returned an unsupported download reference.")
    try:
        query = parse_qsl(parts.query, keep_blank_values=True, max_num_fields=10)
    except ValueError as error:
        raise AdapterError(
            FailureKind.PARSER, "MAM returned an unsupported download query."
        ) from error
    if any(key.lower() != "tid" for key, _ in query):
        # Personal-freeleech flags require a separate explicit policy. Resolving
        # an artifact must not spend account tokens as a hidden URL side effect.
        raise AdapterError(
            FailureKind.UNSUPPORTED, "MAM download reference has unsupported options."
        )
    return "tor/download.php/" + parts.path + "?" + urlencode({"tid": source_id})


class MAMSearch(BaseModel):
    q: str = Field(min_length=1, max_length=300)
    medium: Literal["all", "ebook", "audio"] = "all"
    fields: list[
        Literal["title", "author", "series", "narrator", "description", "tags", "filenames"]
    ] = Field(default=["title", "author", "series"], min_length=1, max_length=7)
    language_ids: list[int] = Field(default=[1], max_length=20)
    sort: Literal["relevance", "seeders"] = "relevance"
    offset: int = Field(default=0, ge=0, le=10000)
    limit: int = Field(default=25, ge=1, le=100)

    @field_validator("q")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("Enter a title, author or series")
        return value.strip()

    @field_validator("language_ids")
    @classmethod
    def languages(cls, value):
        if any(item < 1 or item > 10000 for item in value):
            raise ValueError("Use positive MAM language IDs")
        return list(dict.fromkeys(value))

    def payload(self):
        tor = {
            "text": self.q,
            "srchIn": list(dict.fromkeys(self.fields)),
            "searchType": "all",
            "searchIn": "torrents",
            "main_cat": {"all": [13, 14], "audio": [13], "ebook": [14]}[self.medium],
            "sortType": "seeders" if self.sort == "seeders" else "default",
            "startNumber": self.offset,
        }
        if self.language_ids:
            tor["browse_lang"] = self.language_ids
        return {
            "tor": tor,
            "perpage": self.limit,
            "description": "true",
            "isbn": "true",
            "mediaInfo": "true",
        }


class SourceSeries(BaseModel):
    source_id: str
    name: str
    position: str | None = None


class MAMRelease(Release):
    source: Literal["mam"] = "mam"
    title: str
    series: list[SourceSeries] = Field(default_factory=list)
    category: str | None = None
    language_id: int | None = None
    size_display: str | None = None
    filetype_display: str | None = None
    leechers: int | None = None
    snatches: int | None = None
    uploaded_at: str | None = None
    freeleech: bool | None = None
    vip: bool | None = None
    tags: list[str] = Field(default_factory=list)
    isbn: str | None = None
    media_info: str | None = None
    observed_at: datetime


@dataclass(frozen=True)
class MAMArtifact:
    release: MAMRelease
    content: bytes = field(repr=False)


class ReleasePage(BaseModel):
    source: Literal["mam"] = "mam"
    items: list[MAMRelease]
    offset: int
    limit: int
    total: int | None
    has_more: bool
    warnings: list[str] = Field(default_factory=list)


def cookie_value(value):
    value = value.strip()
    if value.startswith("mam_id="):
        value = value.removeprefix("mam_id=")
    if (
        not value
        or len(value) > 8192
        or any(ord(char) < 33 or ord(char) > 126 or char in ';,"\\' for char in value)
    ):
        raise ValueError("Enter only the mam_id cookie value")
    return value


def integer(value):
    if isinstance(value, bool) or not re.fullmatch(r"\d{1,19}", str(value)):
        return None
    number = int(value)
    return number if number <= 2**63 - 1 else None


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        elif tag in {"br", "p", "div", "li"} and not self.hidden:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        elif tag in {"p", "div", "li"} and not self.hidden:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain(value, limit=1000):
    if not isinstance(value, str):
        return None
    parser = PlainText()
    parser.feed(value[:limit])
    return (
        "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip())
        or None
    )


def structured(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, RecursionError):
            return None
    return value


def contributors(value):
    parsed = structured(value)
    values = (
        parsed.values() if isinstance(parsed, dict) else parsed if isinstance(parsed, list) else []
    )
    return list(dict.fromkeys(name for item in list(values)[:100] if (name := plain(item))))


def release(row, observed_at):
    if not isinstance(row, dict) or not (identifier := integer(row.get("id"))):
        raise ValueError("Release ID is missing")
    if not (title := plain(row.get("title"), 2000)):
        raise ValueError("Release title is missing")
    size_display = plain(row.get("size"), 100)
    size = integer(row.get("size"))
    if size is None and size_display:
        match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*([KMGT]?I?B)", size_display.upper())
        if match:
            number = (
                float(match[1])
                * 1024
                ** {
                    "B": 0,
                    "KB": 1,
                    "MB": 2,
                    "GB": 3,
                    "TB": 4,
                    "KIB": 1,
                    "MIB": 2,
                    "GIB": 3,
                    "TIB": 4,
                }[match[2]]
            )
            size = int(number) if number <= 2**63 - 1 else None
    series = []
    series_info = structured(row.get("series_info"))
    if isinstance(series_info, dict):
        for key, item in list(series_info.items())[:100]:
            if isinstance(item, list) and item and (name := plain(item[0])):
                position = (
                    str(item[1])[:100]
                    if len(item) > 1 and isinstance(item[1], (str, int, float))
                    else None
                )
                series.append(SourceSeries(source_id=str(key)[:200], name=name, position=position))
    tags = structured(row.get("tags"))
    if isinstance(tags, dict):
        tags = list(tags.values())
    if not isinstance(tags, list):
        tags = re.split(r"[,;]", row.get("tags", "")) if isinstance(row.get("tags"), str) else []
    filetype = plain(row.get("filetype"), 300)
    return MAMRelease(
        source_id=str(identifier),
        raw_title=row["title"][:2000],
        title=title,
        medium={13: "audio", 14: "ebook"}.get(integer(row.get("main_cat"))),
        authors=contributors(row.get("author_info")),
        narrators=contributors(row.get("narrator_info")),
        series=series,
        category=plain(row.get("catname")),
        language=plain(row.get("lang_code"), 30),
        language_id=integer(row.get("language")),
        size_bytes=size,
        size_display=size_display,
        formats=list(
            dict.fromkeys(
                re.findall(
                    r"\b(?:epub|pdf|mobi|azw3?|m4b|mp3|flac|aac|ogg|opus|cbz|cbr)\b",
                    (filetype or "").lower(),
                )
            )
        ),
        filetype_display=filetype,
        seeders=integer(row.get("seeders")),
        leechers=integer(row.get("leechers")),
        snatches=integer(row.get("times_completed")),
        uploaded_at=plain(row.get("added"), 100),
        freeleech=bool(row["free"])
        if type(row.get("free")) is int and row["free"] in {0, 1}
        else None,
        vip=bool(row["vip"]) if type(row.get("vip")) is int and row["vip"] in {0, 1} else None,
        tags=[text for tag in tags[:100] if (text := plain(tag))],
        isbn=str(row["isbn"])[:200] if isinstance(row.get("isbn"), (str, int)) else None,
        description=plain(row.get("description"), 100000),
        media_info=plain(row.get("mediainfo"), 100000),
        protocol="torrent",
        observed_at=observed_at,
        details={"size_is_estimate": size is not None and integer(row.get("size")) is None},
    )


def parse_page(value, query):
    error = value.get("error")
    if error:
        empty = re.fullmatch(r"Nothing returned, out of (\d+)", str(error).strip())
        if empty and query.offset >= int(empty[1]):
            return ReleasePage(
                items=[],
                offset=query.offset,
                limit=query.limit,
                total=int(empty[1]),
                has_more=False,
            )
        message = str(error).lower()
        if any(token in message for token in ("not signed in", "not logged in", "invalid session")):
            raise AdapterError(
                FailureKind.AUTHENTICATION,
                "MAM rejected this session. Update mam_id for the configured route.",
            )
        raise AdapterError(
            FailureKind.PARSER,
            "MAM returned a source error. Check the connection and search settings.",
        )
    rows = value.get("data")
    if not isinstance(rows, list) or len(rows) > query.limit:
        raise AdapterError(FailureKind.PARSER, "MAM returned an unexpected search page.")
    total = integer(value.get("found"))
    items, warnings, seen = [], [], set()
    if not rows and total is not None and total > query.offset:
        raise AdapterError(FailureKind.PARSER, "MAM omitted results from a nonempty search page.")
    if total is not None and rows and total < query.offset + len(rows):
        total = None
        warnings.append("MAM's result count changed; the total is unknown.")
    now = datetime.now(UTC)
    for row in rows:
        try:
            item = release(row, now)
        except (ValueError, TypeError, RecursionError):
            warnings.append("A malformed source result was omitted; this page is incomplete.")
            continue
        if item.source_id not in seen:
            items.append(item)
            seen.add(item.source_id)
    if rows and not items:
        raise AdapterError(
            FailureKind.PARSER,
            "MAM results could not be decoded. No valid empty-result claim can be made.",
        )
    return ReleasePage(
        items=items,
        offset=query.offset,
        limit=query.limit,
        total=total,
        has_more=query.offset + len(rows) < total
        if total is not None
        else len(rows) == query.limit,
        warnings=list(dict.fromkeys(warnings)),
    )


class MAMClient:
    def __init__(
        self,
        base_url,
        mam_id,
        *,
        proxy_url=None,
        proxy_username=None,
        proxy_password=None,
        transport=None,
        request_interval=2.0,
    ):
        proxy = (
            httpx.Proxy(proxy_url, auth=(proxy_username or "", proxy_password or ""))
            if proxy_url and (proxy_username or proxy_password)
            else proxy_url
        )
        self.client = httpx.AsyncClient(
            base_url=configured_url(base_url) + "/",
            headers={
                "Cookie": f"mam_id={cookie_value(mam_id)}",
                "Accept": "application/json",
                "User-Agent": "BookSearch/0.1 (self-hosted MAM client)",
            },
            proxy=proxy,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(25, connect=10),
            transport=transport,
        )
        self.rotated_cookie = None
        self.request_interval = request_interval
        self.cooldown = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.client.aclose()

    async def request(self, path, payload=None, *, binary=False):
        try:
            async with (
                asyncio.timeout(40),
                self.client.stream(
                    "POST" if payload else "GET",
                    path,
                    json=payload,
                    headers={"Accept": "application/x-bittorrent"} if binary else None,
                ) as response,
            ):
                self.cooldown = retry_delay(dict(response.headers), datetime.now(UTC))
                # Only the named session cookie from this non-redirected response is persisted.
                host = response.request.url.host
                cookies = [
                    cookie
                    for cookie in response.cookies.jar
                    if cookie.name == "mam_id"
                    and (
                        host == cookie.domain.lstrip(".")
                        or host.endswith("." + cookie.domain.lstrip("."))
                    )
                    and response.status_code in {200, 429}
                ]
                if len(cookies) == 1:
                    try:
                        self.rotated_cookie = cookie_value(cookies[0].value)
                        self.client.headers["Cookie"] = f"mam_id={self.rotated_cookie}"
                    except ValueError:
                        pass
                status = response.status_code
                if status in {401, 403}:
                    raise AdapterError(
                        FailureKind.AUTHENTICATION,
                        "MAM rejected this session. Update mam_id for the configured route.",
                    )
                if status == 429:
                    self.cooldown = max(60, self.cooldown)
                    raise AdapterError(
                        FailureKind.RATE_LIMIT,
                        "MAM is limiting requests. Wait before retrying.",
                        retry_after=int(self.cooldown),
                    )
                if status == 407 or 300 <= status < 400:
                    raise AdapterError(
                        FailureKind.ROUTE,
                        "The source or proxy rejected the route. Check connection settings.",
                    )
                if status != 200:
                    raise AdapterError(
                        FailureKind.UNAVAILABLE, "MAM could not complete the request."
                    )
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_RESPONSE_BYTES:
                        raise AdapterError(
                            FailureKind.PARSER, "MAM's response exceeded the supported page limit."
                        )
                if "text/html" in response.headers.get("content-type", "").lower():
                    raise AdapterError(
                        FailureKind.AUTHENTICATION,
                        "MAM returned a login or challenge page. Check the session and route.",
                    )
                if binary:
                    if not content or not content.startswith(b"d"):
                        raise AdapterError(
                            FailureKind.PARSER, "MAM did not return torrent metadata."
                        )
                    return bytes(content)
                try:
                    value = json.loads(content)
                except (ValueError, UnicodeError, RecursionError) as error:
                    raise AdapterError(
                        FailureKind.PARSER, "MAM returned unreadable JSON."
                    ) from error
                if not isinstance(value, dict):
                    raise AdapterError(FailureKind.PARSER, "MAM returned an unexpected response.")
                return value
        except (httpx.TimeoutException, TimeoutError) as error:
            raise AdapterError(FailureKind.TIMEOUT, "MAM did not respond in time.") from error
        except httpx.HTTPError as error:
            raise AdapterError(
                FailureKind.ROUTE,
                "The configured MAM route could not be reached. No direct fallback was attempted.",
            ) from error

    async def search(self, query):
        return parse_page(await self.request(SEARCH_PATH, query.payload()), query)

    async def detail(self, source_id):
        query = MAMSearch(q="detail", limit=1)
        payload = query.payload()
        payload["tor"] = {
            "id": int(source_id),
            "searchType": "all",
            "searchIn": "torrents",
            "startNumber": 0,
        }
        page = parse_page(await self.request(SEARCH_PATH, payload), query)
        if not page.items:
            raise AdapterError(FailureKind.NOT_FOUND, "This MAM release is no longer available.")
        if len(page.items) != 1 or page.items[0].source_id != source_id:
            raise AdapterError(
                FailureKind.PARSER, "MAM returned a different release than requested."
            )
        return page.items[0]

    async def test(self):
        value = await self.request("jsonLoad.php")
        if not integer(value.get("uid")) or not isinstance(value.get("username"), str):
            raise AdapterError(
                FailureKind.AUTHENTICATION,
                "MAM did not confirm an authenticated account. Check mam_id and route.",
            )
        return None

    async def resolve(self, source_id):
        if not re.fullmatch(r"[1-9][0-9]{0,17}", source_id):
            raise ValueError("Invalid MAM release identifier")
        query = MAMSearch(q="detail", limit=1)
        payload = query.payload()
        payload["dlLink"] = "true"
        payload["tor"] = {
            "id": int(source_id),
            "searchType": "all",
            "searchIn": "torrents",
            "startNumber": 0,
        }
        value = await self.request(SEARCH_PATH, payload)
        page = parse_page(value, query)
        if not page.items:
            raise AdapterError(FailureKind.NOT_FOUND, "This MAM release is no longer available.")
        if (
            len(page.items) != 1
            or page.items[0].source_id != source_id
            or len(value.get("data", [])) != 1
        ):
            raise AdapterError(
                FailureKind.PARSER, "MAM returned a different release than requested."
            )
        path = download_path(value["data"][0].get("dl"), source_id)
        if self.cooldown:
            raise AdapterError(
                FailureKind.RATE_LIMIT,
                "MAM requested a cooldown before fetching torrent metadata. Retry later.",
                retry_after=int(self.cooldown),
            )
        await asyncio.sleep(self.request_interval)
        content = await self.request(path, binary=True)
        return MAMArtifact(release=page.items[0], content=content)
