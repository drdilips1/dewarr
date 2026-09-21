# ruff: noqa: F401, F811
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.db.models import AcquisitionIntent, DownloadAttempt, Operation, SourceResult
from app.domain import automatic_selection, quick_add
from tests.integration.test_acquisition import catalog
from tests.integration.test_acquisition_defaults import save
from tests.integration.test_acquisition_selections import selection_route
from tests.integration.test_automatic_dispatch import authorized
from tests.integration.test_automatic_selection import source

pytestmark = pytest.mark.integration


async def defaults(client, fixture, **extra):
    await save(
        client,
        {
            "desired_media": "audio",
            "downloader_id": fixture["body"]["downloader_id"],
            "audio_destination_id": fixture["body"]["destination_id"],
            **extra,
        },
    )


async def add(client, work, mode=None, key=None):
    return await client.post(
        "/api/requests/quick-add",
        json={
            "work_id": str(work),
            "specification": {"mode": mode} if mode else {},
        },
        headers={"Idempotency-Key": key or str(uuid4())},
    )


async def complete_search(database, operation_id, fixture):
    async with database() as db, db.begin():
        parent = await db.get(Operation, operation_id)
        search = await db.get(Operation, UUID(parent.payload["search_id"]))
        payload = deepcopy(search.payload)
        payload["workers"] = {}
        payload.pop("catalog_preparation", None)
        for unit in payload["sources"].values():
            unit.update(state="completed", count=1, message="Fixture results")
        search.payload = payload
        search.status = "completed"
        original = await db.get(SourceResult, fixture["result"])
        db.add(
            SourceResult(
                owner_id=original.owner_id,
                operation_id=search.id,
                source_key=original.source_key,
                source_generation=original.source_generation,
                expires_at=original.expires_at,
                encrypted_reference=original.encrypted_reference,
                release_snapshot=original.release_snapshot,
            )
        )


async def test_quick_add_inherits_preferences_and_downloads_once(
    client, database, authorized, catalog
):
    await defaults(client, authorized, audio_formats=["m4b", "mp3"])
    response = await add(client, catalog["work"], key="quick-add-one-click")
    assert response.status_code == 202, response.text
    identifier = UUID(response.json()["id"])
    repeated = await add(client, catalog["work"], key="quick-add-one-click")
    assert repeated.json()["id"] == str(identifier)
    repeated = await add(client, catalog["work"])
    assert repeated.json()["id"] == str(identifier)
    async with database() as db:
        op = await db.get(Operation, identifier)
        intent = await db.get(AcquisitionIntent, UUID(op.payload["intent_id"]))
        assert intent.specification["mode"] == "audio"
        assert intent.release_policy["preferences"]["audio_formats"] == ["m4b", "mp3"]
    await complete_search(database, identifier, authorized)
    await quick_add.run(identifier)
    async with database() as db:
        op = await db.get(Operation, identifier)
        assert op.status == "running", op.message
        child_id = UUID(op.payload["slots"]["audio"]["operation_id"])
        child = await db.get(Operation, child_id)
        assert child.payload["command"]["download_when_ready"] is True
    await automatic_selection.run(child_id)
    await quick_add.run(identifier)
    await quick_add.run(identifier)
    async with database() as db:
        op = await db.get(Operation, identifier)
        assert op.status == "completed", op.message
        assert await db.scalar(select(func.count()).select_from(DownloadAttempt)) == 1
    latest = await client.get(f"/api/requests/quick-add/latest/{catalog['work']}")
    assert latest.json()["status"] == "completed"


async def test_quick_add_explicit_medium_overrides_default_without_changing_it(
    client, database, authorized, catalog
):
    await defaults(client, authorized, desired_media="both")
    response = await add(client, catalog["work"], "audio")
    assert response.status_code == 202, response.text
    async with database() as db:
        op = await db.get(Operation, UUID(response.json()["id"]))
        intent = await db.get(AcquisitionIntent, UUID(op.payload["intent_id"]))
        assert intent.specification["mode"] == "audio"
        assert list(op.payload["slots"]) == ["audio"]
    preferences = (await client.get("/api/acquisition/preferences/personal")).json()
    assert preferences["effective"]["desired_media"] == "both"


