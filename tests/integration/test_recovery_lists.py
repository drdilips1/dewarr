from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, text

from app.adapters.goodreads import FeedResult
from app.adapters.hardcover_lists import ListPage
from app.db.models import (
    AcquisitionIntent,
    AcquisitionReason,
    AcquisitionReservation,
    AcquisitionTarget,
    AuditEvent,
    BookList,
    CatalogAccount,
    ListAcquisitionBook,
    ListAcquisitionPolicy,
    ListEntry,
    ListObservation,
    ListSubscription,
    ListWritebackPolicy,
    Operation,
    RateLimit,
    RestoreCheckpoint,
    User,
    Work,
)
from app.domain import hardcover_subscriptions, list_monitoring, list_policies, list_subscriptions
from app.domain import recovery_lists as recovery
from app.domain import recovery_observers as observers
from app.domain import recovery_scans as scans
from app.jobs.queue import recovery_queue
from app.security import decrypt_secrets, encrypt_secrets
from tests.integration.test_hardcover_subscriptions import finish
from tests.integration.test_recovery_scan_workflow import begin, pause, report
from tests.unit.test_goodreads import URL

pytestmark = pytest.mark.integration


@pytest.fixture(params=["hardcover", "goodreads"])
async def ready(request, client, admin, database, monkeypatch):
    provider = request.param

    class Service:
        records = [
            {
                "external_id": str(42 + i),
                "title": title,
                "authors": ["Writer"],
                "isbn": None,
                "isbn13": None,
            }
            for i, title in enumerate(["Kept book", "Omitted book", "Excluded book"])
        ]
        calls = 0
        owner_id = "7"
        callback = None

        async def page(self, *args):
            self.calls += 1
            if self.callback:
                await self.callback()
            cursor = args[-1]
            items = [
                {
                    **record,
                    "entry_id": int(record["external_id"]),
                    "edition_id": None,
                    "position": int(record["external_id"]),
                    "date_added": None,
                }
                for record in self.records
                if int(record["external_id"]) > cursor
            ]
            return ListPage(
                {
                    "external_id": "9",
                    "name": "Remote shelf",
                    "count": len(self.records),
                    "updated_at": "2026-09-19T00:00:00+00:00",
                    "public": False,
                    "owner_id": self.owner_id,
                },
                items,
                max([r["entry_id"] for r in items], default=cursor),
            )

        async def feed(self, *args, **kwargs):
            self.calls += 1
            if self.callback:
                await self.callback()
            return FeedResult(deepcopy(self.records), False, '"current"', None)

    service = Service()
    monkeypatch.setattr(hardcover_subscriptions, "fetch_page", service.page)
    monkeypatch.setattr(list_subscriptions, "fetch_feed", service.feed)
    monkeypatch.setattr(observers, "fetch_feed", service.feed)
    if provider == "hardcover":
        async with database() as db, db.begin():
            db.add(
                CatalogAccount(
                    user_id=UUID(admin["id"]),
                    generation=1,
                    enabled=True,
                    encrypted_token=encrypt_secrets({"token": "private-fixture"}),
                )
            )
    list_id = (await client.post("/api/lists", json={"name": "Recovery shelf"})).json()["id"]
    response = await client.put(
        f"/api/lists/{list_id}/subscription",
        json=(
            {"provider": "hardcover", "hardcover_list_id": 9}
            if provider == "hardcover"
            else {"feed_url": URL}
        ),
    )
    assert response.status_code == 200, response.text
    sync = await client.post(
        f"/api/lists/{list_id}/subscription/sync",
        headers={"Idempotency-Key": "initial-observation"},
    )
    await finish(UUID(sync.json()["id"]))
    async with database() as db:
        rows = {row.external_id: row for row in await db.scalars(select(ListObservation))}
        excluded_id = rows["44"].id
        works = {key: value.work_id for key, value in rows.items()}
    response = await client.patch(
        f"/api/lists/{list_id}/subscription/observations/{excluded_id}", json={"excluded": True}
    )
    assert response.status_code == 204, response.text
    async with database() as db, db.begin():
        row = await db.scalar(select(ListSubscription))
        policy = ListAcquisitionPolicy(
            list_id=UUID(list_id),
            owner_id=UUID(admin["id"]),
            configuration={"mode": "automatic"},
            active=True,
            generation=1,
            revision=1,
            baseline_at=datetime.now(UTC) - timedelta(days=1),
            next_check_at=datetime.now(UTC),
            message="Monitoring",
        )
        db.add(policy)
        manual = Work(title="Local addition", authors=["Local author"])
        db.add(manual)
        await db.flush()
        db.add(ListEntry(list_id=UUID(list_id), work_id=manual.id, locally_added=True))
        if provider == "hardcover":
            db.add(
                ListWritebackPolicy(
                    list_id=UUID(list_id),
                    subscription_id=row.id,
                    enabled=True,
                    account_generation=1,
                    remote_owner_id=7,
                    external_list_id=9,
                )
            )
        outbound = Operation(
            owner_id=UUID(admin["id"]),
            kind="lists.writeback",
            idempotency_key="saved-uncertain-write",
            status="attention",
            message="Uncertain write needs reconciliation",
            payload={
                "list_id": list_id,
                "book_id": "42",
                "desired": True,
                "pending_attempt": {"sent": True},
            },
        )
        db.add(outbound)
        await db.flush()
        policy_id, subscription_id, outbound_id, manual_id = (
            policy.id,
            row.id,
            outbound.id,
            manual.id,
        )
        await db.execute(delete(RateLimit).where(RateLimit.key == "goodreads:rss"))
    service.records = [
        service.records[0],
        service.records[2],
        {
            "external_id": "45",
            "title": "Added after backup",
            "authors": ["Writer"],
            "isbn": None,
            "isbn13": None,
        },
    ]
    checkpoint = await pause(database, admin)
    return {
        "provider": provider,
        "list_id": UUID(list_id),
        "subscription_id": subscription_id,
        "policy_id": policy_id,
        "outbound_id": outbound_id,
        "service": service,
        "checkpoint": checkpoint,
        "works": works,
        "manual_id": manual_id,
    }


