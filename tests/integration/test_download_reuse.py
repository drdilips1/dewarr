# ruff: noqa: F401, F811
import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select, text

from app.db.models import (
    AutomaticImportContinuation,
    AutomaticImportPolicy,
    DownloadAttempt,
    DownloadCapacity,
    DownloadIdentityClaim,
    DownloadMembership,
    Operation,
)
from app.domain import automatic_packs as packs
from app.domain import automatic_selection as automatic
from app.domain import download_attempts as downloads
from app.importing import reuse
from tests.integration.test_acquisition import catalog
from tests.integration.test_acquisition_selections import selection_route
from tests.integration.test_automatic_dispatch import authorized
from tests.integration.test_automatic_pack_selection import series_pack
from tests.integration.test_automatic_packs import pair
from tests.integration.test_automatic_selection import detail, source

pytestmark = pytest.mark.integration


async def first_transfer(client, database, pair):
    await automatic.run(pair[0])
    async with database() as db, db.begin():
        op = await db.get(Operation, pair[0])
        payload = deepcopy(op.payload)
        payload["pack_dispatch"]["deadline"] = (
            datetime.now(UTC) - timedelta(seconds=1)
        ).isoformat()
        op.payload = payload
    await packs.run(pair[0])
    result = await detail(client, pair[0])
    assert result["download_id"], result
    return UUID(result["download_id"])


@pytest.mark.parametrize("state", ["queued", "downloading", "complete"])
async def test_later_request_joins_saved_transfer_without_rewriting_receipt(
    client, database, pair, authorized, state
):
    identifier = await first_transfer(client, database, pair)
    if state != "queued":
        authorized["qbit"].complete = state == "complete"
        await downloads.run(identifier)
    async with database() as db:
        attempt = await db.get(DownloadAttempt, identifier)
        assert attempt.state == state
        original = deepcopy((await db.get(Operation, attempt.operation_id)).payload)
    await automatic.run(pair[1])
    await asyncio.gather(packs.run(pair[1]), packs.run(pair[1]))
    second = await detail(client, pair[1])
    assert second["status"] == "completed" and second["download_id"] == str(identifier), second
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(DownloadAttempt)) == 1
        assert await db.scalar(select(func.count()).select_from(DownloadCapacity)) == 1
        assert await db.scalar(select(func.count()).select_from(DownloadIdentityClaim)) == 1
        memberships = list(await db.scalars(select(DownloadMembership)))
        assert len(memberships) == 2
        joined = next(item for item in memberships if item.join_operation_id)
        receipt = await db.get(Operation, joined.join_operation_id)
        assert receipt.payload["selection_ids"] == [second["selection_id"]]
        assert receipt.payload["attempt_id"] == str(identifier)
        assert (await db.get(Operation, attempt.operation_id)).payload == original
        continuations = list(await db.scalars(select(AutomaticImportContinuation)))
        assert len(continuations) == (1 if state == "complete" else 0)
        if continuations:
            assert continuations[0].evidence["authorized_selection_ids"] == [second["selection_id"]]
    await downloads.run(identifier)
    assert authorized["qbit"].calls.count("submit") == 1


async def test_uncertain_existing_transfer_holds_join_without_new_attempt(
    client, database, pair, authorized
):
    identifier = await first_transfer(client, database, pair)
    async with database() as db, db.begin():
        attempt = await db.get(DownloadAttempt, identifier)
        attempt.state, attempt.external_may_exist = "held", True
    await automatic.run(pair[1])
    await packs.run(pair[1])
    second = await detail(client, pair[1])
    assert second["status"] == "held" and not second["download_id"], second
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(DownloadMembership)) == 1
        assert await db.scalar(select(func.count()).select_from(DownloadAttempt)) == 1
    assert "submit" not in authorized["qbit"].calls


async def test_join_during_live_preflight_is_included_before_submission(
    client, database, pair, authorized
):
    identifier = await first_transfer(client, database, pair)

    async def join_while_observing():
        async with database() as db:
            assert (await db.get(DownloadAttempt, identifier)).state == "preflight"
        await automatic.run(pair[1])
        await packs.run(pair[1])
        second = await detail(client, pair[1])
        assert second["download_id"] == str(identifier), second

    authorized["qbit"].before_find = join_while_observing
    await downloads.run(identifier)
    async with database() as db:
        assert (await db.get(DownloadAttempt, identifier)).state == "downloading"
        assert await db.scalar(select(func.count()).select_from(DownloadMembership)) == 2
        assert await db.scalar(select(func.count()).select_from(DownloadCapacity)) == 1
    assert authorized["qbit"].calls.count("submit") == 1


async def completed_join(client, database, pair, authorized):
    identifier = await first_transfer(client, database, pair)
    authorized["qbit"].complete = True
    await downloads.run(identifier)
    await automatic.run(pair[1])
    await packs.run(pair[1])
    async with database() as db:
        return await db.scalar(select(AutomaticImportContinuation))


@pytest.mark.parametrize("job_state", ["failed", "aborted"])
async def test_stopped_reuse_is_visible_and_recheck_is_deduplicated(
    client, database, pair, authorized, job_state
):
    row = await completed_join(client, database, pair, authorized)
    async with database() as db, db.begin():
        operation = await db.get(Operation, row.operation_id)
        old_job = operation.job_id
        await db.execute(
            text("UPDATE book_queue.procrastinate_jobs SET status=:status WHERE id=:id"),
            {"status": job_state, "id": old_job},
        )
        await reuse.recover(db, row.id)
    view = (await client.get(f"/api/acquisition/downloads/{row.attempt_id}")).json()
    assert view["import_continuations"][0]["state"] == "held", view
    assert "stopped" in view["import_continuations"][0]["message"]
    assert sum(bool(item["join_operation_id"]) for item in view["members"]) == 1
    async with database() as db, db.begin():
        attempt = await db.get(DownloadAttempt, row.attempt_id)
        await reuse.recheck(db, attempt)
        operation = await db.get(Operation, row.operation_id)
        new_job = operation.job_id
        assert new_job != old_job
        await reuse.recheck(db, attempt)
        assert operation.job_id == new_job
        current = await db.get(AutomaticImportContinuation, row.id)
        assert current.created_at == row.created_at and current.state == "queued"
    assert authorized["qbit"].calls.count("submit") == 1


async def test_reuse_verification_expiry_does_not_reset_itself(client, database, pair, authorized):
    row = await completed_join(client, database, pair, authorized)
    async with database() as db, db.begin():
        current = await db.get(AutomaticImportContinuation, row.id)
        current.evidence = {
            **current.evidence,
            "verification_started_at": (datetime.now(UTC) - timedelta(minutes=16)).isoformat(),
        }
    await reuse.run(row.id)
    async with database() as db:
        current = await db.get(AutomaticImportContinuation, row.id)
        assert current.state == "held" and "expired" in current.message
        assert current.created_at == row.created_at
    assert authorized["qbit"].calls.count("submit") == 1


async def test_reapproval_cannot_silently_authorize_a_joined_import(
    client, database, pair, authorized
):
    from fastapi import HTTPException

    row = await completed_join(client, database, pair, authorized)
    async with database() as db, db.begin():
        (await db.get(AutomaticImportPolicy, row.policy_id)).generation += 1
    await reuse.run(row.id)
    async with database() as db, db.begin():
        current = await db.get(AutomaticImportContinuation, row.id)
        assert current.state == "held" and "approval changed" in current.message
        with pytest.raises(HTTPException, match="approval changed"):
            await reuse.recheck(db, await db.get(DownloadAttempt, row.attempt_id))
    assert authorized["qbit"].calls.count("submit") == 1