async def test_quick_add_missing_routes_rolls_back_and_rejects_key_reuse(
    client, database, admin, catalog
):
    await save(client, {"desired_media": "audio"})
    response = await add(client, catalog["work"])
    assert response.status_code == 422, response.text
    assert "downloader" in response.text.lower()
    async with database() as db:
        assert not await db.scalar(select(Operation.id).where(Operation.kind == quick_add.KIND))
        assert not await db.scalar(select(DownloadAttempt.id))


async def test_save_torrent_is_owner_scoped(client, database, authorized):
    response = await client.get(f"/api/source-artifacts/{authorized['artifact']}/torrent")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/x-bittorrent"
    assert response.content.startswith(b"d")
    assert "attachment" in response.headers["content-disposition"]
    response = await client.get(f"/api/source-artifacts/{uuid4()}/torrent")
    assert response.status_code == 404


async def test_both_skips_owned_ebook_without_requiring_ebook_route(
    client, database, authorized, catalog
):
    await defaults(client, authorized, desired_media="both")
    response = await add(client, catalog["work"])
    assert response.status_code == 202, response.text
    async with database() as db:
        op = await db.get(Operation, UUID(response.json()["id"]))
        assert list(op.payload["slots"]) == ["audio"]
        intent = await db.get(AcquisitionIntent, UUID(op.payload["intent_id"]))
        assert intent.specification["mode"] == "both"


async def test_both_missing_media_create_independent_automatic_selections(
    client, database, authorized, catalog, monkeypatch, tmp_path
):
    from app.config import get_settings
    from app.db.models import ImportDestination, LibraryAsset
    from app.importing.destinations import destination_configuration
    from app.importing.naming import fingerprint

    settings = get_settings()
    (tmp_path / "ebooks").mkdir()
    monkeypatch.setattr(
        settings,
        "import_destinations",
        {**settings.import_destinations, "ebook": tmp_path / "ebooks"},
    )
    async with database() as db, db.begin():
        (await db.get(LibraryAsset, catalog["asset"])).full_content = False
        audio = await db.get(ImportDestination, UUID(authorized["body"]["destination_id"]))
        # Updating watched roots changes the audio route revision too.
        audio_revision = fingerprint(await destination_configuration(db, audio))
        audio.probe = {**audio.probe, "configuration_revision": audio_revision}
        ebook = ImportDestination(
            root_key="ebook",
            library_id=audio.library_id,
            medium="ebook",
            backend_path="/ebooks",
        )
        db.add(ebook)
        await db.flush()
        revision = fingerprint(await destination_configuration(db, ebook))
        ebook.probe = {**audio.probe, "configuration_revision": revision}
        ebook_id = str(ebook.id)
    approved_audio = await client.put(
        f"/api/organization/destinations/{authorized['body']['destination_id']}/automatic-import",
        json={
            "enabled": True,
            "expected_generation": 1,
            "destination_revision": audio_revision,
        },
    )
    assert approved_audio.status_code == 200, approved_audio.text
    approved = await client.put(
        f"/api/organization/destinations/{ebook_id}/automatic-import",
        json={
            "enabled": True,
            "expected_generation": 0,
            "destination_revision": revision,
        },
    )
    assert approved.status_code == 200, approved.text
    await defaults(client, authorized, desired_media="both", ebook_destination_id=ebook_id)
    response = await add(client, catalog["work"])
    assert response.status_code == 202, response.text
    identifier = UUID(response.json()["id"])
    await complete_search(database, identifier, authorized)
    await quick_add.run(identifier)
    async with database() as db:
        op = await db.get(Operation, identifier)
        assert set(op.payload["slots"]) == {"ebook", "audio"}
        for medium, progress in op.payload["slots"].items():
            assert "operation_id" in progress, progress
            child = await db.get(Operation, UUID(progress["operation_id"]))
            assert child.payload["command"]["slot"] == medium
            assert child.payload["command"]["download_when_ready"] is True
    # No ebook candidate: that slot must not prevent the audiobook from downloading.
    for progress in op.payload["slots"].values():
        await automatic_selection.run(UUID(progress["operation_id"]))
    await quick_add.run(identifier)
    async with database() as db:
        op = await db.get(Operation, identifier)
        assert op.status == "held", op.message
        assert op.payload["slots"]["ebook"]["failed"]
        assert not op.payload["slots"]["audio"]["failed"]
        assert await db.scalar(select(func.count()).select_from(DownloadAttempt)) == 1


