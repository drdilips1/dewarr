# ruff: noqa: F811
"""Reviewed single-file acquisition through real file publication and fixture ABS."""

import base64
import hashlib
from datetime import UTC, datetime
from uuid import UUID

import libtorrent as lt
import pytest
from sqlalchemy import select

from app.adapters.mam import release
from app.adapters.torrent_descriptor import inspect_torrent
from app.config import get_settings
from app.db.models import (
    AcquisitionReservation,
    AcquisitionSelection,
    DownloadAttempt,
    DownloadFulfillment,
    DownloadIdentityClaim,
    Integration,
    SourceArtifact,
    SourceConnection,
)
from app.domain import download_attempts as downloads
from app.jobs.queue import get_queue
from app.security import encrypt_secrets
from tests.integration.test_acquisition import body, request
from tests.integration.test_acquisition_selections import prepare
from tests.integration.test_download_attempts import Client
from tests.integration.test_download_attempts import start as start_download
from tests.integration.test_import_destinations import route as destination_route  # noqa: F401
from tests.integration.test_import_destinations import start_probe
from tests.integration.test_import_execution import ready_route  # noqa: F401
from tests.integration.test_import_execution import start as start_import
from tests.mam_fixture import release_row
from tests.media_fixtures import epub

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("save_relative", ["", "nested"])
async def test_single_epub_download_to_confirmed_library_keeps_neighbor_private(
    client, admin, database, ready_route, monkeypatch, save_relative
):
    route = ready_route
    old = route["plan"]["document"]["groups"][0]
    name = "selected.epub"
    source = route["source"] / save_relative / name
    epub(source)
    epub(source.parent / "unrelated.epub", title="Not part of this torrent")
    original = source.read_bytes()
    pieces = b"".join(
        hashlib.sha1(original[pos : pos + 16384]).digest() for pos in range(0, len(original), 16384)
    )
    raw = lt.bencode(
        {
            b"info": {
                b"name": name.encode(),
                b"length": len(original),
                b"piece length": 16384,
                b"pieces": pieces,
            }
        }
    )
    descriptor = await inspect_torrent(raw)
    async with database() as db, db.begin():
        db.add(
            SourceConnection(
                key="mam",
                base_url="https://mam.test",
                encrypted_secrets=encrypt_secrets({"mam_id": "fixture-only"}),
            )
        )
        await db.flush()
        downloader = Integration(
            kind="qbittorrent",
            name="Fixture download client",
            base_url="http://qbit.test",
            encrypted_secrets=encrypt_secrets({"username": "fixture", "password": "fixture"}),
            credential_generation=1,
            status="connected",
            config={
                "save_path": "/downloads" + ("/" + save_relative if save_relative else ""),
                "category": "book-search",
                "mappings": [
                    {
                        "download_root": "/downloads",
                        "source_key": "fixture",
                        "source_path": str(route["source"]),
                    }
                ],
            },
        )
        artifact = SourceArtifact(
            owner_id=UUID(admin["id"]),
            source_key="mam",
            source_id="502",
            source_generation=1,
            sha256=descriptor.artifact_sha256,
            descriptor=descriptor.model_dump(mode="json"),
            encrypted_content=encrypt_secrets({"torrent": base64.b64encode(raw).decode()}),
            release_snapshot=release(
                release_row(
                    id=502, title="First Harbor", main_cat=14, filetype="EPUB", narrator_info="{}"
                ),
                datetime.now(UTC),
            ).model_dump(mode="json"),
        )
        db.add_all([downloader, artifact])
        await db.flush()
        downloader_id, artifact_id = str(downloader.id), str(artifact.id)
    wanted = await request(
        client, body({"work": old["work_id"]}, "ebook", ebook_library_id=route["library_id"])
    )
    selected_response = await prepare(
        client,
        {
            "intent_id": wanted["request"]["id"],
            "slot": "ebook",
            "artifact_id": artifact_id,
            "downloader_id": downloader_id,
            "downloader_generation": 1,
            "destination_id": route["destination"]["id"],
            "destination_revision": route["destination"]["revision"],
            "confirmed_work_id": old["work_id"],
        },
    )
    assert selected_response.status_code == 201, selected_response.text
    monkeypatch.setattr(get_settings(), "download_dispatch_enabled", True)
    qbit = Client(database, descriptor.model_dump(mode="json"))
    qbit.complete = True
    monkeypatch.setattr(downloads, "QbitClient", lambda *args: qbit)
    started = await start_download(client, selected_response.json())
    assert started.status_code == 202, started.text
    await get_queue().run_worker_async(wait=False, concurrency=1)
    async with database() as db:
        attempt = await db.scalar(select(DownloadAttempt))
        assert attempt.inspection_id
    inspected = (await client.get(f"/api/organization/inspections/{attempt.inspection_id}")).json()
    assert inspected["state"] == "ready", inspected
    assert inspected["snapshot"]["source_kind"] == "file"
    assert [file["path"] for file in inspected["snapshot"]["files"]] == [name]
    assert not (await client.get(f"/api/catalog/works/{old['work_id']}")).json()["availability"][
        "owned"
    ]
    settings = (await client.get("/api/organization/settings")).json()
    response = await client.post(
        f"/api/organization/inspections/{inspected['id']}/plans",
        json={
            "inspection_revision": inspected["snapshot"]["revision"],
            "profile_revision": settings["revision"],
            "selections": [
                {
                    "group_key": inspected["snapshot"]["groups"][0]["key"],
                    "work_id": old["work_id"],
                    "version_id": old["version_id"],
                    "full_content": True,
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    route["plan"], route["plan_id"] = response.json(), response.json()["id"]
    assert route["plan"]["document"]["source"]["source_kind"] == "file"
    # Prove a first-time route probe can use the selected file, not only a folder.
    await start_probe(client, route, key="file-scope-destination-probe")
    await get_queue().run_worker_async(wait=False, concurrency=1)
    destination = (await client.get("/api/organization/destinations")).json()[0]
    assert destination["probe"]["status"] == "verified", destination
    result = await start_import(client, route, key="file-scoped-import")
    assert result.status_code == 202, result.text
    await get_queue().run_worker_async(wait=False, concurrency=1)
    imported = (await client.get(f"/api/organization/imports/{result.json()['id']}")).json()
    assert imported["entries"][0]["state"] == "confirmed", imported
    async with database() as db:
        fulfillment = await db.scalar(select(DownloadFulfillment))
        assert fulfillment and fulfillment.import_entry_id == UUID(imported["entries"][0]["id"])
        assert fulfillment.evidence["basis"] == "imported"
        selection = await db.get(AcquisitionSelection, UUID(selected_response.json()["id"]))
        assert selection.state == "fulfilled"
        assert (await db.get(AcquisitionReservation, selection.reservation_id)).state == "released"
        assert (await db.scalar(select(DownloadIdentityClaim))).active
    activity = (await client.get(f"/api/acquisition/downloads/{attempt.id}")).json()
    assert activity["fulfillment"]["basis"] == "imported"
    assert activity["fulfillment"]["available_now"]
    output = list(route["target"].rglob("*.epub"))
    assert len(output) == 1 and output[0].stat().st_ino == source.stat().st_ino
    assert output[0].read_bytes() == source.read_bytes() == original
    assert (source.parent / "unrelated.epub").exists()
    assert (await client.get(f"/api/catalog/works/{old['work_id']}")).json()["availability"][
        "owned"
    ]
    repeated = await start_download(client, selected_response.json())
    assert repeated.json()["id"] == started.json()["id"]
    assert qbit.calls.count("submit") == 1
    assert (await start_import(client, route, key="file-scoped-import-again")).json()["entries"][0][
        "state"
    ] == "skipped"
