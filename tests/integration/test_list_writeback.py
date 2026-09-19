# ruff: noqa: F811
import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.adapters.contracts import FailureKind, MutationError
from app.adapters.hardcover_writeback import Membership, Observation, OwnedList
from app.db.models import (
    CatalogAccount,
    ListCatalogBinding,
    ListEntry,
    ListWritebackLease,
    ListWritebackPolicy,
    Operation,
)
from app.domain import list_writeback as writes
from app.jobs.retry import ShelfRetry
from tests.integration.test_hardcover_subscriptions import (  # noqa: F401
    finish,
    service,
    shelf,
    start,
)
from tests.integration.test_list_curation import book, edit

pytestmark = pytest.mark.integration


@pytest.fixture
async def remote(monkeypatch, service):
    class Remote:
        calls = []
        reads = 0
        lose_response = False
        apply = True
        error = None
        before_read = None
        before_send = None

        async def owner(self, *args):
            return OwnedList(id=9, owner_id=7, name="My Hardcover list")

        async def observe(self, owner, generation, token, list_id, book_id):
            self.reads += 1
            if self.before_read:
                await self.before_read()
            if self.error:
                raise self.error
            return Observation(
                list_id=list_id,
                book_id=book_id,
                owner_id=7,
                memberships=tuple(
                    Membership(
                        id=row["entry_id"],
                        list_id=list_id,
                        book_id=book_id,
                        edition_id=int(row["edition_id"]) if row.get("edition_id") else None,
                    )
                    for row in sorted(service.items, key=lambda r: r["entry_id"])
                    if row["external_id"] == str(book_id)
                ),
            )

        async def send(self, owner, generation, token, observation, decision):
            self.calls.append((observation.book_id, decision.action, decision.entry_id))
            if self.before_send:
                await self.before_send()
            if self.apply:
                if decision.action == "add":
                    service.items = [
                        *service.items,
                        {
                            "entry_id": max((r["entry_id"] for r in service.items), default=0) + 1,
                            "external_id": str(observation.book_id),
                            "edition_id": None,
                            "position": 3,
                            "date_added": None,
                            "title": "Added book",
                            "authors": [],
                            "isbn": None,
                            "isbn13": None,
                        },
                    ]
                else:
                    service.items = [r for r in service.items if r["entry_id"] != decision.entry_id]
            if self.lose_response:
                raise MutationError(FailureKind.TIMEOUT, "Response lost", may_have_applied=True)

    remote = Remote()
    monkeypatch.setattr(writes, "fetch_owner", remote.owner)
    monkeypatch.setattr(writes, "fetch_membership", remote.observe)
    monkeypatch.setattr(writes, "send_membership", remote.send)
    return remote


