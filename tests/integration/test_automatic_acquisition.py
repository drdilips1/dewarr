# ruff: noqa: F811
"""Source search and authorized dispatch through real files and fixture ABS confirmation."""

import hashlib
from datetime import UTC, datetime
from uuid import UUID

import libtorrent as lt
import pytest
from sqlalchemy import func, select

from app.adapters.mam import MAMArtifact, MAMRelease, ReleasePage
from app.adapters.torrent_descriptor import inspect_torrent
from app.config import get_settings
from app.db.models import (
    AcquisitionSelection,
    DownloadAttempt,
    DownloadCapacity,
    DownloadFulfillment,
    ImportEntry,
    Integration,
    LibraryGrant,
    SourceConnection,
    User,
)
from app.domain import automatic_selection, book_sources
from app.domain import download_attempts as downloads
from app.importing import execution
from app.jobs.queue import get_queue
from app.security import encrypt_secrets
from tests.integration.test_acquisition import body, request
from tests.integration.test_download_attempts import Client
from tests.integration.test_download_reviews import review_account  # noqa: F401
from tests.integration.test_import_destinations import route as destination_route  # noqa: F401
from tests.integration.test_import_execution import ready_route  # noqa: F401
from tests.integration.test_inspection_matching import edition
from tests.integration.test_single_file_acquisition import prepare_audio_route
from tests.media_fixtures import audio, epub

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("medium", ["ebook", "audio"])
@pytest.mark.parametrize("delayed_backend", [False, True])
@pytest.mark.parametrize("request_limits", [False, True])
async def test_search_to_automatic_download_and_confirmed_member_library(
    client,
    admin,
    database,
    ready_route,
    review_account,
    monkeypatch,
    medium,
    delayed_backend,
    request_limits,
    via_list=False,
):
    route = ready_route
    work_id = route["plan"]["document"]["groups"][0]["work_id"]
    extension = "epub" if medium == "ebook" else "mp3"
    source = route["source"] / ("selected." + extension)
    if medium == "ebook":
        epub(source, isbn="9781234567897")
        await edition(database, work_id=UUID(work_id))
    else:
        audio(source, tags={"isbn": "9781234567897", "language": "en"})
        await prepare_audio_route(client, database, route, work_id, source)
    epub(source.parent / "private-neighbor.epub", title="Unrelated private download")
    original = source.read_bytes()
    raw = lt.bencode(
        {
            b"info": {
                b"name": source.name.encode(),
                b"length": len(original),
                b"piece length": 16384,
                b"pieces": b"".join(
                    hashlib.sha1(original[pos : pos + 16384]).digest()
                    for pos in range(0, len(original), 16384)
                ),
            }
        }
    )
    descriptor = await inspect_torrent(raw)
    release = MAMRelease(
        source_id="502",
        title="First Harbor",
        raw_title="First Harbor",
        authors=["Alex Morgan"],
        narrators=["Jordan Lee"] if medium == "audio" else [],
        medium=medium,
        language="en",
        formats=[extension],
        size_bytes=len(original),
        seeders=42,
        isbn="9781234567897",
        protocol="torrent",
        observed_at=datetime.now(UTC),
    )
    async with database() as db, db.begin():
        db.add(
            SourceConnection(
                key="mam",
                base_url="https://mam.test",
                encrypted_secrets=encrypt_secrets({"mam_id": "fixture-only"}),
            )
        )
        downloader = Integration(
            kind="qbittorrent",
            name="Synthetic downloader",
            base_url="http://qbit.test",
            encrypted_secrets=encrypt_secrets({"username": "fixture", "password": "fixture"}),
            credential_generation=1,
            status="connected",
            config={
                "save_path": "/downloads",
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
        db.add(downloader)
        await db.flush()
        downloader_id = str(downloader.id)
        member = await db.get(User, UUID(admin["id"]))
        member.role, member.can_automate = "member", True
        db.add(LibraryGrant(user_id=UUID(admin["id"]), library_id=UUID(route["library_id"])))

    monkeypatch.setattr(get_settings(), "download_dispatch_enabled", True)
    approval = await review_account[0].put(
        f"/api/organization/destinations/{route['destination']['id']}/automatic-import",
        json={
            "enabled": True,
            "expected_generation": 0,
            "destination_revision": route["destination"]["revision"],
        },
    )
    assert approval.status_code == 200 and approval.json()["ready"], approval.text
    source_calls = []

    async def source_call(owner, action, value, **kwargs):
        assert owner == UUID(admin["id"])
        source_calls.append(action)
        if action == "search":
            return ReleasePage(items=[release], offset=0, limit=50, total=1, has_more=False), 1
        assert action == "resolve" and value == "502"
        return MAMArtifact(release=release, content=raw), 1

    monkeypatch.setattr(book_sources, "source_call", source_call)
    monkeypatch.setattr(automatic_selection, "source_call", source_call)
    qbit = Client(database, descriptor.model_dump(mode="json"))
    qbit.complete = True
    monkeypatch.setattr(downloads, "QbitClient", lambda *args: qbit)
    policy = None
    if via_list:
        from tests.integration.test_list_policies import tick

        shelf = (await client.post("/api/lists", json={"name": "List-to-library fixture"})).json()[
            "id"
        ]
        route["scan_backend"].detect = not delayed_backend
        response = await client.post(
            f"/api/lists/{shelf}/acquisition/preview",
            json={
                "mode": "automatic",
                "specification": {
                    "mode": medium,
                    "download_constraints": {
                        "maximum_bytes": descriptor.torrent_bytes,
                        "blocked_formats": ["pdf" if medium == "ebook" else "flac"],
                    },
                },
                "preference_overrides": {"criteria": ["seeders", "format", "source"]},
                "downloader_id": downloader_id,
                "downloader_generation": 1,
                "routes": {
                    medium: {
                        "destination_id": route["destination"]["id"],
                        "destination_revision": route["destination"]["revision"],
                    }
                },
            },
            headers={"Idempotency-Key": "list-to-library-preview"},
        )
        assert response.status_code == 201, response.text
        activation_url = f"/api/lists/{shelf}/acquisition/previews/{response.json()['id']}/activate"
        activation = await client.post(activation_url)
        assert activation.status_code == 200, activation.text
        policy = activation.json()
        added = await client.post(f"/api/lists/{shelf}/entries", json={"work_id": work_id})
        assert added.status_code == 204
        await tick(database, policy)
        await tick(database, policy, force_books=True)
        async with database() as db:
            from app.db.models import Operation

            operation = await db.scalar(
                select(Operation).where(Operation.kind == automatic_selection.KIND)
            )
            assert operation is not None
            identifier = operation.id
        result = (await client.get(f"/api/acquisition/automatic-selections/{identifier}")).json()
    else:
        wanted = await request(
            client,
            body(
                {"work": work_id},
                medium,
                **{medium + "_library_id": route["library_id"]},
                **(
                    {
                        "download_constraints": {
                            "maximum_bytes": descriptor.torrent_bytes,
                            "blocked_formats": ["pdf" if medium == "ebook" else "flac"],
                        }
                    }
                    if request_limits
                    else {}
                ),
            ),
        )
        search = await client.post(
            f"/api/catalog/works/{work_id}/source-searches",
            json={"medium": medium},
            headers={"Idempotency-Key": "automatic-acquisition-search"},
        )
        assert search.status_code == 202, search.text
        await get_queue().run_worker_async(wait=False, concurrency=1)
        command = {
            "intent_id": wanted["request"]["id"],
            "slot": medium,
            "search_id": search.json()["id"],
            "downloader_id": downloader_id,
            "downloader_generation": 1,
            "destination_id": route["destination"]["id"],
            "destination_revision": route["destination"]["revision"],
            "download_when_ready": True,
        }
        route["scan_backend"].detect = not delayed_backend
        response = await client.post(
            "/api/acquisition/automatic-selections",
            json=command,
            headers={"Idempotency-Key": "automatic-acquisition-command"},
        )
        assert response.status_code == 202, response.text
        await get_queue().run_worker_async(wait=False, concurrency=1)
        result = (
            await client.get(f"/api/acquisition/automatic-selections/{response.json()['id']}")
        ).json()
    assert result["status"] == "completed" and result["download_id"], result
    async with database() as db:
        selection = await db.get(AcquisitionSelection, UUID(result["selection_id"]))
        if request_limits:
            preferences = selection.frozen["profile"]["preferences"]
            assert preferences["maximum_bytes"] == descriptor.torrent_bytes
            assert preferences["blocked_formats"] == ["pdf" if medium == "ebook" else "flac"]
        entries = list(await db.scalars(select(ImportEntry)))
        assert len(entries) == 1
        entry = entries[0]
        assert entry.state == ("awaiting-library" if delayed_backend else "confirmed"), (
            entry.message
        )
        capacity = await db.get(DownloadCapacity, UUID(result["download_id"]))
        assert capacity.automatic and capacity.submitted_at
    if delayed_backend:
        book = (await client.get(f"/api/catalog/works/{work_id}")).json()
        assert not book["availability"]["owned"]
        route["scan_backend"].detect = True
        route["scan_backend"].scan()
        await execution.execute(entry.operation_id)
        await get_queue().run_worker_async(wait=False, concurrency=1)
    async with database() as db:
        assert (await db.get(ImportEntry, entry.id)).state == "confirmed"
        fulfillment = await db.scalar(select(DownloadFulfillment))
        assert fulfillment and fulfillment.import_entry_id == entry.id
        assert await db.scalar(select(func.count()).select_from(DownloadAttempt)) == 1
    output = list(route["target"].rglob("*." + extension))
    assert len(output) == 1 and output[0].stat().st_ino == source.stat().st_ino
    assert output[0].read_bytes() == original == source.read_bytes()
    assert not list(route["target"].rglob("private-neighbor.epub"))
    book = (await client.get(f"/api/catalog/works/{work_id}")).json()
    assert book["availability"]["owned"] and book["availability"][medium]
    if via_list:
        assert (await client.post(activation_url)).json()["id"] == policy["id"]
        await tick(database, policy, force_books=True)
    else:
        repeated = await client.post(
            "/api/acquisition/automatic-selections",
            json=command,
            headers={"Idempotency-Key": "automatic-acquisition-command"},
        )
        assert repeated.json()["download_id"] == result["download_id"]
    await automatic_selection.run(UUID(result["id"]))
    await downloads.run(UUID(result["download_id"]))
    assert qbit.calls.count("submit") == 1 and source_calls == ["search", "resolve"]


@pytest.mark.parametrize("medium", ["ebook", "audio"])
@pytest.mark.parametrize("delayed_backend", [False, True])
async def test_list_addition_reaches_confirmed_library_without_per_title_commands(
    client, admin, database, ready_route, review_account, monkeypatch, medium, delayed_backend
):
    await test_search_to_automatic_download_and_confirmed_member_library(
        client,
        admin,
        database,
        ready_route,
        review_account,
        monkeypatch,
        medium,
        delayed_backend,
        request_limits=True,
        via_list=True,
    )
