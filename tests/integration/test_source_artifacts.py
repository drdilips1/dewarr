import asyncio
import hashlib
import json
import logging
from uuid import UUID

import httpx
import pytest
from sqlalchemy import func, select

from app.adapters.mam import MAMClient
from app.db.models import AuditEvent, SourceArtifact, SourceConnection, User
from app.domain import source_artifacts, source_network
from app.domain.source_artifacts import artifact_bytes
from app.security import decrypt_secrets
from tests.integration.test_correction_migration import migrate
from tests.integration.test_mam_sources import configure
from tests.mam_fixture import release_row, search_response
from tests.torrent_fixture import torrent_bytes

pytestmark = pytest.mark.integration


@pytest.fixture
def artifact_http(monkeypatch):
    state = {
        "cookie": "first-fixture",
        "calls": [],
        "raw": torrent_bytes(),
        "id": 501,
        "dl": "private-download-token?tid=old",
        "status": 200,
        "content_type": "application/x-bittorrent",
        "wait": None,
        "detail_retry_after": None,
        "entered": asyncio.Event(),
    }

    async def handler(request):
        state["calls"].append(request)
        assert request.headers["cookie"] == "mam_id=" + state["cookie"]
        state["cookie"] = "artifact-cookie-" + str(len(state["calls"]))
        headers = {"set-cookie": f"mam_id={state['cookie']}; Path=/"}
        if request.url.path.endswith("loadSearchJSONbasic.php"):
            if state["detail_retry_after"]:
                headers["Retry-After"] = str(state["detail_retry_after"])
            payload = json.loads(request.content)
            assert payload["dlLink"] == "true" and payload["tor"]["id"] == 501
            return httpx.Response(
                200,
                json=search_response(data=[release_row(id=state["id"], dl=state["dl"])]),
                headers=headers,
            )
        assert request.url.path == "/tor/download.php/private-download-token"
        assert request.url.query == b"tid=501"
        state["entered"].set()
        if state["wait"]:
            await state["wait"].wait()
        return httpx.Response(
            state["status"],
            content=state["raw"],
            headers={
                **headers,
                "content-type": state["content_type"],
                "location": "https://elsewhere.test/private",
            },
        )

    monkeypatch.setattr(
        source_network,
        "MAMClient",
        lambda *args, **kwargs: MAMClient(*args, **kwargs, transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(source_network, "REQUEST_INTERVAL", 0)
    return state


async def resolve(client):
    return await client.post("/api/sources/mam/releases/501/artifact")


async def test_resolution_persists_private_immutable_bytes_and_rotating_session(
    client, admin, database, artifact_http, caplog
):
    caplog.set_level(logging.INFO, logger="httpx")
    await configure(client)
    prepared = await resolve(client)
    assert prepared.status_code == 200, prepared.text
    data = prepared.json()
    assert data["current_connection"] and not data["dispatch_available"]
    assert len(data["descriptor"]["files"]) == 2 and data["descriptor"]["private"]
    assert data["descriptor"]["artifact_sha256"] == hashlib.sha256(artifact_http["raw"]).hexdigest()
    assert "private-download-token" not in prepared.text + caplog.text
    assert "private-fixture-passkey" not in prepared.text + caplog.text
    assert "artifact-cookie" not in prepared.text
    assert len(artifact_http["calls"]) == 2
    async with database() as db:
        row = await db.get(SourceArtifact, UUID(data["id"]))
        assert artifact_bytes(row) == artifact_http["raw"]
        assert "private-fixture-passkey" not in row.encrypted_content
        assert "private-download-token" not in json.dumps(row.release_snapshot)
        source = await db.get(SourceConnection, "mam")
        assert decrypt_secrets(source.encrypted_secrets)["mam_id"] == "artifact-cookie-2"
        assert "private" not in str(
            [event.detail for event in await db.scalars(select(AuditEvent))]
        )
    repeated = await resolve(client)
    assert repeated.status_code == 200 and repeated.json()["id"] == data["id"]
    fetched = await client.get(f"/api/source-artifacts/{data['id']}")
    assert fetched.status_code == 200 and fetched.json()["descriptor"] == data["descriptor"]


async def test_detail_cooldown_prevents_binary_fetch_and_persists_rotated_session(
    client, admin, database, artifact_http
):
    await configure(client)
    artifact_http["detail_retry_after"] = 120
    response = await resolve(client)
    assert response.status_code == 429
    assert response.headers["retry-after"] == "120"
    assert len(artifact_http["calls"]) == 1
    async with database() as db:
        source = await db.get(SourceConnection, "mam")
        assert source.blocked_until and not source.lease_token
        assert decrypt_secrets(source.encrypted_secrets)["mam_id"] == "artifact-cookie-1"
        assert await db.scalar(select(func.count()).select_from(SourceArtifact)) == 0
    assert (await resolve(client)).status_code == 429
    assert len(artifact_http["calls"]) == 1


@pytest.mark.parametrize(
    "reference",
    [
        "https://evil.test/key",
        "//evil.test/key",
        "../key",
        "%2e%2e/key",
        "key?fl",
        "https://[",
        "key\r\ninjected",
    ],
)
async def test_download_reference_is_confined_and_never_spends_personal_freeleech(
    client, admin, database, artifact_http, reference
):
    await configure(client)
    artifact_http["dl"] = reference
    response = await resolve(client)
    assert response.status_code in {502, 503}
    assert len(artifact_http["calls"]) == 1
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(SourceArtifact)) == 0


@pytest.mark.parametrize(
    "change",
    [
        {"status": 302},
        {"status": 429},
        {"status": 403},
        {"raw": b"<html>private credential</html>", "content_type": "text/html"},
        {"raw": b"d invalid torrent with private credential"},
        {"id": 502},
    ],
)
async def test_source_and_parser_failures_do_not_create_artifacts(
    client, admin, database, artifact_http, change
):
    await configure(client)
    artifact_http.update(change)
    response = await resolve(client)
    assert response.status_code in {409, 429, 502, 503}
    assert "private credential" not in response.text
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(SourceArtifact)) == 0


