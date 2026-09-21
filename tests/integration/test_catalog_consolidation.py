from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.db.models import LibraryAsset, User, WorkMetadataSource
from app.domain.catalog_consolidation import consolidate
from tests.integration.test_library_discovery import add

pytestmark = pytest.mark.integration


async def test_same_verified_book_groups_reversibly_without_reassigning_copies(
    client, admin, database
):
    async with database() as db, db.begin():
        actor = await db.get(User, UUID(admin["id"]))
        works = []
        assets = []
        for title, language in [
            ("One", "English"),
            ("One audio", "eng"),
            ("Translation", "fr"),
            ("Unknown", None),
        ]:
            work, _, asset = await add(db, title)
            work.language = language
            works.append(work)
            assets.append((asset.id, asset.version_id))
            db.add(
                WorkMetadataSource(
                    work_id=work.id,
                    provider="hardcover",
                    external_id="42",
                    accepted=True,
                    manual_match=False,
                    fetched_at=datetime.now(UTC),
                    snapshot={},
                )
            )
        await db.flush()
        result = await consolidate(db, actor, [work.id for work in works])
        assert len(result) == 1 and result[0]["status"] == "merged"
        by_id = {str(work.id): work for work in works}
        assert by_id[result[0]["source_id"]].redirect_to == UUID(result[0]["target_id"])
        assert {result[0]["source_id"], result[0]["target_id"]} == {str(w.id) for w in works[:2]}
        assert works[2].redirect_to is None and works[3].redirect_to is None
        for asset_id, version_id in assets:
            assert (await db.get(LibraryAsset, asset_id)).version_id == version_id


async def test_conflicting_sources_are_not_consolidated(client, admin, database):
    async with database() as db, db.begin():
        actor = await db.get(User, UUID(admin["id"]))
        works = []
        for title in ["First", "Second"]:
            work, _, _ = await add(db, title)
            work.language = "en"
            works.append(work)
            db.add(
                WorkMetadataSource(
                    work_id=work.id,
                    provider="hardcover",
                    external_id="42",
                    accepted=True,
                    manual_match=False,
                    fetched_at=datetime.now(UTC),
                    snapshot={},
                )
            )
        db.add(
            WorkMetadataSource(
                work_id=works[0].id,
                provider="hardcover",
                external_id="43",
                accepted=False,
                manual_match=False,
                fetched_at=datetime.now(UTC),
                snapshot={},
            )
        )
        await db.flush()
        assert await consolidate(db, actor, [work.id for work in works]) == []
        assert all(work.redirect_to is None for work in works)
