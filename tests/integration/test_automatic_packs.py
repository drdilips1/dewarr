# ruff: noqa: F401, F811
import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.db.models import (
    AcquisitionSelection,
    DownloadAttempt,
    DownloadCapacity,
    DownloadIdentityClaim,
    DownloadMembership,
    Operation,
    SourceResult,
    Work,
    WorkMetadataSource,
)
from app.domain import automatic_packs as packs
from app.domain import automatic_selection as automatic
from app.domain import download_attempts as downloads
from app.jobs.retry import DependencyRetry
from tests.integration.test_acquisition import body, catalog, request
from tests.integration.test_acquisition_selections import selection_route
from tests.integration.test_automatic_dispatch import authorized
from tests.integration.test_automatic_pack_selection import series_pack
from tests.integration.test_automatic_selection import detail, source, start

pytestmark = pytest.mark.integration


@pytest.fixture
async def pair(client, database, admin, series_pack, authorized):
    async with database() as db, db.begin():
        second = await db.scalar(select(Work).where(Work.title == "Roads"))
        second_id = second.id
        db.add(
            WorkMetadataSource(
                work_id=second.id,
                provider="hardcover",
                external_id="43",
                accepted=True,
                fetched_at=datetime.now(UTC),
                snapshot={"title": "Roads", "authors": ["Writer"]},
            )
        )
        old = await db.get(Operation, authorized["search"])
        payload = deepcopy(old.payload)
        payload["work"] = {"id": str(second.id), "title": "Roads", "authors": ["Writer"]}
        search = Operation(
            owner_id=UUID(admin["id"]),
            kind="sources.search",
            idempotency_key="second-pack-search",
            status="completed",
            payload=payload,
        )
        db.add(search)
        await db.flush()
        old_result = await db.get(SourceResult, authorized["result"])
        db.add(
            SourceResult(
                owner_id=old_result.owner_id,
                operation_id=search.id,
                source_key=old_result.source_key,
                source_generation=old_result.source_generation,
                expires_at=old_result.expires_at,
                encrypted_reference=old_result.encrypted_reference,
                release_snapshot=old_result.release_snapshot,
            )
        )
        search_id = search.id
    wanted = await request(client, body({"work": second_id}, "audio"))
    second_source = {
        **authorized,
        "body": {
            **authorized["body"],
            "intent_id": wanted["request"]["id"],
            "search_id": str(search_id),
        },
    }
    first = await start(client, authorized)
    second = await start(client, second_source, key="second-pack-selection")
    return [UUID(first["id"]), UUID(second["id"])]


async def prepare(pair):
    for identifier in pair:
        await automatic.run(identifier)


async def test_independent_automatic_books_share_one_transfer_and_replay(
    client, database, pair, authorized
):
    await prepare(pair)
    await asyncio.gather(*(packs.run(identifier) for identifier in pair))
    values = [await detail(client, identifier) for identifier in pair]
    assert all(v["status"] == "completed" for v in values), values
    assert len({v["download_id"] for v in values}) == 1
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(DownloadAttempt)) == 1
        assert await db.scalar(select(func.count()).select_from(DownloadMembership)) == 2
        assert await db.scalar(select(func.count()).select_from(DownloadCapacity)) == 1
        assert await db.scalar(select(func.count()).select_from(DownloadIdentityClaim)) == 1
        for identifier in pair:
            op = await db.get(Operation, identifier)
            assert len(op.payload["pack_dispatch"]["selection_ids"]) == 2
    await downloads.run(UUID(values[0]["download_id"]))
    await asyncio.gather(*(packs.run(identifier) for identifier in pair))
    await downloads.run(UUID(values[0]["download_id"]))
    assert authorized["qbit"].calls.count("submit") == 1


async def test_waits_for_other_authorized_assessment_then_groups(client, database, pair):
    await automatic.run(pair[0])
    with pytest.raises(DependencyRetry):
        await packs.run(pair[0])
    async with database() as db:
        assert not await db.scalar(select(DownloadAttempt.id))
    await automatic.run(pair[1])
    await packs.run(pair[0])
    assert (await detail(client, pair[0]))["download_id"] == (await detail(client, pair[1]))[
        "download_id"
    ]


async def test_wait_is_bounded_and_never_invents_second_authorization(client, database, pair):
    await automatic.run(pair[0])
    async with database() as db, db.begin():
        op = await db.get(Operation, pair[0])
        payload = deepcopy(op.payload)
        payload["pack_dispatch"]["deadline"] = (
            datetime.now(UTC) - timedelta(seconds=1)
        ).isoformat()
        op.payload = payload
    await packs.run(pair[0])
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(DownloadMembership)) == 1
        assert (await db.get(Operation, pair[1])).payload["selection_id"] is None


