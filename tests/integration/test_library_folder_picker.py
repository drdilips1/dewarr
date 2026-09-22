# ruff: noqa: F811
from uuid import UUID

import pytest
from sqlalchemy import select

from app.api import library_folders
from app.config import get_settings
from app.db.models import AutomaticImportPolicy, ImportDestination, ImportStorageSettings
from app.importing.storage import storage_settings
from app.jobs.queue import get_queue
from tests.integration.test_setup_probe import empty_route, start  # noqa: F401

pytestmark = pytest.mark.integration


async def test_picker_persists_mounts_verifies_and_sets_both_defaults(
    client, admin, database, empty_route, monkeypatch
):
    route = empty_route
    monkeypatch.setattr(library_folders, "Audiobookshelf", route["backend"].client)
    monkeypatch.setattr(get_settings(), "import_destinations", {})
    monkeypatch.setattr(get_settings(), "import_staging_root", None)
    options = (await client.get("/api/organization/library-folders")).json()
    assert options[0]["folders"] == ["/books"]
    library_id = options[0]["library_id"]
    # Replace the prior explicitly configured destination using its current revision.
    existing = (await client.get("/api/organization/destinations")).json()[0]
    response = await client.put(
        "/api/organization/library-folders/ebook",
        json={
            "library_id": library_id,
            "backend_path": "/books",
            "local_path": str(route["target"]),
            "destination_id": existing["id"],
            "expected_revision": existing["revision"],
        },
    )
    assert response.status_code == 200, response.text
    chosen = response.json()
    assert chosen["configured"] and chosen["mode"] == "hardlink"
    assert chosen["seeding_rename"] is False
    assert chosen["local_path"] == str(route["target"])
    assert not chosen["publication_available"]
    denied = await client.post(
        f"/api/organization/library-folders/{chosen['id']}/activate",
        json={"expected_revision": chosen["revision"]},
    )
    assert denied.status_code == 409
    route["destination"] = chosen
    assert (await start(client, route)).status_code == 202
    await get_queue().run_worker_async(wait=False, concurrency=1)
    verified = (await client.get("/api/organization/destinations")).json()[0]
    assert verified["publication_available"], verified
    assert (route["target"].parent / ".book-search-staging").is_dir()
    response = await client.post(
        f"/api/organization/library-folders/{chosen['id']}/activate",
        json={"expected_revision": chosen["revision"]},
    )
    assert response.status_code == 200, response.text
    for scope in ["personal", "installation"]:
        defaults = (await client.get(f"/api/acquisition/preferences/{scope}")).json()["effective"]
        assert defaults["ebook_library_id"] == library_id
        assert defaults["ebook_destination_id"] == chosen["id"]
        assert defaults["downloader_id"] == str(route["downloader"])
    async with database() as db:
        mounted = await storage_settings(db)
        assert mounted.import_destinations["ebooks"] == route["target"]
        assert (await db.scalar(select(AutomaticImportPolicy))).enabled
        assert await db.get(ImportStorageSettings, 1)
        assert (await db.get(ImportDestination, UUID(chosen["id"]))).probe["hardlink"]
    # Another valid media destination must not invalidate the first verified route.
    audio_target = route["target"].parent / "audiobooks"
    audio_target.mkdir()
    response = await client.put(
        "/api/organization/library-folders/audio",
        json={"library_id": library_id, "backend_path": "/books", "local_path": str(audio_target)},
    )
    assert response.status_code == 200, response.text
    saved = (await client.get("/api/organization/destinations")).json()
    assert next(d for d in saved if d["id"] == chosen["id"])["publication_available"]


async def test_picker_rejects_unknown_abs_folder_and_overlapping_mount(
    client, admin, empty_route, monkeypatch
):
    monkeypatch.setattr(library_folders, "Audiobookshelf", empty_route["backend"].client)
    body = {
        "library_id": empty_route["destination"]["library_id"],
        "backend_path": "/not-an-abs-folder",
        "local_path": str(empty_route["target"]),
    }
    assert (
        await client.put("/api/organization/library-folders/audio", json=body)
    ).status_code == 422
    body.update(backend_path="/books", local_path=str(empty_route["source"]))
    assert (
        await client.put("/api/organization/library-folders/audio", json=body)
    ).status_code == 422
    body["local_path"] = "/data/../etc"
    assert (
        await client.put("/api/organization/library-folders/audio", json=body)
    ).status_code == 422
