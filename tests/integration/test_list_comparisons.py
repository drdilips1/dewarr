# ruff: noqa: F811
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.db.models import (
    ListCatalogBinding,
    ListComparisonRow,
    ListEntry,
    Operation,
    Work,
    WorkMetadataSource,
)
from app.domain import list_comparisons as comparisons
from app.domain import list_writeback as writes
from app.jobs.retry import ShelfRetry
from tests.integration.test_hardcover_subscriptions import (  # noqa: F401
    finish,
    service,
    shelf,
    start,
)
from tests.integration.test_list_curation import book, edit
from tests.integration.test_list_writeback import drain, new_book, remote  # noqa: F401

pytestmark = pytest.mark.integration


async def complete(identifier):
    for _ in range(250):
        try:
            await comparisons.run(UUID(str(identifier)))
        except ShelfRetry:
            continue
        return
    raise AssertionError("Comparison did not terminate")


async def preview(client, shelf, generation=0):
    response = await client.post(
        f"/api/lists/{shelf}/writeback/preview",
        json={"expected_generation": generation},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def page(client, shelf, snapshot, **query):
    return await client.get(
        f"/api/lists/{shelf}/writeback/differences/{snapshot['comparison_id']}", params=query
    )


async def configure(client, shelf, snapshot):
    return await client.put(
        f"/api/lists/{shelf}/writeback",
        json={"enabled": True, "preview_id": snapshot["id"], "expected_generation": 0},
        headers={"Idempotency-Key": str(uuid4())},
    )


async def resolve(client, shelf, snapshot, rows, action, generation=0, key=None):
    return await client.post(
        f"/api/lists/{shelf}/writeback/differences/{snapshot['comparison_id']}/resolve",
        json={
            "row_ids": [r["id"] for r in rows],
            "action": action,
            "expected_policy_generation": generation,
        },
        headers={"Idempotency-Key": key or str(uuid4())},
    )


async def differences(client, database, admin, shelf):
    await finish(await start(client, shelf))
    observed = (await client.get(f"/api/lists/{shelf}/subscription/observations")).json()["items"]
    removed = next(r["work_id"] for r in observed if r["external_id"] == "42")
    await edit(client, shelf, "remove", [removed])
    added = await new_book(client, database, admin)
    await edit(client, shelf, "add", [added])
    snapshot = await preview(client, shelf)
    await complete(snapshot["comparison_id"])
    response = await page(client, shelf, snapshot)
    assert response.status_code == 200, response.text
    return snapshot, response.json()["items"], added, removed


async def test_initial_comparison_is_required_read_only_and_does_not_change_inbound_state(
    client, database, shelf, service, remote
):
    await finish(await start(client, shelf))
    snapshot = await preview(client, shelf)
    response = await configure(client, shelf, snapshot)
    assert response.status_code == 409 and "comparison" in response.text
    before = (await client.get(f"/api/lists/{shelf}/subscription")).json()
    await complete(snapshot["comparison_id"])
    result = await page(client, shelf, snapshot, state="all")
    assert result.status_code == 200, result.text
    assert result.json()["counts"] == {"same": 2} and result.json()["total"] == 2
    assert not remote.calls
    assert before == (await client.get(f"/api/lists/{shelf}/subscription")).json()
    assert (await configure(client, shelf, snapshot)).status_code == 200


async def test_selected_local_state_uses_existing_worker_and_replays_receipt(
    client, database, admin, shelf, service, remote
):
    snapshot, rows, added, removed = await differences(client, database, admin, shelf)
    assert {r["state"] for r in rows} == {"local_only", "remote_only"}
    assert (await resolve(client, shelf, snapshot, rows, "apply_local")).status_code == 409
    assert (await configure(client, shelf, snapshot)).status_code == 200
    key = str(uuid4())
    response = await resolve(client, shelf, snapshot, rows, "apply_local", 1, key)
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert len(receipt["outbound_ids"]) == 2 and not remote.calls
    assert (await resolve(client, shelf, snapshot, rows, "apply_local", 1, key)).json() == receipt
    assert (await page(client, shelf, snapshot)).status_code == 409
    for identifier in receipt["outbound_ids"]:
        await drain(UUID(identifier))
    assert {r["external_id"] for r in service.items} == {"43", "44"}
    assert len(remote.calls) == 2
    local = (await client.get(f"/api/lists/{shelf}")).json()["items"]
    assert added in {r["id"] for r in local} and removed not in {r["id"] for r in local}


async def test_keep_remote_applies_selected_local_changes_without_outbound_or_implicit_enablement(
    client, database, admin, shelf, service, remote
):
    snapshot, rows, added, removed = await differences(client, database, admin, shelf)
    response = await resolve(client, shelf, snapshot, rows, "keep_remote")
    assert response.status_code == 200, response.text
    assert response.json()["outbound_ids"] == [] and not remote.calls
    local = (await client.get(f"/api/lists/{shelf}")).json()["items"]
    assert added not in {r["id"] for r in local} and removed in {r["id"] for r in local}
    assert not (await client.get(f"/api/lists/{shelf}/writeback")).json()["enabled"]
    assert (await configure(client, shelf, snapshot)).status_code == 409


async def test_remote_new_book_is_created_only_after_selected_local_addition(
    client, database, shelf, service, remote
):
    await finish(await start(client, shelf))
    service.items.append(
        {**service.items[0], "entry_id": 3, "external_id": "55", "title": "New remote book"}
    )
    async with database() as db:
        count = await db.scalar(select(func.count()).select_from(Work))
    snapshot = await preview(client, shelf)
    await complete(snapshot["comparison_id"])
    rows = (await page(client, shelf, snapshot)).json()["items"]
    assert len(rows) == 1 and rows[0]["work_id"] is None
    assert not rows[0]["can_apply_local"] and rows[0]["can_keep_remote"]
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(Work)) == count
    response = await resolve(client, shelf, snapshot, rows, "keep_remote")
    assert response.status_code == 200, response.text
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(Work)) == count + 1
        binding = await db.scalar(
            select(ListCatalogBinding).where(ListCatalogBinding.identity_key == "hardcover:55")
        )
        assert await db.scalar(
            select(ListEntry.id).where(
                ListEntry.list_id == UUID(shelf), ListEntry.work_id == binding.work_id
            )
        )
    assert not remote.calls


