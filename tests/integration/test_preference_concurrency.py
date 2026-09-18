"""Cross-workflow policy reads must not invert acquisition and configuration locks."""

# ruff: noqa: F401, F811
import asyncio
from uuid import UUID

import pytest
from sqlalchemy import select, text

from app.db.models import AcquisitionIntent, AcquisitionReason, User
from app.domain import (
    acquisition,
    acquisition_selection,
    automatic_selection,
    list_requests,
    release_profiles,
    request_preferences,
)
from tests.integration.test_list_policies import (
    add,
    authorized,
    catalog,
    policy_fixture,
    selection_route,
    source,
)

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("flow", ["request", "selection", "automatic-preparation"])
async def test_list_batch_and_acquisition_finish_without_configuration_work_deadlock(
    client, admin, database, policy_fixture, monkeypatch, flow
):
    f = policy_fixture
    await add(client, f)
    preview = await client.post(
        f"/api/lists/{f['list']}/requests/preview",
        json={"work_ids": [f["work"]], "specification": {"mode": "audio"}},
        headers={"Idempotency-Key": "concurrent-policy-batch"},
    )
    assert preview.status_code == 200, preview.text
    identifier = UUID(preview.json()["id"])
    accepted = await client.post(f"/api/lists/{f['list']}/requests/{identifier}/submit")
    assert accepted.status_code == 202, accepted.text
    batch_resolved, manual_resolving, continue_batch = (asyncio.Event() for _ in range(3))
    original = release_profiles.profile_snapshot

    async def interleaved(*args, **kwargs):
        name = asyncio.current_task().get_name()
        if name == "manual-request":
            manual_resolving.set()
        result = await original(*args, **kwargs)
        if name == "list-batch" and not batch_resolved.is_set():
            batch_resolved.set()
            await continue_batch.wait()
        return result

    monkeypatch.setattr(release_profiles, "profile_snapshot", interleaved)
    monkeypatch.setattr(request_preferences, "profile_snapshot", interleaved)

    async def manual():
        async with database() as db, db.begin():
            user = await db.get(User, UUID(admin["id"]))
            if flow == "request":
                await acquisition.submit(
                    db,
                    user,
                    UUID(f["work"]),
                    acquisition.RequestSpec(mode="audio"),
                    acquisition.RequestReason(),
                    "concurrent-policy-manual",
                )
            elif flow == "selection":
                body = {k: v for k, v in f["source"]["body"].items() if k != "download_when_ready"}
                await acquisition_selection.prepare(
                    db,
                    user,
                    acquisition_selection.SelectionInput(
                        **{
                            **body,
                            "artifact_id": str(f["source"]["artifact"]),
                            "confirmed_work_id": f["work"],
                        }
                    ),
                    "concurrent-policy-selection",
                )
            else:
                await automatic_selection.begin(
                    db,
                    user,
                    automatic_selection.AutomaticSelectionInput(
                        **{
                            **f["source"]["body"],
                            "download_when_ready": False,
                        }
                    ),
                    "concurrent-policy-preparation",
                )

    batch = asyncio.create_task(list_requests.run(identifier), name="list-batch")
    tasks = [batch]
    try:
        await asyncio.wait_for(batch_resolved.wait(), 5)
        tasks.append(asyncio.create_task(manual(), name="manual-request"))
        await asyncio.wait_for(manual_resolving.wait(), 5)
        continue_batch.set()
        results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 10)
        assert all(not isinstance(result, BaseException) for result in results), results
    finally:
        continue_batch.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    receipt = (await client.get(f"/api/lists/{f['list']}/requests/{identifier}")).json()
    assert receipt["status"] == "completed"
    async with database() as db:
        intent = await db.get(AcquisitionIntent, UUID(receipt["receipt"][0]["request_id"]))
        reasons = list(
            await db.scalars(
                select(AcquisitionReason)
                .join(AcquisitionIntent)
                .where(AcquisitionIntent.work_id == intent.work_id)
            )
        )
        assert {reason.kind for reason in reasons if reason.active} == {"manual", "list"}


@pytest.mark.parametrize("commit", [False, True])
async def test_snapshot_reads_committed_layers_without_waiting_for_settings_writer(
    client, admin, database, commit
):
    from app.db.models import AcquisitionDefaults, AcquisitionProfile
    from app.domain.operations import transaction_lock
    from tests.integration.test_acquisition_defaults import save

    await save(client, {"maximum_bytes": 100}, "installation")
    created = (
        await client.post(
            "/api/acquisition/profiles",
            json={
                "name": "Consistent snapshot",
                "preferences": {"source_order": ["mam", "prowlarr"]},
            },
        )
    ).json()
    owner, identifier = UUID(admin["id"]), UUID(created["id"])
    async with database() as reader, database() as writer:
        # Populate the reader's identity map as well; later reads must observe
        # committed columns, not reuse an old ORM instance after another edit.
        await reader.get(AcquisitionProfile, identifier)
        await transaction_lock(writer, release_profiles.DEFAULTS_LOCK)
        await transaction_lock(writer, f"profile:{identifier}")
        installation = await writer.get(AcquisitionDefaults, "installation")
        installation.preferences = {"maximum_bytes": 200}
        installation.generation += 1
        profile = await writer.get(AcquisitionProfile, identifier)
        profile.preferences = {"source_order": ["prowlarr", "mam"]}
        profile.generation += 1
        await writer.flush()
        before = await asyncio.wait_for(
            release_profiles.profile_snapshot(reader, owner, identifier), 3
        )
        assert before.generation == 1
        assert before.preferences.maximum_bytes == 100
        assert before.preferences.source_order == ["mam", "prowlarr"]
        await (writer.commit() if commit else writer.rollback())
        after = await release_profiles.profile_snapshot(reader, owner, identifier)
        assert after.generation == (2 if commit else 1)
        assert after.preferences.maximum_bytes == (200 if commit else 100)
        assert after.preferences.source_order == (
            ["prowlarr", "mam"] if commit else ["mam", "prowlarr"]
        )
        assert (after.effective_revision != before.effective_revision) is commit
        assert before.preferences.maximum_bytes == 100