async def test_changed_source_configuration_fences_native_parser_results(
    client, admin, database, artifact_http, monkeypatch
):
    await configure(client)
    entered, release = asyncio.Event(), asyncio.Event()
    original = source_artifacts.inspect_torrent

    async def slow_parser(data):
        entered.set()
        await release.wait()
        return await original(data)

    monkeypatch.setattr(source_artifacts, "inspect_torrent", slow_parser)
    task = asyncio.create_task(resolve(client))
    await asyncio.wait_for(entered.wait(), 5)
    assert (await configure(client, expected_generation=1, enabled=False)).status_code == 200
    release.set()
    assert (await task).status_code == 409
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(SourceArtifact)) == 0


async def test_saved_artifact_is_stale_after_source_edit_and_private_to_its_owner(
    client, admin, database, artifact_http
):
    await configure(client)
    data = (await resolve(client)).json()
    identifier = data["id"]
    await configure(client, expected_generation=1, enabled=False)
    fetched = await client.get(f"/api/source-artifacts/{identifier}")
    assert fetched.status_code == 200 and not fetched.json()["current_connection"]
    async with database() as db, db.begin():
        other = User(
            username="other",
            display_name="Other reader",
            role="member",
            active=True,
            password_hash="unused",
        )
        db.add(other)
        await db.flush()
        (await db.get(SourceArtifact, UUID(identifier))).owner_id = other.id
    assert (await client.get(f"/api/source-artifacts/{identifier}")).status_code == 404


async def test_viewer_and_revoked_user_cannot_prepare_an_artifact(
    client, admin, database, artifact_http
):
    await configure(client)
    async with database() as db, db.begin():
        (await db.get(User, UUID(admin["id"]))).role = "viewer"
    assert (await resolve(client)).status_code == 403 and not artifact_http["calls"]
    async with database() as db, db.begin():
        (await db.get(User, UUID(admin["id"]))).role = "member"
    artifact_http["wait"] = asyncio.Event()
    task = asyncio.create_task(resolve(client))
    await asyncio.wait_for(artifact_http["entered"].wait(), 5)
    async with database() as db, db.begin():
        (await db.get(User, UUID(admin["id"]))).role = "viewer"
    artifact_http["wait"].set()
    assert (await task).status_code == 403
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(SourceArtifact)) == 0


async def test_artifact_integrity_check_rejects_changed_ciphertext_or_digest(
    client, admin, database, artifact_http
):
    await configure(client)
    data = (await resolve(client)).json()
    async with database() as db:
        row = await db.get(SourceArtifact, UUID(data["id"]))
        row.sha256 = "0" * 64
        with pytest.raises(Exception, match="Stored torrent integrity"):
            artifact_bytes(row)


async def test_populated_artifact_migration_refuses_lossy_downgrade(
    client, admin, database, artifact_http
):
    await configure(client)
    data = (await resolve(client)).json()
    refused = await migrate("downgrade", "0015_sources")
    assert refused.returncode != 0 and "Source artifact history" in refused.stderr
    async with database() as db, db.begin():
        await db.delete(await db.get(SourceArtifact, UUID(data["id"])))
    try:
        downgraded = await migrate("downgrade", "0015_sources")
        assert downgraded.returncode == 0, downgraded.stderr
    finally:
        restored = await migrate("upgrade", "head")
        assert restored.returncode == 0, restored.stderr
