"""Look up exact edition identifiers using Hardcover's published edition fields."""

from pydantic import ValidationError

from app.adapters.catalog_providers import Hardcover, identifier, parse_failure
from app.adapters.catalog_types import SearchPage
from app.adapters.hardcover_discovery import book
from app.importing.match_evidence import isbn_forms

HC_IDENTIFIERS = """query LibraryIdentifierMatch($isbns: [String!]!, $asins: [String!]!) {
 editions(where: {_or: [{isbn_10: {_in: $isbns}}, {isbn_13: {_in: $isbns}},
 {asin: {_in: $asins}}]}, limit: 51, order_by: {id: asc}) {
 id book_id title isbn_10 isbn_13 asin language { code2 code3 }
 reading_format { format }
 book { id canonical_id title release_year cached_image cached_contributors }
 }
}"""


async def search(query, identifiers):
    isbns = sorted(
        {form for scheme, value in identifiers if scheme == "isbn" for form in isbn_forms(value)}
    )
    asins = sorted({value for scheme, value in identifiers if scheme == "asin"})
    if len(isbns) + len(asins) > 100:
        raise parse_failure()
    try:
        rows = (await query(HC_IDENTIFIERS, {"isbns": isbns, "asins": asins}))["editions"]
        if not isinstance(rows, list) or len(rows) > 51:
            raise parse_failure()
        books = {}
        for row in rows[:50]:
            key = identifier("hardcover", str(row["book_id"]))
            value = book(row["book"])
            if value.external_id != key:
                raise parse_failure()
            books.setdefault(key, value).editions.append(Hardcover.edition(row, key))
        return SearchPage(
            provider="hardcover", items=list(books.values()), page=1, has_more=len(rows) > 50
        )
    except (ValueError, TypeError, KeyError, AttributeError, ValidationError) as error:
        raise parse_failure() from error


HC_TITLE = """query LibraryTitleMatch($title: String!) {
 books(where: {title: {_ilike: $title}}, limit: 21, order_by: {id: asc}) {
 id canonical_id title release_year cached_image cached_contributors
 }
}"""


async def title_search(query, title):
    pattern = title.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    try:
        rows = (await query(HC_TITLE, {"title": pattern}))["books"]
        if not isinstance(rows, list) or len(rows) > 21:
            raise parse_failure()
        return SearchPage(
            provider="hardcover",
            items=[book(row) for row in rows[:20]],
            page=1,
            has_more=len(rows) > 20,
        )
    except (ValueError, TypeError, KeyError, AttributeError, ValidationError) as error:
        raise parse_failure() from error
