# ruff: noqa: F401, F811
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text

from app.db.models import (
    AuditEvent,
    Integration,
    Library,
    LibraryGrant,
    LoginSession,
    User,
)
from app.domain import recovery_access as access
from app.domain import recovery_scans
from app.jobs.queue import recovery_queue
from app.security import encrypt_secrets, hash_password
from tests.integration.test_recovery_inventory import inventory_ready
from tests.integration.test_recovery_scan_workflow import begin, pause, report

pytestmark = pytest.mark.integration


@pytest.fixture
async def accounts(database, admin):
    async with database() as db, db.begin():
        reader = User(
            username="reader",
            display_name="Reader",
            password_hash=hash_password("test reader password"),
            role="member",
            active=True,
            can_automate=True,
        )
        disabled = User(
            username="returning",
            display_name="Returning reader",
            password_hash="private-hash",
            role="viewer",
            active=False,
            can_automate=False,
        )
        integration = Integration(
            kind="audiobookshelf",
            name="Household library",
            base_url="http://unused.invalid",
            encrypted_secrets=encrypt_secrets({"token": "private-secret"}),
            enabled=False,
        )
        db.add_all([reader, disabled, integration])
        await db.flush()
        library = Library(
            integration_id=integration.id,
            external_id="books",
            name="Household books",
            accessible=True,
        )
        second = Library(
            integration_id=integration.id,
            external_id="audio",
            name="Household audio",
            accessible=True,
        )
        db.add_all([library, second])
        await db.flush()
        db.add_all(
            [
                LibraryGrant(user_id=reader.id, library_id=library.id),
                LoginSession(
                    token_hash="saved-reader-session",
                    user_id=reader.id,
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                ),
            ]
        )
        return {
            "reader": reader.id,
            "disabled": disabled.id,
            "library": library.id,
            "second": second.id,
            "integration": integration.id,
        }


async def observe(client):
    scan = await begin(client)
    await recovery_scans.run(UUID(scan))
    data = await report(client, scan, domain="review")
    assert data["scan"]["state"] == "completed", data
    result = {}
    for row in data["items"]:
        if row["state"] in {"access-ready", "access-reviewed"}:
            detail = (await client.get(f"/api/recovery/scans/{scan}/findings/{row['id']}")).json()
            result[UUID(row["entity_id"])] = detail
    return scan, result


def change(finding, **kwargs):
    return {"finding_id": finding["id"], **finding["evidence"]["before"], **kwargs}


async def preview(client, scan, changes, key=None, expected=201):
    response = await client.post(
        "/api/recovery/access-reconciliations",
        headers={"Idempotency-Key": key or str(uuid4())},
        json={"scan_id": scan, "changes": changes},
    )
    assert response.status_code == expected, response.text
    return response.json()


async def accept(client, plan, key=None, expected=202):
    response = await client.post(
        f"/api/recovery/access-reconciliations/{plan['id']}/accept",
        headers={"Idempotency-Key": key or str(uuid4())},
        json={"revision": plan["revision"]},
    )
    assert response.status_code == expected, response.text
    return response.json()


async def outcome(client, plan):
    response = await client.get(f"/api/recovery/access-reconciliations/{plan['id']}")
    assert response.status_code == 200, response.text
    return response.json()


