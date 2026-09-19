"""Bounded discovery queries against Hardcover's published GraphQL schema."""

from datetime import date, timedelta

from pydantic import BaseModel, ValidationError

from app.adapters.catalog_providers import contributors, identifier, parse_failure
from app.adapters.catalog_types import BookData, cover_url, year

FIELDS = "id canonical_id title release_year release_date cached_image cached_contributors"
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


class DiscoveryBook(BookData):
    release_date: date | None = None


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


def book(row):
    return DiscoveryBook(
        provider="hardcover",
        external_id=identifier("hardcover", str(row["id"])),
        canonical_id=identifier("hardcover", str(row["canonical_id"]))
        if row.get("canonical_id")
        else None,
        title=row["title"],
        authors=contributors(row.get("cached_contributors"), "Author"),
        publication_year=year(row.get("release_year")),
        release_date=row.get("release_date"),
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
