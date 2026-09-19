# ruff: noqa: F401, F811
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.db.models import (
    AcquisitionIntent,
    AcquisitionReason,
    DownloadAttempt,
    LibraryAsset,
    ListAcquisitionBook,
    ListEntry,
    ListObservation,
    ListSubscription,
    Operation,
    User,
)
from app.domain import automatic_selection, download_attempts
from app.jobs.queue import get_queue
from tests.integration.test_list_policies import (
    activate,
    add,
    authorized,
    catalog,
    policy_fixture,
    preview,
    selection_route,
    source,
    tick,
)
from tests.integration.test_work_merges import book as create_work
from tests.integration.test_work_merges import merge

pytestmark = pytest.mark.integration


async def monitored(client, fixture):
    response = await client.get(f"/api/lists/{fixture['list']}/acquisition/books")
    assert response.status_code == 200, response.text
    return response.json()


async def remove(client, f):
    response = await client.delete(f"/api/lists/{f['list']}/entries/{f['work']}")
    assert response.status_code == 204, response.text


@pytest.mark.parametrize("baseline", [False, True])
async def test_remove_and_readd_is_a_new_membership_even_between_scheduler_ticks(
    client, database, policy_fixture, baseline
):
    f = policy_fixture
    await add(client, f)
    saved = await activate(
        client, f, await preview(client, f, include_work_ids=[] if baseline else [f["work"]])
    )
    await tick(database, saved)
    before = (await monitored(client, f))["items"][0]
    await remove(client, f)
    assert (await monitored(client, f))["items"][0]["state"] == "removed"
    await add(client, f)
    for _ in range(3):
        await tick(database, saved, force_books=True)
    after = (await monitored(client, f))["items"][0]
    assert before["id"] == after["id"] and after["state"] == "pending"
    assert f["source"]["qbit"].calls.count("submit") == 1


async def test_readded_book_while_paused_remains_baseline_until_selected(
    client, database, policy_fixture
):
    f = policy_fixture
    await add(client, f)
    saved = await activate(client, f, await preview(client, f, include_work_ids=[f["work"]]))
    await tick(database, saved, worker=False)
    paused = (
        await client.post(
            f"/api/lists/{f['list']}/acquisition/pause",
            json={"expected_revision": saved["revision"]},
        )
    ).json()
    await remove(client, f)
    await add(client, f)
    resumed = await activate(
        client, f, await preview(client, f, expected_revision=paused["revision"])
    )
    await tick(database, resumed)
    assert (await monitored(client, f))["items"][0]["state"] == "baseline"
    assert f["source"]["qbit"].calls.count("submit") == 0
    selected = await activate(
        client,
        f,
        await preview(
            client, f, expected_revision=resumed["revision"], include_work_ids=[f["work"]]
        ),
    )
    for _ in range(3):
        await tick(database, selected, force_books=True)
    assert f["source"]["qbit"].calls.count("submit") == 1


@pytest.mark.parametrize("submitted", [False, True])
async def test_readdition_reuses_a_prepared_attempt_or_existing_external_transfer(
    client, database, policy_fixture, submitted
):
    f = policy_fixture
    await add(client, f)
    saved = await activate(client, f, await preview(client, f, include_work_ids=[f["work"]]))
    await tick(database, saved)
    await tick(database, saved, worker=False, force_books=True)
    async with database() as db:
        op = await db.scalar(select(Operation).where(Operation.kind == automatic_selection.KIND))
    await automatic_selection.run(op.id)
    async with database() as db:
        attempt = await db.scalar(select(DownloadAttempt))
    if submitted:
        await download_attempts.run(attempt.id)
    await remove(client, f)
    await download_attempts.run(attempt.id)
    async with database() as db:
        assert (await db.get(DownloadAttempt, attempt.id)).state == (
            "downloading" if submitted else "held"
        )
    await add(client, f)
    await tick(database, saved, force_books=True)
    assert f["source"]["qbit"].calls.count("submit") == 1
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(DownloadAttempt)) == 1


