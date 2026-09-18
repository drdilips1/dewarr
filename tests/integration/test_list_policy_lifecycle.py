# ruff: noqa: F401, F811
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.adapters.mam import ReleasePage
from app.db.models import (
    AcquisitionIntent,
    DownloadAttempt,
    ListAcquisitionBook,
    ListEntry,
    Operation,
    Work,
)
from app.domain import automatic_selection, book_sources, download_attempts, list_automation
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

pytestmark = pytest.mark.integration


async def test_overlapping_lists_share_one_download_without_stranding_the_other_policy(
    client, database, policy_fixture
):
    f = policy_fixture
    await add(client, f)
    one = await activate(client, f, await preview(client, f, include_work_ids=[f["work"]]))
    other = {
        **f,
        "list": (await client.post("/api/lists", json={"name": "Second automation reason"})).json()[
            "id"
        ],
    }
    await add(client, other)
    two = await activate(client, other, await preview(client, other, include_work_ids=[f["work"]]))
    await tick(database, one)
    await tick(database, two)
    await tick(database, one, force_books=True, worker=False)
    await tick(database, two, force_books=True, worker=False)
    await get_queue().run_worker_async(wait=False, concurrency=1)
    await tick(database, two, force_books=True)
    assert f["source"]["qbit"].calls.count("submit") == 1
    async with database() as db:
        books = list(await db.scalars(select(ListAcquisitionBook)))
        assert all(b.state != "held" for b in books), [(b.state, b.message) for b in books]
        assert len({b.intent_id for b in books}) == 1


async def test_pause_before_dispatch_and_explicit_resume_reuses_the_original_attempt(
    client, database, policy_fixture
):
    f = policy_fixture
    await add(client, f)
    saved = await activate(client, f, await preview(client, f, include_work_ids=[f["work"]]))
    await tick(database, saved)
    await tick(database, saved, worker=False, force_books=True)
    async with database() as db:
        auto = await db.scalar(select(Operation).where(Operation.kind == automatic_selection.KIND))
    await automatic_selection.run(auto.id)
    async with database() as db:
        attempt = await db.scalar(select(DownloadAttempt))
        assert attempt is not None
    paused = (
        await client.post(
            f"/api/lists/{f['list']}/acquisition/pause",
            json={"expected_revision": saved["revision"]},
        )
    ).json()
    await download_attempts.run(attempt.id)
    assert not f["source"]["qbit"].calls.count("submit")
    resumed = await activate(
        client, f, await preview(client, f, expected_revision=paused["revision"])
    )
    await tick(database, resumed, force_books=True)
    assert f["source"]["qbit"].calls.count("submit") == 1
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(DownloadAttempt)) == 1


async def test_no_release_schedules_bounded_research_without_resetting_on_ticks(
    client, database, policy_fixture, monkeypatch
):
    f = policy_fixture
    calls = []

    async def empty(*args, **kwargs):
        calls.append(1)
        return ReleasePage(items=[], offset=0, limit=50, total=0, has_more=False), 1

    monkeypatch.setattr(book_sources, "source_call", empty)
    await add(client, f)
    saved = await activate(client, f, await preview(client, f, include_work_ids=[f["work"]]))
    await tick(database, saved)
    await tick(database, saved, force_books=True)
    await tick(database, saved, force_books=True)
    async with database() as db:
        book = await db.scalar(select(ListAcquisitionBook))
        assert book.state == "wanted"
        assert book.next_check_at > datetime.now(UTC) + timedelta(hours=5)
    await tick(database, saved, force_books=True)
    assert len(calls) == 1
    now = datetime.now(UTC)
    assert list_automation.retry_at(1, now) == now + timedelta(hours=6)
    assert list_automation.retry_at(8, now) == now + timedelta(days=1)
    assert list_automation.retry_at(9, now) == now + timedelta(days=7)