async def test_cancelled_request_during_search_does_not_download(
    client, database, authorized, catalog
):
    from app.db.models import AcquisitionReason

    await defaults(client, authorized)
    response = await add(client, catalog["work"], key="quick-cancel-fixture")
    assert response.status_code == 202, response.text
    identifier = UUID(response.json()["id"])
    changed = await add(client, catalog["work"], "ebook", key="quick-cancel-fixture")
    assert changed.status_code == 409
    async with database() as db, db.begin():
        op = await db.get(Operation, identifier)
        for reason in await db.scalars(
            select(AcquisitionReason).where(
                AcquisitionReason.intent_id == UUID(op.payload["intent_id"])
            )
        ):
            reason.active = False
    await complete_search(database, identifier, authorized)
    await quick_add.run(identifier)
    async with database() as db:
        op = await db.get(Operation, identifier)
        assert op.status == "held", op.message
        assert not await db.scalar(select(DownloadAttempt.id))


@pytest.mark.parametrize("blocked", [False, True])
async def test_clicked_release_download_is_pinned_and_idempotent(
    client, database, authorized, blocked
):
    await defaults(client, authorized)
    profiles = (await client.get("/api/acquisition/profiles")).json()
    async with database() as db, db.begin():
        search = await db.get(Operation, authorized["search"])
        search.payload = {**search.payload, "profile": profiles[0]}
        original = await db.get(SourceResult, authorized["result"])
        other = SourceResult(
            owner_id=original.owner_id,
            operation_id=original.operation_id,
            source_key=original.source_key,
            source_generation=original.source_generation,
            expires_at=original.expires_at,
            encrypted_reference=original.encrypted_reference,
            release_snapshot={**original.release_snapshot, "seeders": 99999, "source_id": "999"},
        )
        db.add(other)
        if blocked:
            original.release_snapshot = {
                **original.release_snapshot,
                "authors": ["Wrong Author"],
                "title": "Unrelated Book",
            }
    path = f"/api/source-searches/{authorized['search']}/results/{authorized['result']}/download"
    response = await client.post(path, headers={"Idempotency-Key": "clicked-release-download"})
    assert response.status_code == 202, response.text
    identifier = UUID(response.json()["id"])
    await automatic_selection.run(identifier)
    repeated = await client.post(path, headers={"Idempotency-Key": "clicked-release-download"})
    assert repeated.status_code == 202, repeated.text
    assert repeated.json()["id"] == str(identifier)
    async with database() as db:
        operation = await db.get(Operation, identifier)
        assert operation.status == ("held" if blocked else "completed"), operation.message
        assert operation.payload["command"]["result_id"] == str(authorized["result"])
        assert await db.scalar(select(func.count()).select_from(DownloadAttempt)) == (
            0 if blocked else 1
        )
    assert authorized["resolver"].calls == ([] if blocked else [authorized["result"]])


async def test_clicked_release_rejects_result_from_another_search(client, database, authorized):
    response = await client.post(
        f"/api/source-searches/{authorized['search']}/results/{uuid4()}/download",
        headers={"Idempotency-Key": "unknown-clicked-release"},
    )
    assert response.status_code == 404, response.text
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(DownloadAttempt)) == 0
