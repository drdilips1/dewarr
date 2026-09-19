# ruff: noqa: F401, F811
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text

from app.config import get_settings
from app.db.models import AuditEvent, Integration, Library, Operation, User
from app.domain import recovery_connections as connections
from app.domain import recovery_observers, recovery_scans
from app.jobs.queue import recovery_queue
from app.security import decrypt_secrets, encrypt_secrets
from tests.contracts.test_audiobookshelf import ABSFixture
from tests.integration.test_recovery_scan_workflow import begin, pause, report
from tests.unit.test_recovery_census_adapter import CensusServer

pytestmark = pytest.mark.integration


@pytest.fixture
async def configured(database, admin, monkeypatch, tmp_path):
    root = tmp_path / "current-downloads"
    monkeypatch.setattr(get_settings(), "import_sources", {"downloads": root})
    abs_server, qbit_server, logins = ABSFixture({}), CensusServer([]), []

    def abs_client(endpoint, token):
        logins.append(("abs", endpoint, token))
        return abs_server.client(endpoint, token)

    def qbit_client(endpoint, username, password):
        logins.append(("qbit", endpoint, username, password))
        return qbit_server.client(endpoint, username, password)

    for module in (connections, recovery_observers):
        monkeypatch.setattr(module, "Audiobookshelf", abs_client)
        monkeypatch.setattr(module, "QbitClient", qbit_client)
    async with database() as db, db.begin():
        abs_row = Integration(
            kind="audiobookshelf",
            name="Saved ABS",
            credential_generation=1,
            base_url="http://saved-abs.test/abs",
            enabled=False,
            config={"public_url": "https://books.example.test"},
            encrypted_secrets=encrypt_secrets({"token": "old-private-abs-token"}),
        )
        qbit = Integration(
            kind="qbittorrent",
            name="Saved qBit",
            credential_generation=1,
            base_url="http://saved-qbit.test/qbit",
            enabled=False,
            encrypted_secrets=encrypt_secrets(
                {"username": "old-private-user", "password": "old-private-password"}
            ),
            config={
                "saved_extension": {"preserve": True},
                "save_path": "/downloads/books",
                "category": "book-search",
                "mappings": [
                    {
                        "download_root": "/downloads",
                        "source_key": "downloads",
                        "source_path": str(tmp_path / "restored-downloads"),
                    }
                ],
            },
        )
        db.add_all([abs_row, qbit])
        await db.flush()
        library = Library(
            integration_id=abs_row.id,
            external_id="library-one",
            name="Saved library",
            accessible=True,
        )
        db.add(library)
        await db.flush()
        identifiers = {"abs": abs_row.id, "qbit": qbit.id, "library": library.id}
    await pause(database, admin)
    return {
        **identifiers,
        "root": root,
        "logins": logins,
        "abs_server": abs_server,
        "qbit_server": qbit_server,
    }


async def observe(client):
    scan = await begin(client)
    await recovery_scans.run(UUID(scan))
    data = await report(client, scan, domain="review")
    assert data["scan"]["state"] == "completed", data
    findings = {}
    for item in data["items"]:
        if item["state"] in {"connection-ready", "connection-reviewed"}:
            detail = (await client.get(f"/api/recovery/scans/{scan}/findings/{item['id']}")).json()
            findings[UUID(item["entity_id"])] = detail
    return scan, findings


def change(finding, **changes):
    before = deepcopy(finding["evidence"]["before"])
    before.pop("has_credentials")
    for mapping in before.get("mappings", []):
        mapping.pop("worker_path")
    return {"finding_id": finding["id"], **before, **changes}


def repairs(configured, findings):
    return [
        change(
            findings[configured["abs"]],
            name="Current ABS",
            base_url="http://current-abs.test/abs",
            token="private-abs-token",
            enabled=True,
        ),
        change(
            findings[configured["qbit"]],
            name="Current qBit",
            base_url="http://current-qbit.test/qbit",
            username="current-private-user",
            password="current-private-password",
            save_path="/downloads/recovered",
            enabled=True,
        ),
    ]


