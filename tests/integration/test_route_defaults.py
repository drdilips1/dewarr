# ruff: noqa: F401, F811
"""Default routes choose destinations without granting or silently renewing authority."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.db.models import (
    AutomaticImportPolicy,
    DownloadAttempt,
    ListAcquisitionBook,
    ListAcquisitionPolicy,
    Operation,
    User,
)
from app.domain import series_acquisition
from tests.integration.test_acquisition import catalog
from tests.integration.test_acquisition_defaults import save
from tests.integration.test_acquisition_selections import selection_route
from tests.integration.test_automatic_dispatch import authorized
from tests.integration.test_automatic_pack_selection import series_pack
from tests.integration.test_automatic_selection import source
from tests.integration.test_list_policies import activate, add, policy_fixture, preview, tick
from tests.integration.test_series_acquisition import BASE, accept
from tests.integration.test_series_acquisition import ready as series_ready

pytestmark = pytest.mark.integration


async def route_defaults(client, route):
    await save(client, {"downloader_id": route["downloader_id"]}, "installation")
    await save(client, {"audio_destination_id": route["destination_id"]})


async def test_list_defaults_resolve_once_and_changed_defaults_hold_existing_automation(
    client, database, policy_fixture
):
    await route_defaults(client, policy_fixture["source"]["body"])
    plan = await preview(
        client, policy_fixture, downloader_id=None, downloader_generation=None, routes={}
    )
    config = plan["configuration"]
    assert config["route_options"] == {
        "downloader_id": None,
        "downloader_generation": None,
        "routes": {},
    }
    assert config["profile"]["scope_origins"]["downloader_id"] == "Installation default"
    assert config["profile"]["scope_origins"]["audio_destination_id"] == "Personal default"
    assert config["routes"]["audio"] == policy_fixture["config"]["routes"]["audio"]
    policy = await activate(client, policy_fixture, plan)
    reopened = (await client.get(f"/api/lists/{policy_fixture['list']}/acquisition")).json()
    assert reopened["configuration"]["route_options"] == config["route_options"]
    await add(client, policy_fixture)
    await tick(database, policy)
    async with database() as db:
        book = await db.scalar(select(ListAcquisitionBook))
        assert book.state == "searching", book.message
    await save(client, {"audio_destination_id": None})
    await tick(database, policy, force_books=True)
    async with database() as db:
        saved = await db.get(ListAcquisitionPolicy, UUID(policy["id"]))
        assert "preferences changed" in saved.message.lower(), saved.message
        assert saved.configuration["routes"] == config["routes"]
        assert not await db.scalar(select(DownloadAttempt.id))
    assert config["routes"]["audio"] == policy_fixture["config"]["routes"]["audio"]


async def test_series_uses_inherited_routes_and_retains_the_reviewed_configuration(
    client, database, series_ready, authorized
):
    await route_defaults(client, authorized["body"])
    response = await client.post(
        BASE + "/preview",
        json={**series_ready["command"], "automatic": {}},
        headers={"Idempotency-Key": "inherited-series-route-preview"},
    )
    assert response.status_code == 201, response.text
    ready = {**series_ready, "parent": UUID(response.json()["id"])}
    identifier = await accept(client, database, ready)
    await series_acquisition.run(identifier)
    async with database() as db:
        row = await db.get(Operation, identifier)
        assert {book["state"] for book in row.payload["books"].values()} == {"searching"}, (
            row.message
        )
        config = row.payload["configuration"]
        assert config["downloader_id"] == authorized["body"]["downloader_id"]
        assert config["profile"]["scope_origins"]["audio_destination_id"] == "Personal default"


async def test_default_route_preview_does_not_renew_a_changed_import_approval(
    client, database, policy_fixture
):
    await route_defaults(client, policy_fixture["source"]["body"])
    plan = await preview(
        client, policy_fixture, downloader_id=None, downloader_generation=None, routes={}
    )
    async with database() as db, db.begin():
        (await db.scalar(select(AutomaticImportPolicy))).generation += 1
    response = await client.post(
        f"/api/lists/{policy_fixture['list']}/acquisition/previews/{plan['id']}/activate"
    )
    assert response.status_code == 409, response.text


async def test_unavailable_default_is_not_replaced_but_an_explicit_route_can_override_it(
    client, policy_fixture
):
    await save(client, {"audio_destination_id": str(uuid4())})
    response = await client.post(
        f"/api/lists/{policy_fixture['list']}/acquisition/preview",
        json={**policy_fixture["config"], "routes": {}},
        headers={"Idempotency-Key": "unavailable-route-default"},
    )
    assert response.status_code == 409 and "unavailable" in response.text
    plan = await preview(client, policy_fixture)
    assert plan["configuration"]["routes"] == policy_fixture["config"]["routes"]


async def test_default_destination_does_not_bypass_library_access(
    client, database, admin, policy_fixture
):
    await route_defaults(client, policy_fixture["source"]["body"])
    async with database() as db, db.begin():
        user = await db.get(User, UUID(admin["id"]))
        user.role, user.can_automate = "member", True
    response = await client.post(
        f"/api/lists/{policy_fixture['list']}/acquisition/preview",
        json={**policy_fixture["config"], "routes": {}},
        headers={"Idempotency-Key": "private-route-default"},
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "Saved import destination is unavailable; choose a route"


async def test_clearing_a_default_is_persistent_and_does_not_reenable_inheritance(
    client, policy_fixture
):
    route = policy_fixture["source"]["body"]
    await save(client, {"audio_destination_id": route["destination_id"]}, "installation")
    cleared = await save(client, {"audio_destination_id": None})
    assert cleared["overrides"] == {"audio_destination_id": None}
    assert cleared["effective"].get("audio_destination_id") is None
    response = await client.post(
        f"/api/lists/{policy_fixture['list']}/acquisition/preview",
        json={**policy_fixture["config"], "routes": {}},
        headers={"Idempotency-Key": "cleared-route-default"},
    )
    assert response.status_code == 422, response.text
    restored = await save(client, {})
    assert restored["effective"]["audio_destination_id"] == route["destination_id"]
