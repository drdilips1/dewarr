import codecs
import csv
import io

import pytest

from app.adapters.list_csv import MAX_BYTES, MAX_ROWS, parse_snapshot


def fixture(rows, headers=None, delimiter=","):
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=delimiter)
    writer.writerow(headers or ["Book Id", "Title", "Author", "ISBN13", "Private Notes"])
    writer.writerows(rows)
    return output.getvalue().encode()


def test_goodreads_defaults_wrapped_isbn_duplicates_and_private_fields():
    value = parse_snapshot(
        fixture(
            [
                ["12", "A, Book", "Writer", '="9780306406157"', "private-data"],
                ["12", "A, Book", "Writer", '="9780306406157"', "another secret"],
            ]
        )
    )
    assert value.records[0]["isbn13"] == "9780306406157"
    assert value.duplicates == 1 and len(value.records) == 1
    assert "private-data" not in str(value) and "another secret" not in str(value)


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "cp1252"])
def test_encodings_preserve_titles(encoding):
    data = "Title,Author\r\nCafé,René\r\n".encode(encoding)
    result = parse_snapshot(data, encoding="cp1252" if encoding == "cp1252" else "auto")
    assert result.records[0]["title"] == "Café"


@pytest.mark.parametrize(
    "data,match",
    [
        (b"\xffbad", "encoding"),
        (b"Title,Author\nA,\x00", "NUL"),
        (b"Title,Title\nA,B", "unique"),
        (b"Title,Author\nA,B,C", "columns"),
        (b'Title,Author\n"A,B', "quoting"),
        (b"Title,Author\n,Writer", "title"),
        (b"Book Id,Title\n=1+1,A", "Goodreads ID"),
        (fixture([["1", "A", "W", "", ""], ["1", "Other", "W", "", ""]]), "Conflicting"),
    ],
)
def test_malformed_exports_fail_without_partial_result(data, match):
    with pytest.raises(ValueError, match=match):
        parse_snapshot(data)


def test_mapping_required_and_custom_columns_and_shelves():
    data = fixture(
        [["A", "W", "favorites, next", "to-read"]], ["Name", "Creator", "Tags", "Status"], ";"
    )
    value = parse_snapshot(data, delimiter=";")
    assert value.needs_mapping and not value.records
    mapped = parse_snapshot(
        data,
        delimiter=";",
        mapping={
            "title": "Name",
            "author": "Creator",
            "shelves": "Tags",
            "exclusive_shelf": "Status",
        },
    )
    assert mapped.shelves == ["favorites", "next", "to-read"]
    assert mapped.records[0]["identity_key"].startswith("csv:")


@pytest.mark.parametrize(
    "mapping",
    [[], {"title": "Missing"}, {"title": "Title", "author": "Title"}, {"notes": "Private Notes"}],
)
def test_invalid_mapping(mapping):
    with pytest.raises(ValueError, match="Map each"):
        parse_snapshot(fixture([["1", "A", "W", "", ""]]), mapping=mapping)


def test_bounded_size_rows_and_inert_formula():
    with pytest.raises(ValueError, match="4 MiB"):
        parse_snapshot(b"a" * (MAX_BYTES + 1))
    with pytest.raises(ValueError, match="2,000"):
        parse_snapshot(fixture([[str(n + 1), "A", "W", "", ""] for n in range(MAX_ROWS + 1)]))
    value = parse_snapshot(fixture([["1", "=HYPERLINK(unsafe)", "Writer", '=CALL("x")', ""]]))
    assert value.records[0]["title"] == "=HYPERLINK(unsafe)"
    assert value.records[0]["isbn13"] is None
    assert parse_snapshot(codecs.BOM_UTF8 + b"Title,Author\n").records == []