async def preview(client, scan, changes, key=None, expected=201):
    response = await client.post(
        "/api/recovery/connection-reconciliations",
        headers={"Idempotency-Key": key or str(uuid4())},
        json={"scan_id": scan, "changes": changes},
    )
    assert response.status_code == expected, response.text
    return response.json()


async def accept(client, plan, key=None, expected=202):
    response = await client.post(
        f"/api/recovery/connection-reconciliations/{plan['id']}/accept",
        headers={"Idempotency-Key": key or str(uuid4())},
        json={"revision": plan["revision"]},
    )
    assert response.status_code == expected, response.text
    return response.json()


async def run(client, plan):
    queue = recovery_queue()
    async with queue.open_async():
        await queue.run_worker_async(wait=False, concurrency=1)
    response = await client.get(f"/api/recovery/connection-reconciliations/{plan['id']}")
    assert response.status_code == 200, response.text
    return response.json()


async def test_connection_repair_tests_fresh_credentials_and_paths_without_activation(
    client, admin, database, configured
):
    scan, findings = await observe(client)
    assert not configured["logins"]
    body = repairs(configured, findings)
    plan = await preview(client, scan, body, key="repair-connection-once")
    assert (await preview(client, scan, body, key="repair-connection-once"))["id"] == plan["id"]
    changed = deepcopy(body)
    changed[1]["password"] = "different-private-password"
    await preview(client, scan, changed, key="repair-connection-once", expected=409)
    serialized = str(plan) + str(findings)
    assert "private-password" not in serialized and "private-abs-token" not in serialized
    assert "encrypted_secrets" not in serialized and "credential_change" not in serialized
    after = next(item["after"] for item in plan["items"] if item["after"]["kind"] == "qbittorrent")
    assert after["mappings"][0]["worker_path"] == str(configured["root"])
    assert after["save_path"] == "/downloads/recovered"
    assert not configured["logins"], "Preview must not send credentials to the proposed endpoint"
    async with database() as db:
        stored = await db.get(Operation, UUID(plan["id"]))
        assert "private-password" not in str(stored.payload)
        for item in stored.payload["items"]:
            assert item["draft"]["encrypted_secrets"]
    await accept(client, plan, key="accept-connection-once")
    result = await run(client, plan)
    assert result["status"] == "completed", result
    assert all(item["state"] == "tested" and item["changed"] for item in result["results"])
    assert (
        "qbit",
        "http://current-qbit.test/qbit",
        "current-private-user",
        "current-private-password",
    ) in configured["logins"]
    assert ("abs", "http://current-abs.test/abs", "private-abs-token") in configured["logins"]
    calls = deepcopy(configured["logins"])
    await accept(client, plan, key="accept-connection-once")
    await connections.run(UUID(plan["id"]))
    assert configured["logins"] == calls
    async with database() as db:
        abs_row, qbit = (
            await db.get(Integration, configured["abs"]),
            await db.get(Integration, configured["qbit"]),
        )
        assert abs_row.enabled and qbit.enabled and qbit.status == "connected"
        assert abs_row.credential_generation == qbit.credential_generation == 2
        assert decrypt_secrets(qbit.encrypted_secrets)["password"] == "current-private-password"
        assert not (await db.get(Library, configured["library"])).accessible
        audits = list(
            await db.scalars(
                select(AuditEvent).where(AuditEvent.action == "recovery.connection.reviewed")
            )
        )
        assert len(audits) == 2 and "private-password" not in str([a.detail for a in audits])
        jobs = list(await db.scalars(text("SELECT task_name FROM book_queue.procrastinate_jobs")))
        assert set(jobs) <= {"recovery.scan", "recovery.connections"}
    assert (await client.get("/api/lists")).status_code == 423
    assert (await client.get("/api/recovery")).json()["resume_available"] is False
    _, current = await observe(client)
    assert all(f["state"] == "connection-reviewed" for f in current.values())
    assert all(
        method == "GET" or path.endswith("auth/login")
        for method, path in configured["qbit_server"].calls
    )
    assert all("scan" not in path for path in configured["abs_server"].calls)