async def test_cancel_one_child_preserves_other_and_releases_selection(client, database, pair):
    await prepare(pair)
    response = await client.post(f"/api/acquisition/automatic-selections/{pair[0]}/cancel")
    assert response.status_code == 200, response.text
    await packs.run(pair[1])
    values = [await detail(client, identifier) for identifier in pair]
    assert values[0]["status"] == "cancelled" and not values[0]["download_id"]
    assert values[1]["status"] == "completed" and values[1]["download_id"]
    async with database() as db:
        assert (
            await db.get(AcquisitionSelection, UUID(values[0]["selection_id"]))
        ).state == "cancelled"
        assert await db.scalar(select(func.count()).select_from(DownloadMembership)) == 1


async def test_changed_shared_catalog_holds_all_affected_children(client, database, pair):
    await prepare(pair)
    async with database() as db, db.begin():
        (await db.scalar(select(Work).where(Work.title == "Roads"))).title = "Different title"
    await packs.run(pair[0])
    # Catalog coverage changed for both selections: neither is silently grandfathered.
    values = [await detail(client, identifier) for identifier in pair]
    assert all(v["status"] == "held" and not v["download_id"] for v in values)
    async with database() as db:
        assert not await db.scalar(select(DownloadAttempt.id))


async def test_manual_batch_cannot_repurpose_automatic_proofs(client, database, pair):
    await prepare(pair)
    values = [await detail(client, identifier) for identifier in pair]
    response = await client.post(
        "/api/acquisition/downloads",
        headers={"Idempotency-Key": "manual-repurpose-pack"},
        json={
            "selection_id": values[0]["selection_id"],
            "additional_selection_ids": [values[1]["selection_id"]],
        },
    )
    assert response.status_code == 422, response.text
    async with database() as db:
        assert not await db.scalar(select(DownloadAttempt.id))


async def test_withdrawn_child_does_not_block_surviving_authority(client, database, pair):
    from app.db.models import AcquisitionReason

    await prepare(pair)
    async with database() as db, db.begin():
        op = await db.get(Operation, pair[1])
        for reason in await db.scalars(
            select(AcquisitionReason).where(
                AcquisitionReason.intent_id == UUID(op.payload["command"]["intent_id"])
            )
        ):
            reason.active = False
    await packs.run(pair[0])
    first, second = [await detail(client, identifier) for identifier in pair]
    assert first["status"] == "completed" and first["download_id"]
    assert second["status"] == "held" and not second["download_id"]
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(DownloadMembership)) == 1


async def test_pre_dispatch_revocation_of_child_consent_holds_shared_transfer(
    client, database, pair, authorized
):
    await prepare(pair)
    await packs.run(pair[0])
    first = await detail(client, pair[0])
    async with database() as db, db.begin():
        second = await db.get(Operation, pair[1])
        second.status = "cancelled"
    await downloads.run(UUID(first["download_id"]))
    async with database() as db:
        attempt = await db.get(DownloadAttempt, UUID(first["download_id"]))
        assert attempt.state == "held" and not attempt.external_may_exist
    assert not authorized["qbit"].calls


async def test_manual_single_dispatch_cannot_bypass_automatic_budget(client, database, pair):
    await prepare(pair)
    value = await detail(client, pair[0])
    response = await client.post(
        "/api/acquisition/downloads",
        headers={"Idempotency-Key": "manual-single-pack"},
        json={"selection_id": value["selection_id"]},
    )
    assert response.status_code == 409, response.text
    async with database() as db:
        assert not await db.scalar(select(DownloadAttempt.id))


async def test_owned_child_is_skipped_while_missing_child_dispatches(
    client, database, pair, catalog
):
    from app.db.models import AssetContains, LibraryAsset

    await prepare(pair)
    async with database() as db, db.begin():
        asset = LibraryAsset(
            library_id=catalog["library"],
            external_id="new-audio",
            version_id=catalog["versions"][1],
            medium="audio",
            state="present",
            full_content=True,
            match_status="matched",
        )
        db.add(asset)
        await db.flush()
        db.add(AssetContains(asset_id=asset.id, work_id=catalog["work"], verified=True))
    await packs.run(pair[0])
    first, second = [await detail(client, identifier) for identifier in pair]
    assert first["status"] == "completed" and not first["download_id"], first
    assert "skipped" in first["message"]
    assert second["status"] == "completed" and second["download_id"], second
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(DownloadMembership)) == 1


async def test_stopped_coordinator_can_release_selection_before_retry(client, database, pair):
    from sqlalchemy import text

    await prepare(pair)
    async with database() as db, db.begin():
        op = await db.get(Operation, pair[0])
        await db.execute(
            text("UPDATE book_queue.procrastinate_jobs SET status='failed' WHERE id=:id"),
            {"id": op.job_id},
        )
    value = await detail(client, pair[0])
    assert value["status"] == "failed" and "cancel this preparation" in value["message"]
    response = await client.post(f"/api/acquisition/automatic-selections/{pair[0]}/cancel")
    assert response.status_code == 200, response.text
    async with database() as db:
        assert (
            await db.get(AcquisitionSelection, UUID(value["selection_id"]))
        ).state == "cancelled"
    await packs.run(pair[1])
    assert (await detail(client, pair[1]))["download_id"]