async def test_access_review_repairs_permissions_preserves_siblings_and_replays_once(
    client, admin, database, accounts
):
    await pause(database, admin)
    scan, findings = await observe(client)
    assert "private-hash" not in str(findings) and "private-secret" not in str(findings)
    body = [change(findings[accounts["reader"]], role="viewer", can_automate=False, library_ids=[])]
    plan = await preview(client, scan, body, key="access-preview-once")
    assert (await preview(client, scan, body, key="access-preview-once"))["id"] == plan["id"]
    await preview(
        client,
        scan,
        [change(findings[accounts["reader"]], active=False)],
        key="access-preview-once",
        expected=409,
    )
    await accept(client, plan, key="access-accept-once")
    queue = recovery_queue()
    async with queue.open_async():
        await queue.run_worker_async(wait=False, concurrency=1)
    result = await outcome(client, plan)
    assert result["status"] == "completed", result
    assert result["results"][0]["changed"] is True
    await accept(client, plan, key="access-accept-once")
    await access.run(UUID(plan["id"]))
    async with database() as db:
        user = await db.get(User, accounts["reader"])
        assert user.active and user.role == "viewer" and not user.can_automate
        assert not list(
            await db.scalars(select(LibraryGrant).where(LibraryGrant.user_id == user.id))
        )
        assert not await db.get(LoginSession, "saved-reader-session")
        assert (await db.get(User, accounts["disabled"])).active is False
        assert (
            len(
                list(
                    await db.scalars(
                        select(AuditEvent).where(AuditEvent.action == "recovery.access.reviewed")
                    )
                )
            )
            == 1
        )
        assert (
            await db.scalar(
                text(
                    "SELECT count(*) FROM book_queue.procrastinate_jobs "
                    "WHERE task_name NOT LIKE 'recovery.%'"
                )
            )
            == 0
        )
    assert (await client.get("/api/lists")).status_code == 423
    assert not (await client.get("/api/recovery")).json()["resume_available"]
    _, fresh = await observe(client)
    assert fresh[accounts["reader"]]["state"] == "access-reviewed"
    assert fresh[accounts["disabled"]]["state"] == "access-ready"
    async with database() as db, db.begin():
        (await db.get(User, accounts["reader"])).password_hash = "changed-identity"
    _, changed = await observe(client)
    assert changed[accounts["reader"]]["state"] == "access-ready"


@pytest.mark.parametrize("values", [{"active": False}, {"role": "member"}])
async def test_operator_cannot_remove_own_recovery_access(
    client, admin, database, accounts, values
):
    await pause(database, admin)
    scan, findings = await observe(client)
    await preview(client, scan, [change(findings[UUID(admin["id"])], **values)], expected=409)


async def test_unchanged_operator_can_confirm_without_losing_session(
    client, admin, database, accounts
):
    await pause(database, admin)
    scan, findings = await observe(client)
    plan = await preview(client, scan, [change(findings[UUID(admin["id"])])])
    await accept(client, plan)
    await access.run(UUID(plan["id"]))
    result = await outcome(client, plan)
    assert result["status"] == "completed" and not result["results"][0]["changed"]
    assert (await client.get("/api/auth/me")).status_code == 200


@pytest.mark.parametrize(
    "mutation", ["grant", "role", "automation", "identity", "operator", "connection"]
)
async def test_changed_context_holds_access_review(client, admin, database, accounts, mutation):
    await pause(database, admin)
    scan, findings = await observe(client)
    plan = await preview(client, scan, [change(findings[accounts["reader"]], active=False)])
    await accept(client, plan)
    async with database() as db, db.begin():
        user = await db.get(User, accounts["reader"])
        if mutation == "grant":
            db.add(LibraryGrant(user_id=user.id, library_id=accounts["second"]))
        elif mutation == "role":
            user.role = "admin"
        elif mutation == "automation":
            user.can_automate = False
        elif mutation == "identity":
            user.password_hash = "identity-changed"
        elif mutation == "operator":
            (await db.get(User, UUID(admin["id"]))).can_automate = False
        else:
            (await db.get(Integration, accounts["integration"])).credential_generation += 1
    await access.run(UUID(plan["id"]))
    assert (await outcome(client, plan))["status"] == "held"
    async with database() as db:
        assert (await db.get(User, accounts["reader"])).active
        assert not list(
            await db.scalars(
                select(AuditEvent).where(AuditEvent.action == "recovery.access.reviewed")
            )
        )


async def test_access_batch_rolls_back_all_changes_and_sessions(
    client, admin, database, accounts, monkeypatch
):
    await pause(database, admin)
    scan, findings = await observe(client)
    plan = await preview(
        client,
        scan,
        [
            change(findings[accounts["reader"]], active=False),
            change(findings[accounts["disabled"]], active=True),
        ],
    )
    await accept(client, plan)
    original = access.apply
    count = 0

    async def fail_second(*args):
        nonlocal count
        count += 1
        result = await original(*args)
        if count == 2:
            raise RuntimeError("injected transaction failure")
        return result

    monkeypatch.setattr(access, "apply", fail_second)
    await access.run(UUID(plan["id"]))
    assert (await outcome(client, plan))["status"] == "held"
    async with database() as db:
        assert (await db.get(User, accounts["reader"])).active
        assert not (await db.get(User, accounts["disabled"])).active
        assert await db.get(LoginSession, "saved-reader-session")
        assert await db.get(LibraryGrant, (accounts["reader"], accounts["library"]))
        assert not list(
            await db.scalars(
                select(AuditEvent).where(AuditEvent.action == "recovery.access.reviewed")
            )
        )