async def test_readdition_of_available_medium_does_not_search_or_download(
    client, database, policy_fixture, catalog
):
    # Keep the existing approved audio route but confirm the wanted audio asset.
    f = policy_fixture
    async with database() as db, db.begin():
        asset = await db.get(LibraryAsset, catalog["asset"])
        asset.medium, asset.version_id = "audio", catalog["versions"][1]
    await add(client, f)
    saved = await activate(client, f, await preview(client, f, include_work_ids=[f["work"]]))
    await tick(database, saved)
    await remove(client, f)
    await add(client, f)
    await tick(database, saved)
    assert (await monitored(client, f))["items"][0]["state"] == "available"
    assert f["calls"] == [] and f["source"]["qbit"].calls.count("submit") == 0


async def test_canonical_merge_restarts_search_without_losing_original_monitor_or_intent(
    client, database, policy_fixture
):
    f = policy_fixture
    await add(client, f)
    saved = await activate(client, f, await preview(client, f, include_work_ids=[f["work"]]))
    await tick(database, saved)
    before = (await monitored(client, f))["items"][0]
    target = await create_work(client, "Harbor")
    await merge(client, UUID(f["work"]), UUID(target))
    after = (await monitored(client, f))["items"][0]
    assert after["id"] == before["id"] and after["work_id"] == target and after["title"] == "Harbor"
    for _ in range(3):
        await tick(database, saved, force_books=True)
    assert f["source"]["qbit"].calls.count("submit") == 1
    async with database() as db:
        monitor = await db.get(ListAcquisitionBook, UUID(before["id"]))
        assert str(monitor.work_id) == f["work"]
        assert str(monitor.intent_id) == before["intent_id"]
        assert monitor.state == "pending"
        assert await db.scalar(select(func.count()).select_from(ListAcquisitionBook)) == 1


@pytest.mark.parametrize("active", [False, True])
async def test_merge_and_undo_project_one_book_without_erasing_either_origin(
    client, database, policy_fixture, active
):
    f = policy_fixture
    target = await create_work(client, "Harbor")
    await add(client, f)
    await add(client, f, target)
    saved = await activate(
        client, f, await preview(client, f, include_work_ids=[f["work"], target] if active else [])
    )
    await tick(database, saved, worker=False)
    before = (await monitored(client, f))["items"]
    assert len(before) == 2
    change = await merge(client, UUID(f["work"]), UUID(target))
    current = await monitored(client, f)
    assert current["total"] == 1 and current["items"][0]["work_id"] == target
    policy = (await client.get(f"/api/lists/{f['list']}/acquisition")).json()
    assert sum(policy["counts"].values()) == 1
    await tick(database, saved, worker=False, force_books=True)
    response = await client.post(f"/api/identity/changes/{change['id']}/undo")
    assert response.status_code == 204, response.text
    await tick(database, saved, worker=False, force_books=True)
    restored = (await monitored(client, f))["items"]
    assert {b["id"] for b in restored} == {b["id"] for b in before}
    assert {b["work_id"] for b in restored} == {f["work"], target}
    assert all(b["state"] == ("searching" if active else "baseline") for b in restored)
    assert f["source"]["qbit"].calls.count("submit") == 0


async def test_withdrawn_reason_is_not_reauthorized_by_a_canonical_merge(
    client, database, policy_fixture
):
    f = policy_fixture
    await add(client, f)
    saved = await activate(client, f, await preview(client, f, include_work_ids=[f["work"]]))
    # Withdraw at the pre-dispatch boundary. Draining the entire worker also runs
    # due periodic acquisition jobs and can legitimately submit before withdrawal.
    await tick(database, saved, worker=False)
    async with database() as db:
        assert not await db.scalar(select(DownloadAttempt.id))
        reason = await db.scalar(
            select(AcquisitionReason).where(AcquisitionReason.reference.startswith("policy:"))
        )
    assert (
        await client.delete(f"/api/requests/{reason.intent_id}/reasons/{reason.id}")
    ).status_code == 200
    target = await create_work(client, "Harbor")
    await merge(client, UUID(f["work"]), UUID(target))
    await tick(database, saved, force_books=True)
    assert (await monitored(client, f))["items"][0]["state"] == "held"
    assert f["source"]["qbit"].calls.count("submit") == 0
    async with database() as db:
        assert not (await db.get(AcquisitionReason, reason.id)).active


