import asyncio

import pytest
from sqlalchemy import func, select

from app.db.models import AuditEvent, OrganizationSettings

pytestmark = pytest.mark.integration


async def test_naming_defaults_preview_and_saved_profile_survive_reload(client, admin, database):
    settings = (await client.get("/api/organization/settings")).json()
    preview = await client.post("/api/organization/preview", json={})
    assert preview.status_code == 200, preview.text
    assert preview.json()["expected_items"] == 5
    assert not preview.json()["publication_available"]
    profile = {**settings["profile"], "ebook_folder": "{author}/{title}[ - {edition_year}]"}
    saved = await client.put(
        "/api/organization/settings",
        json={"profile": profile, "expected_revision": settings["revision"]},
    )
    assert saved.status_code == 200, saved.text
    assert (await client.get("/api/organization/settings")).json()["profile"] == profile
    paths = (await client.post("/api/organization/preview", json={})).json()["items"]
    assert paths[0]["folder"] == "ebooks/Alex Morgan/The First Harbor - 2017"
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(OrganizationSettings)) == 1
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "organization.settings.changed")
            )
            == 1
        )


async def test_concurrent_naming_edits_reject_stale_revision(client, admin):
    settings = (await client.get("/api/organization/settings")).json()
    responses = await asyncio.gather(
        *[
            client.put(
                "/api/organization/settings",
                json={
                    "profile": {**settings["profile"], "ebook_filename": template},
                    "expected_revision": settings["revision"],
                },
            )
            for template in ("{author} - {title}", "{title}[ - {edition_year}]")
        ]
    )
    assert sorted(response.status_code for response in responses) == [200, 409]


async def test_invalid_templates_rejected_and_preview_has_no_settings_side_effect(
    client, admin, database
):
    bad = await client.post(
        "/api/organization/preview", json={"profile": {"audio_folder": "../{title}"}}
    )
    assert bad.status_code == 422
    await client.post("/api/organization/preview", json={"profile": {"layout": "nested"}})
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(OrganizationSettings)) == 0
    assert (await client.get("/api/organization/settings")).json()["profile"][
        "layout"
    ] == "conventional"


async def test_organization_requires_administrator(client, admin, database):
    from uuid import UUID

    from app.db.models import User

    async with database() as db, db.begin():
        (await db.get(User, UUID(admin["id"]))).role = "member"
    assert (await client.get("/api/organization/settings")).status_code == 403
    assert (await client.post("/api/organization/preview", json={})).status_code == 403


async def test_settings_migration_preserves_configured_profiles(client, admin, database):
    from app.db.session import get_engine
    from tests.integration.test_correction_migration import migrate

    settings = (await client.get("/api/organization/settings")).json()
    await client.put(
        "/api/organization/settings",
        json={"profile": settings["profile"], "expected_revision": settings["revision"]},
    )
    await get_engine().dispose()
    try:
        refused = await migrate("downgrade", "0007_work_merges")
        assert (
            refused.returncode != 0
            and "Organization settings cannot be preserved" in refused.stderr
        )
        async with database() as db:
            assert await db.get(OrganizationSettings, 1) is not None
    finally:
        restored = await migrate("upgrade", "head")
        assert restored.returncode == 0, restored.stderr
        await get_engine().dispose()
