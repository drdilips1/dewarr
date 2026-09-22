"""Unauthenticated Libro.fm lookup for an audiobook Hardcover does not know.

Search is GET /api/v12/explore/search. The release day is one read of the public
ISBN page. There is no login and no app client. A changed search shape stops the lookup.
"""

import json
import re
from datetime import date as Date

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.adapters.catalog_types import cover_url
from app.adapters.contracts import AdapterError, FailureKind
from app.adapters.http import JsonEndpoint

HOST = "https://libro.fm"
# The public ISBN page rejects the API user agent at the edge. A browser agent
# reads the same page. This is not an app client and sends no app version header.
PAGE_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
_FULL_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_YEAR = re.compile(r"^\d{4}$")
_PUBLICATION = re.compile(
    r"<strong>\s*Publication date:\s*</strong>\s*([A-Z][a-z]+ \d{1,2}, \d{4})",
    re.I,
)
_SERIES = re.compile(r'class="audiobook-title__series"[^>]*>\s*(?:<a[^>]*>)?\s*([^<]+)')
_TAGS = re.compile(r"<[^>]+>")
_LD = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.I | re.S)


class LibroHit(BaseModel):
    title: str = Field(min_length=1, max_length=600)
    isbn: str = Field(pattern=r"\d{10}|\d{13}")
    authors: list[str] = Field(default_factory=list, max_length=40)
    narrators: list[str] = Field(default_factory=list, max_length=40)
    cover_url: str | None = None
    coming_soon: bool = False
    genres: list[str] = Field(default_factory=list)


class LibroPublication(BaseModel):
    date: Date | None = None
    year: int | None = None
    publisher: str | None = None
    series: str | None = None
    description: str | None = None


def _names(value):
    if value is None:
        return []
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise AdapterError(FailureKind.PARSER, "The audiobook search response changed shape.")
    return list(dict.fromkeys(item.strip() for item in value))


def _isbn(value):
    text = str(value).strip() if isinstance(value, int | str) else ""
    if not re.fullmatch(r"\d{10}|\d{13}", text):
        raise AdapterError(FailureKind.PARSER, "The audiobook search response changed shape.")
    return text


def _cover(value):
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.startswith("//"):
        text = "https:" + text
    return cover_url(text)


def _genres(filters):
    if not isinstance(filters, list):
        return []
    found = []
    for group in filters:
        if not isinstance(group, dict) or group.get("readable") != "Genres":
            continue
        for choice in group.get("choices") or []:
            if isinstance(choice, dict) and isinstance(choice.get("readable"), str):
                found.append(choice["readable"])
    return found


def parse_search(payload):
    try:
        collection = payload["audiobook_collection"]
        rows = collection["audiobooks"]
    except (TypeError, KeyError, AttributeError) as error:
        raise AdapterError(
            FailureKind.PARSER, "The audiobook search response changed shape."
        ) from error
    if not isinstance(rows, list) or len(rows) > 40:
        raise AdapterError(FailureKind.PARSER, "The audiobook search response changed shape.")
    hits = []
    for row in rows:
        if not isinstance(row, dict):
            raise AdapterError(FailureKind.PARSER, "The audiobook search response changed shape.")
        info = row.get("audiobook_info") or {}
        catalog = row.get("catalog_info") or {}
        if not isinstance(info, dict) or not isinstance(catalog, dict):
            raise AdapterError(FailureKind.PARSER, "The audiobook search response changed shape.")
        if any(key not in row for key in ("title", "isbn", "authors")):
            raise AdapterError(FailureKind.PARSER, "The audiobook search response changed shape.")
        coming = catalog.get("coming_soon", False)
        if type(coming) is not bool:
            raise AdapterError(FailureKind.PARSER, "The audiobook search response changed shape.")
        narrators = info.get("narrators", [])
        try:
            hits.append(
                LibroHit(
                    title=row["title"],
                    isbn=_isbn(row.get("isbn")),
                    authors=_names(row.get("authors")),
                    narrators=_names(narrators),
                    cover_url=_cover(row.get("cover_url")),
                    coming_soon=coming,
                )
            )
        except (ValidationError, TypeError) as error:
            raise AdapterError(
                FailureKind.PARSER, "The audiobook search response changed shape."
            ) from error
    if len(hits) == 1:
        content = collection.get("sort_filter_content") or {}
        if isinstance(content, dict):
            hits[0].genres = _genres(content.get("filters"))
    return hits


