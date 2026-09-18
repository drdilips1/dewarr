from copy import deepcopy

import pytest

from app.adapters.catalog_providers import Hardcover
from app.adapters.contracts import AdapterError
from app.adapters.hardcover_lists import ListPage, choices, page
from app.domain.hardcover_subscriptions import advance


def header():
    return {
        "id": 9,
        "name": "A private list",
        "books_count": 2,
        "updated_at": "2026-09-18T00:00:00Z",
        "public": False,
        "user_id": 7,
    }


def member(key=1, book_id=42):
    return {
        "id": key,
        "book_id": book_id,
        "edition_id": None,
        "position": key,
        "date_added": None,
        "book": {
            "id": book_id,
            "title": f"Book {book_id}",
            "cached_contributors": [{"author": {"name": "Writer"}}],
        },
    }


async def test_page_uses_keyset_order_and_minimal_book_fields():
    calls = []

    async def query(document, variables):
        calls.append((document, variables))
        return {"lists": [{**header(), "list_books": [member(11), member(12, 43)]}]}

    result = await page(query, "9", 10)
    assert result.cursor == 12 and len(result.items) == 2
    assert result.items[0]["authors"] == ["Writer"]
    assert "review" not in str(result.items) and "order_by: {id: asc}" in calls[0][0]
    assert calls[0][1] == {"id": 9, "after": 10}


@pytest.mark.parametrize(
    "change",
    [
        lambda r: r.update(books_count=5001),
        lambda r: r.update(books_count=True),
        lambda r: r.update(updated_at="not-date"),
        lambda r: r.update(public="false"),
        lambda r: r.update(list_books=[member(1), member(1)]),
        lambda r: r.update(list_books=[{**member(), "book": None}]),
        lambda r: r.update(list_books=[{**member(), "book_id": 44}]),
        lambda r: r.update(list_books=[{**member(), "edition_id": 0}]),
        lambda r: r.update(list_books=[{**member(), "date_added": "invalid"}]),
    ],
)
async def test_malformed_or_hidden_memberships_never_become_empty_snapshots(change):
    row = {**header(), "list_books": [member()]}
    change(row)

    async def query(*args):
        return {"lists": [row]}

    with pytest.raises(AdapterError):
        await page(query, "9", 0)


@pytest.mark.parametrize("mode", ["owned", "followed", "public"])
async def test_list_choices_are_paged_and_scoped(mode):
    async def query(document, variables):
        rows = [{**header(), "id": n, "public": mode == "public"} for n in range(1, 27)]
        if mode == "public":
            return {"lists": rows}
        if mode == "followed":
            return {"me": [{"id": 7, "followed_lists": [{"id": r["id"], "list": r} for r in rows]}]}
        return {"me": [{"id": 7, "lists": rows}]}

    result = await choices(query, mode, 0)
    assert len(result.items) == 25 and result.next_cursor == 25


async def test_no_access_and_graphql_partial_errors_are_rejected():
    async def query(*args):
        return {"lists": []}

    with pytest.raises(AdapterError):
        await page(query, "9", 0)

    async def request(*args, **kwargs):
        return {"data": {"lists": []}, "errors": [{"extensions": {"code": "access-denied"}}]}

    with pytest.raises(AdapterError):
        await Hardcover(request).list_page("9")


def test_staging_requires_two_equal_complete_passes():
    info = {"count": 2, "name": "List"}
    rows = [{"entry_id": 1}, {"entry_id": 2}]
    stage, done = advance(None, ListPage(info, rows, 2))
    assert not done
    stage, done = advance(stage, ListPage(info, [], 2))
    assert stage["phase"] == "verify" and not done and stage["cursor"] == 0
    with pytest.raises(AdapterError):
        advance(deepcopy(stage), ListPage(info, [{"entry_id": 3}], 3))
    with pytest.raises(AdapterError):
        advance(deepcopy(stage), ListPage(info, [], 0))
    stage, done = advance(stage, ListPage(info, rows, 2))
    assert not done
    stage, done = advance(stage, ListPage(info, [], 2))
    assert done
    with pytest.raises(AdapterError):
        advance(None, ListPage(info, [], 0))
    with pytest.raises(AdapterError):
        advance(stage, ListPage({**info, "name": "Changed"}, [], 2))
