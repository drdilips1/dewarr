# ruff: noqa: F811
"""Source search and authorized dispatch through real files and fixture ABS confirmation."""

import asyncio
import hashlib
from copy import deepcopy
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
    series_pack=False,
    counterfeit=False,
    automatic_group=False,
    late_join=False,
    reuse_failure=None,
    via_series=False,
    inherited_routes=False,
):
    route = ready_route
    if series_pack:
        monkeypatch.setattr(get_queue().periodic_registry, "periodic_tasks", {})
    work_id = route["plan"]["document"]["groups"][0]["work_id"]
    extension = "epub" if medium == "ebook" else "mp3"
    source = route["source"] / ("selected." + extension)
    if series_pack:
        source = route["source"] / "Coast" / ("First Harbor." + extension)
    if medium == "ebook":
        epub(source, isbn="9781234567897")
        await edition(database, work_id=UUID(work_id))
    else:
        audio(source, tags={"isbn": "9781234567897", "language": "en"})
        await prepare_audio_route(client, database, route, work_id, source)
    epub(route["source"] / "private-neighbor.epub", title="Unrelated private download")
    if counterfeit:
        epub(source, title="Second Harbor", isbn="9780140328721")
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
    if series_pack:
        from tests.pack_fixture import catalog as pack_catalog

        second = await edition(
            database, title="Second Harbor", identifiers={"isbn_13": "9780140328721"}
        )
        await pack_catalog(database, admin["id"], [work_id, second["work"]])
        epub(source.parent / "Second Harbor.epub", title="Second Harbor", isbn="9780140328721")
        contents = {p.name: p.read_bytes() for p in sorted(source.parent.glob("*.epub"))}
        payload = b"".join(contents.values())
        raw = lt.bencode(
            {
                b"info": {
                    b"name": b"Coast",
                    b"piece length": 16384,
                    b"files": [
                        {b"length": len(data), b"path": [name.encode()]}
                        for name, data in contents.items()
                    ],
                    b"pieces": b"".join(
                        hashlib.sha1(payload[pos : pos + 16384]).digest()
                        for pos in range(0, len(payload), 16384)
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
    if series_pack:
        release = release.model_copy(
            update={
                "title": "Coast",
                "raw_title": "Coast Books 1-2",
                "size_bytes": descriptor.torrent_bytes,
            }
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

    async def remember_first():
        from app.db.models import AutomaticImport, Operation

        async with database() as db:
            base = await db.scalar(select(AutomaticImport))
            entry = await db.scalar(select(ImportEntry))
            attempt = await db.scalar(select(DownloadAttempt))
            assert base.import_run_id and attempt.state == "complete"
            paths = {str(p): p.stat().st_ino for p in route["target"].rglob("*.epub")}
            assert len(paths) == 1
            return {
                "run_id": base.import_run_id,
                "entry_id": entry.id,
                "entry_operation": entry.operation_id,
                "receipt": deepcopy((await db.get(Operation, attempt.operation_id)).payload),
                "paths": paths,
            }

    policy = None
    if via_series:
        from app.db.models import Operation
        from app.domain import series_acquisition
        from tests.integration.test_acquisition_defaults import save as save_defaults

        if inherited_routes:
            await save_defaults(
                client,
                {
                    "downloader_id": downloader_id,
                    medium + "_destination_id": route["destination"]["id"],
                },
            )

        series_base = "/api/catalog/series/hardcover/pack-series/requests"
        response = await client.post(
            series_base + "/preview",
            headers={"Idempotency-Key": "automatic-series-preview"},
            json={
                "work_ids": [work_id, str(second["work"])],
                "scope": "complete_series",
                "confirm_main_membership": True,
                "expected_generation": 1,
                "specification": {"mode": medium},
                "automatic": {}
                if inherited_routes
                else {
                    "downloader_id": downloader_id,
                    "downloader_generation": 1,
                    "routes": {
                        medium: {
                            "destination_id": route["destination"]["id"],
                            "destination_revision": route["destination"]["revision"],
                        }
                    },
                },
            },
        )
        assert response.status_code == 201, response.text
        series_request = response.json()["id"]
        assert response.json()["automatic"]
        assert (await client.post(f"{series_base}/{series_request}/submit")).status_code == 202
        route["scan_backend"].detect = not delayed_backend
        await get_queue().run_worker_async(
            wait=False, concurrency=1, listen_notify=False, install_signal_handlers=False
        )

        async def series_tick():
            from copy import deepcopy

            async with database() as db, db.begin():
                parent = await db.get(Operation, UUID(series_request))
                row = await db.get(Operation, UUID(parent.payload["acquisition_id"]))
                payload = deepcopy(row.payload)
                for book in payload["books"].values():
                    if book["next_at"]:
                        book["next_at"] = datetime.now(UTC).isoformat()
                row.payload = payload
                identifier = row.id
            await series_acquisition.run(identifier)
            await get_queue().run_worker_async(
                wait=False, concurrency=1, listen_notify=False, install_signal_handlers=False
            )

        await series_tick()
        async with database() as db:
            operation = await db.scalar(
                select(Operation).where(
                    Operation.kind == automatic_selection.KIND,
                    Operation.payload["work"]["id"].astext == work_id,
                )
            )
            assert operation is not None
            result = (
                await client.get(f"/api/acquisition/automatic-selections/{operation.id}")
            ).json()
    elif via_list:
        from tests.integration.test_acquisition_defaults import save as save_defaults
        from tests.integration.test_list_policies import tick

        await save_defaults(
            client,
            {
                "desired_media": medium,
                "language": "en",
                "required_narrators": ["Jordan Lee"],
                medium + "_library_id": route["library_id"],
                **(
                    {
                        "downloader_id": downloader_id,
                        medium + "_destination_id": route["destination"]["id"],
                    }
                    if inherited_routes
                    else {}
                ),
            },
        )
        shelf = (await client.post("/api/lists", json={"name": "List-to-library fixture"})).json()[
            "id"
        ]
        route["scan_backend"].detect = not delayed_backend
        response = await client.post(
            f"/api/lists/{shelf}/acquisition/preview",
            json={
                "mode": "automatic",
                "specification": {
                    "download_constraints": {
                        "maximum_bytes": descriptor.torrent_bytes,
                        "blocked_formats": ["pdf" if medium == "ebook" else "flac"],
                    },
                },
                "preference_overrides": {"criteria": ["seeders", "format", "source"]},
                "downloader_id": None if inherited_routes else downloader_id,
                "downloader_generation": None if inherited_routes else 1,
                "routes": {}
                if inherited_routes
                else {
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
        if automatic_group or late_join:
            import json

            second_shelf = (
                await client.post("/api/lists", json={"name": "Second independent pack list"})
            ).json()["id"]
            second_preview = await client.post(
                f"/api/lists/{second_shelf}/acquisition/preview",
                json=json.loads(response.request.content),
                headers={"Idempotency-Key": "second-pack-list-preview"},
            )
            assert second_preview.status_code == 201, second_preview.text
            second_activation = await client.post(
                f"/api/lists/{second_shelf}/acquisition/previews/{second_preview.json()['id']}/activate"
            )
            assert second_activation.status_code == 200, second_activation.text
            second_policy = second_activation.json()
            if not late_join:
                assert (
                    await client.post(
                        f"/api/lists/{second_shelf}/entries", json={"work_id": str(second["work"])}
                    )
                ).status_code == 204
                assert (
                    await client.post(
                        f"/api/lists/{second_shelf}/entries", json={"work_id": work_id}
                    )
                ).status_code == 204
        added = await client.post(f"/api/lists/{shelf}/entries", json={"work_id": work_id})
        assert added.status_code == 204
        if automatic_group:
            # Both independent policies authorize searches before either transfer starts.
            for saved_policy in [policy, second_policy]:
                await tick(database, saved_policy, worker=False)
            await get_queue().run_worker_async(
                wait=False, concurrency=1, listen_notify=False, install_signal_handlers=False
            )
            for saved_policy in [policy, second_policy]:
                await tick(database, saved_policy, worker=False, force_books=True)
            await get_queue().run_worker_async(
                wait=False, concurrency=1, listen_notify=False, install_signal_handlers=False
            )
        else:
            await tick(database, policy)
            await tick(database, policy, force_books=True)
        async with database() as db:
            from app.db.models import Operation

            operation = await db.scalar(
                select(Operation).where(
                    Operation.kind == automatic_selection.KIND,
                    Operation.payload["work"]["id"].astext == str(work_id),
                )
            )
            assert operation is not None
            identifier = operation.id
        result = (await client.get(f"/api/acquisition/automatic-selections/{identifier}")).json()
        if late_join:
            prior_import = await remember_first()
            for value in [str(second["work"]), work_id]:
                assert (
                    await client.post(f"/api/lists/{second_shelf}/entries", json={"work_id": value})
                ).status_code == 204
            await tick(database, second_policy)
            await tick(database, second_policy, force_books=True)
    else:
        wanted = await request(
            client,
            body(
                {"work": work_id},
                medium,
                **{medium + "_library_id": route["library_id"]},
                **({"required_narrators": ["Jordan Lee"]} if medium == "audio" else {}),
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
        if late_join:
            await get_queue().run_worker_async(
                wait=False, concurrency=1, listen_notify=False, install_signal_handlers=False
            )
            prior_import = await remember_first()
        if automatic_group or late_join:
            second_wanted = await request(
                client,
                body({"work": second["work"]}, "ebook", ebook_library_id=route["library_id"]),
            )
            second_search = await client.post(
                f"/api/catalog/works/{second['work']}/source-searches",
                json={"medium": "ebook"},
                headers={"Idempotency-Key": "second-automatic-pack-search"},
            )
            assert second_search.status_code == 202, second_search.text
            await book_sources.run(UUID(second_search.json()["id"]), "mam")
            second_command = {
                **command,
                "intent_id": second_wanted["request"]["id"],
                "search_id": second_search.json()["id"],
            }
            second_response = await client.post(
                "/api/acquisition/automatic-selections",
                json=second_command,
                headers={"Idempotency-Key": "second-automatic-pack-command"},
            )
            assert second_response.status_code == 202, second_response.text
        if reuse_failure:
            saved_states = deepcopy(qbit.states)
            if reuse_failure == "missing":
                qbit.states = []
            else:
                qbit.states[0].files[0].relative_path += ".renamed"
        await get_queue().run_worker_async(
            wait=False, concurrency=1, listen_notify=False, install_signal_handlers=False
        )
        result = (
            await client.get(f"/api/acquisition/automatic-selections/{response.json()['id']}")
        ).json()
    assert result["status"] == "completed" and result["download_id"], result
    if automatic_group or late_join or via_series:
        from app.db.models import DownloadMembership, Operation
        from app.domain import automatic_packs

        async with database() as db:
            second_operation = await db.scalar(
                select(Operation).where(
                    Operation.kind == automatic_selection.KIND,
                    Operation.payload["work"]["id"].astext == str(second["work"]),
                )
            )
            assert second_operation is not None
        second_result = (
            await client.get(f"/api/acquisition/automatic-selections/{second_operation.id}")
        ).json()

        if reuse_failure:
            from app.db.models import AutomaticImportContinuation
            from app.importing import reuse

            async with database() as db:
                continuation = await db.scalar(select(AutomaticImportContinuation))
                assert continuation.state == "held", continuation.message
                created = continuation.created_at
                assert await db.scalar(select(func.count()).select_from(ImportEntry)) == 1
            current = (
                await client.get(f"/api/acquisition/downloads/{result['download_id']}")
            ).json()
            assert current["import_continuations"][0]["state"] == "held", current
            assert qbit.calls.count("submit") == 1
            qbit.states = saved_states
            async with database() as db, db.begin():
                attempt = await db.get(DownloadAttempt, UUID(result["download_id"]))
                await reuse.recheck(db, attempt)
            await get_queue().run_worker_async(
                wait=False, concurrency=1, listen_notify=False, install_signal_handlers=False
            )
            async with database() as db:
                assert (
                    await db.get(AutomaticImportContinuation, continuation.id)
                ).created_at == created

        assert second_result["download_id"] == result["download_id"], second_result
        async with database() as db:
            entries = list(await db.scalars(select(ImportEntry)))
            assert len(entries) == 2
            assert {entry.state for entry in entries} == {
                "awaiting-library" if delayed_backend else "confirmed"
            }
            assert await db.scalar(select(func.count()).select_from(DownloadMembership)) == 2
            assert await db.scalar(select(func.count()).select_from(DownloadAttempt)) == 1
            if late_join:
                from app.db.models import AutomaticImport, AutomaticImportContinuation

                base = await db.scalar(select(AutomaticImport))
                continuation = await db.scalar(select(AutomaticImportContinuation))
                assert base.import_run_id == prior_import["run_id"]
                assert continuation and continuation.state == "importing", (
                    continuation.message if continuation else second_result
                )
                assert continuation.import_run_id != prior_import["run_id"]
                assert (
                    await db.get(ImportEntry, prior_import["entry_id"])
                ).operation_id == prior_import["entry_operation"]
                from fastapi import HTTPException

                from app.db.models import Version
                from app.importing.automatic import publication_authority

                original_entry = await db.get(ImportEntry, prior_import["entry_id"])
                # The old book still has a valid request, but cannot lend its
                # authorization to the separate continuation for the new book.
                with pytest.raises(HTTPException, match="outside the reviewed transfer scope"):
                    await publication_authority(
                        db,
                        continuation.import_run_id,
                        version=await db.get(Version, original_entry.version_id),
                        destination_id=original_entry.destination_id,
                    )
                attempt = await db.scalar(select(DownloadAttempt))
                assert (await db.get(Operation, attempt.operation_id)).payload == prior_import[
                    "receipt"
                ]
                for path, inode in prior_import["paths"].items():
                    from pathlib import Path

                    assert (await asyncio.to_thread(Path(path).stat)).st_ino == inode
            if via_list:
                proofs = [
                    item.frozen["automatic_selection"]["list_authority"]
                    for item in await db.scalars(select(AcquisitionSelection))
                ]
                assert {proof["list_id"] for proof in proofs} == {shelf, second_shelf}
        if delayed_backend:
            route["scan_backend"].detect = True
            route["scan_backend"].scan()
            for entry in entries:
                await execution.execute(entry.operation_id)
            await get_queue().run_worker_async(
                wait=False, concurrency=1, listen_notify=False, install_signal_handlers=False
            )
        async with database() as db:
            assert set(await db.scalars(select(ImportEntry.state))) == {"confirmed"}
            assert await db.scalar(select(func.count()).select_from(DownloadFulfillment)) == 2
        if late_join:
            current = (
                await client.get(f"/api/acquisition/downloads/{result['download_id']}")
            ).json()
            assert current["import_continuations"][0]["state"] == "complete", current
            assert sum(bool(item["join_operation_id"]) for item in current["members"]) == 1
        for identifier in [result["id"], second_result["id"]]:
            await automatic_packs.run(UUID(identifier))
        await downloads.run(UUID(result["download_id"]))
        assert qbit.calls.count("submit") == 1
        for identifier in [work_id, second["work"]]:
            assert (await client.get(f"/api/catalog/works/{identifier}")).json()["availability"][
                "owned"
            ]
        if via_series:
            await series_tick()
            final = (await client.get(f"{series_base}/{series_request}")).json()
            assert final["acquisition_status"] == "completed", final
            assert {r["acquisition_state"] for r in final["records"]} == {"available"}, final
            assert final["counts"]["satisfied"] == 2
            async with database() as db:
                selections = list(await db.scalars(select(AcquisitionSelection)))
                assert all(
                    s.frozen["automatic_selection"]["series_authority"]["operation_id"]
                    == series_request
                    for s in selections
                )
        assert {p.name: p.read_bytes() for p in source.parent.glob("*.epub")} == contents
        imported = list(route["target"].rglob("*.epub"))
        assert len(imported) == 2
        for path in source.parent.glob("*.epub"):
            assert any(dest.stat().st_ino == path.stat().st_ino for dest in imported)
        return
    if counterfeit:
        from app.db.models import AutomaticImport

        async with database() as db:
            automatic_import = await db.scalar(select(AutomaticImport))
            assert automatic_import and automatic_import.state == "held", automatic_import.message
            assert not await db.scalar(select(ImportEntry.id))
            assert not await db.scalar(select(DownloadFulfillment.id))
        assert not (await client.get(f"/api/catalog/works/{work_id}")).json()["availability"][
            "owned"
        ]
        assert qbit.calls.count("submit") == 1
        assert source.read_bytes() == original
        return
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
        assert policy["configuration"]["specification"]["mode"] == medium
        assert policy["configuration"]["specification"]["language"] == "en"
        if medium == "audio":
            assert policy["configuration"]["specification"]["required_narrators"] == ["Jordan Lee"]
            assert (
                policy["configuration"]["profile"]["scope_origins"]["required_narrators"]
                == "Personal default"
            )
        else:
            assert not policy["configuration"]["specification"].get("required_narrators")
        assert policy["configuration"]["profile"]["scope_origins"]["mode"] == "Personal default"
        assert policy["configuration"]["profile"]["scope_origins"]["language"] == "Personal default"
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
    assert qbit.calls.count("submit") == 1
    assert source_calls == (
        ["search", "search", "resolve"] if series_pack else ["search", "resolve"]
    )
    if series_pack:
        assert len(result["decisions"][0]["coverage"]["members"]) == 2
        assert not (await client.get(f"/api/catalog/works/{second['work']}")).json()[
            "availability"
        ]["owned"]
        assert {p.name: p.read_bytes() for p in source.parent.glob("*.epub")} == contents


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


@pytest.mark.parametrize("via_list", [False, True])
@pytest.mark.parametrize("delayed_backend", [False, True])
async def test_known_pack_reaches_requested_library_without_importing_unrequested_sibling(
    client, admin, database, ready_route, review_account, monkeypatch, via_list, delayed_backend
):
    await test_search_to_automatic_download_and_confirmed_member_library(
        client,
        admin,
        database,
        ready_route,
        review_account,
        monkeypatch,
        "ebook",
        delayed_backend,
        request_limits=True,
        via_list=via_list,
        series_pack=True,
    )


async def test_pack_filename_cannot_override_wrong_downloaded_book_identity(
    client, admin, database, ready_route, review_account, monkeypatch
):
    await test_search_to_automatic_download_and_confirmed_member_library(
        client,
        admin,
        database,
        ready_route,
        review_account,
        monkeypatch,
        "ebook",
        False,
        request_limits=True,
        series_pack=True,
        counterfeit=True,
    )


@pytest.mark.parametrize("delayed_backend", [False, True])
@pytest.mark.parametrize("via_list", [False, True])
async def test_automatic_pack_groups_two_requests_and_confirms_both_books(
    client, admin, database, ready_route, review_account, monkeypatch, delayed_backend, via_list
):
    await test_search_to_automatic_download_and_confirmed_member_library(
        client,
        admin,
        database,
        ready_route,
        review_account,
        monkeypatch,
        "ebook",
        delayed_backend,
        request_limits=True,
        series_pack=True,
        automatic_group=True,
        via_list=via_list,
    )


@pytest.mark.parametrize("delayed_backend", [False, True])
@pytest.mark.parametrize("via_list", [False, True])
async def test_later_pack_request_imports_from_completed_transfer_without_republishing(
    client, admin, database, ready_route, review_account, monkeypatch, delayed_backend, via_list
):
    await test_search_to_automatic_download_and_confirmed_member_library(
        client,
        admin,
        database,
        ready_route,
        review_account,
        monkeypatch,
        "ebook",
        delayed_backend,
        request_limits=True,
        series_pack=True,
        late_join=True,
        via_list=via_list,
    )


@pytest.mark.parametrize("failure", ["missing", "renamed"])
async def test_completed_pack_reuse_checks_saved_files_and_recovers_without_new_transfer(
    client, admin, database, ready_route, review_account, monkeypatch, failure
):
    await test_search_to_automatic_download_and_confirmed_member_library(
        client,
        admin,
        database,
        ready_route,
        review_account,
        monkeypatch,
        "ebook",
        False,
        request_limits=True,
        series_pack=True,
        late_join=True,
        reuse_failure=failure,
    )


@pytest.mark.parametrize("delayed_backend", [False, True])
async def test_reviewed_complete_series_automatically_acquires_and_confirms_each_book(
    client, admin, database, ready_route, review_account, monkeypatch, delayed_backend
):
    await test_search_to_automatic_download_and_confirmed_member_library(
        client,
        admin,
        database,
        ready_route,
        review_account,
        monkeypatch,
        "ebook",
        delayed_backend,
        request_limits=True,
        series_pack=True,
        via_series=True,
    )


@pytest.mark.parametrize("via_series", [False, True])
@pytest.mark.parametrize("delayed_backend", [False, True])
async def test_inherited_routes_reach_confirmed_library_through_list_or_series(
    client, admin, database, ready_route, review_account, monkeypatch, via_series, delayed_backend
):
    await test_search_to_automatic_download_and_confirmed_member_library(
        client,
        admin,
        database,
        ready_route,
        review_account,
        monkeypatch,
        "ebook",
        delayed_backend,
        request_limits=True,
        series_pack=via_series,
        via_series=via_series,
        via_list=not via_series,
        inherited_routes=True,
    )
