import pytest

from app.adapters.contracts import AdapterError
from app.adapters.hardcover_identifiers import HC_IDENTIFIERS, HC_TITLE, search, title_search


async def test_identifier_lookup_expands_isbn_forms_and_keeps_edition_evidence():
    async def query(document, variables):
        assert document == HC_IDENTIFIERS
        assert variables == {"isbns": ["0306406152", "9780306406157"], "asins": ["B000000001"]}
        return {
            "editions": [
                {
                    "id": 7,
                    "book_id": 42,
                    "isbn_10": "0306406152",
                    "language": {"code2": "en"},
                    "book": {
                        "id": 42,
                        "title": "A book",
                        "cached_contributors": [{"author": {"name": "Writer"}}],
                    },
                }
            ]
        }

    value = await search(query, [("isbn", "9780306406157"), ("asin", "B000000001")])
    assert value.items[0].external_id == "42"
    assert value.items[0].editions[0].identifiers == {"isbn_10": "0306406152"}
    assert not value.has_more


async def test_identifier_book_mismatch_rejected():
    async def query(*args):
        return {"editions": [{"id": 7, "book_id": 42, "book": {"id": 43, "title": "Wrong book"}}]}

    with pytest.raises(AdapterError):
        await search(query, [("isbn", "9780306406157")])


async def test_title_lookup_escapes_wildcards_and_reports_truncation():
    async def query(document, variables):
        assert document == HC_TITLE
        assert variables["title"] == "100\\%\\_complete%"
        return {"books": [{"id": i, "title": "A book"} for i in range(1, 22)]}

    page = await title_search(query, "100%_complete")
    assert page.has_more and len(page.items) == 20
