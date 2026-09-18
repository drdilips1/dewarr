# ruff: noqa: F811
import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text

from app.db.models import (
    AcquisitionIntent,
    AcquisitionReason,
    AcquisitionReservation,
    Operation,
    User,
    Work,
)
from app.domain import list_requests
from tests.integration.test_acquisition import catalog  # noqa: F401

pytestmark = pytest.mark.integration


@pytest.fixture
async def shelf(client, admin, catalog):
    result = await client.post("/api/lists", json={"name": "Batch reading"})
    identifier = result.json()["id"]
    await client.post(f"/api/lists/{identifier}/entries", json={"work_id": str(catalog["work"])})
    return identifier


async def preview(client, shelf, ids, mode="both", key=None, **options):
    response = await client.post(
        f"/api/lists/{shelf}/requests/preview",
        json={"work_ids": list(map(str, ids)), "specification": {"mode": mode, **options}},
        headers={"Idempotency-Key": key or str(uuid4())},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def submit(client, shelf, plan):
    response = await client.post(f"/api/lists/{shelf}/requests/{plan['id']}/submit")
    assert response.status_code == 202, response.text
    return response.json()


async def detail(client, shelf, plan):
    response = await client.get(f"/api/lists/{shelf}/requests/{plan['id']}")
    assert response.status_code == 200, response.text
    return response.json()


async def test_preview_has_no_requests_and_commit_preserves_owned_medium(
    client, database, shelf, catalog
):
    plan = await preview(client, shelf, [catalog["work"]])
    assert plan["counts"]["satisfied"] == 1 and plan["counts"]["wanted"] == 1
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(AcquisitionIntent)) == 0
    await submit(client, shelf, plan)
    await list_requests.run(UUID(plan["id"]))
    saved = await detail(client, shelf, plan)
    assert saved["status"] == "completed" and len(saved["receipt"]) == 1
    assert saved["counts"]["satisfied"] == 1 and saved["counts"]["pending"] == 1
    async with database() as db:
        reservations = list(await db.scalars(select(AcquisitionReservation)))
        assert len(reservations) == 1 and reservations[0].requirements["medium"] == "audio"
        assert (
            await db.scalar(
                text(
                    "SELECT count(*) FROM book_queue.procrastinate_jobs "
                    "WHERE task_name='acquisition.download'"
                )
            )
            == 0
        )


async def test_either_does_not_request_missing_other_medium(client, database, shelf, catalog):
    plan = await preview(client, shelf, [catalog["work"]], mode="either", preferred_medium="audio")
    await submit(client, shelf, plan)
    await list_requests.run(UUID(plan["id"]))
    assert (await detail(client, shelf, plan))["counts"]["satisfied"] == 1
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(AcquisitionReservation)) == 0


async def test_replay_and_second_list_keep_one_intent_independent_reasons(
    client, database, shelf, catalog
):
    plan = await preview(client, shelf, [catalog["work"]], key="same-batch-command")
    assert (await preview(client, shelf, [catalog["work"]], key="same-batch-command"))[
        "id"
    ] == plan["id"]
    await submit(client, shelf, plan)
    await asyncio.gather(list_requests.run(UUID(plan["id"])), list_requests.run(UUID(plan["id"])))
    second = (await client.post("/api/lists", json={"name": "Second reason"})).json()["id"]
    await client.post(f"/api/lists/{second}/entries", json={"work_id": str(catalog["work"])})
    other = await preview(client, second, [catalog["work"]])
    assert other["counts"]["pending"] == 1
    await submit(client, second, other)
    await list_requests.run(UUID(other["id"]))
    await client.delete(f"/api/lists/{shelf}/entries/{catalog['work']}")
    await list_requests.run(UUID(plan["id"]))
    await submit(client, shelf, plan)  # Completed replay cannot reactivate removed reasons.
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(AcquisitionIntent)) == 1
        reasons = list(await db.scalars(select(AcquisitionReason)))
        assert len(reasons) == 2
        assert {str(r.list_id): r.active for r in reasons} == {shelf: False, second: True}


