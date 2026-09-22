# ruff: noqa: F811
import asyncio
from uuid import UUID, uuid4

import httpx
import pytest

from app.domain import list_requests
from tests.integration.test_acquisition import body, catalog, request  # noqa: F401

pytestmark = pytest.mark.integration


async def session_for(username, password):
    from app.main import create_app

    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()),
        base_url="http://testserver",
        headers={"Origin": "http://testserver"},
    )
    login = await client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert login.status_code == 200, login.text
    client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
    return client


async def test_request_waits_for_approval_unless_the_account_can_download(client, admin, catalog):
    created = await client.post(
        "/api/auth/users",
        json={
            "username": "family",
            "display_name": "Family Reader",
            "password": "a long family password",
            "role": "requester",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["access_label"] == "Requester"
    assert created.json()["role"] == "member"
    assert "auto_approve" not in created.json()["permissions"]
    assert "request" in created.json()["permissions"]

    family = await session_for("family", "a long family password")
    try:
        saved = await request(family, body(catalog, "audio"))
        pending = saved["request"]
        assert pending["approval_status"] == "pending"
        assert pending["targets"][0]["state"] == "paused"
        assert pending["targets"][0]["next_action"] == "none"
        assert pending["targets"][0]["message"] == "Waiting for approval"
        search = await family.post(
            "/api/catalog/works/" + str(catalog["work"]) + "/source-searches",
            json={"request_id": pending["id"], "medium": "audio"},
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert search.status_code == 403, search.text

        queue = (await client.get("/api/requests?pending_only=true")).json()
        assert queue["total"] == 1
        assert queue["items"][0]["owner_name"] == "Family Reader"
        assert queue["items"][0]["can_decide"] is True
        denied = await family.get("/api/requests?pending_only=true")
        assert denied.status_code == 403

        declined = await client.post(
            f"/api/requests/{pending['id']}/decision",
            json={"status": "declined", "expected_status": "pending", "note": "Not this one"},
            headers={"Idempotency-Key": "decline-family-request"},
        )
        assert declined.status_code == 200, declined.text
        assert declined.json()["request"]["approval_status"] == "declined"
        assert declined.json()["download_started"] is False

        again = await request(family, body(catalog, "audio"), key="family-asks-again")
        assert again["request"]["id"] == pending["id"]
        assert again["request"]["approval_status"] == "pending"

        approved = await client.post(
            f"/api/requests/{pending['id']}/decision",
            json={"status": "approved", "expected_status": "pending", "download": False},
            headers={"Idempotency-Key": "approve-family-request"},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["request"]["approval_status"] == "approved"
        assert approved.json()["request"]["targets"][0]["next_action"] == "none"
        assert approved.json()["request"]["can_start_download"] is True
        ready = (await client.get("/api/requests?download_ready=true")).json()
        assert ready["total"] == 1
        assert ready["items"][0]["id"] == pending["id"]
        assert ready["items"][0]["can_start_download"] is True
        assert (await family.get("/api/requests?download_ready=true")).status_code == 403
        still_blocked = await family.post(
            "/api/catalog/works/" + str(catalog["work"]) + "/source-searches",
            json={"request_id": pending["id"], "medium": "audio"},
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert still_blocked.status_code == 403

        own = await request(client, body(catalog, "audio"), key="admin-downloads")
        assert own["request"]["approval_status"] == "approved"
        assert own["request"]["targets"][0]["next_action"] == "search"
    finally:
        await family.aclose()


async def test_custom_role_updates_members_and_cannot_remove_the_last_administrator(client, admin):
    catalog = (await client.get("/api/auth/access")).json()
    assert {item["id"] for item in catalog["presets"]} >= {
        "admin",
        "member",
        "requester",
        "approver",
        "viewer",
    }
    role = await client.post(
        "/api/auth/roles",
        json={
            "name": "Family",
            "description": "Ask for audiobooks",
            "permissions": ["request", "request_audio"],
        },
    )
    assert role.status_code == 201, role.text
    role_id = role.json()["id"]
    created = await client.post(
        "/api/auth/users",
        json={
            "username": "cousin",
            "display_name": "Cousin",
            "password": "a long cousin password",
            "permissions": ["request", "request_audio"],
        },
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]
    assigned = await client.put(
        f"/api/auth/users/{user_id}/permissions",
        json={
            "permissions": ["request", "request_audio"],
            "role_id": role_id,
            "expected_permissions": created.json()["permissions"],
        },
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["access_label"] == "Family"
    revised = await client.put(
        f"/api/auth/roles/{role_id}",
        json={
            "name": "Family",
            "description": "Ask for either medium",
            "permissions": ["request", "request_ebook", "request_audio"],
        },
    )
    assert revised.status_code == 200, revised.text
    accounts = (await client.get("/api/auth/users")).json()
    cousin = next(user for user in accounts if user["id"] == user_id)
    assert "request_ebook" in cousin["permissions"]
    demote = await client.put(
        f"/api/auth/users/{admin['id']}/permissions",
        json={
            "permissions": ["request"],
            "expected_permissions": next(
                user["permissions"] for user in accounts if user["id"] == admin["id"]
            ),
        },
    )
    assert demote.status_code == 409


async def test_list_requests_wait_in_the_approval_queue(client, admin, catalog):
    created = await client.post(
        "/api/auth/users",
        json={
            "username": "shelf",
            "display_name": "Shelf Reader",
            "password": "a long shelf password",
            "role": "requester",
        },
    )
    assert created.status_code == 201, created.text
    family = await session_for("shelf", "a long shelf password")
    try:
        shelf = await family.post("/api/lists", json={"name": "Waiting shelf"})
        assert shelf.status_code == 201, shelf.text
        shelf_id = shelf.json()["id"]
        added = await family.post(
            f"/api/lists/{shelf_id}/entries", json={"work_id": str(catalog["work"])}
        )
        assert added.status_code == 204, added.text
        plan = await family.post(
            f"/api/lists/{shelf_id}/requests/preview",
            json={
                "work_ids": [str(catalog["work"])],
                "specification": {"mode": "audio"},
            },
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert plan.status_code == 200, plan.text
        submitted = await family.post(f"/api/lists/{shelf_id}/requests/{plan.json()['id']}/submit")
        assert submitted.status_code == 202, submitted.text
        await list_requests.run(UUID(plan.json()["id"]))
        detail = await family.get(f"/api/lists/{shelf_id}/requests/{plan.json()['id']}")
        assert detail.status_code == 200, detail.text
        assert "sent it for approval" in detail.json()["message"]
        assert detail.json()["records"][0]["targets"][0]["message"] == "Waiting for approval"
        queue = (await client.get("/api/requests?pending_only=true")).json()
        assert queue["total"] == 1
        waiting = queue["items"][0]
        assert waiting["owner_name"] == "Shelf Reader"
        assert waiting["approval_status"] == "pending"
        assert waiting["can_decide"] is True
        assert any(reason["kind"] == "list" for reason in waiting["reasons"])
        approved = await client.post(
            f"/api/requests/{waiting['id']}/decision",
            json={"status": "approved", "expected_status": "pending", "download": False},
            headers={"Idempotency-Key": "approve-shelf-request"},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["request"]["approval_status"] == "approved"
        assert (await client.get("/api/requests?pending_only=true")).json()["total"] == 0
    finally:
        await family.aclose()


async def test_user_manager_cannot_widen_their_own_access_or_edit_administrators(client, admin):
    created = await client.post(
        "/api/auth/users",
        json={
            "username": "steward",
            "display_name": "Steward",
            "password": "a long steward password",
            "permissions": ["manage_users", "request"],
        },
    )
    assert created.status_code == 201, created.text
    steward = await session_for("steward", "a long steward password")
    try:
        widened = await steward.put(
            f"/api/auth/users/{created.json()['id']}/permissions",
            json={
                "permissions": ["manage_users", "request", "auto_approve"],
                "expected_permissions": created.json()["permissions"],
            },
        )
        assert widened.status_code == 403, widened.text
        demoted = await steward.put(
            f"/api/auth/users/{admin['id']}/permissions",
            json={
                "permissions": ["request"],
                "expected_permissions": admin["permissions"],
            },
        )
        assert demoted.status_code == 403, demoted.text
        role = await steward.post(
            "/api/auth/roles",
            json={"name": "Downloaders", "permissions": ["request", "auto_approve"]},
        )
        assert role.status_code == 403, role.text
        reader = await steward.post(
            "/api/auth/users",
            json={
                "username": "reader",
                "display_name": "Reader",
                "password": "a long reader password",
                "permissions": ["request"],
            },
        )
        assert reader.status_code == 201, reader.text
    finally:
        await steward.aclose()


async def test_one_medium_cannot_request_both_formats(client, admin, catalog):
    created = await client.post(
        "/api/auth/users",
        json={
            "username": "ebookonly",
            "display_name": "Ebook Only",
            "password": "a long ebook password",
            "permissions": ["request_ebook"],
        },
    )
    assert created.status_code == 201, created.text
    reader = await session_for("ebookonly", "a long ebook password")
    try:
        both = await reader.post(
            "/api/requests",
            json=body(catalog, "both"),
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert both.status_code == 403, both.text
        assert "audiobook" in both.text.lower()
        either = await reader.post(
            "/api/requests",
            json=body(catalog, "either", preferred_medium="audio"),
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert either.status_code == 403, either.text
        saved = await request(reader, body(catalog, "ebook"))
        assert saved["request"]["approval_status"] == "pending"
    finally:
        await reader.aclose()


async def test_failed_approval_download_keeps_the_request_pending(client, admin, catalog):
    created = await client.post(
        "/api/auth/users",
        json={
            "username": "held",
            "display_name": "Held Reader",
            "password": "a long held password",
            "role": "requester",
        },
    )
    assert created.status_code == 201, created.text
    reader = await session_for("held", "a long held password")
    try:
        saved = await request(reader, body(catalog, "audio"))
        failed = await client.post(
            f"/api/requests/{saved['request']['id']}/decision",
            json={"status": "approved", "expected_status": "pending", "download": True},
            headers={"Idempotency-Key": "approval-download-fails"},
        )
        assert failed.status_code == 200, failed.text
        assert failed.json()["download_started"] is False
        assert failed.json()["download_message"]
        assert failed.json()["request"]["approval_status"] == "pending"
        assert failed.json()["request"]["can_decide"] is True
        queue = (await client.get("/api/requests?pending_only=true")).json()
        assert queue["total"] == 1
        assert (await client.get("/api/requests?download_ready=true")).json()["total"] == 0
    finally:
        await reader.aclose()


async def test_two_administrators_cannot_remove_the_last_admin_together(client, admin, database):
    from sqlalchemy import func, select

    from app.db.models import User

    created = await client.post(
        "/api/auth/users",
        json={
            "username": "secondadmin",
            "display_name": "Second Admin",
            "password": "a long second password",
            "role": "admin",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["role"] == "admin"
    other = await session_for("secondadmin", "a long second password")
    try:
        accounts = (await client.get("/api/auth/users")).json()
        first = next(user for user in accounts if user["id"] == admin["id"])
        second = next(user for user in accounts if user["id"] == created.json()["id"])

        async def demote(actor, target):
            return await actor.put(
                f"/api/auth/users/{target['id']}/permissions",
                json={
                    "permissions": ["request"],
                    "expected_permissions": target["permissions"],
                },
            )

        left, right = await asyncio.gather(demote(client, second), demote(other, first))
        assert {left.status_code, right.status_code} <= {200, 403, 409}
        assert 200 in {left.status_code, right.status_code}
        async with database() as db:
            remaining = await db.scalar(
                select(func.count())
                .select_from(User)
                .where(User.role == "admin", User.active.is_(True))
            )
        assert remaining == 1
    finally:
        await other.aclose()
