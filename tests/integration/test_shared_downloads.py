# ruff: noqa: F811
"""One reviewed transfer retains independently authorized book requests."""

import asyncio
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text

from app.adapters.contracts import AdapterError, FailureKind
from app.db.models import (
    AcquisitionReason,
    AcquisitionReservation,
    AcquisitionSelection,
    AssetContains,
    DownloadAttempt,
    DownloadCapacity,
    DownloadFulfillment,
    DownloadIdentityClaim,
    DownloadMembership,
    LibraryAsset,
    User,
    Version,
    Work,
)
from app.db.session import get_engine
from app.domain import download_attempts as downloads
from app.domain import download_reviews
from app.domain.download_fulfillment import reconcile_work
from tests.integration.test_acquisition import body, catalog, request  # noqa: F401
from tests.integration.test_acquisition_selections import prepare, selection_route  # noqa: F401
from tests.integration.test_correction_migration import migrate
from tests.integration.test_download_attempts import downloader, selected  # noqa: F401

pytestmark = pytest.mark.integration


@pytest.fixture
async def second(client, database, selection_route, selected):
    async with database() as db, db.begin():
        work = Work(title="Roads", authors=["Writer"])
        db.add(work)
        await db.flush()
        version = Version(work_id=work.id, medium="audio", language="en", narrators=["Reader A"])
        db.add(version)
        await db.flush()
        work_id, version_id = work.id, version.id
    wanted = await request(client, body({"work": work_id}, "audio"))
    response = await prepare(
        client,
        {
            **selection_route,
            "intent_id": wanted["request"]["id"],
            "confirmed_work_id": str(work_id),
        },
        key="second-book-selection",
    )
    assert response.status_code == 201, response.text
    return {**response.json(), "version_id": str(version_id)}


async def grouped(client, first, second, key="shared-download-command"):
    return await client.post(
        "/api/acquisition/downloads",
        headers={"Idempotency-Key": key},
        json={"selection_id": first["id"], "additional_selection_ids": [second["id"]]},
    )


async def add_asset(database, work_id, version_id, library_id):
    async with database() as db, db.begin():
        asset = LibraryAsset(
            library_id=library_id,
            external_id=str(uuid4()),
            version_id=version_id,
            medium="audio",
            state="present",
            full_content=True,
            match_status="matched",
        )
        db.add(asset)
        await db.flush()
        db.add(AssetContains(asset_id=asset.id, work_id=work_id, verified=True))
    async with database() as db, db.begin():
        await reconcile_work(db, work_id)


async def test_concurrent_grouping_replay_and_child_lookup(client, database, selected, second):
    responses = await asyncio.gather(
        grouped(client, selected, second),
        grouped(client, selected, second),
        grouped(client, second, selected, "reversed-group-command"),
    )
    assert all(row.status_code == 202 for row in responses), [row.text for row in responses]
    assert len({row.json()["id"] for row in responses}) == 1
    attempt_id = responses[0].json()["id"]
    for item in (selected, second):
        listing = await client.get(
            "/api/acquisition/downloads", params={"selection_id": item["id"]}
        )
        assert listing.json()["total"] == 1 and listing.json()["items"][0]["id"] == attempt_id
        replay = await client.post(
            "/api/acquisition/downloads",
            headers={"Idempotency-Key": "member-replay-" + item["id"]},
            json={"selection_id": item["id"]},
        )
        assert replay.status_code == 202 and replay.json()["id"] == attempt_id
    assert {m["work_title"] for m in responses[0].json()["members"]} == {"Harbor", "Roads"}
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(DownloadAttempt)) == 1
        assert await db.scalar(select(func.count()).select_from(DownloadCapacity)) == 1
        assert await db.scalar(select(func.count()).select_from(DownloadIdentityClaim)) == 1
        assert await db.scalar(select(func.count()).select_from(DownloadMembership)) == 2
        assert {r.state for r in await db.scalars(select(AcquisitionSelection))} == {"committed"}


