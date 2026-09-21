import pytest

from app.adapters.contracts import AdapterError, FailureKind
from app.adapters.hardcover_authors import HC_AUTHOR, detail


async def test_author_identity_roles_and_bounded_pagination():
    async def query(document, variables):
        assert document == HC_AUTHOR
        assert variables == {"id": 9, "offset": 24}
        assert 'contribution: {_eq: "Author"}' in document
        assert "author_id: {_eq: $id}" in document
        return {
            "authors": [
                {
                    "id": 9,
                    "name": "Writer",
                    "bio": "Biography",
                    "cached_image": {"url": "https://untrusted.example/image"},
                }
            ],
            "books": [{"id": i, "title": f"Book {i}"} for i in range(1, 26)],
        }

    value = await detail(query, "9", 2)
    assert value.author.name == "Writer"
    assert value.author.image_url is None
    assert len(value.books) == 24
    assert value.has_more
    assert value.page == 2


@pytest.mark.parametrize(
    "authors, books",
    [
        ([{"id": 10, "name": "Wrong author"}], []),
        ([{"id": 9, "name": "Writer"}], [{"id": 1, "title": "Book"}] * 2),
        ([{"id": 9, "name": "Writer"}], [{"id": 1, "title": "Book", "canonical_id": 2}]),
        ([{"id": 9, "name": "Writer"}], None),
    ],
)
async def test_rejects_malformed_author_responses(authors, books):
    async def query(*args):
        return {"authors": authors, "books": books}

    with pytest.raises(AdapterError) as error:
        await detail(query, "9", 1)
    assert error.value.kind == FailureKind.PARSER


async def test_missing_author_and_invalid_identifier():
    calls = []

    async def query(*args):
        calls.append(args)
        return {"authors": [], "books": []}

    with pytest.raises(AdapterError) as error:
        await detail(query, "9", 1)
    assert error.value.kind == FailureKind.NOT_FOUND
    with pytest.raises(AdapterError):
        await detail(query, "invalid", 1)
    assert len(calls) == 1
