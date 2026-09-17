"""Synthetic ABS import HTTP contract backed by a disposable worker folder."""

import json

import httpx

from app.adapters.audiobookshelf import Audiobookshelf


class ImportBackendFixture:
    def __init__(self, root, *, library_id="synthetic", backend_path="/books"):
        self.root = root
        self.library_id = library_id
        self.backend_path = backend_path
        self.version = "2.36.1"
        self.user_type = "root"
        self.settings = {
            "audiobooksOnly": False,
            "disableWatcher": False,
            "metadataPrecedence": [
                "folderStructure",
                "audioMetatags",
                "nfoFile",
                "txtFiles",
                "opfFile",
                "absMetadata",
            ],
        }
        self.path_checks = []
        self.before_exists = None

    async def handle(self, request):
        assert request.headers["authorization"] == "Bearer private-import-token"
        path = request.url.path
        if path == "/status":
            return httpx.Response(
                200, json={"app": "audiobookshelf", "serverVersion": self.version}
            )
        if path == "/api/authorize":
            return httpx.Response(
                200,
                json={
                    "user": {"id": "fixture", "type": self.user_type, "permissions": {}},
                    "serverVersion": self.version,
                },
            )
        if path == f"/api/libraries/{self.library_id}":
            return httpx.Response(
                200,
                json={
                    "id": self.library_id,
                    "mediaType": "book",
                    "folders": [{"fullPath": self.backend_path}],
                    "settings": self.settings,
                },
            )
        if path == "/api/filesystem/pathexists":
            body = json.loads(request.content)
            assert body["folderPath"] == self.backend_path
            if self.before_exists:
                await self.before_exists(body["directory"])
            exists = (self.root / body["directory"]).exists()
            self.path_checks.append(exists)
            return httpx.Response(200, json={"exists": exists})
        raise AssertionError(f"Unexpected ABS fixture request {path}")

    def client(self, url="http://fixture", token="private-import-token"):
        return Audiobookshelf(url, token, transport=httpx.MockTransport(self.handle))