async def test_changed_idempotency_scope_and_retroactive_expansion_rejected(
    client, database, selected, second
):
    original = await client.post(
        "/api/acquisition/downloads",
        headers={"Idempotency-Key": "original-one-book-command"},
        json={"selection_id": selected["id"]},
    )
    assert original.status_code == 202
    for key in ("original-one-book-command", "new-expansion-command"):
        response = await grouped(client, selected, second, key)
        assert response.status_code == 409, response.text
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(DownloadMembership)) == 1
        assert (await db.get(AcquisitionSelection, UUID(second["id"]))).state == "prepared"


@pytest.mark.parametrize("change", ["route", "source", "automatic", "cancelled", "foreign"])
async def test_batch_incompatibility_rolls_back_every_selection(
    client, database, selected, second, change
):
    async with database() as db, db.begin():
        row = await db.get(AcquisitionSelection, UUID(second["id"]))
        if change == "route":
            row.frozen = {
                **row.frozen,
                "mapping": {**row.frozen["mapping"], "relative_path": "other"},
            }
        elif change == "source":
            row.frozen = {**row.frozen, "source_generation": 2}
        elif change == "automatic":
            row.frozen = {**row.frozen, "automatic_selection": {"dispatch_approval": {}}}
        elif change == "cancelled":
            row.state = "cancelled"
        elif change == "foreign":
            other = User(
                username="other-pack-owner",
                display_name="Other",
                role="member",
                password_hash="not-a-login",
            )
            db.add(other)
            await db.flush()
            row.owner_id = other.id
    response = await grouped(client, selected, second)
    assert response.status_code in {404, 409, 422}, response.text
    async with database() as db:
        assert not await db.scalar(select(DownloadAttempt.id))
        assert not await db.scalar(select(DownloadMembership.selection_id))
        assert (await db.get(AcquisitionSelection, UUID(selected["id"]))).state == "prepared"


async def test_cancel_entire_unsubmitted_transfer_releases_each_selection(
    client, database, selected, second
):
    started = await grouped(client, selected, second)
    cancelled = await client.delete("/api/acquisition/downloads/" + started.json()["id"])
    assert cancelled.status_code == 200 and cancelled.json()["state"] == "cancelled"
    async with database() as db:
        for item in (selected, second):
            selection = await db.get(AcquisitionSelection, UUID(item["id"]))
            assert selection.state == "cancelled"
            assert (
                await db.get(AcquisitionReservation, selection.reservation_id)
            ).state == "planned"
        assert not await db.scalar(
            select(DownloadIdentityClaim.id).where(DownloadIdentityClaim.active)
        )


@pytest.mark.parametrize("first_change", ["satisfied", "withdrawn"])
async def test_other_book_continues_when_representative_no_longer_wanted(
    client, database, selected, second, catalog, downloader, first_change
):
    response = await grouped(client, selected, second)
    identifier = UUID(response.json()["id"])
    if first_change == "satisfied":
        await add_asset(database, catalog["work"], catalog["versions"][1], catalog["library"])
    else:
        async with database() as db, db.begin():
            reason = await db.scalar(
                select(AcquisitionReason).where(
                    AcquisitionReason.intent_id == UUID(selected["intent_id"])
                )
            )
            reason.active = False
    downloader.complete = True
    await downloads.run(identifier)
    await downloads.run(identifier)
    assert downloader.calls.count("submit") == 1
    current = (await client.get(f"/api/acquisition/downloads/{identifier}")).json()
    assert current["state"] == "complete" and current["inspection_id"], current
    assert (await client.delete(f"/api/acquisition/downloads/{identifier}")).status_code == 409
    await add_asset(
        database, UUID(second["work_id"]), UUID(second["version_id"]), catalog["library"]
    )
    async with database() as db:
        child = await db.get(AcquisitionSelection, UUID(second["id"]))
        assert child.state == "fulfilled"
        assert (await db.get(AcquisitionReservation, child.reservation_id)).state == "released"
        assert await db.scalar(
            select(DownloadFulfillment.id).where(
                DownloadFulfillment.attempt_id == identifier,
                DownloadFulfillment.target_id == child.target_id,
            )
        )
        assert await db.scalar(select(DownloadIdentityClaim.active))


