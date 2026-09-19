# ruff: noqa: F401, F811
import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text

from app.db.models import AuditEvent, Operation, SourceConnection, User
from app.domain import recovery_scans, recovery_sources, source_network
from app.jobs.queue import recovery_queue
from app.security import decrypt_secrets, encrypt_secrets
from tests.integration.test_audiobookbay_sources import abb_http
from tests.integration.test_mam_sources import source_http
from tests.integration.test_prowlarr_sources import prowlarr_http
from tests.integration.test_recovery_scan_workflow import begin, pause, report

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def routed_mam(source_http, monkeypatch):
    # Native proxy transport is covered by the real local proxy adapter test.
    # Keep these database/session fixtures offline while recording the selected route.
    factory = source_network.MAMClient
    source_http["routes"] = []

    def client(*args, **kwargs):
        source_http["routes"].append(dict(kwargs))
        for name in ("proxy_url", "proxy_username", "proxy_password"):
            kwargs.pop(name, None)
        return factory(*args, **kwargs)

    monkeypatch.setattr(source_network, "MAMClient", client)


@pytest.fixture
async def configured(client, admin, database):
    for key, url, secret in (
        (
            "mam",
            "https://mam.test",
            {
                "mam_id": "restored-private-cookie",
                "proxy_username": "old-proxy-user",
                "proxy_password": "old-proxy-password",
            },
        ),
        (
            "prowlarr",
            "https://prowlarr.test/base",
            {"api_key": "secret-api", "excluded_indexers": [7]},
        ),
        ("audiobookbay", "https://abb.test", {"metadata_downloader_id": None}),
    ):
        async with database() as db, db.begin():
            db.add(
                SourceConnection(
                    key=key,
                    base_url=url,
                    enabled=True,
                    generation=1,
                    proxy_url="http://old-proxy.test" if key == "mam" else None,
                    encrypted_secrets=encrypt_secrets(secret),
                )
            )
    await pause(database, admin)


async def observe(client):
    scan = await begin(client)
    await recovery_scans.run(UUID(scan))
    data = await report(client, scan, domain="review")
    assert data["scan"]["state"] == "completed", data
    findings = {}
    for item in data["items"]:
        if item["state"] in {"source-ready", "source-verified"}:
            detail = (await client.get(f"/api/recovery/scans/{scan}/findings/{item['id']}")).json()
            findings[detail["evidence"]["before"]["source_key"]] = detail
    return scan, findings


def change(finding, **changes):
    before = dict(finding["evidence"]["before"])
    before.pop("has_credentials")
    before.pop("has_proxy_credentials")
    return {"finding_id": finding["id"], **before, **changes}


async def preview(client, scan, change, *, key=None, expected=201):
    response = await client.post(
        "/api/recovery/source-reconciliations",
        headers={"Idempotency-Key": key or str(uuid4())},
        json={"scan_id": scan, "change": change},
    )
    assert response.status_code == expected, response.text
    return response.json()


async def accept(client, plan, *, key=None, expected=202, revision=None):
    response = await client.post(
        f"/api/recovery/source-reconciliations/{plan['id']}/accept",
        headers={"Idempotency-Key": key or str(uuid4())},
        json={"revision": revision or plan["revision"]},
    )
    assert response.status_code == expected, response.text
    return response.json()


async def result(client, plan):
    response = await client.get(f"/api/recovery/source-reconciliations/{plan['id']}")
    assert response.status_code == 200, response.text
    return response.json()


async def work():
    queue = recovery_queue()
    async with queue.open_async():
        await queue.run_worker_async(wait=False, concurrency=1)


async def save(client, plan):
    await accept(client, plan)
    await recovery_sources.run(UUID(plan["id"]))
    return await result(client, plan)