@pytest.mark.parametrize("kind", ["abs", "qbit"])
async def test_changed_endpoint_never_reuses_restored_credentials(client, configured, kind):
    scan, findings = await observe(client)
    await preview(
        client,
        scan,
        [change(findings[configured[kind]], base_url="http://different.test", enabled=False)],
        expected=422,
    )
    assert not configured["logins"]


async def test_disabling_missing_mount_preserves_evidence_without_network_test(
    client, database, configured, monkeypatch
):
    monkeypatch.setattr(get_settings(), "import_sources", {})
    scan, findings = await observe(client)
    plan = await preview(
        client, scan, [change(findings[configured["qbit"]], name="Unavailable qBit")]
    )
    await accept(client, plan)
    result = await run(client, plan)
    assert result["status"] == "completed" and result["results"][0]["state"] == "disabled"
    assert not configured["logins"]
    async with database() as db:
        row = await db.get(Integration, configured["qbit"])
        assert not row.enabled and row.config["mappings"][0]["source_key"] == "downloads"
        assert row.config["save_path"] == "/downloads/books"
        assert row.config["saved_extension"] == {"preserve": True}


async def test_unchanged_disabled_connection_confirmation_preserves_generation(
    client, database, configured
):
    scan, findings = await observe(client)
    plan = await preview(client, scan, [change(findings[configured["qbit"]])])
    await accept(client, plan)
    result = await run(client, plan)
    assert result["status"] == "completed" and result["results"][0]["changed"] is False
    async with database() as db:
        assert (await db.get(Integration, configured["qbit"])).credential_generation == 1


@pytest.mark.parametrize("mutation", ["credentials", "settings", "operator", "roots"])
async def test_changed_context_holds_accepted_connection_repair(
    client, admin, database, configured, monkeypatch, tmp_path, mutation
):
    scan, findings = await observe(client)
    plan = await preview(client, scan, repairs(configured, findings))
    await accept(client, plan)
    if mutation == "roots":
        monkeypatch.setattr(get_settings(), "import_sources", {"downloads": tmp_path / "new-root"})
    else:
        async with database() as db, db.begin():
            row = await db.get(Integration, configured["qbit"])
            if mutation == "credentials":
                row.encrypted_secrets = encrypt_secrets(
                    {"username": "another", "password": "another"}
                )
            elif mutation == "settings":
                row.config = {**row.config, "category": "changed"}
            else:
                (await db.get(User, UUID(admin["id"]))).can_automate = False
    result = await run(client, plan)
    assert result["status"] == "held", result
    assert not configured["logins"]
    async with database() as db:
        assert not (await db.get(Integration, configured["abs"])).enabled
        assert not list(
            await db.scalars(
                select(AuditEvent).where(AuditEvent.action == "recovery.connection.reviewed")
            )
        )


async def test_remote_test_failure_leaves_all_settings_unchanged(
    client, database, configured, monkeypatch
):
    from app.adapters.contracts import AdapterError, FailureKind

    scan, findings = await observe(client)
    plan = await preview(client, scan, repairs(configured, findings))

    def fail(*args, **kwargs):
        raise AdapterError(FailureKind.AUTHENTICATION, "Current authentication failed")

    monkeypatch.setattr(connections, "QbitClient", fail)
    await accept(client, plan)
    result = await run(client, plan)
    assert result["status"] == "held" and "authentication" in result["message"]
    async with database() as db:
        for name in ("abs", "qbit"):
            row = await db.get(Integration, configured[name])
            assert row.credential_generation == 1 and not row.enabled


async def test_second_connection_apply_failure_rolls_back_first_and_audit(
    client, database, configured, monkeypatch
):
    scan, findings = await observe(client)
    plan = await preview(client, scan, repairs(configured, findings))
    original, applied = connections.apply, []

    async def fail_second(db, review, item, current):
        applied.append(item["integration_id"])
        if len(applied) == 2:
            raise RuntimeError("synthetic second-item failure")
        return await original(db, review, item, current)

    monkeypatch.setattr(connections, "apply", fail_second)
    await accept(client, plan)
    result = await run(client, plan)
    assert result["status"] == "held" and len(applied) == 2
    async with database() as db:
        for name in ("abs", "qbit"):
            row = await db.get(Integration, configured[name])
            assert row.credential_generation == 1 and not row.enabled
        assert (await db.get(Library, configured["library"])).accessible
        assert not list(
            await db.scalars(
                select(AuditEvent).where(AuditEvent.action == "recovery.connection.reviewed")
            )
        )