@pytest.mark.parametrize("change", ["membership", "identity", "role", "deleted"])
async def test_worker_rechecks_selected_books_and_actor(
    client, database, shelf, catalog, admin, change
):
    plan = await preview(client, shelf, [catalog["work"]])
    await submit(client, shelf, plan)
    if change == "membership":
        await client.delete(f"/api/lists/{shelf}/entries/{catalog['work']}")
    elif change == "deleted":
        await client.delete(f"/api/lists/{shelf}")
    else:
        async with database() as db, db.begin():
            if change == "identity":
                (await db.get(Work, catalog["work"])).title = "A changed identity"
            else:
                (await db.get(User, UUID(admin["id"]))).role = "viewer"
    await list_requests.run(UUID(plan["id"]))
    async with database() as db:
        assert (await db.get(Operation, UUID(plan["id"]))).status == "failed"
        assert await db.scalar(select(func.count()).select_from(AcquisitionIntent)) == 0


async def test_current_inventory_rechecked_after_preview(client, database, shelf, catalog):
    from app.db.models import LibraryAsset

    plan = await preview(client, shelf, [catalog["work"]], mode="ebook")
    async with database() as db, db.begin():
        (await db.get(LibraryAsset, catalog["asset"])).state = "stale"
    await submit(client, shelf, plan)
    await list_requests.run(UUID(plan["id"]))
    saved = await detail(client, shelf, plan)
    assert saved["counts"]["awaiting-inventory"] == 1
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(AcquisitionReservation)) == 0


async def test_queue_failure_rolls_back_submission(client, database, shelf, catalog, monkeypatch):
    plan = await preview(client, shelf, [catalog["work"]])

    async def fail(*args, **kwargs):
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(list_requests, "enqueue", fail)
    with pytest.raises(RuntimeError):
        await client.post(f"/api/lists/{shelf}/requests/{plan['id']}/submit")
    async with database() as db:
        assert (await db.get(Operation, UUID(plan["id"]))).status == "preview"
        assert await db.scalar(text("SELECT count(*) FROM book_queue.procrastinate_jobs")) == 0


async def test_worker_rolls_back_whole_batch_then_retry_reuses_receipt(
    client, database, shelf, catalog, monkeypatch
):
    other = (
        await client.post(
            "/api/catalog/works", json={"title": "Another book", "authors": ["Writer"]}
        )
    ).json()["id"]
    await client.post(f"/api/lists/{shelf}/entries", json={"work_id": other})
    plan = await preview(client, shelf, [catalog["work"], other])
    await submit(client, shelf, plan)
    original = list_requests.submit
    calls = 0

    async def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated worker crash")
        return await original(*args, **kwargs)

    monkeypatch.setattr(list_requests, "submit", fail_second)
    with pytest.raises(RuntimeError):
        await list_requests.run(UUID(plan["id"]))
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(AcquisitionIntent)) == 0
        assert (await db.get(Operation, UUID(plan["id"]))).status == "queued"
    monkeypatch.setattr(list_requests, "submit", original)
    await list_requests.run(UUID(plan["id"]))
    assert len((await detail(client, shelf, plan))["receipt"]) == 2


async def test_expiry_cancel_and_queue_exhaustion_have_explicit_actions(
    client, database, shelf, catalog
):
    plan = await preview(client, shelf, [catalog["work"]])
    async with database() as db, db.begin():
        operation = await db.get(Operation, UUID(plan["id"]))
        operation.payload = {
            **operation.payload,
            "expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        }
    assert (
        await client.post(f"/api/lists/{shelf}/requests/{plan['id']}/submit")
    ).status_code == 409
    plan = await preview(client, shelf, [catalog["work"]])
    await submit(client, shelf, plan)
    async with database() as db, db.begin():
        operation = await db.get(Operation, UUID(plan["id"]))
        await db.execute(
            text("UPDATE book_queue.procrastinate_jobs SET status='failed' WHERE id=:id"),
            {"id": operation.job_id},
        )
    assert (await detail(client, shelf, plan))["status"] == "failed"
    await submit(client, shelf, plan)
    cancelled = await client.post(f"/api/lists/{shelf}/requests/{plan['id']}/cancel")
    assert cancelled.json()["status"] == "cancelled"
    await list_requests.run(UUID(plan["id"]))
    assert (
        await client.post(f"/api/lists/{shelf}/requests/{plan['id']}/submit")
    ).status_code == 409
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(AcquisitionIntent)) == 0


