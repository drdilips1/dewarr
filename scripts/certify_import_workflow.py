"""Optional real-server import workflow used by certify_abs, with a disposable DB."""

import asyncio
from uuid import UUID

import httpx
from sqlalchemy import text

from app.config import get_settings
from app.db.models import Base, Version
from app.db.session import get_engine, session_factory
from app.importing.execution import execute
from app.jobs.queue import get_queue
from app.main import create_app
from tests.media_fixtures import epub


async def certify_workflow(base, token, root, backend_client):
    target = root / "workflow-library"
    target.mkdir()
    settings = get_settings()
    settings.import_sources = {"native": root / "downloads"}
    settings.import_destinations = {"ebooks": target}
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
            "name": "Workflow certification",
            "mediaType": "book",
            "folders": [{"fullPath": str(target)}],
            "settings": {"disableWatcher": True, "audiobooksOnly": False},
        },
    )
    response.raise_for_status()
    external_library = response.json()["id"]
    epub(root / "downloads/workflow/book.epub", title="Workflow Harbor", author="Fixture Author")
    queue = get_queue()
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
            library = next(row for row in libraries if row["name"] == "Workflow certification")
            assert library["accessible"]
            work = await request(
                "POST",
                "/api/catalog/works",
                201,
                json={"title": "Workflow Harbor", "authors": ["Fixture Author"], "language": "en"},
            )
            async with session_factory()() as db, db.begin():
                version = Version(
                    work_id=UUID(work["id"]), medium="ebook", language="en", publication_year=2024
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
                    "relative_path": "workflow",
                    "completed_download": True,
                },
            )
            await drain()
            inspection = await request("GET", f"/api/organization/inspections/{inspection['id']}")
            naming = await request("GET", "/api/organization/settings")
            plan = await request(
                "POST",
                f"/api/organization/inspections/{inspection['id']}/plans",
                201,
                json={
                    "inspection_revision": inspection["snapshot"]["revision"],
                    "profile_revision": naming["revision"],
                    "selections": [
                        {
                            "group_key": inspection["snapshot"]["groups"][0]["key"],
                            "work_id": work["id"],
                            "version_id": version_id,
                            "full_content": True,
                        }
                    ],
                },
            )
            destination = await request(
                "PUT",
                "/api/organization/destinations/ebooks",
                json={"library_id": library["id"], "medium": "ebook", "backend_path": str(target)},
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
                    "ebook": {"id": destination["id"], "revision": destination["revision"]}
                },
            }
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
            owned = await request("GET", f"/api/catalog/works/{work['id']}")
            assert owned["availability"]["owned"] and owned["availability"]["ebook"]
            assert not owned["availability"]["audio"]
            source = root / "downloads/workflow/book.epub"
            published = list(target.rglob("*.epub"))
            assert len(published) == 1 and published[0].stat().st_ino == source.stat().st_ino
            assert published[0].read_bytes() == source.read_bytes()
            second = await request(
                "POST",
                f"/api/organization/plans/{plan['id']}/imports",
                202,
                headers={"Idempotency-Key": "native-duplicate-check"},
                json=body,
            )
            assert second["entries"][0]["state"] == "skipped"
            return {
                "confirmed": True,
                "owned": True,
                "source_preserved": True,
                "duplicate_skipped": True,
                "medium": "ebook",
                "catalog_version_seeded": True,
                "server_library_id": external_library,
            }
    finally:
        # This database is disposable; do not retain ephemeral server credentials.
        async with get_engine().begin() as db:
            await db.execute(
                text(
                    f"TRUNCATE {tables}, book_queue.procrastinate_jobs, "
                    "book_queue.procrastinate_workers RESTART IDENTITY CASCADE"
                )
            )
        await get_engine().dispose()