async def test_mam_save_then_verify_rotates_cookie_once_and_keeps_pause(
    client,
    admin,
    database,
    configured,
    source_http,
):
    scan, findings = await observe(client)
    assert not source_http["calls"]
    assert findings["mam"]["evidence"]["requires_current_session"]
    choice = change(
        findings["mam"],
        mam_id="first-fixture",
        proxy_url="http://new-proxy.test",
        proxy_username="new-proxy-user",
        proxy_password="new-proxy-password",
    )
    plan = await preview(client, scan, choice, key="prepare-source-once")
    assert (await preview(client, scan, choice, key="prepare-source-once"))["id"] == plan["id"]
    await preview(
        client,
        scan,
        {**choice, "mam_id": "different-cookie"},
        key="prepare-source-once",
        expected=409,
    )
    assert not source_http["calls"]
    assert all(
        value not in str(plan) + str(findings)
        for value in (
            "first-fixture",
            "restored-private-cookie",
            "new-proxy-password",
            "encrypted_secrets",
            "credential_change",
        )
    )
    await accept(client, plan, revision="0" * 64, expected=409)
    await accept(client, plan, key="accept-source-once")
    await work()
    saved = await result(client, plan)
    assert saved["status"] == "completed" and saved["verification"]["status"] == "completed", saved
    assert len(source_http["calls"]) == 1
    assert source_http["routes"][0]["proxy_url"] == "http://new-proxy.test"
    assert source_http["routes"][0]["proxy_password"] == "new-proxy-password"
    await accept(client, plan, key="accept-source-once")
    await work()
    assert len(source_http["calls"]) == 1
    async with database() as db:
        row = await db.get(SourceConnection, "mam")
        secrets = decrypt_secrets(row.encrypted_secrets)
        assert secrets["mam_id"] == "rotated-1"
        assert secrets["proxy_password"] == "new-proxy-password"
        assert row.generation == 2 and not row.lease_token and row.status == "connected"
        audits = [a.detail for a in await db.scalars(select(AuditEvent))]
        assert "rotated-1" not in str(audits) and "new-proxy-password" not in str(audits)
        jobs = list(await db.scalars(text("SELECT task_name FROM book_queue.procrastinate_jobs")))
        assert set(jobs) <= {"recovery.scan", "recovery.sources", "recovery.source-test"}
    _, current = await observe(client)
    assert current["mam"]["state"] == "source-verified"
    assert not current["mam"]["evidence"]["requires_current_session"]
    assert (await client.post("/api/sources/mam/connection/test")).status_code == 423
    assert (await client.get("/api/recovery")).json()["resume_available"] is False


async def test_failure_keeps_saved_settings_rotated_cookie_and_cooldown(
    client,
    admin,
    database,
    configured,
    source_http,
):
    source_http["status"] = 429
    source_http["headers"] = {"Retry-After": "300"}
    scan, findings = await observe(client)
    plan = await preview(client, scan, change(findings["mam"], mam_id="first-fixture"))
    await accept(client, plan)
    await work()
    state = await result(client, plan)
    assert state["status"] == "completed" and state["verification"]["status"] == "held"
    assert "Settings remain saved" in state["verification"]["message"]
    async with database() as db:
        row = await db.get(SourceConnection, "mam")
        assert row.generation == 2
        assert decrypt_secrets(row.encrypted_secrets)["mam_id"] == "rotated-1"
        assert row.blocked_until > datetime.now(UTC) and row.lease_token is None
        blocked_until = row.blocked_until
    scan, findings = await observe(client)
    assert not findings["mam"]["evidence"]["requires_current_session"]
    plan = await preview(client, scan, change(findings["mam"]))
    await accept(client, plan)
    await work()
    assert (await result(client, plan))["verification"]["status"] == "held"
    assert len(source_http["calls"]) == 1, "A retry must not bypass source cooldown"
    async with database() as db:
        row = await db.get(SourceConnection, "mam")
        assert row.blocked_until == blocked_until and row.generation == 3


@pytest.mark.parametrize(
    "key,changes",
    [
        ("mam", {}),
        ("mam", {"base_url": "https://new-mam.test", "enabled": False}),
        ("prowlarr", {"base_url": "http://new-prowlarr.test"}),
    ],
)
async def test_restored_session_and_new_endpoints_need_current_credentials(
    client,
    admin,
    database,
    configured,
    key,
    changes,
):
    scan, findings = await observe(client)
    await preview(client, scan, change(findings[key], **changes), expected=422)


async def test_disabled_source_clears_proxy_credentials_without_network(
    client,
    admin,
    database,
    configured,
    source_http,
):
    scan, findings = await observe(client)
    plan = await preview(
        client, scan, change(findings["mam"], enabled=False, clear_proxy_credentials=True)
    )
    await accept(client, plan)
    await work()
    state = await result(client, plan)
    assert state["status"] == "completed" and state["verification"] is None
    assert not source_http["calls"]
    async with database() as db:
        row = await db.get(SourceConnection, "mam")
        assert not row.enabled and row.status == "disabled"
        assert "proxy_password" not in decrypt_secrets(row.encrypted_secrets)