async def test_unmatched_and_competing_identities_never_authorize_absence_or_writes(
    client, database, admin, shelf, service, remote
):
    await finish(await start(client, shelf))
    unknown = await book(client, "Unknown identity")
    await edit(client, shelf, "add", [unknown])
    duplicate = await book(client, "Competing catalog identity")
    async with database() as db, db.begin():
        db.add(
            WorkMetadataSource(
                work_id=UUID(duplicate),
                provider="hardcover",
                external_id="42",
                snapshot={},
                fetched_at=datetime.now(UTC),
                accepted=True,
            )
        )
    await edit(client, shelf, "add", [duplicate])
    snapshot = await preview(client, shelf)
    await complete(snapshot["comparison_id"])
    rows = (await page(client, shelf, snapshot)).json()["items"]
    assert rows and all(r["state"] == "unmatched" for r in rows)
    assert all(not r["can_apply_local"] and not r["can_keep_remote"] for r in rows)
    assert (await resolve(client, shelf, snapshot, rows, "keep_remote")).status_code == 409
    assert not remote.calls


@pytest.mark.parametrize("change", ["membership", "identity", "expired"])
async def test_stale_comparison_blocks_pages_and_selected_actions(
    client, database, admin, shelf, service, remote, change
):
    snapshot, rows, added, _ = await differences(client, database, admin, shelf)
    if change == "membership":
        await edit(client, shelf, "remove", [added])
    else:
        async with database() as db, db.begin():
            if change == "identity":
                db.add(
                    ListCatalogBinding(
                        owner_id=UUID(admin["id"]),
                        work_id=UUID(added),
                        identity_key="hardcover:999",
                        assertion={},
                    )
                )
            else:
                op = await db.get(Operation, UUID(snapshot["comparison_id"]))
                op.payload = {
                    **op.payload,
                    "expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
                }
    assert (await page(client, shelf, snapshot)).status_code == 409
    assert (await resolve(client, shelf, snapshot, rows, "keep_remote")).status_code == 409
    assert not remote.calls


async def test_partial_remote_change_never_publishes_differences(
    client, database, shelf, service, remote
):
    await finish(await start(client, shelf))
    snapshot = await preview(client, shelf)
    identifier = UUID(snapshot["comparison_id"])
    with pytest.raises(ShelfRetry):
        await comparisons.run(identifier)
    service.items[0] = {**service.items[0], "entry_id": 99}
    await complete(identifier)
    response = await page(client, shelf, snapshot)
    assert response.json()["status"] == "failed" and response.json()["items"] == []
    assert (await configure(client, shelf, snapshot)).status_code == 409
    assert not remote.calls