async def test_concurrent_profile_writes_still_have_one_revision_winner(client, admin):
    created = (await client.post("/api/acquisition/profiles", json={"name": "Concurrent"})).json()

    async def edit(limit):
        return await client.put(
            f"/api/acquisition/profiles/{created['id']}",
            json={
                "name": "Concurrent",
                "expected_generation": created["generation"],
                "preferences": {"maximum_bytes": limit},
            },
        )

    responses = await asyncio.gather(edit(100), edit(200))
    assert sorted(r.status_code for r in responses) == [200, 409]
    saved = next(r.json() for r in responses if r.status_code == 200)
    assert saved["generation"] == created["generation"] + 1
    profiles = (await client.get("/api/acquisition/profiles")).json()
    assert next(p for p in profiles if p["id"] == created["id"]) == saved


@pytest.mark.parametrize("scope", ["personal", "installation"])
async def test_preferences_committed_during_network_preflight_hold_automatic_submission(
    client, database, authorized, scope
):
    from app.db.models import DownloadAttempt
    from app.domain import download_attempts
    from tests.integration.test_acquisition_defaults import save
    from tests.integration.test_automatic_selection import detail, start

    operation = await start(client, authorized)
    await automatic_selection.run(UUID(operation["id"]))
    receipt = await detail(client, operation["id"])
    identifier = UUID(receipt["download_id"])
    authorized["qbit"].before_find = lambda: save(client, {"audio_formats": ["mp3", "m4b"]}, scope)
    await download_attempts.run(identifier)
    assert "submit" not in authorized["qbit"].calls
    async with database() as db:
        attempt = await db.get(DownloadAttempt, identifier)
        assert attempt.state == "held" and not attempt.external_may_exist


@pytest.mark.parametrize("scope", ["personal", "installation"])
async def test_final_submission_fences_settings_writes_until_marker_commits(
    client, database, authorized, monkeypatch, scope
):
    from app.api import acquisition_preferences
    from app.db.models import DownloadAttempt
    from app.domain import capacity, download_attempts
    from tests.integration.test_automatic_selection import detail, start

    before = (await client.get(f"/api/acquisition/preferences/{scope}")).json()
    operation = await start(client, authorized)
    await automatic_selection.run(UUID(operation["id"]))
    receipt = await detail(client, operation["id"])
    identifier = UUID(receipt["download_id"])
    validated, resume, writer_started = (asyncio.Event() for _ in range(3))
    submitted = capacity.submitted
    lock = acquisition_preferences.transaction_lock
    pids = {}

    async def pause_after_validation(db, attempt):
        await submitted(db, attempt)
        pids["dispatch"] = await db.scalar(text("SELECT pg_backend_pid()"))
        validated.set()
        await resume.wait()

    async def observe_settings_lock(db, key):
        pids["writer"] = await db.scalar(text("SELECT pg_backend_pid()"))
        writer_started.set()
        await lock(db, key)
        # Once the writer has the fence, dispatch must already be durable.
        attempt = await db.get(DownloadAttempt, identifier)
        assert attempt.external_may_exist

    monkeypatch.setattr(capacity, "submitted", pause_after_validation)
    monkeypatch.setattr(acquisition_preferences, "transaction_lock", observe_settings_lock)
    tasks = [asyncio.create_task(download_attempts.run(identifier))]
    try:
        await asyncio.wait_for(validated.wait(), 5)
        tasks.append(
            asyncio.create_task(
                client.put(
                    f"/api/acquisition/preferences/{scope}",
                    json={
                        "overrides": {"audio_formats": ["mp3", "m4b"]},
                        "expected_revision": before["revision"],
                    },
                )
            )
        )
        await asyncio.wait_for(writer_started.wait(), 5)
        async with database() as db, asyncio.timeout(3):
            # Observe PostgreSQL's real wait graph rather than timing a sleep.
            while not await db.scalar(  # noqa: ASYNC110
                text("SELECT :dispatch = ANY(pg_blocking_pids(:writer))"), pids
            ):
                await asyncio.sleep(0.01)
            assert not (await db.get(DownloadAttempt, identifier)).external_may_exist
        resume.set()
        results = await asyncio.wait_for(asyncio.gather(*tasks), 10)
        assert results[1].status_code == 200, results[1].text
    finally:
        resume.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    await download_attempts.run(identifier)
    assert authorized["qbit"].calls.count("submit") == 1
    async with database() as db:
        attempt = await db.get(DownloadAttempt, identifier)
        assert attempt.external_may_exist and attempt.state == "downloading"
