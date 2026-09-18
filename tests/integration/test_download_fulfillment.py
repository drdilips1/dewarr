# ruff: noqa: F811
"""Confirmed request closure is independent from transfer identity and current ownership."""

import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text

from app.config import get_settings
from app.db.models import (
    AcquisitionIntent,
    AcquisitionReservation,
    AcquisitionSelection,
    AcquisitionTarget,
    AssetContains,
    AuditEvent,
    DownloadAttempt,
    DownloadFulfillment,
    DownloadIdentityClaim,
    Library,
    LibraryAsset,
    LibraryGrant,
    User,
    Work,
)
from app.domain import download_attempts as downloads
from app.domain.acquisition import reconcile_requests
from app.domain.download_fulfillment import reconcile_work
from app.domain.work_merges import merge_works, preview_merge
from tests.integration.test_acquisition import body, catalog, request  # noqa: F401
from tests.integration.test_acquisition_selections import prepare, selection_route  # noqa: F401
from tests.integration.test_download_attempts import downloader, start  # noqa: F401

pytestmark = pytest.mark.integration


@pytest.fixture
async def selected(client, admin, catalog, selection_route, monkeypatch):
    wanted = await request(
        client,
        body(
            catalog,
            "audio",
            audio_library_id=str(catalog["library"]),
            audio_version_id=str(catalog["versions"][1]),
        ),
    )
    response = await prepare(client, {**selection_route, "intent_id": wanted["request"]["id"]})
    assert response.status_code == 201, response.text
    monkeypatch.setattr(get_settings(), "download_dispatch_enabled", True)
    return response.json()


@pytest.fixture
async def completed(client, database, selected, downloader):
    downloader.complete = True
    response = await start(client, selected)
    assert response.status_code == 202, response.text
    identifier = UUID(response.json()["id"])
    await downloads.run(identifier)
    async with database() as db:
        assert (await db.get(DownloadAttempt, identifier)).state == "complete"
    return identifier


async def asset(database, catalog, *, index=1, state="present", library_id=None, full=True):
    async with database() as db, db.begin():
        row = LibraryAsset(
            library_id=library_id or catalog["library"],
            external_id=str(uuid4()),
            version_id=catalog["versions"][index],
            medium="ebook" if index == 0 else "audio",
            state=state,
            full_content=full,
            match_status="matched",
        )
        db.add(row)
        await db.flush()
        db.add(AssetContains(asset_id=row.id, work_id=catalog["work"], verified=True))
        return row.id


async def reconcile(database, work_id):
    async with database() as db, db.begin():
        await reconcile_work(db, work_id)


async def selected_state(database, selected):
    async with database() as db:
        selection = await db.get(AcquisitionSelection, UUID(selected["id"]))
        reservation = await db.get(AcquisitionReservation, selection.reservation_id)
        return selection.state, reservation.state


async def test_completed_download_is_not_fulfillment(
    client, database, catalog, selected, completed
):
    await reconcile(database, catalog["work"])
    assert await selected_state(database, selected) == ("committed", "committed")
    view = (await client.get(f"/api/acquisition/downloads/{completed}")).json()
    assert view["fulfillment"] is None and view["can_recheck"]
    assert view["state"] == "complete"


async def test_confirmed_closure_is_concurrent_durable_and_keeps_claims(
    client, database, catalog, selected, completed, downloader
):
    asset_id = await asset(database, catalog)
    await asyncio.gather(*(reconcile(database, catalog["work"]) for _ in range(4)))
    assert await selected_state(database, selected) == ("fulfilled", "released")
    async with database() as db:
        selection = await db.get(AcquisitionSelection, UUID(selected["id"]))
        records = list(await db.scalars(select(DownloadFulfillment)))
        original = [row for row in records if row.target_id == selection.target_id]
        assert len(original) == 1 and original[0].asset_id == asset_id
        assert original[0].import_entry_id is None
        assert original[0].evidence["basis"] == "existing-library"
        assert len(records) == 2  # Generic and exact requests shared the reservation.
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "acquisition.fulfilled")
            )
            == 1
        )
        assert all(row.active for row in await db.scalars(select(DownloadIdentityClaim)))
    view = (await client.get(f"/api/acquisition/downloads/{completed}")).json()
    assert view["fulfillment"]["available_now"]
    assert "owner_id" not in str(view["fulfillment"])
    assert (await start(client, selected, "replayed-after-fulfillment")).json()["id"] == str(
        completed
    )
    await downloads.run(completed)
    assert downloader.calls.count("submit") == 1


@pytest.mark.parametrize(
    "options", [{"index": 0}, {"index": 2}, {"state": "stale"}, {"full": False}]
)
async def test_ineligible_asset_cannot_close_exact_recording(
    database, catalog, selected, completed, options
):
    await asset(database, catalog, **options)
    await reconcile(database, catalog["work"])
    assert await selected_state(database, selected) == ("committed", "committed")
    async with database() as db:
        selection = await db.get(AcquisitionSelection, UUID(selected["id"]))
        assert not await db.scalar(
            select(DownloadFulfillment.id).where(
                DownloadFulfillment.target_id == selection.target_id
            )
        )


