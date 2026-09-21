import pytest

from app.adapters.contracts import AdapterError, FailureKind
from app.adapters.hardcover_details import HC_DETAILS, HC_REVIEWS, details


def book():
    return {
        "id": 42,
        "rating": 4.25,
        "ratings_count": 120,
        "pages": 320,
        "contributions": [
            {"contribution": "Author", "author": {"id": 9, "name": "Writer", "bio": "Bio"}},
            {"contribution": "Narrator", "author": {"id": 10, "name": "Reader"}},
        ],
    }


async def test_details_keep_author_roles_and_public_review_spoilers():
    async def query(document, variables):
        assert variables == {"id": 42}
        if document == HC_DETAILS:
            return {"books": [book()]}
        assert document == HC_REVIEWS
        assert "privacy_setting_id: {_eq: 1}" in document
        assert "limit: 10" in document
        assert "private_notes" not in document
        return {
            "user_books": [
                {
                    "id": 7,
                    "user": {"username": "reader"},
                    "rating": 0,
                    "review_raw": "A public review",
                    "review_has_spoilers": True,
                }
            ]
        }

    value = await details(query, "42")
    assert [author.name for author in value.authors] == ["Writer"]
    assert value.reviews[0].spoilers
    assert value.reviews[0].rating == 0
    assert value.rating == 4.25


@pytest.mark.parametrize(
    "failure",
    [FailureKind.PERMISSION, FailureKind.RATE_LIMIT, FailureKind.PARSER, FailureKind.UNAVAILABLE],
)
async def test_review_outage_preserves_book_details(failure):
    async def query(document, variables):
        if document == HC_DETAILS:
            return {"books": [book()]}
        raise AdapterError(failure, "private upstream message")

    value = await details(query, "42")
    assert value.pages == 320
    assert value.reviews == []
    assert value.reviews_warning
    assert "private upstream" not in value.reviews_warning


@pytest.mark.parametrize("rows", [[], [{"id": 43}], [{"id": 42, "rating": 6}]])
async def test_invalid_or_missing_book_is_not_success(rows):
    async def query(*args):
        return {"books": rows}

    with pytest.raises(AdapterError):
        await details(query, "42")


async def test_missing_spoiler_flag_is_hidden_and_review_text_is_not_html():
    async def query(document, variables):
        if document == HC_DETAILS:
            return {"books": [book()]}
        return {
            "user_books": [
                {
                    "id": 7,
                    "user": {"username": "reader"},
                    "review_raw": "<script>untrusted</script>",
                }
            ]
        }

    value = await details(query, "42")
    assert value.reviews[0].spoilers
    assert value.reviews[0].text == "<script>untrusted</script>"