async def test_bulk_enqueue_failure_rolls_back_every_selected_intent(
    client, database, admin, shelf, service, remote, monkeypatch
):
    snapshot, rows, _, _ = await differences(client, database, admin, shelf)
    assert (await configure(client, shelf, snapshot)).status_code == 200
    original = writes.enqueue
    calls = 0

    async def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("Synthetic enqueue failure")
        return await original(*args, **kwargs)

    monkeypatch.setattr(writes, "enqueue", fail_second)
    with pytest.raises(RuntimeError, match="enqueue failure"):
        await resolve(client, shelf, snapshot, rows, "apply_local", 1)
    async with database() as db:
        assert (
            await db.scalar(
                select(func.count()).select_from(Operation).where(Operation.kind == writes.KIND)
            )
            == 0
        )
    assert (await page(client, shelf, snapshot)).status_code == 200
    assert not remote.calls


async def test_differences_are_private_after_sharing_and_revalidate_role(
    client, database, admin, shelf, service, remote
):
    snapshot, rows, _, _ = await differences(client, database, admin, shelf)
    assert (await client.patch(f"/api/lists/{shelf}", json={"shared": True})).status_code == 200
    from tests.integration.test_discovery import login_member

    await login_member(client)
    assert (await page(client, shelf, snapshot)).status_code == 404
    assert (await resolve(client, shelf, snapshot, rows, "keep_remote")).status_code == 404


async def test_comparison_rows_are_paged_searchable_and_selection_is_exact(
    client, database, shelf, service, remote
):
    await finish(await start(client, shelf))
    service.items.extend(
        {
            **service.items[0],
            "entry_id": n,
            "external_id": str(1000 + n),
            "title": f"Remote book {n:03}",
        }
        for n in range(3, 60)
    )
    snapshot = await preview(client, shelf)
    await complete(snapshot["comparison_id"])
    first = (await page(client, shelf, snapshot, limit=10)).json()
    last = (await page(client, shelf, snapshot, limit=10, offset=50)).json()
    assert first["total"] == 57 and len(first["items"]) == 10 and len(last["items"]) == 7
    response = await page(client, shelf, snapshot, q="Remote book 059")
    assert response.json()["total"] == 1
    chosen = [first["items"][0], last["items"][-1]]
    response = await resolve(client, shelf, snapshot, chosen, "keep_remote")
    assert response.status_code == 200 and response.json()["selected"] == 2
    assert (await client.get(f"/api/lists/{shelf}")).json()["count"] == 4
    async with database() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(ListComparisonRow)
                .where(ListComparisonRow.comparison_id == UUID(snapshot["comparison_id"]))
            )
            == 59
        )


async def test_concurrent_selected_commands_replay_once_and_changed_key_is_rejected(
    client, database, admin, shelf, service, remote
):
    import asyncio

    snapshot, rows, _, _ = await differences(client, database, admin, shelf)
    assert (await configure(client, shelf, snapshot)).status_code == 200
    key = str(uuid4())
    first, second = await asyncio.gather(
        resolve(client, shelf, snapshot, rows, "apply_local", 1, key),
        resolve(client, shelf, snapshot, rows, "apply_local", 1, key),
    )
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() and len(first.json()["outbound_ids"]) == 2
    changed = await resolve(client, shelf, snapshot, rows, "keep_remote", 1, key)
    assert changed.status_code == 409
    assert not remote.calls


async def test_remote_readdition_after_comparison_is_held_by_the_existing_worker(
    client, database, admin, shelf, service, remote
):
    snapshot, rows, _, _ = await differences(client, database, admin, shelf)
    assert (await configure(client, shelf, snapshot)).status_code == 200
    chosen = [r for r in rows if r["state"] == "remote_only"]
    response = await resolve(client, shelf, snapshot, chosen, "apply_local", 1)
    assert response.status_code == 200, response.text
    service.items = [
        {**r, "entry_id": 99} if r["external_id"] == "42" else r for r in service.items
    ]
    identifier = UUID(response.json()["outbound_ids"][0])
    await drain(identifier)
    async with database() as db:
        operation = await db.get(Operation, identifier)
        assert operation.status == "attention" and "changed" in operation.message
    assert not remote.calls