async def test_shared_inspection_requires_each_books_scope_and_version(
    client, database, selected, second, catalog, downloader
):
    response = await grouped(client, selected, second)
    downloader.complete = True
    await downloads.run(UUID(response.json()["id"]))
    current = (await client.get("/api/acquisition/downloads/" + response.json()["id"])).json()
    async with database() as db, db.begin():
        inspection_id = UUID(current["inspection_id"])
        for version_id in (catalog["versions"][1], UUID(second["version_id"])):
            await download_reviews.validate_inspection(
                db, inspection_id, version=await db.get(Version, version_id)
            )
        child = await db.get(AcquisitionSelection, UUID(second["id"]))
        child.frozen = {
            **child.frozen,
            "requirements": {**child.frozen["requirements"], "required_narrators": ["Reader B"]},
        }
        await db.flush()
        await download_reviews.validate_inspection(
            db, inspection_id, version=await db.get(Version, catalog["versions"][1])
        )
        with pytest.raises(HTTPException, match="required narrator"):
            await download_reviews.validate_inspection(
                db, inspection_id, version=await db.get(Version, UUID(second["version_id"]))
            )
        wrong_work = Work(title="Not requested")
        db.add(wrong_work)
        await db.flush()
        wrong = Version(work_id=wrong_work.id, medium="audio")
        db.add(wrong)
        await db.flush()
        with pytest.raises(HTTPException, match="outside the reviewed transfer scope"):
            await download_reviews.validate_inspection(db, inspection_id, version=wrong)
        with pytest.raises(HTTPException, match="medium or language"):
            await download_reviews.validate_inspection(
                db, inspection_id, version=await db.get(Version, catalog["versions"][0])
            )


async def test_lost_pack_submission_response_reconciles_without_a_second_transfer(
    client, database, selected, second, downloader
):
    started = await grouped(client, selected, second)
    identifier = UUID(started.json()["id"])
    downloader.fail = AdapterError(FailureKind.UNCERTAIN, "Synthetic lost response")
    await downloads.run(identifier)
    async with database() as db:
        attempt = await db.get(DownloadAttempt, identifier)
        assert attempt.external_may_exist and attempt.state == "uncertain"
    downloader.fail = None
    await downloads.run(identifier)
    current = (await client.get(f"/api/acquisition/downloads/{identifier}")).json()
    assert current["state"] == "downloading" and len(current["members"]) == 2
    assert downloader.calls.count("submit") == 1


async def test_withdrawn_group_holds_without_dispatching(
    client, database, selected, second, downloader
):
    started = await grouped(client, selected, second)
    async with database() as db, db.begin():
        for reason in await db.scalars(select(AcquisitionReason)):
            reason.active = False
    await downloads.run(UUID(started.json()["id"]))
    current = (await client.get("/api/acquisition/downloads/" + started.json()["id"])).json()
    assert current["state"] == "held" and not current["external_may_exist"]
    assert "submit" not in downloader.calls


async def test_migration_preserves_single_attempt_and_guards_shared_history(
    client, database, selected, second
):
    response = await grouped(client, selected, second)
    assert response.status_code == 202
    await get_engine().dispose()
    refused = await migrate("downgrade", "0035_source_queries")
    assert refused.returncode != 0 and "Shared download history" in refused.stderr
    async with database() as db, db.begin():
        # Historical fixture: model the one-member shape that existed before 0036.
        await db.execute(
            text("DELETE FROM download_memberships WHERE selection_id=:id"),
            {"id": UUID(second["id"])},
        )
    await get_engine().dispose()
    try:
        downgraded = await migrate("downgrade", "0035_source_queries")
        assert downgraded.returncode == 0, downgraded.stderr
        upgraded = await migrate("upgrade", "head")
        assert upgraded.returncode == 0, upgraded.stderr
        async with database() as db:
            saved = await db.get(DownloadMembership, UUID(selected["id"]))
            assert str(saved.attempt_id) == response.json()["id"]
            assert await db.scalar(select(func.count()).select_from(DownloadMembership)) == 1
    finally:
        await get_engine().dispose()
        restored = await migrate("upgrade", "head")
        assert restored.returncode == 0, restored.stderr
