"""Inherited scope must become the same strict request on every acquisition path."""

# ruff: noqa: F401, F811
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.db.models import AcquisitionIntent, AcquisitionReason, Operation
from app.domain import automatic_selection, list_requests
from app.domain.acquisition import RequestSpec
from tests.integration.test_acquisition_defaults import save as defaults
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


async def plan(client, work, options=None, choice=None, reason=None):
    body = {"work_id": str(work), "specification": options or {}}
    if choice is not None:
        body["release_preferences"] = choice
    if reason:
        body["reason"] = {"list_id": reason}
    response = await client.post("/api/requests/preview", json=body)
    assert response.status_code == 200, response.text
    return body, response.json()


async def accept(client, body, preview, key=None):
    return await client.post(
        "/api/requests",
        json={
            **body,
            "expected_preference_revision": preview["release_policy"]["effective_revision"],
        },
        headers={"Idempotency-Key": key or str(uuid4())},
    )


async def test_scope_defaults_become_frozen_requirements_and_preserve_ownership(
    client, admin, catalog, database
):
    await defaults(
        client,
        {
            "desired_media": "both",
            "language": "eng",
            "abridged": False,
            "audio_library_id": str(catalog["library"]),
        },
        "installation",
    )
    body, previewed = await plan(client, catalog["work"])
    assert previewed["specification"]["mode"] == "both"
    assert previewed["specification"]["language"] == "en"
    assert previewed["specification"]["abridged"] is False
    assert previewed["specification"]["preferred_medium"] is None
    assert {t["slot"]: t["state"] for t in previewed["targets"]} == {
        "ebook": "satisfied",
        "audio": "wanted",
    }
    assert previewed["release_policy"]["scope_origins"]["mode"] == "Installation default"
    saved = await accept(client, body, previewed)
    assert saved.status_code == 202, saved.text
    item = saved.json()["request"]
    assert item["specification"] == previewed["specification"]
    async with database() as db:
        intent = await db.get(AcquisitionIntent, UUID(item["id"]))
        reason = await db.scalar(
            select(AcquisitionReason).where(AcquisitionReason.intent_id == intent.id)
        )
        assert intent.release_policy == reason.release_policy == item["release_policy"]
    await defaults(client, {"desired_media": "ebook", "language": "fr"})
    assert (await client.get(f"/api/requests/{item['id']}")).json()["specification"] == item[
        "specification"
    ]


async def test_all_scope_layers_and_explicit_any_with_inapplicable_defaults(client, policy_fixture):
    f = policy_fixture
    await defaults(
        client, {"desired_media": "both", "language": "en", "abridged": False}, "installation"
    )
    await defaults(client, {"desired_media": "audio", "standalone": True})
    profile = (
        await client.post(
            "/api/acquisition/profiles", json={"name": "French", "preferences": {"language": "fr"}}
        )
    ).json()
    await add(client, f)
    activated = await activate(
        client,
        f,
        await preview(
            client,
            f,
            mode="manual",
            specification={},
            profile_id=profile["id"],
            profile_generation=1,
            preference_overrides={"desired_media": "either", "preferred_medium": "ebook"},
        ),
    )
    assert activated["configuration"]["scope_options"] == {}
    body, inherited = await plan(client, f["work"], reason=f["list"])
    assert inherited["specification"]["mode"] == "either"
    assert inherited["specification"]["preferred_medium"] == "ebook"
    assert inherited["specification"]["language"] == "fr"
    assert inherited["release_policy"]["scope_origins"]["mode"] == "List override"
    assert inherited["release_policy"]["scope_origins"]["language"] == "Profile"
    _, cleared = await plan(
        client,
        f["work"],
        {"mode": "ebook", "language": None, "standalone": False},
        reason=f["list"],
    )
    assert cleared["specification"]["language"] is None
    assert cleared["specification"]["standalone"] is False
    assert cleared["specification"]["abridged"] is None
    assert cleared["release_policy"]["scope_origins"]["language"] == "Request override"
    assert cleared["release_policy"]["scope_origins"]["abridged"] == "Not applicable"


async def test_inherited_scope_preview_rejects_changed_default_and_replay_keeps_original(
    client, catalog
):
    await defaults(client, {"desired_media": "audio", "language": "en"})
    body, previous = await plan(client, catalog["work"])
    key = str(uuid4())
    accepted = await accept(client, body, previous, key)
    assert accepted.status_code == 202
    await defaults(client, {"desired_media": "ebook", "language": "fr"})
    stale = await accept(client, body, previous)
    assert stale.status_code == 409
    replay = await accept(client, body, previous, key)
    assert replay.status_code == 202
    assert replay.json()["request"]["id"] == accepted.json()["request"]["id"]
    assert replay.json()["request"]["specification"]["language"] == "en"