async def test_an_unknown_earlier_effect_blocks_both_selected_resolutions(
    client, database, admin, shelf, service, remote
):
    from tests.integration.test_list_writeback import enable, latest

    await finish(await start(client, shelf))
    await enable(client, shelf)
    work = await new_book(client, database, admin)
    remote.apply = False
    remote.lose_response = True
    await edit(client, shelf, "add", [work])
    await drain((await latest(database)).id)
    snapshot = await preview(client, shelf, 1)
    await complete(snapshot["comparison_id"])
    rows = (await page(client, shelf, snapshot)).json()["items"]
    for action in ("apply_local", "keep_remote"):
        response = await resolve(client, shelf, snapshot, rows, action, 1)
        assert response.status_code == 409 and "unconfirmed" in response.text
    assert len(remote.calls) == 1


async def test_catalog_merge_counts_a_book_once_and_invalidates_older_comparison(
    client, database, admin, shelf, service, remote
):
    from tests.integration.test_work_merges import merge

    await finish(await start(client, shelf))
    old = await preview(client, shelf)
    await complete(old["comparison_id"])
    observation = (await client.get(f"/api/lists/{shelf}/subscription/observations")).json()[
        "items"
    ][0]
    alias = await book(client, "New canonical title")
    await edit(client, shelf, "add", [alias])
    await merge(client, observation["work_id"], alias)
    assert (await page(client, shelf, old)).status_code == 409
    current = await preview(client, shelf)
    await complete(current["comparison_id"])
    response = await page(client, shelf, current, state="all")
    assert response.status_code == 200, response.text
    assert response.json()["counts"] == {"same": 2} and response.json()["total"] == 2
    assert "New canonical title" in {r["title"] for r in response.json()["items"]}


async def test_revocation_during_remote_read_prevents_comparison_publication(
    client, database, shelf, service, remote
):
    from app.db.models import CatalogAccount

    await finish(await start(client, shelf))
    snapshot = await preview(client, shelf)

    async def revoke():
        async with database() as db, db.begin():
            account = await db.scalar(select(CatalogAccount))
            account.generation += 1

    service.callback = revoke
    await complete(snapshot["comparison_id"])
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(ListComparisonRow)) == 0
        operation = await db.get(Operation, UUID(snapshot["comparison_id"]))
        assert operation.status == "failed"
    assert not remote.calls


async def test_comparison_queue_failure_rolls_back_enablement_preview(
    client, database, shelf, service, remote, monkeypatch
):
    await finish(await start(client, shelf))

    async def failed(*args, **kwargs):
        raise RuntimeError("Comparison enqueue failed")

    monkeypatch.setattr(comparisons, "enqueue", failed)
    with pytest.raises(RuntimeError, match="enqueue failed"):
        await preview(client, shelf)
    async with database() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(Operation)
                .where(Operation.kind.in_([comparisons.KIND, "lists.writeback.preview"]))
            )
            == 0
        )


async def test_empty_comparison_migration_roundtrip(database):
    from app.db.session import get_engine
    from tests.integration.test_correction_migration import migrate

    await get_engine().dispose()
    try:
        result = await migrate("downgrade", "0039_list_writeback")
        assert result.returncode == 0, result.stderr
    finally:
        result = await migrate("upgrade", "head")
        assert result.returncode == 0, result.stderr


async def test_worker_refreshes_cached_state_after_acquiring_the_list_lock(
    client, database, shelf, service, remote
):
    await finish(await start(client, shelf))
    snapshot = await preview(client, shelf)
    identifier = UUID(snapshot["comparison_id"])
    async with database() as first:
        cached = await first.get(Operation, identifier)
        assert cached.status == "queued"
        async with database() as second, second.begin():
            operation, _ = await comparisons.load(second, identifier)
            operation.status = "running"
            operation.payload = {
                **operation.payload,
                "run_token": "other-worker",
                "lease_until": (datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
            }
        loaded, _ = await comparisons.load(first, identifier)
        assert loaded.status == "running" and loaded.payload["run_token"] == "other-worker"
    with pytest.raises(ShelfRetry):
        await comparisons.run(identifier)


async def test_concurrent_comparison_worker_does_not_fetch_a_leased_page_twice(
    client, database, shelf, service, remote
):
    import asyncio

    await finish(await start(client, shelf))
    snapshot = await preview(client, shelf)
    identifier = UUID(snapshot["comparison_id"])
    started, release = asyncio.Event(), asyncio.Event()
    calls_before = len(service.calls)

    async def hold():
        started.set()
        await release.wait()

    service.callback = hold
    worker = asyncio.create_task(comparisons.run(identifier))
    try:
        await asyncio.wait_for(started.wait(), 2)
        with pytest.raises(ShelfRetry):
            await comparisons.run(identifier)
        assert len(service.calls) == calls_before + 1
    finally:
        release.set()
        with pytest.raises(ShelfRetry):
            await worker