@pytest.mark.parametrize("key", ["prowlarr", "audiobookbay"])
async def test_other_sources_use_native_verification(
    client,
    admin,
    database,
    configured,
    prowlarr_http,
    abb_http,
    key,
):
    scan, findings = await observe(client)
    plan = await preview(client, scan, change(findings[key]))
    await accept(client, plan)
    await work()
    state = await result(client, plan)
    assert state["status"] == "completed" and state["verification"]["status"] == "completed", state
    assert bool(prowlarr_http["calls"]) == (key == "prowlarr")
    assert bool(abb_http["calls"]) == (key == "audiobookbay")
    assert not abb_http["qbit_calls"], "Source testing must not resolve magnets or add downloads"


async def test_new_proxy_drops_saved_auth_and_stale_preview_does_not_apply(
    client,
    admin,
    database,
    configured,
    source_http,
):
    scan, findings = await observe(client)
    plan = await preview(
        client,
        scan,
        change(findings["mam"], mam_id="first-fixture", proxy_url="http://new-proxy.test"),
    )
    assert plan["items"][0]["proxy_credentials"] == "clear"
    assert plan["items"][0]["after"]["has_proxy_credentials"] is False
    async with database() as db, db.begin():
        row = await db.get(SourceConnection, "prowlarr")
        row.generation += 1
    await accept(client, plan, expected=409)
    assert not source_http["calls"]
    async with database() as db:
        assert (await db.get(SourceConnection, "mam")).generation == 1


async def test_context_change_after_save_blocks_network_but_keeps_explicit_settings(
    client,
    admin,
    database,
    configured,
    source_http,
):
    scan, findings = await observe(client)
    plan = await preview(client, scan, change(findings["mam"], mam_id="first-fixture"))
    state = await save(client, plan)
    async with database() as db, db.begin():
        row = await db.get(SourceConnection, "prowlarr")
        row.generation += 1
    await recovery_sources.verify(UUID(state["verification"]["id"]))
    assert (await result(client, plan))["verification"]["status"] == "held"
    assert not source_http["calls"]
    async with database() as db:
        assert (
            decrypt_secrets((await db.get(SourceConnection, "mam")).encrypted_secrets)["mam_id"]
            == "first-fixture"
        )


async def test_authority_lost_during_verification_still_saves_rotated_cookie(
    client,
    admin,
    database,
    configured,
    source_http,
):
    scan, findings = await observe(client)
    plan = await preview(client, scan, change(findings["mam"], mam_id="first-fixture"))
    state = await save(client, plan)
    source_http["wait"] = asyncio.Event()
    task = asyncio.create_task(recovery_sources.verify(UUID(state["verification"]["id"])))
    await asyncio.wait_for(source_http["entered"].wait(), 5)
    async with database() as db, db.begin():
        (await db.get(User, UUID(admin["id"]))).role = "viewer"
    source_http["wait"].set()
    await asyncio.wait_for(task, 5)
    async with database() as db:
        op = await db.get(Operation, UUID(state["verification"]["id"]))
        assert op.status == "held"
        row = await db.get(SourceConnection, "mam")
        assert decrypt_secrets(row.encrypted_secrets)["mam_id"] == "rotated-1"
        assert row.lease_token is None