async def test_explicit_scope_masks_later_defaults_and_invalid_scope_never_creates_request(
    client, catalog, database
):
    await defaults(client, {"desired_media": "both", "language": "fr"})
    body, previewed = await plan(client, catalog["work"], {"mode": "ebook", "language": None})
    await defaults(client, {"desired_media": "audio", "language": "de"})
    assert (await accept(client, body, previewed)).status_code == 202
    for options in (
        {"mode": "either", "preferred_medium": None},
        {"mode": "ebook", "abridged": False},
        {"mode": "audio", "audio_library_id": str(uuid4())},
    ):
        response = await client.post(
            "/api/requests",
            json={"work_id": str(catalog["work"]), "specification": options},
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert response.status_code in {404, 422}, response.text
    async with database() as db:
        assert len(list(await db.scalars(select(AcquisitionIntent)))) == 1


async def test_no_implicit_media_without_a_default(client, catalog):
    response = await client.post(
        "/api/requests/preview", json={"work_id": str(catalog["work"]), "specification": {}}
    )
    assert response.status_code == 422 and "Choose media" in response.text


async def test_batch_retains_sparse_options_and_freezes_effective_scope(
    client, database, policy_fixture
):
    f = policy_fixture
    await defaults(client, {"desired_media": "both", "language": "en"})
    await add(client, f)
    response = await client.post(
        f"/api/lists/{f['list']}/requests/preview",
        json={"work_ids": [f["work"]], "specification": {}},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 200, response.text
    identifier = response.json()["id"]
    assert response.json()["specification"]["mode"] == "both"
    assert (
        await client.post(f"/api/lists/{f['list']}/requests/{identifier}/submit")
    ).status_code == 202
    await list_requests.run(UUID(identifier))
    receipt = (await client.get(f"/api/lists/{f['list']}/requests/{identifier}")).json()
    assert receipt["status"] == "completed"
    item = (await client.get("/api/requests/" + receipt["receipt"][0]["request_id"])).json()
    assert item["specification"] == receipt["specification"]
    async with database() as db:
        operation = await db.get(Operation, UUID(identifier))
        assert operation.payload["command"]["specification"] == {}


async def test_automatic_list_resolves_scope_once_and_dispatches_once(
    client, database, policy_fixture
):
    f = policy_fixture
    await defaults(client, {"desired_media": "audio", "language": "en"})
    activated = await activate(client, f, await preview(client, f, specification={}))
    await add(client, f)
    for _ in range(3):
        await tick(database, activated, force_books=True)
    assert f["source"]["qbit"].calls.count("submit") == 1, (
        await client.get(f"/api/lists/{f['list']}/acquisition/books")
    ).json()
    assert (await client.get(f"/api/lists/{f['list']}/acquisition")).json()["configuration"][
        "scope_options"
    ] == {}
    await tick(database, activated, force_books=True)
    assert f["source"]["qbit"].calls.count("submit") == 1


async def test_legacy_request_replay_uses_original_command_defaults(client, database, catalog):
    body, previewed = await plan(client, catalog["work"], {"mode": "audio"})
    key = str(uuid4())
    saved = await accept(client, body, previewed, key)
    assert saved.status_code == 202
    async with database() as db, db.begin():
        operation = await db.get(Operation, UUID(saved.json()["operation"]["id"]))
        payload = dict(operation.payload)
        command = dict(payload["command"])
        command.pop("scope_inheritance")
        command["specification"] = RequestSpec(mode="audio").model_dump(mode="json")
        payload["command"] = command
        operation.payload = payload
    await defaults(client, {"language": "fr"})
    replay = await accept(client, body, previewed, key)
    assert replay.status_code == 202
    assert replay.json()["request"]["id"] == saved.json()["request"]["id"]


async def test_general_search_cannot_replace_an_explicit_request_profile(client, authorized):
    from tests.integration.test_automatic_selection import start

    saved_profile = (
        await client.post(
            "/api/acquisition/profiles",
            json={
                "name": "Explicit request profile",
                "preferences": {"audio_formats": ["mp3", "m4b"]},
            },
        )
    ).json()
    old = (await client.get("/api/requests/" + authorized["body"]["intent_id"])).json()
    body, previewed = await plan(
        client,
        old["work_id"],
        old["specification"],
        {"profile_id": saved_profile["id"], "profile_generation": saved_profile["generation"]},
    )
    wanted = await accept(client, body, previewed)
    assert wanted.status_code == 202, wanted.text
    result = await client.post(
        "/api/acquisition/automatic-selections",
        json={**authorized["body"], "intent_id": wanted.json()["request"]["id"]},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert result.status_code == 409 and "Refresh sources" in result.text
    assert authorized["qbit"].calls == []


async def test_browse_only_list_needs_no_media_default_and_authorizes_no_acquisition(
    client, database, policy_fixture
):
    f = policy_fixture
    await add(client, f)
    saved = await activate(client, f, await preview(client, f, mode="browse", specification={}))
    assert saved["configuration"]["specification"]["mode"] == "either"
    assert saved["configuration"]["profile"]["preferences"]["desired_media"] is None
    assert saved["configuration"]["profile"]["scope_origins"]["mode"] == "Browse inventory"
    response = await client.post(
        "/api/requests/preview",
        json={"work_id": f["work"], "specification": {}, "reason": {"list_id": f["list"]}},
    )
    assert response.status_code == 422 and "Choose media" in response.text
    await tick(database, saved)
    assert f["source"]["qbit"].calls == []