def _plain(value):
    if not isinstance(value, str):
        return None
    text = _TAGS.sub(" ", value)
    text = " ".join(text.replace("&nbsp;", " ").split())
    return text[:4000] if text else None


def _json_ld(html):
    match = _LD.search(html)
    if not match:
        return {}
    try:
        value = json.loads(match.group(1))
    except (ValueError, UnicodeError):
        return {}
    return value if isinstance(value, dict) else {}


def parse_publication(html):
    if not isinstance(html, str) or len(html) > 1_000_000:
        raise AdapterError(FailureKind.PARSER, "The audiobook page response changed shape.")
    if (
        "application/ld+json" not in html
        and "Publication date" not in html
        and "audiobook-title" not in html
    ):
        raise AdapterError(FailureKind.PARSER, "The audiobook page response changed shape.")
    linked = _json_ld(html)
    published = linked.get("datePublished")
    day = None
    year = None
    if isinstance(published, str) and _FULL_DAY.fullmatch(published):
        try:
            day = Date.fromisoformat(published)
        except ValueError:
            day = None
    elif isinstance(published, str) and _YEAR.fullmatch(published):
        year = int(published)
    if day is None:
        labeled = _PUBLICATION.search(html)
        if labeled:
            from app.domain.release_dates import parse_prose_day

            day = parse_prose_day(labeled.group(1))
    if day:
        year = day.year
    series = _SERIES.search(html)
    publisher = linked.get("publisher") if isinstance(linked.get("publisher"), str) else None
    return LibroPublication(
        date=day,
        year=year,
        publisher=publisher.strip()[:300] if publisher and publisher.strip() else None,
        series=series.group(1).strip()[:300] if series and series.group(1).strip() else None,
        description=_plain(linked.get("description")),
    )


class LibroClient:
    """Fixed host. Tests pass the request callables; production opens them around one lookup."""

    def __init__(self, search_request, page_request):
        self.search_request = search_request
        self.page_request = page_request

    async def search(self, query, *, isbn=False):
        params = {"page": 1, "q": query, "searchby": "isbn" if isbn else "all"}
        return parse_search(await self.search_request(params))

    async def publication(self, isbn):
        if not re.fullmatch(r"\d{10}|\d{13}", isbn):
            raise AdapterError(FailureKind.PARSER, "The audiobook page response changed shape.")
        return parse_publication(await self.page_request(isbn))


def open_client(*, transport=None):
    endpoint = JsonEndpoint(HOST, transport=transport)
    page = httpx.AsyncClient(
        base_url=HOST + "/",
        headers={"Accept": "text/html", "User-Agent": PAGE_USER_AGENT},
        timeout=httpx.Timeout(30, connect=10),
        trust_env=False,
        follow_redirects=False,
        transport=transport,
    )

    async def search_request(params):
        return await endpoint.request("GET", "api/v12/explore/search", params=params)

    async def page_request(isbn):
        try:
            response = await page.get(f"audiobooks/{isbn}")
        except httpx.HTTPError as error:
            raise AdapterError(
                FailureKind.ROUTE, "The audiobook page could not be reached."
            ) from error
        if response.status_code == 404:
            raise AdapterError(FailureKind.NOT_FOUND, "This audiobook page was not found.")
        if response.status_code == 429:
            raise AdapterError(FailureKind.RATE_LIMIT, "The audiobook page is limiting requests.")
        if response.status_code != 200:
            raise AdapterError(FailureKind.UNAVAILABLE, "The audiobook page could not be read.")
        if len(response.content) > 1_000_000:
            raise AdapterError(FailureKind.PARSER, "The audiobook page response changed shape.")
        return response.text

    return endpoint, page, LibroClient(search_request, page_request)
