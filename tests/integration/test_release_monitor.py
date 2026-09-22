"""A future release is requested and not searched until the day arrives."""

# ruff: noqa: F401, F811
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.db.models import AcquisitionIntent, DownloadAttempt, MonitoredRelease, Operation, Work
from app.domain import automatic_selection
from app.domain.release_monitor import schedule
from tests.integration.test_acquisition import catalog
from tests.integration.test_acquisition_selections import selection_route
from tests.integration.test_automatic_dispatch import authorized
from tests.integration.test_automatic_selection import source
from tests.integration.test_quick_add import add, complete_search, defaults

pytestmark = pytest.mark.integration


async def release(database, work_id, day):
    async with database() as db, db.begin():
        work = await db.get(Work, work_id)
        work.metadata_fields = {
            "release": {
                "date": day,
                "basis": "audiobook",
                "coming_soon": True,
                "source": "hardcover",
            }
        }


async def test_quick_add_before_the_release_date_does_not_search(
    client, database, authorized, catalog
):
    await defaults(client, authorized, audio_formats=["m4b", "mp3"])
    future = (datetime.now(UTC).date() + timedelta(days=30)).isoformat()
    await release(database, catalog["work"], future)
    response = await add(client, catalog["work"], "audio", key="release-wait")
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "held"
    assert future in body["message"]
    async with database() as db:
        operation = await db.get(Operation, UUID(body["id"]))
        assert "search_id" not in operation.payload
        assert operation.payload["waiting_for_release"] == future
        searches = set(
            await db.scalars(select(Operation.id).where(Operation.kind == "sources.search"))
        )
        assert searches == {authorized["search"]}
        monitor = await db.scalar(select(MonitoredRelease))
        assert monitor.state == "waiting" and monitor.release_date.isoformat() == future


async def test_release_day_starts_the_wanted_search_and_a_mismatch_does_not_download(
    client, database, authorized, catalog
):
    await defaults(client, authorized, audio_formats=["flac"])
    today = datetime.now(UTC).date().isoformat()
    await release(database, catalog["work"], today)
    response = await add(client, catalog["work"], "audio", key="release-today")
    assert response.status_code == 202, response.text
    identifier = UUID(response.json()["id"])
    async with database() as db:
        operation = await db.get(Operation, identifier)
        assert operation.payload.get("search_id")
        monitor = await db.scalar(select(MonitoredRelease))
        assert monitor.state == "wanted"
        assert await db.scalar(select(func.count()).select_from(DownloadAttempt)) == 0
    await complete_search(database, identifier, authorized)
    from app.domain import quick_add

    await quick_add.run(identifier)
    for _ in range(4):
        async with database() as db:
            operation = await db.get(Operation, identifier)
            slot = operation.payload["slots"]["audio"]
            if slot.get("done"):
                break
            child = UUID(slot["operation_id"])
        await automatic_selection.run(child)
        await quick_add.run(identifier)
    async with database() as db:
        operation = await db.get(Operation, identifier)
        assert operation.status == "held", operation.message
        assert operation.payload["slots"]["audio"]["failed"]
        assert await db.scalar(select(func.count()).select_from(DownloadAttempt)) == 0
        monitor = await db.scalar(select(MonitoredRelease))
        assert monitor.state == "wanted" and monitor.next_check_at > datetime.now(UTC)


async def test_the_scheduler_resumes_a_parked_request_on_release_day(
    client, database, authorized, catalog
):
    await defaults(client, authorized, audio_formats=["m4b", "mp3"])
    future = (datetime.now(UTC).date() + timedelta(days=30)).isoformat()
    await release(database, catalog["work"], future)
    response = await add(client, catalog["work"], "audio", key="release-resume")
    assert response.status_code == 202, response.text
    today = datetime.now(UTC).date()
    async with database() as db, db.begin():
        work = await db.get(Work, catalog["work"])
        work.metadata_fields = {
            "release": {
                "date": today.isoformat(),
                "basis": "audiobook",
                "coming_soon": False,
                "source": "hardcover",
            }
        }
        monitor = await db.scalar(select(MonitoredRelease))
        monitor.release_date = today
        monitor.next_check_at = datetime.now(UTC) - timedelta(minutes=1)
    await schedule()
    async with database() as db:
        monitor = await db.scalar(select(MonitoredRelease))
        operation = await db.get(Operation, monitor.operation_id)
        assert operation.payload.get("search_id")
        assert "waiting_for_release" not in operation.payload
        expires = datetime.fromisoformat(operation.payload["expires_at"])
        assert expires > datetime.now(UTC)
        assert monitor.state == "wanted"
        assert await db.scalar(select(Operation.id).where(Operation.kind == "sources.search"))
        resumed_id = operation.id
    from app.domain import quick_add

    await quick_add.run(resumed_id)
    async with database() as db:
        resumed = await db.get(Operation, resumed_id)
        assert "timed out" not in (resumed.message or "")


async def test_a_later_follow_records_the_first_known_release_day(
    client, database, authorized, catalog
):
    await defaults(client, authorized, audio_formats=["m4b", "mp3"])
    first = await client.post(
        "/api/releases/follow",
        json={"work_id": str(catalog["work"]), "basis": "unknown"},
    )
    assert first.status_code == 201, first.text
    assert first.json()["state"] == "waiting"
    assert first.json()["release_date"] is None
    day = (datetime.now(UTC).date() + timedelta(days=40)).isoformat()
    learned = await client.post(
        "/api/releases/follow",
        json={"work_id": str(catalog["work"]), "basis": "work", "release_date": day},
    )
    assert learned.status_code == 201, learned.text
    assert learned.json()["release_date"] == day
    assert day in learned.json()["message"]
    status = await client.get(f"/api/releases/follow/{catalog['work']}")
    assert status.status_code == 200, status.text
    assert status.json()["state"] == "waiting"
    assert status.json()["release_date"] == day
    async with database() as db:
        monitor = await db.scalar(select(MonitoredRelease))
        assert monitor.state == "waiting" and monitor.release_date.isoformat() == day
        operation = await db.get(Operation, monitor.operation_id)
        assert operation.payload["waiting_for_release"] == day
        assert "search_id" not in operation.payload
        searches = set(
            await db.scalars(select(Operation.id).where(Operation.kind == "sources.search"))
        )
        assert searches == {authorized["search"]}
    later = (datetime.now(UTC).date() + timedelta(days=50)).isoformat()
    again = await client.post(
        "/api/releases/follow",
        json={"work_id": str(catalog["work"]), "basis": "work", "release_date": later},
    )
    assert again.status_code == 201, again.text
    assert again.json()["message"] == "Already following this book"
    assert again.json()["release_date"] == day


async def test_follow_without_a_saved_medium_waits_for_a_choice(
    client, database, authorized, catalog
):
    await defaults(client, authorized, desired_media=None)
    missing = await client.post(
        "/api/releases/follow",
        json={"work_id": str(catalog["work"]), "basis": "work"},
    )
    assert missing.status_code == 422, missing.text
    assert missing.json()["detail"] == "Choose media to request or set a default"
    chosen = await client.post(
        "/api/releases/follow",
        json={"work_id": str(catalog["work"]), "basis": "work", "mode": "ebook"},
    )
    assert chosen.status_code == 201, chosen.text
    assert chosen.json()["state"] == "available"
    async with database() as db:
        # The route fixture already requested audio. The follow adds the ebook.
        followed = [
            intent
            for intent in await db.scalars(select(AcquisitionIntent))
            if intent.specification.get("mode") == "ebook"
        ]
        assert len(followed) == 1
