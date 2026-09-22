"""Bounded discovery queries against Hardcover's published GraphQL schema."""

from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, ValidationError

from app.adapters.catalog_providers import contributors, identifier, parse_failure
from app.adapters.catalog_types import BookData, cover_url, year
from app.domain.release_dates import genre_slug

FIELDS = "id canonical_id rating title release_year release_date cached_image cached_contributors"
HC_TRENDING = """query DiscoveryTrending($offset: Int!) {
 books_trending(duration: month, limit: 21, offset: $offset) { ids error }
}"""
HC_DISCOVERY_BOOKS = """query DiscoveryBooks($ids: [Int!]!) {
 books(where: {id: {_in: $ids}}, limit: 20) { $FIELDS }
}""".replace("$FIELDS", FIELDS)
HC_RECENT = """query DiscoveryRecent($from: date!, $to: date!, $offset: Int!) {
 books(where: {canonical_id: {_is_null: true}, release_date: {_gte: $from, _lte: $to}},
 order_by: [{release_date: desc}, {id: asc}], limit: 21, offset: $offset) { $FIELDS }
}""".replace("$FIELDS", FIELDS)
HC_RELATED = """query DiscoveryRelated($id: Int!) {
 books(where: {id: {_eq: $id}}, limit: 1) { id cached_similar_book_ids }
}"""
# Audio editions only. reading_format_id 2 is Hardcover's audiobook format.
# The edition release_date is the day on the calendar; the parent work date is not.
HC_UPCOMING = """query UpcomingAudio($from: date!, $to: date!, $offset: Int!) {
 editions(where: {reading_format_id: {_eq: 2}, release_date: {_gte: $from, _lte: $to},
 book: {canonical_id: {_is_null: true}}},
 order_by: [{release_date: asc}, {id: asc}], limit: 21, offset: $offset) {
  id release_date
  book {
   id canonical_id rating title release_year release_date
   cached_image cached_contributors cached_tags
  }
 }
}"""


class DiscoveryBook(BookData):
    release_date: date | None = None
    genres: list[str] = []
    date_basis: Literal["audiobook", "work", "unknown"] = "unknown"


class DiscoveryBatch(BaseModel):
    items: list[DiscoveryBook]
    has_more: bool = False
    warning: str | None = None


def ids(values, maximum):
    if not isinstance(values, list) or len(values) > maximum:
        raise parse_failure()
    if any(type(value) is not int for value in values) or len(set(values)) != len(values):
        raise parse_failure()
    return [int(identifier("hardcover", str(value))) for value in values]


def genres_from_tags(raw):
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise parse_failure()
    found = []
    for item in raw:
        if isinstance(item, str):
            name = item
        elif isinstance(item, dict) and ("tag" in item or "name" in item):
            name = item.get("tag") if isinstance(item.get("tag"), str) else item.get("name")
            if not isinstance(name, str):
                raise parse_failure()
        else:
            raise parse_failure()
        slug = genre_slug(name)
        if slug and slug not in found:
            found.append(slug)
    return found


def book(row, *, release_date=None, genres=None, date_basis="unknown"):
    return DiscoveryBook(
        provider="hardcover",
        external_id=identifier("hardcover", str(row["id"])),
        canonical_id=identifier("hardcover", str(row["canonical_id"]))
        if row.get("canonical_id")
        else None,
        title=row["title"],
        rating=row.get("rating"),
        authors=contributors(row.get("cached_contributors"), "Author"),
        publication_year=year(row.get("release_year")),
        release_date=row.get("release_date") if release_date is None else release_date,
        genres=genres or [],
        date_basis=date_basis,
        cover_url=cover_url((row.get("cached_image") or {}).get("url")),
    )


async def load_ids(query, selected, *, has_more=False):
    if not selected:
        return DiscoveryBatch(items=[], has_more=has_more)
    rows = (await query(HC_DISCOVERY_BOOKS, {"ids": selected}))["books"]
    if not isinstance(rows, list) or len(rows) > len(selected):
        raise parse_failure()
    books = {value.external_id: value for value in map(book, rows)}
    if len(books) != len(rows) or set(books) - {str(value) for value in selected}:
        raise parse_failure()
    return DiscoveryBatch(
        items=[books[str(value)] for value in selected if str(value) in books],
        has_more=has_more,
        warning="Some Hardcover titles are no longer available in this shelf."
        if len(books) != len(selected)
        else None,
    )


async def browse(query, shelf, page, today):
    try:
        if shelf == "trending":
            result = (await query(HC_TRENDING, {"offset": (page - 1) * 20}))["books_trending"]
            if result.get("error"):
                raise parse_failure()
            selected = ids(result["ids"], 21)
            return await load_ids(query, selected[:20], has_more=len(selected) > 20)
        start = today - timedelta(days=90)
        rows = (
            await query(
                HC_RECENT,
                {"from": start.isoformat(), "to": today.isoformat(), "offset": (page - 1) * 20},
            )
        )["books"]
        if not isinstance(rows, list) or len(rows) > 21:
            raise parse_failure()
        books = [book(row) for row in rows]
        if len({b.external_id for b in books}) != len(books) or any(
            not value.release_date or not start <= value.release_date <= today or value.canonical_id
            for value in books
        ):
            raise parse_failure()
        return DiscoveryBatch(items=books[:20], has_more=len(books) > 20)
    except (TypeError, ValueError, KeyError, AttributeError, ValidationError) as error:
        raise parse_failure() from error


async def upcoming(query, start, end, page):
    """One month of audiobook edition dates. Work dates are resolved per book, not here."""
    try:
        rows = (
            await query(
                HC_UPCOMING,
                {"from": start.isoformat(), "to": end.isoformat(), "offset": (page - 1) * 20},
            )
        )["editions"]
        if not isinstance(rows, list) or len(rows) > 21:
            raise parse_failure()
        books = []
        seen = set()
        for row in rows:
            if not isinstance(row, dict):
                raise parse_failure()
            parent = row.get("book")
            if not isinstance(parent, dict):
                raise parse_failure()
            edition_day = row.get("release_date")
            if not isinstance(edition_day, str) or not (
                start.isoformat() <= edition_day <= end.isoformat()
            ):
                raise parse_failure()
            parsed = date.fromisoformat(edition_day)
            if not start <= parsed <= end:
                raise parse_failure()
            # A redirect, or a second audio edition of a book already kept, is ordinary.
            # The first edition wins because the query is ordered by release day.
            if parent.get("canonical_id"):
                continue
            external = identifier("hardcover", str(parent.get("id")))
            if external in seen:
                continue
            seen.add(external)
            books.append(
                book(
                    parent,
                    release_date=edition_day,
                    genres=genres_from_tags(parent.get("cached_tags")),
                    date_basis="audiobook",
                )
            )
        return DiscoveryBatch(items=books[:20], has_more=len(rows) > 20)
    except (TypeError, ValueError, KeyError, AttributeError, ValidationError) as error:
        raise parse_failure() from error


async def related(query, external_id):
    try:
        key = int(identifier("hardcover", external_id))
        rows = (await query(HC_RELATED, {"id": key}))["books"]
        if not isinstance(rows, list) or len(rows) != 1 or rows[0]["id"] != key:
            raise parse_failure()
        raw = rows[0].get("cached_similar_book_ids")
        selected = ids([] if raw is None else raw, 1000)
        return await load_ids(query, [value for value in selected if value != key][:20])
    except (TypeError, ValueError, KeyError, AttributeError, ValidationError) as error:
        raise parse_failure() from error
