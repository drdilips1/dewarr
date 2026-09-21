from datetime import UTC, datetime

import pytest

from app.db.models import LibraryGrant, Work, WorkMetadataSource
from tests.integration.test_discovery import login_member
from tests.integration.test_library_discovery import add

pytestmark = pytest.mark.integration


async def browse(client, kind="authors", **params):
    response = await client.get(f"/api/library/groups/{kind}", params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def test_groups_count_owned_books_before_paging_and_include_local_series(
    client, admin, database
):
    async with database() as db, db.begin():
        first, library, _ = await add(
            db, "First", metadata_snapshot={"series": [{"name": "Earthsea"}]}
        )
        first.authors = ["Ursula Le Guin", "Another Writer"]
        second, _, _ = await add(
            db,
            "Second",
            medium="audio",
            state="stale",
            metadata_snapshot={"series": [{"name": "Earthsea"}]},
        )
        second.authors = ["Ursula Le Guin"]
        alias, _, _ = await add(db, "Duplicate", medium="audio")
        alias.redirect_to = first.id
        missing, _, _ = await add(db, "Missing", state="missing-confirmed")
        missing.authors = ["Missing Writer"]
        db.add(Work(title="Only saved", authors=["Saved Writer"]))
        db.add(
            WorkMetadataSource(
                work_id=first.id,
                provider="hardcover",
                external_id="101",
                accepted=True,
                fetched_at=datetime.now(UTC),
                snapshot={"series": [{"name": "Earthsea", "external_id": "7"}]},
            )
        )
        library_id, first_id = str(library.id), str(first.id)
    authors = await browse(client, limit=1)
    assert authors["total"] == 2
    assert authors["items"][0]["name"] == "Another Writer"
    next_page = await browse(client, offset=1, limit=1)
    assert next_page["items"][0]["book_count"] == 2
    series = await browse(client, "series")
    assert series["items"][0]["hardcover_book_id"] == "101"
    assert next_page["items"][0]["hardcover_book_id"] == "101"
    assert series["total"] == 1
    assert series["items"][0]["book_count"] == 2
    assert series["items"][0]["external_id"] == "7"
    assert len(series["items"][0]["books"]) == 2
    assert (await browse(client, "series", library_id=library_id))["items"][0]["book_count"] == 1
    assert (await browse(client, q="%"))["total"] == 0
    assert (await browse(client, q="ursula", medium="ebook"))["items"][0]["book_count"] == 1
    detail = await client.get(
        "/api/library/groups/authors/books", params={"name": "ursula le guin", "medium": "ebook"}
    )
    assert detail.status_code == 200, detail.text
    assert [book["id"] for book in detail.json()["items"]] == [first_id]


@pytest.mark.parametrize("role", ["member", "viewer"])
async def test_groups_and_book_details_respect_library_grants(client, admin, database, role):
    async with database() as db, db.begin():
        allowed, library, _ = await add(
            db, "Allowed", metadata_snapshot={"series": [{"name": "Visible series"}]}
        )
        allowed.authors = ["Visible writer"]
        secret, hidden, _ = await add(
            db, "Secret", metadata_snapshot={"series": [{"name": "Secret series"}]}
        )
        secret.authors = ["Secret writer"]
        library_id, hidden_id = library.id, hidden.id
    owner = await login_member(client, role)
    assert (await browse(client))["total"] == 0
    async with database() as db, db.begin():
        db.add(LibraryGrant(library_id=library_id, user_id=owner))
    assert (await browse(client))["items"][0]["name"] == "Visible writer"
    assert (await browse(client, "series"))["items"][0]["name"] == "Visible series"
    assert (await browse(client, library_id=str(hidden_id)))["total"] == 0
    for kind, name in [("authors", "Secret writer"), ("series", "Secret series")]:
        response = await client.get(f"/api/library/groups/{kind}/books", params={"name": name})
        assert response.status_code == 200
        assert response.json()["total"] == 0


async def test_groups_require_login(client):
    assert (await client.get("/api/library/groups/authors")).status_code == 401
