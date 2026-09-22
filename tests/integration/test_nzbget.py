# ruff: noqa: F811
import base64
from uuid import UUID

import httpx
import pytest

from app.adapters.contracts import SubmissionReceipt
from app.adapters.nzb_descriptor import inspect_nzb
from app.adapters.nzbget import NzbClient, NzbState
from app.config import get_settings
from app.db.models import DownloadAttempt, DownloadInspection, Integration, SourceArtifact
from app.domain import download_attempts as downloads
from app.domain import downloaders as downloader_settings
from app.security import decrypt_secrets, encrypt_secrets
from tests.integration.test_acquisition import catalog  # noqa: F401
from tests.integration.test_acquisition_selections import prepare, selection_route  # noqa: F401
from tests.integration.test_download_attempts import start
from tests.nzb_fixture import nzb_bytes

pytestmark = pytest.mark.integration


def nzb_body(**changes):
    return {
        "kind": "nzbget",
        "name": "NZBGet",
        "base_url": "http://nzb.test:6789",
        "username": "private-nzb-user",
        "password": "private-nzb-password",
        "category": "books",
        **changes,
    }


async def test_nzbget_connection_keeps_credentials_private(client, admin, database, monkeypatch):
    monkeypatch.setattr(get_settings(), "import_sources", {})
    calls = []

    async def handler(request):
        calls.append(request)
        assert "private-nzb-password" not in str(request.url)
        assert request.headers["authorization"].startswith("Basic ")
        assert b"private-nzb-password" not in request.content
        import json

        method = json.loads(request.content)["method"]
        if method == "version":
            return httpx.Response(200, json={"jsonrpc": "2.0", "result": "25.4", "id": 1})
        if method == "config":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "result": [
                        {"Name": "DestDir", "Value": "/downloads/complete"},
                        {"Name": "Category1.Name", "Value": "books"},
                        {"Name": "Category1.DestDir", "Value": "/downloads/books"},
                    ],
                    "id": 1,
                },
            )
        raise AssertionError(method)

    monkeypatch.setattr(
        downloader_settings,
        "NzbClient",
        lambda *args, **kwargs: NzbClient(*args, transport=httpx.MockTransport(handler), **kwargs),
    )
    created = await client.post("/api/downloaders", json=nzb_body())
    assert created.status_code == 201, created.text
    assert created.json()["kind"] == "nzbget"
    assert created.json()["has_credentials"]
    assert "private-nzb-password" not in created.text
    assert "private-nzb-user" not in created.text
    tested = await client.post(f"/api/downloaders/{created.json()['id']}/test")
    assert tested.status_code == 200, tested.text
    assert tested.json()["status"] == "connected"
    assert tested.json()["version"] == "25.4"
    assert tested.json()["save_path"] == "/downloads/books"
    assert "private-nzb-password" not in tested.text
    async with database() as db:
        row = await db.get(Integration, UUID(created.json()["id"]))
        secrets = decrypt_secrets(row.encrypted_secrets)
        assert secrets["username"] == "private-nzb-user"
        assert secrets["password"] == "private-nzb-password"
        assert "private-nzb-password" not in row.encrypted_secrets
    assert calls
    assert all(request.method == "POST" for request in calls)
    qbit = await client.post(
        "/api/downloaders",
        json={"base_url": "http://nzb.test:6789", "category": "books"},
    )
    assert qbit.status_code == 201, qbit.text
    open_client = await client.post(
        "/api/downloaders",
        json={
            "kind": "nzbget",
            "name": "Open NZBGet",
            "base_url": "http://nzb-open.test:6789",
            "category": "books",
        },
    )
    assert open_client.status_code == 201, open_client.text
    assert open_client.json()["has_credentials"] is False


class Grab:
    def __init__(self):
        self.calls = []
        self.tag = None
        self.category = None
        self.complete = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def capabilities(self):
        return None

    async def find(self, **kwargs):
        self.calls.append("find")
        if not self.tag:
            return []
        if self.complete:
            return [
                NzbState(
                    external_id="42",
                    state="SUCCESS/ALL",
                    completed=True,
                    save_path="/downloads/Finished Book",
                    category=self.category,
                    dupe_key=self.tag,
                    reported_complete=True,
                )
            ]
        return [
            NzbState(
                external_id="42",
                state="DOWNLOADING",
                completed=False,
                save_path="/pending",
                category=self.category,
                dupe_key=self.tag,
            )
        ]

    async def submit(self, content, *, attempt_tag, save_path, category):
        self.calls.append("submit")
        assert b"<nzb" in content
        assert save_path == "/downloads"
        self.tag, self.category = attempt_tag, category
        return SubmissionReceipt(external_ids=["42"])


async def test_usenet_grab_is_sent_to_nzbget_once(
    client, admin, database, selection_route, monkeypatch
):
    raw = nzb_bytes()
    descriptor = inspect_nzb(raw)
    async with database() as db, db.begin():
        artifact = await db.get(SourceArtifact, UUID(selection_route["artifact_id"]))
        artifact.sha256 = descriptor.artifact_sha256
        artifact.descriptor = descriptor.model_dump(mode="json")
        artifact.encrypted_content = encrypt_secrets({"nzb": base64.b64encode(raw).decode()})
        artifact.release_snapshot = {**artifact.release_snapshot, "protocol": "nzb"}
        downloader = await db.get(Integration, UUID(selection_route["downloader_id"]))
        downloader.kind = "nzbget"
        downloader.encrypted_secrets = encrypt_secrets(
            {"username": "private-nzb-user", "password": "private-nzb-password"}
        )
    monkeypatch.setattr(get_settings(), "download_dispatch_enabled", True)
    grab = Grab()
    monkeypatch.setattr(downloads, "NzbClient", lambda *args, **kwargs: grab)
    prepared = await prepare(client, selection_route)
    assert prepared.status_code == 201, prepared.text
    assert "private-nzb-password" not in prepared.text
    saved = (await start(client, prepared.json())).json()
    await downloads.run(UUID(saved["id"]))
    assert grab.calls.count("submit") == 1
    async with database() as db:
        assert (await db.get(DownloadAttempt, UUID(saved["id"]))).state == "downloading"
    grab.complete = True
    await downloads.run(UUID(saved["id"]))
    assert grab.calls.count("submit") == 1
    async with database() as db:
        attempt = await db.get(DownloadAttempt, UUID(saved["id"]))
        inspection = await db.get(DownloadInspection, attempt.inspection_id)
        assert attempt.state == "complete"
        assert inspection.relative_path == "Finished Book"