async def test_limits_foreign_members_and_book_specific_versions_rejected(client, shelf, catalog):
    base = {"work_ids": [str(catalog["work"])], "specification": {"mode": "both"}}
    for value in [
        {**base, "work_ids": [str(uuid4()) for _ in range(101)]},
        {**base, "work_ids": [str(catalog["work"])] * 2},
        {
            **base,
            "specification": {"mode": "both", "audio_version_id": str(catalog["versions"][1])},
        },
    ]:
        assert (
            await client.post(
                f"/api/lists/{shelf}/requests/preview",
                json=value,
                headers={"Idempotency-Key": str(uuid4())},
            )
        ).status_code == 422
    assert (
        await client.post(
            f"/api/lists/{shelf}/requests/preview",
            json={**base, "work_ids": [str(uuid4())]},
            headers={"Idempotency-Key": str(uuid4())},
        )
    ).status_code == 409


async def test_shared_list_does_not_share_preview_or_request_authority(
    client, database, shelf, catalog
):
    from contextlib import aclosing

    from tests.integration.test_list_subscriptions import member

    plan = await preview(client, shelf, [catalog["work"]])
    await client.patch(f"/api/lists/{shelf}", json={"name": "Shared reading", "shared": True})
    async with aclosing(await member(database, "batch-member")) as other:
        assert (await other.get(f"/api/lists/{shelf}")).status_code == 200
        assert (await other.get(f"/api/lists/{shelf}/requests")).status_code == 404
        assert (await other.get(f"/api/lists/{shelf}/requests/{plan['id']}")).status_code == 404
        assert (
            await other.post(f"/api/lists/{shelf}/requests/{plan['id']}/submit")
        ).status_code == 404


async def test_compatible_pending_media_is_shared_across_different_request_specs(
    client, database, shelf, catalog
):
    from tests.integration.test_acquisition import body, request

    await request(client, body(catalog, mode="audio"))
    plan = await preview(client, shelf, [catalog["work"]], mode="both")
    assert plan["counts"]["satisfied"] == 1 and plan["counts"]["pending"] == 1
    await submit(client, shelf, plan)
    await list_requests.run(UUID(plan["id"]))
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(AcquisitionReservation)) == 1
        assert await db.scalar(select(func.count()).select_from(AcquisitionIntent)) == 2


async def test_different_language_or_destination_is_not_reported_as_compatible_pending(
    client, shelf, catalog
):
    from tests.integration.test_acquisition import body, request

    await request(client, body(catalog, mode="audio", language="fr"))
    plan = await preview(client, shelf, [catalog["work"]], mode="audio", language="en")
    assert plan["counts"]["wanted"] == 1 and plan["counts"]["pending"] == 0
    plan = await preview(
        client, shelf, [catalog["work"]], mode="audio", audio_library_id=str(catalog["library"])
    )
    assert plan["counts"]["wanted"] == 1 and plan["counts"]["pending"] == 0


async def test_maximum_batch_is_not_truncated(client, database, shelf, catalog):
    from app.db.models import ListEntry

    identifiers = [catalog["work"]]
    async with database() as db, db.begin():
        for index in range(99):
            work = Work(title=f"Batch book {index}", authors=["Fixture Writer"])
            db.add(work)
            await db.flush()
            identifiers.append(work.id)
            db.add(ListEntry(list_id=UUID(shelf), work_id=work.id, position=index + 2))
    plan = await preview(client, shelf, identifiers, mode="ebook")
    assert len(plan["records"]) == 100 and plan["counts"]["wanted"] == 99
    await submit(client, shelf, plan)
    await list_requests.run(UUID(plan["id"]))
    assert len((await detail(client, shelf, plan))["receipt"]) == 100
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(AcquisitionIntent)) == 100
        assert await db.scalar(select(func.count()).select_from(AcquisitionReason)) == 100


