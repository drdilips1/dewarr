from datetime import date

import pytest

from app.adapters.catalog_providers import Hardcover
from app.adapters.contracts import AdapterError
from app.adapters.hardcover_discovery import (
    HC_DISCOVERY_BOOKS,
    HC_RECENT,
    HC_RELATED,
    HC_TRENDING,
)


def row(key, **extra):
    return {"id": key, "title": f"Book {key}", **extra}


def adapter(responses):
    calls = []

    async def request(method, path, *, json):
        calls.append(json)
        return {"data": responses[json["query"]]}

    return Hardcover(request), calls


async def test_trending_keeps_rank_and_batches_hydration_without_editions():
    source, calls = adapter(
        {
            HC_TRENDING: {"books_trending": {"ids": list(range(21, 0, -1))}},
            HC_DISCOVERY_BOOKS: {"books": [row(key, rating=4.25) for key in range(2, 22)]},
        }
    )
    result = await source.discovery("trending", 2, date(2026, 9, 18))
    assert result.has_more
    assert result.items[0].rating == 4.25
    assert "rating" in calls[1]["query"]
    assert [b.external_id for b in result.items] == [str(key) for key in range(21, 1, -1)]
    assert len(calls) == 2 and calls[0]["variables"] == {"offset": 20}
    assert calls[1]["variables"]["ids"] == list(range(21, 1, -1))


@pytest.mark.parametrize("value", [None, {}, [True], [1, 1], [-1], [2147483648], ["42"]])
async def test_malformed_trending_never_looks_like_an_empty_success(value):
    source, _ = adapter({HC_TRENDING: {"books_trending": {"ids": value}}})
    with pytest.raises(AdapterError):
        await source.discovery("trending", 1, date(2026, 9, 18))


async def test_provider_declared_error_is_not_an_empty_shelf():
    source, _ = adapter({HC_TRENDING: {"books_trending": {"ids": [], "error": "private"}}})
    with pytest.raises(AdapterError, match="unexpected response"):
        await source.discovery("trending", 1, date(2026, 9, 18))


async def test_empty_shelf_does_not_fetch_editions_or_books():
    source, calls = adapter({HC_TRENDING: {"books_trending": {"ids": []}}})
    assert not (await source.discovery("trending", 1, date(2026, 9, 18))).items
    assert len(calls) == 1


async def test_missing_hydrated_book_is_explicit_and_unrequested_ids_rejected():
    responses = {
        HC_TRENDING: {"books_trending": {"ids": [1, 2]}},
        HC_DISCOVERY_BOOKS: {"books": [row(2)]},
    }
    source, _ = adapter(responses)
    result = await source.discovery("trending", 1, date(2026, 9, 18))
    assert result.warning and [b.external_id for b in result.items] == ["2"]
    responses[HC_DISCOVERY_BOOKS] = {"books": [row(3)]}
    with pytest.raises(AdapterError):
        await source.discovery("trending", 1, date(2026, 9, 18))


async def test_new_releases_use_a_bounded_date_window_and_not_search_popularity():
    source, calls = adapter({HC_RECENT: {"books": [row(1, release_date="2026-09-17")]}})
    result = await source.discovery("new-releases", 1, date(2026, 9, 18))
    assert result.items[0].release_date == date(2026, 9, 17)
    assert calls[0]["variables"] == {"from": "2026-06-20", "to": "2026-09-18", "offset": 0}


@pytest.mark.parametrize(
    "extra",
    [
        {"release_date": "2027-01-01"},
        {"release_date": "2020-01-01"},
        {"release_date": None},
        {"release_date": "invalid"},
        {"release_date": "2026-09-17", "canonical_id": 22},
    ],
)
async def test_invalid_release_date_or_redirect_does_not_claim_new_publication(extra):
    source, _ = adapter({HC_RECENT: {"books": [row(1, **extra)]}})
    with pytest.raises(AdapterError):
        await source.discovery("new-releases", 1, date(2026, 9, 18))


async def test_related_suggestions_preserve_provider_order_and_exclude_the_seed():
    source, calls = adapter(
        {
            HC_RELATED: {"books": [row(1, cached_similar_book_ids=[3, 1, 2])]},
            HC_DISCOVERY_BOOKS: {"books": [row(2), row(3)]},
        }
    )
    result = await source.related("1")
    assert [b.external_id for b in result.items] == ["3", "2"]
    assert calls[1]["variables"] == {"ids": [3, 2]}


async def test_related_rejects_an_unknown_cached_similarity_shape():
    source, _ = adapter({HC_RELATED: {"books": [row(1, cached_similar_book_ids={})]}})
    with pytest.raises(AdapterError):
        await source.related("1")