async def test_connection_preview_validates_paths_kinds_secrets_and_exact_authority(
    client, database, configured
):
    scan, findings = await observe(client)
    valid = repairs(configured, findings)
    for replacement in (
        {"username": None},
        {"save_path": "/outside/downloads"},
        {"enabled": False, "save_path": "/outside/downloads"},
        {"mappings": [{"download_root": "/downloads", "source_key": "unknown"}]},
        {"token": "wrong-kind-private-token"},
        {"base_url": "http://user:private-password@invalid.test"},
    ):
        response = await preview(client, scan, [{**valid[1], **replacement}], expected=422)
        assert "private-password" not in str(response) and "wrong-kind-private-token" not in str(
            response
        )
    plan = await preview(client, scan, valid)
    await accept(client, {**plan, "revision": "0" * 64}, expected=409)
    no_csrf = await client.post(
        f"/api/recovery/connection-reconciliations/{plan['id']}/accept",
        headers={"Idempotency-Key": str(uuid4()), "X-CSRF-Token": "incorrect"},
        json={"revision": plan["revision"]},
    )
    assert no_csrf.status_code == 403
    async with database() as db:
        assert (await db.get(Operation, UUID(plan["id"]))).status == "prepared"
    await observe(client)
    await accept(client, plan, expected=409)


async def test_duplicate_downloader_endpoint_is_rejected_before_any_network_call(
    client, database, configured
):
    async with database() as db, db.begin():
        source = await db.get(Integration, configured["qbit"])
        db.add(
            Integration(
                kind="qbittorrent",
                name="Another downloader",
                base_url="http://another-qbit.test",
                enabled=False,
                config=deepcopy(source.config),
                encrypted_secrets=source.encrypted_secrets,
            )
        )
    scan, findings = await observe(client)
    body = repairs(configured, findings)[1]
    body["base_url"] = "http://another-qbit.test"
    await preview(client, scan, [body], expected=409)
    assert not configured["logins"]


async def test_root_change_after_successful_remote_checks_prevents_commit(
    client, database, configured, monkeypatch, tmp_path
):
    scan, findings = await observe(client)
    plan = await preview(client, scan, repairs(configured, findings))
    original = connections.read_current

    async def changed_after_read(*args):
        current = await original(*args)
        monkeypatch.setattr(get_settings(), "import_sources", {"downloads": tmp_path / "moved"})
        return current

    monkeypatch.setattr(connections, "read_current", changed_after_read)
    await accept(client, plan)
    result = await run(client, plan)
    assert result["status"] == "held" and len(configured["logins"]) == 2
    async with database() as db:
        for name in ("abs", "qbit"):
            row = await db.get(Integration, configured[name])
            assert row.credential_generation == 1 and not row.enabled


async def test_enabling_without_saved_credentials_requires_explicit_replacement(
    client, database, configured
):
    async with database() as db, db.begin():
        (await db.get(Integration, configured["abs"])).encrypted_secrets = ""
    scan, findings = await observe(client)
    await preview(client, scan, [change(findings[configured["abs"]], enabled=True)], expected=422)
    plan = await preview(
        client, scan, [change(findings[configured["abs"]], enabled=True, token="private-abs-token")]
    )
    await accept(client, plan)
    assert (await run(client, plan))["status"] == "completed"


async def test_unchanged_implicit_public_url_does_not_invalidate_library(
    client, database, configured
):
    async with database() as db, db.begin():
        (await db.get(Integration, configured["abs"])).config = {}
    scan, findings = await observe(client)
    plan = await preview(client, scan, [change(findings[configured["abs"]])])
    await accept(client, plan)
    result = await run(client, plan)
    assert result["status"] == "completed" and result["results"][0]["changed"] is False
    async with database() as db:
        row = await db.get(Integration, configured["abs"])
        assert row.credential_generation == 1 and row.config == {}
        assert (await db.get(Library, configured["library"])).accessible