async def test_activation_preview_paginates_all_members_and_limits_selected_backlog(
    client, database, policy_fixture
):
    f = policy_fixture
    async with database() as db, db.begin():
        works = [Work(title=f"Backlog {i}", authors=["Writer"]) for i in range(51)]
        db.add_all(works)
        await db.flush()
        db.add_all([ListEntry(list_id=UUID(f["list"]), work_id=w.id) for w in works])
        ids = [str(w.id) for w in works]
    plan = await preview(client, f)
    assert plan["total"] == 51 and len(plan["records"]) == 50
    second = (
        await client.get(f"/api/lists/{f['list']}/acquisition/previews/{plan['id']}?offset=50")
    ).json()
    assert len(second["records"]) == 1
    invalid = await client.post(
        f"/api/lists/{f['list']}/acquisition/preview",
        json={**f["config"], "include_work_ids": ids[:26]},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert invalid.status_code == 422
    policy = await activate(client, f, plan)
    assert policy["counts"] == {"baseline": 51}


async def test_administrator_can_grant_and_revoke_list_automation_with_stale_write_protection(
    client, admin
):
    created = await client.post(
        "/api/auth/users",
        json={
            "username": "automator",
            "display_name": "Automator",
            "password": "long fixture password",
            "role": "member",
        },
    )
    assert created.status_code == 201
    user = created.json()
    path = f"/api/auth/users/{user['id']}/automation"
    granted = await client.put(path, json={"allowed": True, "expected_allowed": False})
    assert granted.status_code == 200 and granted.json()["can_automate"]
    assert (
        await client.put(path, json={"allowed": False, "expected_allowed": False})
    ).status_code == 409
    revoked = await client.put(path, json={"allowed": False, "expected_allowed": True})
    assert revoked.status_code == 200 and not revoked.json()["can_automate"]


async def test_policy_migration_refuses_to_discard_activation_history(
    client, database, policy_fixture
):
    from app.db.session import get_engine
    from tests.integration.test_correction_migration import migrate

    await preview(client, policy_fixture)
    await get_engine().dispose()
    try:
        rejected = await migrate("downgrade", "0029_request_constraints")
        assert rejected.returncode != 0 and "pre-upgrade backup" in rejected.stderr
    finally:
        assert (await migrate("upgrade", "head")).returncode == 0
        await get_engine().dispose()


async def test_profile_limits_are_inherited_and_edits_require_a_new_activation(
    client, database, policy_fixture
):
    f = policy_fixture
    profile = (
        await client.post(
            "/api/acquisition/profiles",
            json={
                "name": "Small audio",
                "preferences": {"maximum_bytes": 12, "blocked_formats": ["flac"]},
            },
        )
    ).json()
    f["config"].update(profile_id=profile["id"], profile_generation=profile["generation"])
    await add(client, f)
    saved = await activate(client, f, await preview(client, f, include_work_ids=[f["work"]]))
    assert saved["configuration"]["specification"]["download_constraints"] == {
        "maximum_bytes": 12,
        "blocked_formats": ["flac"],
    }
    await tick(database, saved)
    async with database() as db:
        book = await db.scalar(select(ListAcquisitionBook))
        intent = await db.get(AcquisitionIntent, book.intent_id)
        assert intent.specification["download_constraints"]["maximum_bytes"] == 12
    await client.put(
        f"/api/acquisition/profiles/{profile['id']}",
        json={"name": "Changed", "expected_generation": 1, "preferences": {"maximum_bytes": 24}},
    )
    await tick(database, saved, force_books=True)
    assert not f["source"]["qbit"].calls.count("submit")


async def test_explicit_backlog_selection_can_restore_a_withdrawn_policy_reason(
    client, database, policy_fixture
):
    from app.db.models import AcquisitionReason

    f = policy_fixture
    await add(client, f)
    saved = await activate(client, f, await preview(client, f, include_work_ids=[f["work"]]))
    await tick(database, saved, worker=False)
    async with database() as db:
        reason = await db.scalar(
            select(AcquisitionReason).where(AcquisitionReason.reference.startswith("policy:"))
        )
    cancelled = await client.delete(f"/api/requests/{reason.intent_id}/reasons/{reason.id}")
    assert cancelled.status_code == 200
    await tick(database, saved, worker=False, force_books=True)
    restored = await activate(
        client,
        f,
        await preview(client, f, expected_revision=saved["revision"], include_work_ids=[f["work"]]),
    )
    await tick(database, restored)
    await tick(database, restored, force_books=True)
    assert f["source"]["qbit"].calls.count("submit") == 1


async def test_shared_list_does_not_expose_policy_or_grant_automation_to_another_member(
    client, database, policy_fixture
):
    import httpx

    from app.main import create_app

    f = policy_fixture
    saved = await preview(client, f)
    await client.patch(f"/api/lists/{f['list']}", json={"name": "Shared shelf", "shared": True})
    created = await client.post(
        "/api/auth/users",
        json={
            "username": "other-policy-user",
            "display_name": "Other",
            "password": "a long fixture password",
            "role": "member",
        },
    )
    assert created.status_code == 201
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()),
        base_url="http://testserver",
        headers={"Origin": "http://testserver"},
    ) as other:
        auth = await other.post(
            "/api/auth/login",
            json={"username": "other-policy-user", "password": "a long fixture password"},
        )
        other.headers["X-CSRF-Token"] = auth.json()["csrf_token"]
        assert (await other.get(f"/api/lists/{f['list']}/acquisition")).status_code == 404
        assert (
            await other.post(f"/api/lists/{f['list']}/acquisition/previews/{saved['id']}/activate")
        ).status_code == 404
        permission = await other.put(
            f"/api/auth/users/{created.json()['id']}/automation",
            json={"allowed": True, "expected_allowed": False},
        )
        assert permission.status_code == 403


