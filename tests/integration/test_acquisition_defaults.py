# ruff: noqa: F401, F811
"""Layered policies must stay private, explicit, and frozen at acquisition boundaries."""

import asyncio
from uuid import UUID

import pytest
from sqlalchemy import select

from app.db.models import AcquisitionDefaults, User
from app.domain import automatic_selection, download_attempts
from app.domain.release_profiles import (
    ProfileSnapshot,
    ReleasePreferences,
    profile_snapshot,
    same_profile,
)
from tests.integration.test_acquisition import catalog
from tests.integration.test_acquisition_selections import selection_route
from tests.integration.test_automatic_dispatch import authorized
from tests.integration.test_automatic_selection import detail, source, start
from tests.integration.test_book_sources import begin, read
from tests.integration.test_list_policies import activate, add, policy_fixture, preview, tick

pytestmark = pytest.mark.integration


async def defaults(client, scope="personal"):
    response = await client.get(f"/api/acquisition/preferences/{scope}")
    assert response.status_code == 200, response.text
    return response.json()


async def save(client, values, scope="personal"):
    before = await defaults(client, scope)
    response = await client.put(
        f"/api/acquisition/preferences/{scope}",
        json={
            "overrides": values,
            "expected_revision": before["revision"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_sparse_precedence_clear_and_restore(client, admin, database):
    base = await defaults(client)
    assert base["overrides"] == {} and base["effective"]["ebook_formats"][0] == "epub"
    await save(
        client,
        {"ebook_formats": ["pdf", "epub"], "maximum_bytes": 500, "blocked_formats": ["mobi"]},
        "installation",
    )
    personal = await save(client, {"maximum_bytes": None, "blocked_formats": []})
    assert personal["effective"]["maximum_bytes"] is None
    assert personal["effective"]["blocked_formats"] == []
    assert personal["origins"]["ebook_formats"] == "Installation default"
    assert personal["origins"]["maximum_bytes"] == "Personal default"
    created = await client.post(
        "/api/acquisition/profiles",
        json={
            "name": "Audio preference",
            "preferences": {"audio_formats": ["mp3", "m4b"]},
        },
    )
    assert created.status_code == 201, created.text
    profile = created.json()
    assert profile["overrides"] == {"audio_formats": ["mp3", "m4b"]}
    assert profile["preferences"]["ebook_formats"] == ["pdf", "epub"]
    assert profile["origins"]["audio_formats"] == "Profile"
    await save(client, {})
    refreshed = (await client.get("/api/acquisition/profiles")).json()[1]
    assert refreshed["preferences"]["maximum_bytes"] == 500
    assert refreshed["preferences"]["blocked_formats"] == ["mobi"]
    assert refreshed["effective_revision"] != profile["effective_revision"]
    async with database() as db:
        row = await db.get(AcquisitionDefaults, f"user:{admin['id']}")
        assert row.preferences == {} and row.generation == 2


@pytest.mark.parametrize(
    "overrides",
    [
        {"ebook_formats": []},
        {"audio_formats": []},
        {"source_order": []},
        {"criteria": ["seeders"]},
        {"maximum_bytes": 0},
        {"blocked_formats": None},
        {"ebook_formats": None},
        {"not_a_setting": True},
    ],
)
async def test_invalid_overrides_do_not_silently_inherit(client, admin, overrides):
    before = await defaults(client)
    response = await client.put(
        "/api/acquisition/preferences/personal",
        json={
            "overrides": overrides,
            "expected_revision": before["revision"],
        },
    )
    assert response.status_code == 422
    assert (await defaults(client))["revision"] == before["revision"]


async def test_concurrent_default_edits_have_one_winner_and_aba_is_stale(client, admin):
    before = await defaults(client)

    async def edit(limit):
        return await client.put(
            "/api/acquisition/preferences/personal",
            json={
                "overrides": {"maximum_bytes": limit},
                "expected_revision": before["revision"],
            },
        )

    results = await asyncio.gather(edit(100), edit(200))
    assert sorted(r.status_code for r in results) == [200, 409]
    restored = await save(client, {})
    assert restored["revision"] != before["revision"]
    assert (await edit(300)).status_code == 409


async def test_installation_change_invalidates_inherited_edit_preview(client, admin):
    before = await defaults(client)
    await save(client, {"maximum_bytes": 100}, "installation")
    response = await client.put(
        "/api/acquisition/preferences/personal",
        json={
            "overrides": {"source_order": ["prowlarr", "mam"]},
            "expected_revision": before["revision"],
        },
    )
    assert response.status_code == 409


async def test_effective_profile_change_invalidates_search_but_replay_keeps_receipt(
    client, admin, database, catalog
):
    initial = (await client.get("/api/acquisition/profiles")).json()[0]
    search = await begin(client, catalog, profile_effective_revision=initial["effective_revision"])
    await save(client, {"ebook_formats": ["pdf", "epub"]})
    replay = await begin(client, catalog, profile_effective_revision=initial["effective_revision"])
    assert replay["id"] == search["id"]
    frozen = (await read(client, search["id"])).json()["profile"]
    assert frozen["preferences"]["ebook_formats"][0] == "epub"
    rejected = await client.post(
        f"/api/catalog/works/{catalog['work']}/source-searches",
        json={
            "profile_effective_revision": initial["effective_revision"],
        },
        headers={"Idempotency-Key": "stale-defaults-search"},
    )
    assert rejected.status_code == 409
    fresh = await begin(client, catalog, key="fresh-defaults-search")
    assert (await read(client, fresh["id"])).json()["profile"]["preferences"]["ebook_formats"][
        0
    ] == "pdf"


async def test_explicit_profile_masks_changed_defaults_and_legacy_snapshot_is_readable(
    client, admin, database
):
    explicit = ReleasePreferences().model_dump()
    created = (
        await client.post(
            "/api/acquisition/profiles",
            json={
                "name": "Pinned",
                "preferences": explicit,
            },
        )
    ).json()
    await save(client, {"ebook_formats": ["pdf", "epub"]}, "installation")
    async with database() as db:
        current = await profile_snapshot(
            db, UUID(admin["id"]), UUID(created["id"]), 1, created["effective_revision"]
        )
    assert same_profile(
        current,
        ProfileSnapshot(id=created["id"], generation=1, name="Pinned", preferences=explicit),
    )
    updated = await client.put(
        f"/api/acquisition/profiles/{created['id']}",
        json={
            "name": "Now inherited",
            "preferences": {},
            "expected_generation": 1,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["overrides"] == {}
    assert updated.json()["preferences"]["ebook_formats"][0] == "pdf"


async def test_personal_defaults_are_isolated_and_members_cannot_change_installation(
    client, admin, database
):
    await save(client, {"maximum_bytes": 987})
    created = await client.post(
        "/api/auth/users",
        json={
            "username": "member",
            "display_name": "Member",
            "password": "a long member password",
            "role": "member",
        },
    )
    assert created.status_code == 201, created.text
    await client.post("/api/auth/logout")
    login = (
        await client.post(
            "/api/auth/login",
            json={
                "username": "member",
                "password": "a long member password",
            },
        )
    ).json()
    client.headers["X-CSRF-Token"] = login["csrf_token"]
    personal = await defaults(client)
    assert personal["effective"]["maximum_bytes"] is None
    assert (await client.get("/api/acquisition/preferences/installation")).status_code == 403
    denied = await client.put(
        "/api/acquisition/preferences/installation",
        json={
            "overrides": {},
            "expected_revision": personal["revision"],
        },
    )
    assert denied.status_code == 403
    await save(client, {"maximum_bytes": 234})
    async with database() as db, db.begin():
        row = await db.get(User, UUID(login["user"]["id"]))
        row.role = "viewer"
    assert (await client.get("/api/acquisition/preferences/personal")).status_code == 403


async def test_changed_defaults_hold_list_policy_until_new_activation(
    client, database, policy_fixture
):
    f = policy_fixture
    await add(client, f)
    saved = await activate(client, f, await preview(client, f, include_work_ids=[f["work"]]))
    await save(client, {"maximum_bytes": 100})
    await tick(database, saved)
    policy = (await client.get(f"/api/lists/{f['list']}/acquisition")).json()
    assert "preferences changed" in policy["message"].lower()
    assert f["source"]["qbit"].calls.count("submit") == 0


@pytest.mark.parametrize("already_submitted", [False, True])
async def test_changed_defaults_hold_unsubmitted_automatic_attempt_but_preserve_running_transfer(
    client, database, authorized, already_submitted
):
    operation = await start(client, authorized)
    await automatic_selection.run(UUID(operation["id"]))
    result = await detail(client, operation["id"])
    attempt_id = UUID(result["download_id"])
    if already_submitted:
        await download_attempts.run(attempt_id)
    await save(client, {"audio_formats": ["mp3", "m4b"]})
    await download_attempts.run(attempt_id)
    assert authorized["qbit"].calls.count("submit") == int(already_submitted)
    from app.db.models import DownloadAttempt

    async with database() as db:
        attempt = await db.get(DownloadAttempt, attempt_id)
        assert attempt.state == ("downloading" if already_submitted else "held")


async def test_populated_default_settings_block_lossy_downgrade(client, admin, database):
    from sqlalchemy import text

    from tests.integration.test_correction_migration import migrate

    await save(client, {"maximum_bytes": 500})
    async with database() as db:
        before = await db.scalar(text("SELECT version_num FROM alembic_version"))
    result = await migrate("downgrade", "0030_list_policies")
    assert result.returncode != 0 and "pre-upgrade backup" in result.stderr
    async with database() as db:
        assert await db.scalar(text("SELECT version_num FROM alembic_version")) == before
