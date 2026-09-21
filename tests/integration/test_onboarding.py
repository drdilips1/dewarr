import pytest

pytestmark = pytest.mark.integration


async def test_new_account_progress_persists_through_sign_in(client, admin):
    assert admin["onboarding_status"] == "pending"
    initial = await client.get("/api/setup/onboarding")
    assert initial.json() == {"status": "pending", "step": 0, "skipped": []}
    progress = {"status": "deferred", "step": 3, "skipped": [1, 2]}
    assert (await client.put("/api/setup/onboarding", json=progress)).json() == progress
    assert (await client.get("/api/auth/me")).json()["user"]["onboarding_status"] == "deferred"
    await client.post("/api/auth/logout")
    response = await client.post(
        "/api/auth/login", json={"username": "admin", "password": "a long test password"}
    )
    assert response.json()["user"]["onboarding_status"] == "deferred"
    assert (await client.get("/api/setup/onboarding")).json() == progress


@pytest.mark.parametrize("status", ["completed", "skipped"])
async def test_setup_can_be_dismissed_without_connections(client, admin, status):
    response = await client.put("/api/setup/onboarding", json={"status": status, "step": 0})
    assert response.status_code == 200
    assert (await client.get("/api/auth/me")).json()["user"]["onboarding_status"] == status
    assert (await client.get("/api/integrations")).json() == []


async def test_progress_belongs_to_current_user(client, admin):
    response = await client.post(
        "/api/auth/users",
        json={
            "username": "viewer",
            "display_name": "Viewer",
            "password": "a separate long password",
            "role": "viewer",
        },
    )
    assert response.status_code == 201
    await client.put("/api/setup/onboarding", json={"status": "completed"})
    await client.post("/api/auth/logout")
    response = await client.post(
        "/api/auth/login", json={"username": "viewer", "password": "a separate long password"}
    )
    assert response.json()["user"]["onboarding_status"] == "pending"
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    assert (
        await client.put("/api/setup/onboarding", json={"status": "skipped"})
    ).status_code == 200
    assert (await client.get("/api/setup/readiness")).status_code == 403


@pytest.mark.parametrize(
    "body", [{"status": "unknown"}, {"step": 7}, {"skipped": [-1]}, {"skipped": [7]}]
)
async def test_progress_validation(client, admin, body):
    assert (await client.put("/api/setup/onboarding", json=body)).status_code == 422


async def test_progress_requires_auth_and_csrf(client, admin):
    del client.headers["X-CSRF-Token"]
    assert (
        await client.put("/api/setup/onboarding", json={"status": "skipped"})
    ).status_code == 403
    client.cookies.clear()
    assert (await client.get("/api/setup/onboarding")).status_code == 401