async def test_source_only_removal_and_reappearance_reenter_automation_but_exclusion_does_not(
    client, admin, database, policy_fixture
):
    from app.api.list_subscriptions import remove_unneeded
    from app.domain.list_requests import owner_context
    from app.domain.list_subscriptions import ensure_membership
    from app.security import encrypt_secrets

    f = policy_fixture
    async with database() as db, db.begin():
        subscription = ListSubscription(
            list_id=UUID(f["list"]),
            provider="hardcover",
            baseline_at=datetime.now(UTC),
            encrypted_config=encrypt_secrets({"external_id": "fixture-list"}),
        )
        db.add(subscription)
        await db.flush()
        observation = ListObservation(
            subscription_id=subscription.id,
            work_id=UUID(f["work"]),
            external_id="42",
            snapshot={},
            last_seen_at=datetime.now(UTC),
        )
        db.add(observation)
        await db.flush()
        await ensure_membership(db, subscription, observation)
    saved = await activate(client, f, await preview(client, f))
    async with database() as db, db.begin():
        _, user = await owner_context(db, UUID(admin["id"]), UUID(f["list"]))
        subscription = await db.get(ListSubscription, subscription.id)
        observation = await db.get(ListObservation, observation.id)
        observation.present = False
        await db.flush()
        await remove_unneeded(db, user, subscription, observation.work_id)
    assert (await monitored(client, f))["items"][0]["state"] == "removed"
    async with database() as db, db.begin():
        await owner_context(db, UUID(admin["id"]), UUID(f["list"]))
        observation = await db.get(ListObservation, observation.id)
        subscription = await db.get(ListSubscription, subscription.id)
        observation.present = True
        await ensure_membership(db, subscription, observation)
    for _ in range(3):
        await tick(database, saved, force_books=True)
    assert f["source"]["qbit"].calls.count("submit") == 1
    await remove(client, f)
    async with database() as db, db.begin():
        observation = await db.get(ListObservation, observation.id)
        assert observation.excluded
        await ensure_membership(db, await db.get(ListSubscription, subscription.id), observation)
    assert (await monitored(client, f))["items"][0]["state"] == "removed"
    async with database() as db:
        assert not await db.scalar(select(ListEntry.id).where(ListEntry.list_id == UUID(f["list"])))


async def test_a_withdrawn_merged_origin_does_not_block_another_active_request(
    client, database, policy_fixture
):
    f = policy_fixture
    target = await create_work(client, "Harbor")
    await add(client, f)
    await add(client, f, target)
    saved = await activate(
        client, f, await preview(client, f, include_work_ids=[f["work"], target])
    )
    await tick(database, saved, worker=False)
    async with database() as db:
        reason = await db.scalar(
            select(AcquisitionReason)
            .join(AcquisitionIntent)
            .where(
                AcquisitionReason.reference.startswith("policy:"),
                AcquisitionIntent.work_id == UUID(f["work"]),
            )
        )
    response = await client.delete(f"/api/requests/{reason.intent_id}/reasons/{reason.id}")
    assert response.status_code == 200
    await merge(client, UUID(f["work"]), UUID(target))
    for _ in range(3):
        await tick(database, saved, force_books=True)
    assert f["source"]["qbit"].calls.count("submit") == 1
    rows = await monitored(client, f)
    assert rows["total"] == 1 and rows["items"][0]["state"] == "pending"
    async with database() as db:
        assert not (await db.get(AcquisitionReason, reason.id)).active
