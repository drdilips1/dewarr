# ruff: noqa: F401, F811
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.db.models import CatalogAccount, Integration, Library, Operation, SourceConnection, User
from app.jobs.queue import get_queue
from tests.integration.test_import_destinations import route, start_probe
from tests.integration.test_recovery_scan_workflow import pause

pytestmark = pytest.mark.integration


async def read(client):
    response = await client.get("/api/setup/readiness")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


async def test_empty_setup_is_read_only_and_reports_deployment_switch(
    client, admin, database, monkeypatch
):
    settings = get_settings()
    monkeypatch.setattr(settings, "download_dispatch_enabled", False)
    before = await read(client)
    assert not before["download_dispatch_enabled"]
    assert before["catalog"] is None
    assert not any(before[key] for key in ("libraries", "sources", "downloaders", "destinations"))
    monkeypatch.setattr(settings, "download_dispatch_enabled", True)
    assert (await read(client))["download_dispatch_enabled"]
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(Operation)) == 0


async def test_setup_requires_admin_and_obeys_recovery_pause(client, admin, database):
    async with database() as db, db.begin():
        user = await db.get(User, UUID(admin["id"]))
        user.role = "member"
    assert (await client.get("/api/setup/readiness")).status_code == 403
    async with database() as db, db.begin():
        user = await db.get(User, UUID(admin["id"]))
        user.role = "admin"
    await pause(database, admin)
    assert (await client.get("/api/setup/readiness")).status_code == 423
    client.cookies.clear()
    assert (await client.get("/api/setup/readiness")).status_code == 401


async def test_saved_status_does_not_hide_failed_disabled_or_partial_setup(
    client, admin, database, monkeypatch, tmp_path
):
    recorded = datetime.now(UTC) - timedelta(days=3)
    root = tmp_path / "downloads"
    monkeypatch.setattr(get_settings(), "import_sources", {"books": root})
    async with database() as db, db.begin():
        other = User(username="other", display_name="Other", password_hash="unused", role="admin")
        db.add(other)
        await db.flush()
        db.add(
            CatalogAccount(user_id=other.id, encrypted_token="do-not-decrypt", status="connected")
        )
        backend = Integration(
            name="Library",
            kind="audiobookshelf",
            base_url="http://private.invalid",
            encrypted_secrets="do-not-decrypt",
            status="authentication",
            last_success_at=recorded,
        )
        downloader = Integration(
            name="Downloader",
            kind="qbittorrent",
            base_url="http://private.invalid",
            encrypted_secrets="do-not-decrypt",
            status="connected",
            enabled=False,
            last_success_at=recorded,
            config={"mappings": [{"source_key": "books", "source_path": str(root)}]},
        )
        personal = Integration(
            name="Private integration",
            kind="audiobookshelf",
            owner_id=other.id,
            base_url="http://private.invalid",
            encrypted_secrets="do-not-decrypt",
        )
        source = SourceConnection(
            key="mam",
            base_url="http://private.invalid",
            proxy_url="http://proxy.invalid",
            encrypted_secrets="do-not-decrypt",
            status="rate-limit",
            last_success_at=recorded,
            blocked_until=recorded + timedelta(days=5),
            generation=7,
        )
        db.add_all([backend, downloader, personal, source])
        await db.flush()
        db.add_all(
            [
                Library(
                    integration_id=backend.id,
                    external_id="ok",
                    name="Synced",
                    accessible=True,
                    last_complete_sync=recorded,
                ),
                Library(
                    integration_id=backend.id,
                    external_id="partial",
                    name="Partial",
                    accessible=True,
                ),
                Library(
                    integration_id=backend.id,
                    external_id="lost",
                    name="Lost",
                    accessible=False,
                    last_complete_sync=recorded,
                ),
            ]
        )
    result = await read(client)
    assert result["catalog"] is None  # Another admin's token never supplies this user's catalog.
    assert len(result["libraries"]) == 1
    assert result["libraries"][0]["libraries"] == 3
    assert result["libraries"][0]["inventoried_libraries"] == 1
    assert result["libraries"][0]["status"] == "authentication"
    assert not result["downloaders"][0]["enabled"]
    assert result["downloaders"][0]["mappings_current"]
    assert result["sources"][0]["uses_proxy"]
    assert result["sources"][0]["status"] == "rate-limit"
    assert "private.invalid" not in str(result) and "do-not-decrypt" not in str(result)
    monkeypatch.setattr(get_settings(), "import_sources", {"books": root / "changed"})
    assert not (await read(client))["downloaders"][0]["mappings_current"]
    async with database() as db:
        source = await db.get(SourceConnection, "mam")
        assert source.generation == 7 and source.encrypted_secrets == "do-not-decrypt"
        assert source.blocked_until == recorded + timedelta(days=5)
        assert await db.scalar(select(func.count()).select_from(Operation)) == 0


async def test_setup_uses_actual_probe_evidence_and_invalidates_changed_roots(
    client, admin, route, monkeypatch
):
    assert not (await read(client))["destinations"][0]["publication_available"]
    response = await start_probe(client, route)
    assert response.status_code == 202
    await get_queue().run_worker_async(wait=False, concurrency=1)
    assert (await read(client))["destinations"][0]["publication_available"]
    monkeypatch.setattr(get_settings(), "import_sources", {"fixture": route["source"] / "changed"})
    assert not (await read(client))["destinations"][0]["publication_available"]
