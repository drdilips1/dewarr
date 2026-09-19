# ruff: noqa: F811
"""Exact recording candidates preserve catalog identity through preparation and dispatch."""

from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.db.models import (
    AcquisitionIntent,
    AcquisitionSelection,
    DownloadAttempt,
    Operation,
    ProviderObject,
    SourceArtifact,
    SourceResult,
    Version,
    WorkMetadataSource,
)
from app.domain import automatic_selection as automatic
from app.domain import download_attempts as downloads
from app.domain.acquisition import RequestSpec
from app.domain.corrections import revision
from tests.integration.test_acquisition import catalog  # noqa: F401
from tests.integration.test_acquisition_selections import selection_route  # noqa: F401
from tests.integration.test_automatic_selection import detail, source, start  # noqa: F401
from tests.integration.test_download_attempts import Client
from tests.integration.test_download_attempts import start as start_download

pytestmark = pytest.mark.integration


@pytest.fixture
async def recording(database, source, catalog):
    identifier = catalog["versions"][1]
    source["release"] = source["release"].model_copy(
        update={"isbn": "9780306406157", "narrators": ["Reader A"], "tags": ["Unabridged"]}
    )
    async with database() as db, db.begin():
        version = await db.get(Version, identifier)
        version.identifiers = {"isbn_13": "9780306406157"}
        intent = await db.get(AcquisitionIntent, UUID(source["body"]["intent_id"]))
        specification = RequestSpec.model_validate(intent.specification).model_copy(
            update={"audio_version_id": identifier}
        )
        intent.specification = specification.model_dump(mode="json")
        intent.fingerprint = revision(intent.specification)
        for model, key in [(SourceArtifact, "artifact"), (SourceResult, "result")]:
            (await db.get(model, source[key])).release_snapshot = source["release"].model_dump(
                mode="json"
            )
    return identifier


async def test_exact_recording_prepares_once_without_creating_another_catalog_version(
    client, database, source, recording
):
    async with database() as db:
        count = await db.scalar(select(func.count()).select_from(Version))
    operation = await start(client, source)
    await automatic.run(UUID(operation["id"]))
    value = await detail(client, operation["id"])
    assert value["status"] == "completed" and value["selection_id"], value
    await automatic.run(UUID(operation["id"]))
    async with database() as db:
        selected = await db.get(AcquisitionSelection, UUID(value["selection_id"]))
        assert selected.frozen["requirements"]["version_id"] == str(recording)
        assert selected.frozen["version_identity_revision"]
        assert (await db.get(Operation, UUID(operation["id"]))).payload[
            "version_identity_revision"
        ] == selected.frozen["version_identity_revision"]
        assert await db.scalar(select(func.count()).select_from(Version)) == count
        assert await db.scalar(select(func.count()).select_from(AcquisitionSelection)) == 1
        assert await db.scalar(select(func.count()).select_from(DownloadAttempt)) == 0


@pytest.mark.parametrize("phase", ["queued", "inspecting", "prepared"])
@pytest.mark.parametrize("field", ["identifiers", "publication_year"])
async def test_changed_version_evidence_requires_new_selection_before_dispatch(
    client, database, source, recording, monkeypatch, phase, field
):
    async def change():
        async with database() as db, db.begin():
            setattr(
                await db.get(Version, recording),
                field,
                {"isbn_13": "9780140328721"} if field == "identifiers" else 2026,
            )

    operation = await start(client, source)
    if phase == "queued":
        await change()
    elif phase == "inspecting":
        source["resolver"].callback = change
    await automatic.run(UUID(operation["id"]))
    value = await detail(client, operation["id"])
    if phase == "prepared":
        assert value["status"] == "completed" and value["selection_id"], value
        await change()
        monkeypatch.setattr(get_settings(), "download_dispatch_enabled", True)
        result = await start_download(client, {"id": value["selection_id"]})
        assert result.status_code == 409, result.text
    else:
        assert value["status"] == "held" and not value["selection_id"], value
        assert "recording changed" in value["message"]
        assert len(source["resolver"].calls) == (0 if phase == "queued" else 1)
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(DownloadAttempt)) == 0


async def test_metadata_conflict_during_inspection_prevents_recording_preparation(
    client, database, source, recording
):
    async def conflict():
        async with database() as db, db.begin():
            provider = await db.scalar(
                select(ProviderObject).where(ProviderObject.version_id == recording)
            )
            provider.match_status = "needs-review"

    source["resolver"].callback = conflict
    operation = await start(client, source)
    await automatic.run(UUID(operation["id"]))
    value = await detail(client, operation["id"])
    assert value["status"] == "held" and "metadata conflict" in value["message"], value
    assert not value["selection_id"]


async def test_legacy_pending_exact_recording_without_frozen_identity_needs_fresh_selection(
    client, database, source, recording
):
    operation = await start(client, source)
    async with database() as db, db.begin():
        saved = await db.get(Operation, UUID(operation["id"]))
        saved.payload = {
            key: value for key, value in saved.payload.items() if key != "version_identity_revision"
        }
    await automatic.run(UUID(operation["id"]))
    value = await detail(client, operation["id"])
    assert value["status"] == "held" and not source["resolver"].calls


