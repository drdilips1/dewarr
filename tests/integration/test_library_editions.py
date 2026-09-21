from uuid import UUID

import pytest
from sqlalchemy import select

from app.db.models import LibraryAsset, LibraryGrant, Version, Work
from tests.integration.test_discovery import add_owned, login_member

pytestmark = pytest.mark.integration


async def edition(db, title, medium, *, authors=None, language=None, narrators=None):
    work = Work(title=title, authors=authors or ["Stephen King"], language=language)
    db.add(work)
    await db.flush()
    library = await add_owned(db, work)
    version = Version(work_id=work.id, medium=medium, title=title, narrators=narrators or [])
    db.add(version)
    await db.flush()
    asset = await db.scalar(select(LibraryAsset).where(LibraryAsset.library_id == library.id))
    asset.title, asset.medium, asset.version_id = title, medium, version.id
    asset.files = [
        {
            "path": f"/library/{version.id}/book.m4b"
            if medium == "audio"
            else f"/library/{version.id}/book.epub",
            "format": "m4b" if medium == "audio" else "epub",
        }
    ]
    await db.flush()
    return work, version, asset, library


@pytest.mark.parametrize(
    "title, other, medium, authors, language",
    [
        (
            "'Salem's Lot",
            "'Salem's Lot (read by Richard Nazarewich)",
            "audio",
            ["Stephen King"],
            None,
        ),
        ("Christine", "Christine (older version)", "audio", ["Stephen King"], None),
        (
            "America Before: The Key to Earth's Lost Civilization: A new investigation",
            "America Before",
            "ebook",
            ["Graham Hancock"],
            "en",
        ),
        (
            "The Coddling of the American Mind",
            "The Coddling of the American Mind: How Good Intentions and Bad Ideas "
            "Are Setting Up a Generation for Failure (Unabridged)",
            "ebook",
            ["Greg Lukianoff", "Jonathan Haidt"],
            "en-US",
        ),
        (
            "Countdown to Zero Day: Stuxnet and the Launch of the World's First Digital Weapon",
            "Countdown to Zero Day: Stuxnet and the Launch of the World's "
            "First Digital Weapon (Unabridged)",
            "ebook",
            ["Kim Zetter"],
            "en",
        ),
    ],
)
async def test_real_world_variants_keep_versions_under_one_book(
    client, admin, database, title, other, medium, authors, language
):
    async with database() as db, db.begin():
        first, first_version, _, _ = await edition(
            db, title, medium, authors=authors, language=language
        )
        second, second_version, _, _ = await edition(
            db,
            other,
            "audio",
            authors=list(reversed(authors)),
            language="English" if language else None,
        )
        first_id, second_id = str(first.id), str(second.id)
        version_ids = {str(first_version.id), str(second_version.id)}
    for endpoint in ["/api/catalog/works", "/api/library/books"]:
        response = await client.get(endpoint, params={"limit": 1})
        assert response.status_code == 200, response.text
        page = response.json()
        assert page["total"] == 1
        work = page["items"][0]
        assert work["id"] == first_id
        assert work["availability"]["audio_versions"] == (2 if medium == "audio" else 1)
        assert work["availability"]["ebook_versions"] == (1 if medium == "ebook" else 0)
    for work_id in [first_id, second_id]:
        detail = (await client.get(f"/api/catalog/works/{work_id}")).json()
        assert detail["id"] == work_id
        copies = (await client.get("/api/library/assets", params={"work_id": work_id})).json()
        assert copies["total"] == 2
        assert {item["version_id"] for item in copies["items"]} == version_ids
        assert len({item["files"][0]["path"] for item in copies["items"]}) == 2
        if "Salem" in title:
            assert detail["availability"]["primary_audio_narrators"] == ["Richard Nazarewich"]
            assert any(item["narrators"] == ["Richard Nazarewich"] for item in copies["items"])
    assert (await client.get("/api/discovery/library")).json()["has_more"] is False
    assert len((await client.get("/api/discovery/library")).json()["items"]) == 1


async def test_counts_versions_not_files_or_repeated_copies(client, admin, database):
    async with database() as db, db.begin():
        work, version, asset, _ = await edition(db, "Book", "ebook")
        other_library = await add_owned(db, work)
        other = await db.scalar(
            select(LibraryAsset).where(LibraryAsset.library_id == other_library.id)
        )
        other.version_id = version.id
        asset.files += [{"path": "/library/book.pdf", "format": "pdf"}]
        await edition(db, "Book", "ebook")
    work = (await client.get("/api/catalog/works")).json()["items"][0]
    assert work["availability"]["ebook_versions"] == 2


async def test_private_recording_is_not_counted_or_named(client, admin, database):
    async with database() as db, db.begin():
        first, _, _, library = await edition(db, "Book", "audio", narrators=["Public Narrator"])
        second, _, _, _ = await edition(db, "Book (read by Private Narrator)", "audio")
        first.catalog_public = second.catalog_public = False
        work_id, library_id = first.id, library.id
    user = await login_member(client)
    async with database() as db, db.begin():
        db.add(LibraryGrant(user_id=UUID(str(user)), library_id=library_id))
    work = (await client.get(f"/api/catalog/works/{work_id}")).json()
    assert work["availability"]["audio_versions"] == 1
    assert work["availability"]["primary_audio_narrators"] == ["Public Narrator"]


async def test_ambiguous_subtitles_are_not_collapsed(client, admin, database):
    async with database() as db, db.begin():
        for title in [
            "A Shared Title",
            "A Shared Title: First Journey",
            "A Shared Title: Another Journey",
        ]:
            await edition(db, title, "audio")
    assert (await client.get("/api/library/books")).json()["total"] == 3
