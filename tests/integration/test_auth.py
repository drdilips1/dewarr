import asyncio

import httpx
import pytest
from sqlalchemy import func, select

from app.db.models import User

pytestmark = pytest.mark.integration


async def test_bootstrap_is_once_even_when_concurrent(client, database):
    body = {
        "username": "admin",
        "password": "a long test password",
        "display_name": "Test admin",
        "bootstrap_token": "test-only-bootstrap-token",
    }
    responses = await asyncio.gather(
        *[client.post("/api/auth/bootstrap", json=body) for _ in range(4)]
    )
    assert sorted(response.status_code for response in responses) == [201, 409, 409, 409]
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(User)) == 1


async def test_setup_token_and_origin_required(client):
    body = {
        "username": "admin",
        "password": "a long test password",
        "display_name": "Test admin",
        "bootstrap_token": "incorrect-bootstrap-token",
    }
    assert (await client.post("/api/auth/bootstrap", json=body)).status_code == 403
    body["bootstrap_token"] = "test-only-bootstrap-token"
    assert (
        await client.post(
            "/api/auth/bootstrap", json=body, headers={"Origin": "https://untrusted.invalid"}
        )
    ).status_code == 403


async def test_session_csrf_and_revocation(client, admin):
    response = await client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "password" not in response.text
    assert (
        await client.post("/api/auth/logout", headers={"X-CSRF-Token": "incorrect"})
    ).status_code == 403
    previous = client.cookies.get("book_session")
    assert (await client.post("/api/auth/logout")).status_code == 204
    client.cookies.set("book_session", previous)
    assert (await client.get("/api/auth/me")).status_code == 401
    client.cookies.clear()
    login = await client.post(
        "/api/auth/login",
        json={
            "username": "ADMIN",
            "password": "a long test password",
        },
    )
    assert login.status_code == 200
    assert client.cookies.get("book_session") != previous


async def test_viewer_cannot_administer(client, admin):
    assert (
        await client.post(
            "/api/auth/users",
            json={
                "username": "viewer",
                "display_name": "Reader",
                "role": "viewer",
                "password": "a long viewer password",
            },
        )
    ).status_code == 201
    from app.main import create_app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()),
        base_url="http://testserver",
        headers={"Origin": "http://testserver"},
    ) as viewer:
        login = await viewer.post(
            "/api/auth/login",
            json={
                "username": "viewer",
                "password": "a long viewer password",
            },
        )
        viewer.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        assert (await viewer.get("/api/auth/users")).status_code == 403
        assert (
            await viewer.post("/api/system/probe", headers={"Idempotency-Key": "viewer-probe"})
        ).status_code == 403


async def test_login_budget_persists_failed_requests(client, admin):
    for _ in range(15):
        response = await client.post(
            "/api/auth/login",
            json={
                "username": "unknown",
                "password": "a wrong long password",
            },
        )
        assert response.status_code == 401
    response = await client.post(
        "/api/auth/login",
        json={
            "username": "unknown",
            "password": "a wrong long password",
        },
    )
    assert response.status_code == 429