async def test_new_metadata_conflict_blocks_dispatch_of_prepared_exact_recording(
    client, database, source, recording, monkeypatch
):
    operation = await start(client, source)
    await automatic.run(UUID(operation["id"]))
    value = await detail(client, operation["id"])
    assert value["status"] == "completed" and value["selection_id"], value
    async with database() as db, db.begin():
        provider = await db.scalar(
            select(ProviderObject).where(ProviderObject.version_id == recording)
        )
        provider.match_status = "needs-review"
    monkeypatch.setattr(get_settings(), "download_dispatch_enabled", True)
    result = await start_download(client, {"id": value["selection_id"]})
    assert result.status_code == 409, result.text
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(DownloadAttempt)) == 0


async def test_legacy_automatic_selection_cannot_dispatch_without_frozen_version_identity(
    client, database, source, recording, monkeypatch
):
    operation = await start(client, source)
    await automatic.run(UUID(operation["id"]))
    value = await detail(client, operation["id"])
    assert value["status"] == "completed" and value["selection_id"], value
    async with database() as db, db.begin():
        saved = await db.get(AcquisitionSelection, UUID(value["selection_id"]))
        saved.frozen = {
            key: item for key, item in saved.frozen.items() if key != "version_identity_revision"
        }
    monkeypatch.setattr(get_settings(), "download_dispatch_enabled", True)
    result = await start_download(client, {"id": value["selection_id"]})
    assert result.status_code == 409, result.text
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(DownloadAttempt)) == 0


async def test_existing_legacy_transfer_remains_observable_without_repeating_submission(
    client, database, source, recording, monkeypatch
):
    operation = await start(client, source)
    await automatic.run(UUID(operation["id"]))
    value = await detail(client, operation["id"])
    assert value["selection_id"], value
    downloader = Client(database, source["descriptor"].model_dump(mode="json"))
    monkeypatch.setattr(downloads, "QbitClient", lambda *args: downloader)
    monkeypatch.setattr(get_settings(), "download_dispatch_enabled", True)
    response = await start_download(client, {"id": value["selection_id"]})
    assert response.status_code == 202, response.text
    attempt_id = UUID(response.json()["id"])
    await downloads.run(attempt_id)
    async with database() as db, db.begin():
        attempt = await db.get(DownloadAttempt, attempt_id)
        assert attempt.state == "downloading" and attempt.external_may_exist
        saved = await db.get(AcquisitionSelection, UUID(value["selection_id"]))
        saved.frozen = {
            key: item for key, item in saved.frozen.items() if key != "version_identity_revision"
        }
    prior = downloader.calls.count("find")
    await downloads.run(attempt_id)
    assert downloader.calls.count("find") > prior
    assert downloader.calls.count("submit") == 1
    async with database() as db:
        assert (await db.get(DownloadAttempt, attempt_id)).state == "downloading"


async def test_corrected_recording_history_remains_readable_only_while_version_access_survives(
    client, database, source, recording, monkeypatch
):
    async with database() as db, db.begin():
        intent = await db.get(AcquisitionIntent, UUID(source["body"]["intent_id"]))
        spec = RequestSpec.model_validate(intent.specification).model_copy(
            update={"required_narrators": ["Reader A"]}
        )
        intent.specification = spec.model_dump(mode="json")
        intent.fingerprint = revision(intent.specification)
    operation = await start(client, source)
    await automatic.run(UUID(operation["id"]))
    prepared = await detail(client, operation["id"])
    assert prepared["selection_id"], prepared
    async with database() as db, db.begin():
        (await db.get(Version, recording)).narrators = ["Corrected Reader"]
    receipt = await detail(client, operation["id"])
    assert receipt["selection_id"] == prepared["selection_id"]
    request_url = f"/api/requests/{source['body']['intent_id']}"
    response = await client.get(request_url)
    assert response.status_code == 200, response.text
    assert response.json()["work_title"] != "Unavailable book"
    assert "Corrected Reader" in response.json()["description"]
    monkeypatch.setattr(get_settings(), "download_dispatch_enabled", True)
    response = await start_download(client, {"id": prepared["selection_id"]})
    assert response.status_code == 409, response.text
    async with database() as db, db.begin():
        provider = await db.scalar(
            select(ProviderObject).where(ProviderObject.version_id == recording)
        )
        (await db.get(WorkMetadataSource, provider.metadata_source_id)).accepted = False
    response = await client.get(f"/api/acquisition/automatic-selections/{operation['id']}")
    assert response.status_code == 404, response.text
    response = await client.get(request_url)
    assert response.status_code == 200, response.text
    assert response.json()["work_title"] == "Unavailable book"
    assert "Corrected Reader" not in response.json()["description"]
    assert all(target["state"] == "paused" for target in response.json()["targets"])
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(DownloadAttempt)) == 0