async def enable(client, shelf, generation=0):
    path = f"/api/lists/{shelf}/writeback"
    preview = await client.post(
        path + "/preview",
        json={"expected_generation": generation},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert preview.status_code == 200, preview.text
    from app.domain import list_comparisons

    for _ in range(30):
        try:
            await list_comparisons.run(UUID(preview.json()["comparison_id"]))
        except ShelfRetry:
            continue
        break
    reply = await client.put(
        path,
        json={
            "enabled": True,
            "expected_generation": generation,
            "preview_id": preview.json()["id"],
        },
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert reply.status_code == 200, reply.text
    return reply.json()


async def new_book(client, database, admin, external_id="44"):
    work = await book(client, "Added book")
    async with database() as db, db.begin():
        db.add(
            ListCatalogBinding(
                owner_id=UUID(admin["id"]),
                identity_key=f"hardcover:{external_id}",
                work_id=UUID(work),
                assertion={},
            )
        )
    return work


async def latest(database):
    async with database() as db:
        return await db.scalar(
            select(Operation)
            .where(Operation.kind == writes.KIND)
            .order_by(Operation.created_at.desc(), Operation.id.desc())
            .limit(1)
        )


async def drain(identifier):
    for _ in range(12):
        try:
            await writes.run(identifier)
        except ShelfRetry:
            continue
        return
    raise AssertionError("Write did not reach a terminal state")


async def test_enable_requires_verified_baseline_and_fresh_preview_and_sends_no_backlog(
    client, database, shelf, service, remote
):
    path = f"/api/lists/{shelf}/writeback"
    assert not (await client.get(path)).json()["enabled"]
    early = await client.post(
        path + "/preview", json={}, headers={"Idempotency-Key": "too-early-preview"}
    )
    assert early.status_code == 409
    await finish(await start(client, shelf))
    missing = await client.put(
        path, json={"enabled": True}, headers={"Idempotency-Key": "no-preview-enable"}
    )
    assert missing.status_code == 409
    policy = await enable(client, shelf)
    assert policy["enabled"] and policy["generation"] == 1 and policy["confirmed_at"] is None
    assert not remote.calls
    assert await latest(database) is None


async def test_lost_mutation_response_reconciles_once_and_inbound_echo_does_not_write(
    client, database, admin, shelf, service, remote
):
    await finish(await start(client, shelf))
    await enable(client, shelf)
    work = await new_book(client, database, admin)
    remote.lose_response = True
    reply = await edit(client, shelf, "add", [work], "add-and-sync-once")
    assert reply.status_code == 200, reply.text
    operation = await latest(database)
    assert operation.job_id and operation.status == "queued"
    await drain(operation.id)
    assert (await latest(database)).status == "completed"
    assert len(remote.calls) == 1
    await finish(await start(client, shelf, "echo-after-write"))
    await edit(client, shelf, "add", [work], "add-and-sync-once")
    await writes.run(operation.id)
    async with database() as db:
        assert (
            await db.scalar(
                select(func.count()).select_from(Operation).where(Operation.kind == writes.KIND)
            )
            == 1
        )
        assert (await db.get(ListWritebackPolicy, UUID(shelf))).confirmed_at
    assert len(remote.calls) == 1


async def test_removal_targets_each_observed_edition_membership_and_preserves_other_books(
    client, database, shelf, service, remote
):
    service.items.append({**service.items[0], "entry_id": 3, "edition_id": "71"})
    service.items.sort(key=lambda r: r["entry_id"])
    await finish(await start(client, shelf))
    await enable(client, shelf)
    records = (await client.get(f"/api/lists/{shelf}/subscription/observations")).json()["items"]
    work = next(r["work_id"] for r in records if r["external_id"] == "42")
    reply = await edit(client, shelf, "remove", [work])
    assert reply.status_code == 200, reply.text
    operation = await latest(database)
    await drain(operation.id)
    assert remote.calls == [(42, "remove", 1), (42, "remove", 3)]
    assert [r["external_id"] for r in service.items] == ["43"]
    assert (await latest(database)).status == "completed"


async def test_readded_remote_membership_is_not_deleted_by_old_local_intent(
    client, database, shelf, service, remote
):
    await finish(await start(client, shelf))
    await enable(client, shelf)
    records = (await client.get(f"/api/lists/{shelf}/subscription/observations")).json()["items"]
    work = next(row["work_id"] for row in records if row["external_id"] == "42")
    await edit(client, shelf, "remove", [work])
    service.items = [
        {**r, "entry_id": 20} if r["external_id"] == "42" else r for r in service.items
    ]
    await drain((await latest(database)).id)
    assert (await latest(database)).status == "attention" and not remote.calls


async def test_unknown_nonapplied_write_is_not_retried_even_by_reconciliation(
    client, database, admin, shelf, service, remote
):
    await finish(await start(client, shelf))
    await enable(client, shelf)
    work = await new_book(client, database, admin)
    remote.apply = False
    remote.lose_response = True
    await edit(client, shelf, "add", [work])
    operation = await latest(database)
    await drain(operation.id)
    assert (await latest(database)).status == "attention" and len(remote.calls) == 1
    reply = await client.post(f"/api/lists/{shelf}/writeback/changes/{operation.id}/reconcile")
    assert reply.status_code == 200, reply.text
    await drain(operation.id)
    assert len(remote.calls) == 1
    assert (await latest(database)).payload["pending_attempt"]


async def test_local_remove_readd_supersedes_unsent_intent(
    client, database, admin, shelf, service, remote
):
    await finish(await start(client, shelf))
    await enable(client, shelf)
    work = await new_book(client, database, admin)
    await edit(client, shelf, "add", [work])
    original = await latest(database)
    await edit(client, shelf, "remove", [work])
    await edit(client, shelf, "add", [work])
    newest = await latest(database)
    await drain(original.id)
    async with database() as db:
        assert (await db.get(Operation, original.id)).status == "attention"
    assert not remote.calls
    await drain(newest.id)
    assert len(remote.calls) == 1


async def test_account_change_during_read_prevents_sending(
    client, database, admin, shelf, service, remote
):
    await finish(await start(client, shelf))
    await enable(client, shelf)
    work = await new_book(client, database, admin)
    await edit(client, shelf, "add", [work])

    async def change():
        async with database() as db, db.begin():
            (await db.get(CatalogAccount, UUID(admin["id"]))).generation += 1

    remote.before_read = change
    await drain((await latest(database)).id)
    assert not remote.calls and (await latest(database)).status == "attention"


async def test_pause_after_send_reconciles_effect_without_further_writes(
    client, database, admin, shelf, service, remote
):
    await finish(await start(client, shelf))
    await enable(client, shelf)
    work = await new_book(client, database, admin)
    await edit(client, shelf, "add", [work])

    async def pause():
        result = await client.put(
            f"/api/lists/{shelf}/writeback",
            json={"enabled": False, "expected_generation": 1},
            headers={"Idempotency-Key": "pause-after-send"},
        )
        assert result.status_code == 200, result.text

    remote.before_send = pause
    operation = await latest(database)
    await drain(operation.id)
    final = await latest(database)
    assert (
        len(remote.calls) == 1
        and final.status == "attention"
        and final.payload["pending_attempt"] is None
    )


async def test_concurrent_worker_lease_serializes_remote_attempt(
    client, database, admin, shelf, service, remote
):
    await finish(await start(client, shelf))
    await enable(client, shelf)
    work = await new_book(client, database, admin)
    await edit(client, shelf, "add", [work])
    operation = await latest(database)
    started, release = asyncio.Event(), asyncio.Event()

    async def wait():
        started.set()
        await release.wait()

    remote.before_read = wait
    running = asyncio.create_task(writes.run(operation.id))
    await asyncio.wait_for(started.wait(), 3)
    try:
        with pytest.raises(ShelfRetry):
            await writes.run(operation.id)
    finally:
        release.set()
    with pytest.raises(ShelfRetry):
        await running
    remote.before_read = None
    await drain(operation.id)
    assert len(remote.calls) == 1


async def test_enqueue_failure_rolls_back_curation_and_policy_sequence(
    client, database, admin, shelf, service, remote, monkeypatch
):
    await finish(await start(client, shelf))
    await enable(client, shelf)
    work = await new_book(client, database, admin)

    async def fail(*args, **kwargs):
        raise RuntimeError("Queue unavailable")

    monkeypatch.setattr(writes, "enqueue", fail)
    with pytest.raises(RuntimeError, match="Queue unavailable"):
        await edit(client, shelf, "add", [work])
    async with database() as db:
        assert not await db.scalar(
            select(ListEntry.id).where(
                ListEntry.list_id == UUID(shelf), ListEntry.work_id == UUID(work)
            )
        )
        assert (await db.get(ListWritebackPolicy, UUID(shelf))).sequence == 0
    assert await latest(database) is None and not remote.calls


async def review_change(client, shelf, work):
    response = await client.post(
        f"/api/lists/{shelf}/writeback/changes/preview",
        json={"work_id": work},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_conflict_review_applies_only_current_membership_and_replays_receipt(
    client, database, shelf, service, remote
):
    await finish(await start(client, shelf))
    await enable(client, shelf)
    records = (await client.get(f"/api/lists/{shelf}/subscription/observations")).json()["items"]
    work = next(row["work_id"] for row in records if row["external_id"] == "42")
    await edit(client, shelf, "remove", [work])
    original = await latest(database)
    service.items = [
        {**r, "entry_id": 20} if r["external_id"] == "42" else r for r in service.items
    ]
    await drain(original.id)
    preview = await review_change(client, shelf, work)
    assert not preview["local_present"] and preview["remote_present"]
    payload = {"preview_id": preview["id"], "action": "apply_local"}
    path = f"/api/lists/{shelf}/writeback/changes/resolve"
    resolved = await client.post(
        path, json=payload, headers={"Idempotency-Key": "reviewed-current-membership"}
    )
    assert resolved.status_code == 200, resolved.text
    await drain(UUID(resolved.json()["outbound_id"]))
    assert remote.calls == [(42, "remove", 20)]
    repeated = await client.post(
        path, json=payload, headers={"Idempotency-Key": "reviewed-current-membership"}
    )
    assert repeated.json() == resolved.json()
    async with database() as db:
        assert (await db.get(Operation, original.id)).status == "superseded"
    assert len(remote.calls) == 1


async def test_keep_remote_changes_local_membership_without_echo_or_file_actions(
    client, database, admin, shelf, service, remote
):
    await finish(await start(client, shelf))
    await enable(client, shelf)
    work = await new_book(client, database, admin)
    await edit(client, shelf, "add", [work])
    operation = await latest(database)

    # A definite rejection creates a reviewable difference, not an unknown effect.
    async def reject(*args):
        raise MutationError(
            FailureKind.PERMISSION, "Missing write:lists scope", may_have_applied=False
        )

    remote.send = reject
    from app.domain import list_writeback

    original_send = list_writeback.send_membership
    list_writeback.send_membership = reject
    try:
        await drain(operation.id)
    finally:
        list_writeback.send_membership = original_send
    preview = await review_change(client, shelf, work)
    response = await client.post(
        f"/api/lists/{shelf}/writeback/changes/resolve",
        json={"preview_id": preview["id"], "action": "keep_remote"},
        headers={"Idempotency-Key": "keep-reviewed-remote-state"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["outbound_id"] is None
    async with database() as db:
        assert not await db.scalar(
            select(ListEntry.id).where(
                ListEntry.list_id == UUID(shelf), ListEntry.work_id == UUID(work)
            )
        )
        assert (
            await db.scalar(
                select(func.count()).select_from(Operation).where(Operation.kind == writes.KIND)
            )
            == 1
        )
    assert not remote.calls


async def test_review_refuses_stale_local_revision_and_unknown_prior_effect(
    client, database, admin, shelf, service, remote
):
    await finish(await start(client, shelf))
    await enable(client, shelf)
    work = await new_book(client, database, admin)
    preview = await review_change(client, shelf, work)
    await edit(client, shelf, "add", [work])
    response = await client.post(
        f"/api/lists/{shelf}/writeback/changes/resolve",
        json={"preview_id": preview["id"], "action": "apply_local"},
        headers={"Idempotency-Key": "stale-review-local-change"},
    )
    assert response.status_code == 409
    remote.apply = False
    remote.lose_response = True
    await drain((await latest(database)).id)
    current = await review_change(client, shelf, work)
    for action in ["apply_local", "keep_remote"]:
        response = await client.post(
            f"/api/lists/{shelf}/writeback/changes/resolve",
            json={"preview_id": current["id"], "action": action},
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 409 and "unconfirmed" in response.text
    assert len(remote.calls) == 1


async def test_outbound_settings_and_history_are_private_even_when_list_shared(
    client, database, admin, shelf, service, remote
):
    await finish(await start(client, shelf))
    await enable(client, shelf)
    assert (await client.patch(f"/api/lists/{shelf}", json={"shared": True})).status_code == 200
    from tests.integration.test_discovery import login_member

    await login_member(client)
    for suffix in ["", "/changes"]:
        response = await client.get(f"/api/lists/{shelf}/writeback{suffix}")
        assert response.status_code == 404
    response = await client.post(
        f"/api/lists/{shelf}/writeback/preview",
        json={},
        headers={"Idempotency-Key": "another-user-preview"},
    )
    assert response.status_code == 404 and not remote.calls


async def test_readd_uses_confirmed_own_removal_before_inbound_snapshot_catches_up(
    client, database, shelf, service, remote
):
    await finish(await start(client, shelf))
    await enable(client, shelf)
    records = (await client.get(f"/api/lists/{shelf}/subscription/observations")).json()["items"]
    work = next(r["work_id"] for r in records if r["external_id"] == "42")
    await edit(client, shelf, "remove", [work])
    await drain((await latest(database)).id)
    assert remote.calls == [(42, "remove", 1)]
    await edit(client, shelf, "add", [work])
    await drain((await latest(database)).id)
    assert (await latest(database)).status == "completed"
    assert remote.calls == [(42, "remove", 1), (42, "add", None)]


async def test_crash_after_external_effect_reconciles_after_lease_recovery(
    client, database, admin, shelf, service, remote, monkeypatch
):
    await finish(await start(client, shelf))
    await enable(client, shelf)
    work = await new_book(client, database, admin)
    await edit(client, shelf, "add", [work])
    operation = await latest(database)

    async def crash(*args):
        await remote.send(*args)
        raise RuntimeError("Simulated worker termination after remote effect")

    monkeypatch.setattr(writes, "send_membership", crash)
    with pytest.raises(RuntimeError, match="worker termination"):
        await writes.run(operation.id)
    async with database() as db, db.begin():
        saved = await db.get(Operation, operation.id)
        assert saved.payload["pending_attempt"] and saved.status == "running"
        lease = await db.get(ListWritebackLease, writes.target(saved.payload))
        lease.lease_until = datetime.now(UTC)
    await drain(operation.id)
    assert (await latest(database)).status == "completed" and len(remote.calls) == 1


async def test_recovery_mode_preserves_pending_intent_without_network(
    client, database, admin, shelf, service, remote, monkeypatch
):
    await finish(await start(client, shelf))
    await enable(client, shelf)
    work = await new_book(client, database, admin)
    await edit(client, shelf, "add", [work])
    operation = await latest(database)
    monkeypatch.setattr(writes.get_settings(), "recovery_mode", True)
    with pytest.raises(ShelfRetry):
        await writes.run(operation.id)
    assert not remote.calls and remote.reads == 0 and (await latest(database)).status == "queued"


async def test_missing_worker_job_surfaces_attention_and_reconciliation_never_sends(
    client, database, admin, shelf, service, remote
):
    await finish(await start(client, shelf))
    await enable(client, shelf)
    work = await new_book(client, database, admin)
    await edit(client, shelf, "add", [work])
    operation = await latest(database)
    async with database() as db, db.begin():
        saved = await db.get(Operation, operation.id)
        saved.job_id = None
    response = await client.get(f"/api/lists/{shelf}/writeback/changes")
    assert response.status_code == 200, response.text
    assert (await latest(database)).status == "attention"
    response = await client.post(f"/api/lists/{shelf}/writeback/changes/{operation.id}/reconcile")
    assert response.status_code == 200, response.text
    assert (await latest(database)).job_id is not None
    await drain(operation.id)
    assert (await latest(database)).status == "attention" and not remote.calls


async def test_writeback_migration_refuses_to_drop_outbound_history(
    client, database, shelf, service, remote
):
    from tests.integration.test_correction_migration import migrate

    await finish(await start(client, shelf))
    await enable(client, shelf)
    result = await migrate("downgrade", "0038_asset_containment")
    assert result.returncode != 0 and "history requires a pre-upgrade backup" in result.stderr
    assert (await client.get(f"/api/lists/{shelf}/writeback")).json()["enabled"]


@pytest.mark.parametrize("suffix", ["", "/subscription"])
async def test_deletion_preserves_uncertain_write_recovery_until_confirmed(
    client, database, admin, shelf, service, remote, suffix
):
    await finish(await start(client, shelf))
    await enable(client, shelf)
    work = await new_book(client, database, admin)
    await edit(client, shelf, "add", [work])
    operation = await latest(database)
    remote.lose_response = True

    async def delete_during_send():
        response = await client.delete(f"/api/lists/{shelf}{suffix}")
        assert response.status_code == 409 and "unconfirmed" in response.text

    remote.before_send = delete_during_send
    with pytest.raises(ShelfRetry):
        await writes.run(operation.id)
    response = await client.delete(f"/api/lists/{shelf}{suffix}")
    assert response.status_code == 409 and "unconfirmed" in response.text
    assert (await client.get(f"/api/lists/{shelf}/writeback/changes")).status_code == 200
    await drain(operation.id)
    assert (await latest(database)).status == "completed" and len(remote.calls) == 1
    response = await client.delete(f"/api/lists/{shelf}{suffix}")
    assert response.status_code == 204, response.text


async def test_writeback_empty_schema_roundtrip(database):
    from app.db.session import get_engine
    from tests.integration.test_correction_migration import migrate

    await get_engine().dispose()
    try:
        result = await migrate("downgrade", "0038_asset_containment")
        assert result.returncode == 0, result.stderr
    finally:
        result = await migrate("upgrade", "head")
        assert result.returncode == 0, result.stderr