async def test_batch_child_command_lock_order_matches_ordinary_requests(
    client, database, shelf, catalog, admin
):
    from app.domain.acquisition import RequestReason, RequestSpec
    from app.domain.acquisition import submit as submit_request
    from app.domain.operations import transaction_lock

    plan = await preview(client, shelf, [catalog["work"]])
    await submit(client, shelf, plan)
    child_key = f"list-request:{plan['id']}:{catalog['work']}"
    async with database() as db:
        user = await db.get(User, UUID(admin["id"]))
        await transaction_lock(db, f"operation:{user.id}:{child_key}")
        task = asyncio.create_task(list_requests.run(UUID(plan["id"])))
        try:
            # Find a real waiter on our held advisory lock, not a timing guess.
            async with asyncio.timeout(3):
                while True:
                    pid = await db.scalar(
                        text(
                            "SELECT pid FROM pg_locks WHERE NOT granted "
                            "AND :pid = ANY(pg_blocking_pids(pid)) LIMIT 1"
                        ),
                        {"pid": await db.scalar(text("SELECT pg_backend_pid()"))},
                    )
                    if pid:
                        break
                    await asyncio.sleep(0.01)
            async with asyncio.timeout(3):
                await submit_request(
                    db,
                    user,
                    catalog["work"],
                    RequestSpec(mode="both"),
                    RequestReason(list_id=UUID(shelf)),
                    child_key,
                )
                await db.commit()
                await task
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await db.rollback()
    assert (await detail(client, shelf, plan))["status"] == "completed"


async def test_account_visibility_changes_redact_saved_preview(client, database, catalog, admin):
    from contextlib import aclosing

    from tests.integration.test_list_subscriptions import member

    async with aclosing(await member(database, "private-batch-reader")) as other:
        target = (await other.post("/api/lists", json={"name": "My reading"})).json()["id"]
        await other.post(f"/api/lists/{target}/entries", json={"work_id": str(catalog["work"])})
        plan = await preview(other, target, [catalog["work"]])
        async with database() as db, db.begin():
            work = await db.get(Work, catalog["work"])
            work.catalog_public = False
            work.catalog_owner_id = UUID(admin["id"])
        value = await detail(other, target, plan)
        assert value["counts"]["unresolved"] == 1
        assert value["records"][0]["title"] == "Book needs review"
        assert "Harbor" not in str(value)
        assert (
            await other.post(f"/api/lists/{target}/requests/{plan['id']}/submit")
        ).status_code == 409


async def test_lost_destination_permission_fails_before_creating_any_request(
    client, database, shelf, catalog
):
    from app.db.models import Library

    plan = await preview(client, shelf, [catalog["work"]], audio_library_id=str(catalog["library"]))
    await submit(client, shelf, plan)
    async with database() as db, db.begin():
        (await db.get(Library, catalog["library"])).accessible = False
    await list_requests.run(UUID(plan["id"]))
    async with database() as db:
        assert (await db.get(Operation, UUID(plan["id"]))).status == "failed"
        assert await db.scalar(select(func.count()).select_from(AcquisitionIntent)) == 0


async def test_preview_history_is_paged_and_abandoned_previews_are_bounded(client, shelf, catalog):
    first = await preview(client, shelf, [catalog["work"]])
    await submit(client, shelf, first)
    await list_requests.run(UUID(first["id"]))
    for _ in range(12):
        await preview(client, shelf, [catalog["work"]])
    response = await client.get(f"/api/lists/{shelf}/requests", params={"limit": 4, "offset": 8})
    assert response.status_code == 200 and response.json()["total"] == 11
    assert len(response.json()["items"]) == 3
    assert (await detail(client, shelf, first))["status"] == "completed"