async def observe(client, ready):
    scan_id = await begin(client)
    await scans.run(UUID(scan_id))
    result = await report(client, scan_id, domain="lists")
    finding = next(row for row in result["items"] if row["state"] == "list-ready")
    return {"scan_id": scan_id, "finding_ids": [finding["id"]]}


async def preview(client, body, key=None):
    response = await client.post(
        "/api/recovery/list-reconciliations",
        headers={"Idempotency-Key": key or str(uuid4())},
        json=body,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def accept(client, plan, key=None):
    return await client.post(
        f"/api/recovery/list-reconciliations/{plan['id']}/accept",
        headers={"Idempotency-Key": key or str(uuid4())},
        json={"revision": plan["revision"]},
    )


async def outcome(client, plan):
    return (await client.get(f"/api/recovery/list-reconciliations/{plan['id']}")).json()


async def test_reviewed_baseline_preserves_curated_members_and_never_acquires_catchup(
    client, admin, database, ready
):
    body = await observe(client, ready)
    plan = await preview(client, body, "same-list-review")
    assert await preview(client, body, "same-list-review") == plan
    assert plan["items"][0]["summary"]["new"] == 1
    assert plan["items"][0]["summary"]["missing"] == (ready["provider"] == "hardcover")
    assert "membership_digest" not in str(plan) and URL not in str(plan)
    remote_before = deepcopy(ready["service"].records)
    async with database() as db:
        pending = await db.get(Operation, ready["outbound_id"])
        pending_before = {c.name: getattr(pending, c.name) for c in Operation.__table__.columns}
        jobs_before = list(
            await db.scalars(
                text(
                    "SELECT id FROM book_queue.procrastinate_jobs "
                    "WHERE task_name NOT LIKE 'recovery.%'"
                )
            )
        )
    assert (await accept(client, plan, "same-list-accept")).status_code == 202
    assert (await accept(client, plan, "same-list-accept")).status_code == 202
    queue = recovery_queue()
    async with queue.open_async():
        await queue.run_worker_async(wait=False, concurrency=1)
    result = await outcome(client, plan)
    assert result["status"] == "completed", result
    async with database() as db:
        row = await db.get(ListSubscription, ready["subscription_id"])
        assert row.generation == 2 and row.state == "idle" and row.baseline_at
        assert row.run_token is row.lease_until is row.next_sync_at is row.operation_id is None
        observations = {r.external_id: r for r in await db.scalars(select(ListObservation))}
        assert observations["44"].excluded
        assert observations["43"].present == (ready["provider"] == "goodreads")
        entries = set(await db.scalars(select(ListEntry.work_id)))
        assert observations["44"].work_id not in entries
        assert (observations["43"].work_id in entries) == (ready["provider"] == "goodreads")
        assert observations["45"].work_id in entries and ready["manual_id"] in entries
        policy = await db.get(ListAcquisitionPolicy, ready["policy_id"])
        assert not policy.active and policy.revision == 2
        books = list(await db.scalars(select(ListAcquisitionBook)))
        assert all(book.state == "baseline" and book.next_check_at is None for book in books)
        assert not list(await db.scalars(select(AcquisitionIntent)))
        if ready["provider"] == "hardcover":
            writeback = await db.get(ListWritebackPolicy, ready["list_id"])
            assert not writeback.enabled and writeback.generation == 2
        assert "etag" not in decrypt_secrets(row.encrypted_config)
        pending = await db.get(Operation, ready["outbound_id"])
        assert pending_before == {
            c.name: getattr(pending, c.name) for c in Operation.__table__.columns
        }
        assert jobs_before == list(
            await db.scalars(
                text(
                    "SELECT id FROM book_queue.procrastinate_jobs "
                    "WHERE task_name NOT LIKE 'recovery.%'"
                )
            )
        )
        assert (await db.get(RestoreCheckpoint, ready["checkpoint"])).active
    calls = ready["service"].calls
    await recovery.run(UUID(plan["id"]))
    assert ready["service"].calls == calls and ready["service"].records == remote_before
    assert (await client.get("/api/recovery")).json()["latest_list_reconciliation"] == result
    assert (await client.get("/api/lists")).status_code == 423


@pytest.mark.parametrize("change", ["remote", "owner", "policy", "membership"])
async def test_changed_review_context_or_remote_membership_holds_the_baseline(
    client, admin, database, ready, change
):
    plan = await preview(client, await observe(client, ready))
    assert (await accept(client, plan)).status_code == 202
    if change == "remote":
        ready["service"].records[-1]["title"] = "Different current book"
    else:
        async with database() as db, db.begin():
            if change == "owner":
                (await db.get(User, UUID(admin["id"]))).role = "viewer"
            elif change == "policy":
                (await db.get(ListAcquisitionPolicy, ready["policy_id"])).revision += 1
            else:
                (await db.scalar(select(ListEntry))).locally_added = True
    await recovery.run(UUID(plan["id"]))
    async with database() as db:
        operation = await db.get(Operation, UUID(plan["id"]))
        assert operation.status == "held"
        assert (await db.get(ListSubscription, ready["subscription_id"])).generation == 1
        assert not await db.scalar(
            select(ListObservation.id).where(ListObservation.external_id == "45")
        )


async def test_failed_application_rolls_back_catalog_memberships_and_policy_changes(
    client, admin, database, ready, monkeypatch
):
    plan = await preview(client, await observe(client, ready))
    assert (await accept(client, plan)).status_code == 202
    original = recovery.record_baseline

    async def fail(*args):
        await original(*args)
        raise RuntimeError("Simulated failure after local changes")

    monkeypatch.setattr(recovery, "record_baseline", fail)
    await recovery.run(UUID(plan["id"]))
    assert (await outcome(client, plan))["status"] == "held"
    async with database() as db:
        assert (await db.get(ListAcquisitionPolicy, ready["policy_id"])).active
        assert (await db.get(ListSubscription, ready["subscription_id"])).generation == 1
        assert not await db.scalar(select(Work.id).where(Work.title == "Added after backup"))
        assert not await db.scalar(
            select(AuditEvent.id).where(AuditEvent.action == "recovery.list.rebaselined")
        )


async def test_recovered_entries_stay_baseline_and_only_future_additions_become_wanted(
    client, admin, database, ready
):
    plan = await preview(client, await observe(client, ready))
    assert (await accept(client, plan)).status_code == 202
    await recovery.run(UUID(plan["id"]))
    assert (await outcome(client, plan))["status"] == "completed"
    async with database() as db, db.begin():
        policy = await db.get(ListAcquisitionPolicy, ready["policy_id"])
        owner = await db.get(User, UUID(admin["id"]))
        records = await list_policies.members(db, owner, ready["list_id"])
        await list_monitoring.reconcile(db, policy, records, datetime.now(UTC))
        assert all(
            book.state == "baseline" for book in await db.scalars(select(ListAcquisitionBook))
        )
        future = Work(title="Future explicit addition", authors=["Writer"])
        db.add(future)
        await db.flush()
        db.add(ListEntry(list_id=ready["list_id"], work_id=future.id, created_at=datetime.now(UTC)))
        await db.flush()
        records = await list_policies.members(db, owner, ready["list_id"])
        await list_monitoring.reconcile(db, policy, records, datetime.now(UTC))
        wanted = list(
            await db.scalars(
                select(ListAcquisitionBook).where(ListAcquisitionBook.state == "wanted")
            )
        )
        assert len(wanted) == 1 and wanted[0].work_id == future.id
        assert not policy.active  # Membership classification does not authorize dispatch.


@pytest.mark.parametrize("local_copy", [False, True])
async def test_removal_preserves_manual_or_other_list_reasons_and_existing_reservations(
    client, admin, database, ready, local_copy
):
    async with database() as db, db.begin():
        if local_copy:
            entry = await db.scalar(
                select(ListEntry).where(ListEntry.work_id == ready["works"]["43"])
            )
            entry.locally_added = True
        intent = AcquisitionIntent(
            owner_id=UUID(admin["id"]),
            work_id=ready["works"]["43"],
            fingerprint="f" * 64,
            specification={"mode": "ebook"},
        )
        reservation = AcquisitionReservation(
            work_id=ready["works"]["43"],
            scope="fixture",
            requirements={"medium": "ebook"},
            state="committed",
        )
        db.add_all([intent, reservation])
        await db.flush()
        db.add_all(
            [
                AcquisitionReason(
                    intent_id=intent.id, kind="manual", reference="independent-manual"
                ),
                AcquisitionReason(intent_id=intent.id, kind="list", reference="another-list"),
                AcquisitionReason(
                    intent_id=intent.id,
                    kind="list",
                    reference=str(ready["list_id"]),
                    list_id=ready["list_id"],
                ),
                AcquisitionTarget(
                    intent_id=intent.id,
                    slot="ebook",
                    state="wanted",
                    message="Existing acquisition",
                    reservation_id=reservation.id,
                ),
            ]
        )
        intent_id, reservation_id = intent.id, reservation.id
    plan = await preview(client, await observe(client, ready))
    assert (await accept(client, plan)).status_code == 202
    await recovery.run(UUID(plan["id"]))
    assert (await outcome(client, plan))["status"] == "completed"
    async with database() as db:
        reasons = {row.reference: row.active for row in await db.scalars(select(AcquisitionReason))}
        assert reasons["independent-manual"] and reasons["another-list"]
        assert reasons[str(ready["list_id"])] == (local_copy or ready["provider"] == "goodreads")
        assert (await db.get(AcquisitionReservation, reservation_id)).state == "committed"
        target = await db.scalar(
            select(AcquisitionTarget).where(AcquisitionTarget.intent_id == intent_id)
        )
        assert target.state == "wanted" and target.reservation_id == reservation_id


async def test_rebaseline_invalidates_old_sync_lease_and_retains_staged_history(
    client, admin, database, ready
):
    async with database() as db, db.begin():
        row = await db.get(ListSubscription, ready["subscription_id"])
        old = await db.get(Operation, row.operation_id)
        old.status = row.state = "running"
        old.payload = {**old.payload, "stage": {"private_previous_membership": True}}
        row.run_token, row.lease_until = uuid4(), datetime.now(UTC) + timedelta(minutes=2)
        operation_id, old_payload = old.id, deepcopy(old.payload)
    plan = await preview(client, await observe(client, ready))
    assert (await accept(client, plan)).status_code == 202
    await recovery.run(UUID(plan["id"]))
    assert (await outcome(client, plan))["status"] == "completed"
    async with database() as db, db.begin():
        old = await db.get(Operation, operation_id)
        assert old.status == "attention" and old.payload == old_payload
        assert await list_subscriptions.context(db, operation_id) is None
        row = await db.get(ListSubscription, ready["subscription_id"])
        assert row.run_token is None and row.operation_id is None and row.next_sync_at is None


async def test_local_policy_change_during_provider_read_cannot_publish_a_baseline(
    client, admin, database, ready
):
    plan = await preview(client, await observe(client, ready))
    assert (await accept(client, plan)).status_code == 202
    changed = False

    async def mutate():
        nonlocal changed
        if changed:
            return
        changed = True
        async with database() as db, db.begin():
            row = await db.get(ListAcquisitionPolicy, ready["policy_id"])
            row.revision += 1

    ready["service"].callback = mutate
    await recovery.run(UUID(plan["id"]))
    assert (await outcome(client, plan))["status"] == "held"
    async with database() as db:
        assert (await db.get(ListSubscription, ready["subscription_id"])).generation == 1


async def test_review_requires_exact_revision_and_serializes_with_other_recovery_actions(
    client, admin, database, ready
):
    body = await observe(client, ready)
    plan = await preview(client, body)
    path = f"/api/recovery/list-reconciliations/{plan['id']}/accept"
    wrong = await client.post(
        path, headers={"Idempotency-Key": "wrong-list-revision"}, json={"revision": "0" * 64}
    )
    assert wrong.status_code == 409
    forbidden = await client.post(
        path,
        headers={"Idempotency-Key": "wrong-list-csrf", "X-CSRF-Token": "bad"},
        json={"revision": plan["revision"]},
    )
    assert forbidden.status_code == 403
    assert (
        await client.get(f"/api/recovery/inventory-reconciliations/{plan['id']}")
    ).status_code == 404
    assert (await accept(client, plan)).status_code == 202
    assert (
        await client.post(
            "/api/recovery/scans", headers={"Idempotency-Key": "during-list-rebaseline"}
        )
    ).status_code == 409
    await recovery.run(UUID(plan["id"]))
    stale = await client.post(
        "/api/recovery/list-reconciliations",
        headers={"Idempotency-Key": "stale-list-review"},
        json=body,
    )
    assert stale.status_code == 409


async def test_changed_hardcover_owner_or_nonfresh_rss_cannot_offer_a_baseline(
    client, admin, database, ready, monkeypatch
):
    if ready["provider"] == "hardcover":
        ready["service"].owner_id = "different-owner"
    else:

        async def unchanged(*args, **kwargs):
            return FeedResult([], True, '"old"', None)

        monkeypatch.setattr(observers, "fetch_feed", unchanged)
    scan_id = await begin(client)
    await scans.run(UUID(scan_id))
    data = await report(client, scan_id, domain="lists")
    assert not any(row["state"] == "list-ready" for row in data["items"])
    rejected = next(row for row in data["items"] if row["state"] in {"blocked", "conflict"})
    response = await client.post(
        "/api/recovery/list-reconciliations",
        headers={"Idempotency-Key": "reject-incomplete-list"},
        json={"scan_id": scan_id, "finding_ids": [rejected["id"]]},
    )
    assert response.status_code == 409


async def test_multi_list_failure_rolls_back_all_selected_baselines(
    client, admin, database, ready, monkeypatch
):
    async with database() as db, db.begin():
        original = await db.get(ListSubscription, ready["subscription_id"])
        second_list = BookList(owner_id=UUID(admin["id"]), name="Another followed shelf")
        db.add(second_list)
        await db.flush()
        second = ListSubscription(
            list_id=second_list.id,
            provider=original.provider,
            encrypted_config=original.encrypted_config,
            enabled=True,
        )
        db.add(second)
        await db.flush()
        second_id = second.id
    scan_id = await begin(client)
    await scans.run(UUID(scan_id))
    data = await report(client, scan_id, domain="lists")
    ids = [row["id"] for row in data["items"] if row["state"] == "list-ready"]
    assert len(ids) == 2, data
    plan = await preview(client, {"scan_id": scan_id, "finding_ids": ids})
    assert (await accept(client, plan)).status_code == 202
    original = recovery.record_baseline
    count = 0

    async def fail_second(*args):
        nonlocal count
        result = await original(*args)
        count += 1
        if count == 2:
            raise RuntimeError("Injected second-list failure")
        return result

    monkeypatch.setattr(recovery, "record_baseline", fail_second)
    await recovery.run(UUID(plan["id"]))
    assert (await outcome(client, plan))["status"] == "held"
    async with database() as db:
        assert (await db.get(ListSubscription, ready["subscription_id"])).generation == 1
        assert (await db.get(ListSubscription, second_id)).generation == 1
        assert not list(
            await db.scalars(
                select(ListObservation).where(ListObservation.subscription_id == second_id)
            )
        )
        assert not await db.scalar(select(Work.id).where(Work.title == "Added after backup"))
