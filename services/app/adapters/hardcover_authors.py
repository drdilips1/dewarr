"""Identity-based, bounded author bibliography; browsing never imports books."""

from pydantic import BaseModel, ValidationError

from app.adapters.catalog_providers import identifier, parse_failure
from app.adapters.catalog_types import BookData, cover_url
from app.adapters.contracts import AdapterError, FailureKind
from app.adapters.hardcover_details import AuthorDetails
from app.adapters.hardcover_discovery import FIELDS, book

HC_AUTHOR = """query ReaderAuthor($id: Int!, $offset: Int!) {
 authors(where: {id: {_eq: $id}}, limit: 1) { id name slug bio cached_image }
 books(where: {canonical_id: {_is_null: true}, contributions: {
  author_id: {_eq: $id}, _or: [{contribution: {_eq: "Author"}},
  {contribution: {_is_null: true}}]}},
  order_by: [{release_date: asc_nulls_last}, {id: asc}], limit: 25, offset: $offset) {
  $FIELDS
 }
}""".replace("$FIELDS", FIELDS)


class AuthorPage(BaseModel):
    author: AuthorDetails
    books: list[BookData]
    page: int
    has_more: bool = False
    stale: bool = False
    warning: str | None = None


async def detail(query, external_id, page):
    key = int(identifier("hardcover", external_id))
    try:
        data = await query(HC_AUTHOR, {"id": key, "offset": (page - 1) * 24})
        rows = data["authors"]
        if rows == []:
            raise AdapterError(
                FailureKind.NOT_FOUND, "This author is no longer available on Hardcover."
            )
        if not isinstance(rows, list) or len(rows) != 1 or rows[0]["id"] != key:
            raise parse_failure()
        row = rows[0]
        books = data["books"]
        if not isinstance(books, list) or len(books) > 25:
            raise parse_failure()
        parsed = [book(value) for value in books]
        if len({value.external_id for value in parsed}) != len(parsed) or any(
            value.canonical_id for value in parsed
        ):
            raise parse_failure()
        return AuthorPage(
            author=AuthorDetails(
                external_id=external_id,
                name=row["name"],
                slug=row.get("slug"),
                bio=row.get("bio"),
                image_url=cover_url((row.get("cached_image") or {}).get("url")),
            ),
            books=parsed[:24],
            page=page,
            has_more=len(parsed) > 24,
        )
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, ValidationError) as error:
        raise parse_failure() from error