async def test_interrupted_test_is_not_replayed_and_requires_new_session(
    client,
    admin,
    database,
    configured,
    source_http,
):
    scan, findings = await observe(client)
    plan = await preview(client, scan, change(findings["mam"], mam_id="first-fixture"))
    state = await save(client, plan)
    identifier = UUID(state["verification"]["id"])
    source_http["wait"] = asyncio.Event()
    task = asyncio.create_task(recovery_sources.verify(identifier))
    await asyncio.wait_for(source_http["entered"].wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with database() as db, db.begin():
        op = await db.get(Operation, identifier)
        op.payload = {
            **op.payload,
            "lease_until": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        }
        row = await db.get(SourceConnection, "mam")
        assert row.lease_token
        row.lease_until = datetime.now(UTC) - timedelta(seconds=1)
    await recovery_sources.verify(identifier)
    assert len(source_http["calls"]) == 1
    assert (await result(client, plan))["verification"]["status"] == "held"
    await work()  # Durable queue redelivery must also retain the held result.
    scan, findings = await observe(client)
    assert findings["mam"]["evidence"]["requires_current_session"]
    await preview(client, scan, change(findings["mam"]), expected=422)
    source_http["wait"] = None
    plan = await preview(client, scan, change(findings["mam"], mam_id="first-fixture"))
    await accept(client, plan)
    await work()
    assert (await result(client, plan))["verification"]["status"] == "completed"
    assert len(source_http["calls"]) == 2


async def test_source_preview_requires_csrf_and_rejects_mixed_kind_fields(
    client,
    admin,
    database,
    configured,
):
    scan, findings = await observe(client)
    choice = change(findings["mam"], mam_id="first-fixture")
    csrf = client.headers.pop("X-CSRF-Token")
    await preview(client, scan, choice, expected=403)
    client.headers["X-CSRF-Token"] = csrf
    for changes in (
        {"api_key": "wrong-kind"},
        {"proxy_username": "unpaired"},
        {"proxy_url": "http://proxy.test/path"},
        {"excluded_indexers": [1]},
    ):
        await preview(client, scan, {**choice, **changes}, expected=422)
    await preview(
        client, scan, change(findings["prowlarr"], api_key="has whitespace"), expected=422
    )
    await preview(client, scan, change(findings["prowlarr"], excluded_indexers=[-1]), expected=422)


async def test_pending_verification_blocks_other_reviews_and_duplicate_runs(
    client,
    admin,
    database,
    configured,
    source_http,
):
    from app.jobs.retry import ShelfRetry

    scan, findings = await observe(client)
    plan = await preview(client, scan, change(findings["mam"], mam_id="first-fixture"))
    state = await save(client, plan)
    assert (
        await client.post("/api/recovery/scans", headers={"Idempotency-Key": str(uuid4())})
    ).status_code == 409
    await preview(client, scan, change(findings["prowlarr"]), expected=409)
    source_http["wait"] = asyncio.Event()
    identifier = UUID(state["verification"]["id"])
    task = asyncio.create_task(recovery_sources.verify(identifier))
    await asyncio.wait_for(source_http["entered"].wait(), 5)
    with pytest.raises(ShelfRetry):
        await recovery_sources.verify(identifier)
    source_http["wait"].set()
    await asyncio.wait_for(task, 5)
    assert len(source_http["calls"]) == 1
    assert (await result(client, plan))["verification"]["status"] == "completed"


async def test_context_changes_during_test_hold_proof_but_preserve_rotation(
    client,
    admin,
    database,
    configured,
    source_http,
):
    scan, findings = await observe(client)
    plan = await preview(client, scan, change(findings["mam"], mam_id="first-fixture"))
    state = await save(client, plan)
    source_http["wait"] = asyncio.Event()
    task = asyncio.create_task(recovery_sources.verify(UUID(state["verification"]["id"])))
    await asyncio.wait_for(source_http["entered"].wait(), 5)
    async with database() as db, db.begin():
        (await db.get(SourceConnection, "prowlarr")).generation += 1
    source_http["wait"].set()
    await asyncio.wait_for(task, 5)
    assert (await result(client, plan))["verification"]["status"] == "held"
    async with database() as db:
        row = await db.get(SourceConnection, "mam")
        assert decrypt_secrets(row.encrypted_secrets)["mam_id"] == "rotated-1"


async def test_proxy_auth_change_requires_current_cookie_even_after_verification(
    client,
    admin,
    database,
    configured,
    source_http,
):
    scan, findings = await observe(client)
    plan = await preview(client, scan, change(findings["mam"], mam_id="first-fixture"))
    await accept(client, plan)
    await work()
    scan, findings = await observe(client)
    assert not findings["mam"]["evidence"]["requires_current_session"]
    await preview(client, scan, change(findings["mam"], clear_proxy_credentials=True), expected=422)
    await preview(
        client,
        scan,
        change(findings["mam"], proxy_username="other-user", proxy_password="other-password"),
        expected=422,
    )


async def test_preview_change_before_worker_never_applies_settings(
    client,
    admin,
    database,
    configured,
    source_http,
):
    scan, findings = await observe(client)
    plan = await preview(client, scan, change(findings["mam"], mam_id="first-fixture"))
    await accept(client, plan)
    async with database() as db, db.begin():
        row = await db.get(SourceConnection, "prowlarr")
        row.generation += 1
    await work()
    state = await result(client, plan)
    assert state["status"] == "held" and state["verification"] is None
    assert not source_http["calls"]
    async with database() as db:
        assert (await db.get(SourceConnection, "mam")).generation == 1


async def test_live_source_lease_is_not_cleared_by_new_cookie(
    client,
    admin,
    database,
    configured,
    source_http,
):
    async with database() as db, db.begin():
        row = await db.get(SourceConnection, "mam")
        row.lease_token, row.lease_until = uuid4(), datetime.now(UTC) + timedelta(minutes=1)
    scan, findings = await observe(client)
    await preview(client, scan, change(findings["mam"], mam_id="first-fixture"), expected=409)
    assert not source_http["calls"]