async def test_scheduler_queue_failure_rolls_back_policy_receipt(
    client, database, policy_fixture, monkeypatch
):
    from app.db.models import ListAcquisitionPolicy

    f = policy_fixture
    saved = await activate(client, f, await preview(client, f))

    async def unavailable(*args, **kwargs):
        raise RuntimeError("synthetic queue outage")

    monkeypatch.setattr(list_automation, "enqueue", unavailable)
    with pytest.raises(RuntimeError, match="synthetic queue outage"):
        await list_automation.schedule()
    async with database() as db:
        assert not await db.scalar(
            select(Operation.id).where(Operation.kind == list_automation.KIND)
        )
        assert not (await db.get(ListAcquisitionPolicy, UUID(saved["id"]))).operation_id


async def test_scheduler_deadline_does_not_skip_the_next_minute_for_worker_jitter(
    client, database, policy_fixture, monkeypatch
):
    from app.db.models import ListAcquisitionPolicy

    saved = await activate(client, policy_fixture, await preview(client, policy_fixture))
    now = datetime.now(UTC).replace(second=0, microsecond=900000) + timedelta(minutes=1)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(list_automation, "datetime", Clock)
    await list_automation.schedule()
    async with database() as db:
        policy = await db.get(ListAcquisitionPolicy, UUID(saved["id"]))
        first = policy.operation_id
        assert policy.next_check_at == now.replace(microsecond=0) + timedelta(minutes=1)
    await list_automation.run(first)
    # The following cron tick is earlier within its minute than the preceding worker.
    now = now.replace(microsecond=100000) + timedelta(minutes=1)
    await list_automation.schedule()
    async with database() as db:
        policy = await db.get(ListAcquisitionPolicy, UUID(saved["id"]))
        assert policy.operation_id != first


async def test_changed_policy_does_not_hide_a_held_previous_generation_transfer(
    client, database, policy_fixture
):
    f = policy_fixture
    await add(client, f)
    saved = await activate(client, f, await preview(client, f, include_work_ids=[f["work"]]))
    # Stop before dispatch deliberately. An unrestricted queue drain can cross a
    # cron minute and legitimately submit before this test changes the policy.
    await tick(database, saved, worker=False)
    async with database() as db:
        book = await db.scalar(select(ListAcquisitionBook))
        search_id = UUID(book.progress["audio"]["search_id"])
    await book_sources.run(search_id, "mam")
    await tick(database, saved, worker=False, force_books=True)
    async with database() as db:
        auto = await db.scalar(select(Operation).where(Operation.kind == automatic_selection.KIND))
    await automatic_selection.run(auto.id)
    async with database() as db:
        attempt = await db.scalar(select(DownloadAttempt))
        assert attempt and not attempt.external_may_exist and attempt.state == "queued"
    profile = (
        await client.post(
            "/api/acquisition/profiles", json={"name": "Changed list choice", "preferences": {}}
        )
    ).json()
    changed = await activate(
        client,
        f,
        await preview(
            client,
            f,
            expected_revision=saved["revision"],
            include_work_ids=[f["work"]],
            profile_id=profile["id"],
            profile_generation=profile["generation"],
        ),
    )
    assert changed["generation"] > saved["generation"]
    await download_attempts.run(attempt.id)
    await tick(database, changed, worker=False, force_books=True)
    async with database() as db:
        book = await db.scalar(select(ListAcquisitionBook))
        assert book.state == "held" and "Activity" in book.message
    assert f["source"]["qbit"].calls.count("submit") == 0