async def test_history_does_not_claim_missing_or_newly_private_asset_is_available(
    client, database, admin, catalog, selected, completed
):
    asset_id = await asset(database, catalog)
    await reconcile(database, catalog["work"])
    async with database() as db, db.begin():
        (await db.get(LibraryAsset, asset_id)).state = "missing-confirmed"
    view = (await client.get(f"/api/acquisition/downloads/{completed}")).json()
    assert not view["fulfillment"]["available_now"]
    async with database() as db, db.begin():
        (await db.get(LibraryAsset, asset_id)).state = "present"
        (await db.get(User, UUID(admin["id"]))).role = "member"
    view = (await client.get(f"/api/acquisition/downloads/{completed}")).json()
    assert not view["fulfillment"]["available_now"]
    assert await selected_state(database, selected) == ("fulfilled", "released")
    await reconcile_requests()
    async with database() as db:
        assert all(row.active for row in await db.scalars(select(DownloadIdentityClaim)))


async def test_inaccessible_asset_and_revoked_account_do_not_create_fulfillment(
    database, admin, catalog, selected, completed
):
    async with database() as db, db.begin():
        library = await db.get(Library, catalog["library"])
        private = Library(
            integration_id=library.integration_id, external_id="private", name="Private"
        )
        db.add(private)
        await db.flush()
        private_id = private.id
        (await db.get(User, UUID(admin["id"]))).role = "member"
        db.add(LibraryGrant(user_id=UUID(admin["id"]), library_id=catalog["library"]))
    await asset(database, catalog, library_id=private_id)
    await reconcile(database, catalog["work"])
    assert await selected_state(database, selected) == ("committed", "committed")
    await asset(database, catalog)
    async with database() as db, db.begin():
        (await db.get(User, UUID(admin["id"]))).active = False
    await reconcile(database, catalog["work"])
    async with database() as db:
        assert not await db.scalar(select(DownloadFulfillment.id))


async def test_unknown_transfer_keeps_committed_reservation_even_if_request_is_satisfied(
    client, database, catalog, selected, downloader
):
    response = await start(client, selected)
    identifier = UUID(response.json()["id"])
    await downloads.run(identifier)
    async with database() as db, db.begin():
        (await db.get(DownloadAttempt, identifier)).state = "uncertain"
    await asset(database, catalog)
    await reconcile(database, catalog["work"])
    assert await selected_state(database, selected) == ("committed", "committed")
    async with database() as db:
        assert await db.scalar(select(DownloadFulfillment.id))
        assert all(row.active for row in await db.scalars(select(DownloadIdentityClaim)))


async def test_recheck_repairs_detached_legacy_target_without_new_dispatch(
    client, database, catalog, selected, completed, downloader, monkeypatch
):
    asset_id = await asset(database, catalog)
    async with database() as db, db.begin():
        target = await db.scalar(
            select(AcquisitionTarget)
            .join(AcquisitionIntent)
            .where(AcquisitionIntent.id == UUID(selected["intent_id"]))
        )
        target.reservation_id = None
        target.state, target.satisfied_asset_id = "satisfied", asset_id
    monkeypatch.setattr(get_settings(), "download_dispatch_enabled", False)
    response = await client.post(f"/api/acquisition/downloads/{completed}/recheck")
    assert response.status_code == 202, response.text
    assert response.json()["fulfillment"]["available_now"]
    assert await selected_state(database, selected) == ("fulfilled", "released")
    assert downloader.calls.count("submit") == 1
    assert (await client.post(f"/api/acquisition/downloads/{completed}/recheck")).status_code == 409


async def test_fulfilled_history_survives_book_merge_and_refuses_lossy_downgrade(
    database, admin, catalog, selected, completed
):
    from tests.integration.test_correction_migration import migrate

    await asset(database, catalog)
    await reconcile(database, catalog["work"])
    async with database() as db, db.begin():
        other = Work(title="Canonical Harbor", authors=["Writer"])
        db.add(other)
        await db.flush()
        user = await db.get(User, UUID(admin["id"]))
        preview = await preview_merge(db, catalog["work"], other.id, user.id)
        # Use the same command contract as the catalog correction API.
        await merge_works(db, user.id, catalog["work"], other.id, preview["revision"])
    async with database() as db:
        assert await db.scalar(select(DownloadFulfillment.id))
        assert all(row.active for row in await db.scalars(select(DownloadIdentityClaim)))
    async with database() as db:
        before = await db.scalar(text("SELECT version_num FROM alembic_version"))
    result = await migrate("downgrade", "0018_attempts")
    assert result.returncode != 0 and "Fulfillment history requires" in result.stderr
    async with database() as db:
        assert await db.scalar(text("SELECT version_num FROM alembic_version")) == before
