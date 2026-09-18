"""Optional real-server import workflow used by certify_abs, with a disposable DB."""

import asyncio
import hashlib
from unittest.mock import patch
from uuid import UUID

import httpx
from sqlalchemy import select, text

from app.config import get_settings
from app.db.models import Base, Version, Work
from app.db.session import get_engine, session_factory
from app.importing.execution import execute
from app.jobs.queue import get_queue
from app.main import create_app
from tests.cover_fixture import COVER_URL, CoverServiceFixture
from tests.media_fixtures import audio, cbz, epub, pdf


async def certify_workflow(base, token, root, backend_client, medium="ebook", *, case=None):
    case = case or medium
    target = root / f"workflow-library-{case}"
    target.mkdir()
    settings = get_settings()
    settings.import_sources = {"native": root / "downloads"}
    settings.import_destinations = {medium: target}
    settings.import_staging_root = root / "staging"
    if not settings.database_url.get_secret_value().endswith("_abs_test"):
        raise RuntimeError("Native workflow requires a dedicated _abs_test database")
    async with get_engine().begin() as db:
        tables = ", ".join(f'public."{name}"' for name in Base.metadata.tables)
        await db.execute(
            text(
                f"TRUNCATE {tables}, book_queue.procrastinate_jobs, "
                "book_queue.procrastinate_workers RESTART IDENTITY CASCADE"
            )
        )
    response = await backend_client.post(
        "api/libraries",
        json={
            "name": f"Workflow certification {case}",
            "mediaType": "book",
            "folders": [{"fullPath": str(target)}],
            "settings": {"disableWatcher": True, "audiobooksOnly": False},
        },
    )
    response.raise_for_status()
    external_library = response.json()["id"]
    title = f"Workflow Harbor {case}"
    source = root / "downloads" / f"workflow-{case}"
    if medium == "ebook":
        if case in {"pdf", "cbz"}:
            {"pdf": pdf, "cbz": cbz}[case](
                source / f"book.{case}", title=title, author="Fixture Author"
            )
        else:
            epub(source / "book.epub", title=title, author="Fixture Author")
            if case == "ebook-formats":
                pdf(source / "book.pdf", title=title, author="Fixture Author")
    else:
        # Separate folders deliberately require a reviewed merge before import.
        audio(source / "part-a/01.mp3", title=title, author="Fixture Author", track=1)
        if case == "audio-companion":
            pdf(source / "companion.pdf", title="Supporting notes", author="Fixture Author")
        else:
            audio(source / "part-b/02.mp3", title=title, author="Fixture Author", track=2)
    source_bytes = {path: path.read_bytes() for path in source.rglob("*") if path.is_file()}
    queue = get_queue()
    cover_service = CoverServiceFixture()
    cover_patch = patch("app.importing.execution.fetch_cover", new=cover_service.fetch)
    cover_patch.start()
    try:
        async with (
            queue.open_async(),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=create_app()),
                base_url=settings.public_url,
                headers={"Origin": settings.public_url},
            ) as client,
        ):

            async def request(method, path, expected=200, **kwargs):
                response = await client.request(method, path, **kwargs)
                assert response.status_code == expected, (path, response.status_code, response.text)
                return response.json()

            async def drain():
                await asyncio.wait_for(
                    queue.run_worker_async(wait=False, concurrency=1), timeout=45
                )

            bootstrap = await request(
                "POST",
                "/api/auth/bootstrap",
                201,
                json={
                    "username": "native-fixture",
                    "password": "disposable fixture password",
                    "display_name": "Native fixture",
                    "bootstrap_token": settings.bootstrap_token.get_secret_value(),
                },
            )
            client.headers["X-CSRF-Token"] = bootstrap["csrf_token"]
            connection = await request(
                "POST",
                "/api/integrations",
                201,
                json={"name": "Disposable real ABS", "base_url": base, "token": token},
            )
            await request(
                "POST",
                f"/api/integrations/{connection['id']}/sync",
                202,
                headers={"Idempotency-Key": "native-inventory"},
            )
            await drain()
            libraries = await request("GET", "/api/library/libraries")
            library = next(
                row for row in libraries if row["name"] == f"Workflow certification {case}"
            )
            assert library["accessible"]
            work = await request(
                "POST",
                "/api/catalog/works",
                201,
                json={"title": title, "authors": ["Fixture Author"], "language": "en"},
            )
            async with session_factory()() as db, db.begin():
                (await db.get(Work, UUID(work["id"]))).cover_url = COVER_URL
                version = Version(
                    work_id=UUID(work["id"]),
                    medium=medium,
                    language="en",
                    publication_year=2024,
                    narrators=["Jordan Lee"] if medium == "audio" else [],
                )
                db.add(version)
                await db.flush()
                version_id = str(version.id)
            inspection = await request(
                "POST",
                "/api/organization/inspections",
                202,
                headers={"Idempotency-Key": "native-inspection"},
                json={
                    "source_key": "native",
                    "relative_path": source.name,
                    "completed_download": True,
                },
            )
            await drain()
            inspection = await request("GET", f"/api/organization/inspections/{inspection['id']}")
            grouping = await request(
                "GET", f"/api/organization/inspections/{inspection['id']}/grouping"
            )
            if medium == "audio" or case == "ebook-formats":
                assert len(grouping["content"]["groups"]) == 2
                grouping = await request(
                    "PUT",
                    f"/api/organization/inspections/{inspection['id']}/grouping",
                    json={
                        "inspection_revision": inspection["snapshot"]["revision"],
                        "expected_revision": grouping["revision"],
                        "groups": [
                            {
                                "same_edition": case == "ebook-formats",
                                "files": [
                                    {
                                        **{key: file.get(key) for key in ("path", "disc", "track")},
                                        "role": "supplement"
                                        if case == "audio-companion"
                                        and file["path"].endswith(".pdf")
                                        else "media",
                                    }
                                    for group in grouping["content"]["groups"]
                                    for file in group["files"]
                                ],
                            }
                        ],
                        "excluded": [],
                    },
                )
                assert len(grouping["content"]["groups"]) == 1
            naming = await request("GET", "/api/organization/settings")
            plan = await request(
                "POST",
                f"/api/organization/inspections/{inspection['id']}/plans",
                201,
                json={
                    "inspection_revision": inspection["snapshot"]["revision"],
                    "profile_revision": naming["revision"],
                    "grouping_revision": grouping["revision"],
                    "selections": [
                        {
                            "group_key": grouping["content"]["groups"][0]["key"],
                            "work_id": work["id"],
                            "version_id": version_id,
                            "full_content": True,
                        }
                    ],
                },
            )
            destination = await request(
                "PUT",
                f"/api/organization/destinations/{medium}",
                json={"library_id": library["id"], "medium": medium, "backend_path": str(target)},
            )
            await request(
                "POST",
                f"/api/organization/destinations/{destination['id']}/probe",
                202,
                headers={"Idempotency-Key": "native-destination"},
                json={"plan_id": plan["id"], "expected_revision": destination["revision"]},
            )
            await drain()
            destination = (await request("GET", "/api/organization/destinations"))[0]
            assert destination["publication_available"], destination.get("probe")
            body = {
                "plan_revision": plan["revision"],
                "destinations": {
                    medium: {"id": destination["id"], "revision": destination["revision"]}
                },
            }
            stopped = await request(
                "POST",
                f"/api/organization/plans/{plan['id']}/imports",
                202,
                headers={"Idempotency-Key": "native-cancel-before-publication"},
                json=body,
            )
            await request(
                "POST",
                f"/api/organization/imports/{stopped['id']}/entries/{stopped['entries'][0]['id']}/cancel",
                202,
            )
            await drain()
            stopped = await request("GET", f"/api/organization/imports/{stopped['id']}")
            assert stopped["entries"][0]["state"] == "cancelled", stopped
            assert not [path for path in target.rglob("*") if path.is_file()]
            assert all(path.read_bytes() == data for path, data in source_bytes.items())
            run = await request(
                "POST",
                f"/api/organization/plans/{plan['id']}/imports",
                202,
                headers={"Idempotency-Key": "native-publication"},
                json=body,
            )
            await drain()
            for _ in range(40):
                current = await request("GET", f"/api/organization/imports/{run['id']}")
                entry = current["entries"][0]
                if entry["state"] == "confirmed":
                    break
                assert entry["state"] == "awaiting-library", entry
                await asyncio.sleep(0.25)
                await execute(UUID(entry["operation_id"]))
            assert entry["state"] == "confirmed", entry
            assert (
                entry["cover_export"]["backend_selected"] and entry["cover_export"]["unchanged"]
            ), entry
            covers = list(target.rglob("cover.jpg"))
            assert len(covers) == 1 and covers[0].stat().st_nlink == 1
            assert (
                hashlib.sha256(covers[0].read_bytes()).hexdigest()
                == entry["cover_export"]["sha256"]
            )
            owned = await request("GET", f"/api/catalog/works/{work['id']}")
            assert owned["availability"]["owned"] and owned["availability"][medium]
            assert not owned["availability"]["audio" if medium == "ebook" else "ebook"]
            published = [
                path
                for path in target.rglob("*")
                if path.suffix in {".epub", ".pdf", ".cbz", ".mp3"}
            ]
            assert len(published) == len(source_bytes)
            for original, content in source_bytes.items():
                matches = [
                    path for path in published if path.stat().st_ino == original.stat().st_ino
                ]
                assert (
                    len(matches) == 1
                    and matches[0].read_bytes() == original.read_bytes() == content
                )
            copies = (await request("GET", "/api/library/assets", params={"work_id": work["id"]}))[
                "items"
            ]
            expected_formats = sorted(
                {
                    path.suffix[1:]
                    for path in source_bytes
                    if medium == "ebook" or path.suffix != ".pdf"
                }
            )
            owned_copy = next(copy for copy in copies if copy["medium"] == medium)
            assert owned_copy["formats"] == expected_formats, copies
            await request(
                "POST",
                f"/api/integrations/{connection['id']}/sync",
                202,
                headers={"Idempotency-Key": "native-post-import-inventory"},
            )
            await drain()
            copies = (await request("GET", "/api/library/assets", params={"work_id": work["id"]}))[
                "items"
            ]
            assert (
                next(copy for copy in copies if copy["medium"] == medium)["formats"]
                == expected_formats
            ), (case, expected_formats, copies)
            owned = await request("GET", f"/api/catalog/works/{work['id']}")
            assert not owned["availability"]["audio" if medium == "ebook" else "ebook"]
            async with session_factory()() as db:
                versions = (
                    await db.scalars(select(Version).where(Version.work_id == UUID(work["id"])))
                ).all()
                assert len(versions) == 1, (
                    "Formats and companion PDFs must not invent catalog editions"
                )
            # A later operator edit is never replaced by a repeat import.
            from app.importing.cover_image import normalize
            from tests.media_fixtures import cover_bytes

            changed_cover = normalize(cover_bytes(color="green"))
            covers[0].write_bytes(changed_cover)
            second = await request(
                "POST",
                f"/api/organization/plans/{plan['id']}/imports",
                202,
                headers={"Idempotency-Key": "native-duplicate-check"},
                json=body,
            )
            assert second["entries"][0]["state"] == "skipped"
            assert covers[0].read_bytes() == changed_cover and len(cover_service.calls) == 1
            return {
                "confirmed": True,
                "owned": True,
                "source_preserved": True,
                "duplicate_skipped": True,
                "cancelled_before_publication": True,
                "cover_selected_by_abs": True,
                "later_cover_edit_preserved": True,
                "cover_http": "synthetic fixture; real decoder and ABS scanner",
                "medium": medium,
                "case": case,
                "formats": expected_formats,
                "formats_survive_inventory_refresh": True,
                "single_catalog_version": True,
                "reviewed_group_merge": medium == "audio" or case == "ebook-formats",
                "playback_order_confirmed": case == "audio",
                "companion_not_owned_as_ebook": case == "audio-companion",
                "catalog_version_seeded": True,
                "server_library_id": external_library,
            }
    finally:
        cover_patch.stop()
        # This database is disposable; do not retain ephemeral server credentials.
        async with get_engine().begin() as db:
            await db.execute(
                text(
                    f"TRUNCATE {tables}, book_queue.procrastinate_jobs, "
                    "book_queue.procrastinate_workers RESTART IDENTITY CASCADE"
                )
            )
        await get_engine().dispose()