@pytest.mark.parametrize("changed", ["none", "credentials", "inventory"])
async def test_new_grants_require_current_reconciled_backend_inventory(
    client, admin, database, inventory_ready, changed
):
    from app.domain import recovery_inventory
    from tests.integration.test_recovery_inventory import accept as inventory_accept
    from tests.integration.test_recovery_inventory import preview as inventory_preview

    ready = inventory_ready
    async with database() as db, db.begin():
        user = User(
            username="new-member",
            display_name="New member",
            password_hash="private",
            role="member",
            active=True,
            can_automate=False,
        )
        db.add(user)
        await db.flush()
        user_id = user.id
    scan, findings = await observe(client)
    await preview(
        client,
        scan,
        [change(findings[user_id], library_ids=[str(ready["library_id"])])],
        expected=409,
    )
    current = await report(client, scan, domain="library")
    finding = next(row for row in current["items"] if row["state"] == "inventory-ready")
    plan = await inventory_preview(client, {"scan_id": scan, "finding_id": finding["id"]})
    assert (await inventory_accept(client, plan)).status_code == 202
    await recovery_inventory.run(UUID(plan["id"]))
    if changed == "credentials":
        async with database() as db, db.begin():
            (await db.get(Integration, ready["integration_id"])).credential_generation += 1
    elif changed == "inventory":
        ready["fixture"].items["new"]["media"]["metadata"]["title"] = "Changed current inventory"
    scan, findings = await observe(client)
    changes = [change(findings[user_id], library_ids=[str(ready["library_id"])])]
    if changed != "none":
        await preview(client, scan, changes, expected=409)
        return
    plan = await preview(client, scan, changes)
    await accept(client, plan)
    await access.run(UUID(plan["id"]))
    assert (await outcome(client, plan))["status"] == "completed"
    async with database() as db:
        assert await db.get(LibraryGrant, (user_id, ready["library_id"]))


async def test_access_api_rejects_duplicate_invalid_and_stale_acceptance(
    client, admin, database, accounts
):
    await pause(database, admin)
    scan, findings = await observe(client)
    member = change(findings[accounts["reader"]])
    await preview(client, scan, [member, member], expected=422)
    await preview(client, scan, [dict(member, role="viewer", can_automate=True)], expected=422)
    await preview(client, scan, [dict(member, library_ids=[str(uuid4())])], expected=409)
    plan = await preview(client, scan, [member])
    wrong = deepcopy(plan)
    wrong["revision"] = "0" * 64
    await accept(client, wrong, expected=409)
    csrf = client.headers.pop("X-CSRF-Token")
    await accept(client, plan, expected=403)
    client.headers["X-CSRF-Token"] = csrf
    await begin(client)
    await accept(client, plan, expected=409)


async def test_explicit_reenable_and_disable_are_atomic_without_resuming_work(
    client, admin, database, accounts
):
    await pause(database, admin)
    scan, findings = await observe(client)
    plan = await preview(
        client,
        scan,
        [
            change(findings[accounts["reader"]], active=False),
            change(findings[accounts["disabled"]], active=True, role="member", can_automate=True),
        ],
    )
    await accept(client, plan)
    await access.run(UUID(plan["id"]))
    result = await outcome(client, plan)
    assert result["status"] == "completed" and len(result["results"]) == 2
    async with database() as db:
        assert not (await db.get(User, accounts["reader"])).active
        returned = await db.get(User, accounts["disabled"])
        assert returned.active and returned.role == "member" and returned.can_automate
        assert await db.get(LibraryGrant, (accounts["reader"], accounts["library"]))
        assert not await db.get(LoginSession, "saved-reader-session")
        assert (
            len(
                list(
                    await db.scalars(
                        select(AuditEvent).where(AuditEvent.action == "recovery.access.reviewed")
                    )
                )
            )
            == 2
        )
    state = (await client.get("/api/recovery")).json()
    assert state["paused"] and not state["resume_available"]
    assert (await client.get("/api/lists")).status_code == 423
