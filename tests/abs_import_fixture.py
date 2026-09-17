"""Synthetic ABS import HTTP contract backed by a disposable worker folder."""

import json

import httpx
from defusedxml.ElementTree import parse

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


class ScanningBackend(ImportBackendFixture):
    def __init__(self, root):
        super().__init__(root)
        self.items = {}
        self.detect = True
        self.scan_count = 0

    def scan(self):
        self.scan_count += 1
        if not self.detect:
            return
        dc = "{http://purl.org/dc/elements/1.1/}"
        for index, opf in enumerate(sorted(self.root.rglob("metadata.opf"))):
            xml = parse(opf)
            folder = opf.parent
            relative = folder.relative_to(self.root)
            files = [
                {
                    "ino": str(path.stat().st_ino),
                    "metadata": {
                        "path": f"{self.backend_path}/{relative}/{path.name}",
                        "ext": path.suffix,
                        "size": path.stat().st_size,
                    },
                }
                for path in sorted(folder.iterdir())
                if path.is_file()
            ]
            media = {
                "metadata": {
                    "title": xml.find(f".//{dc}title").text,
                    "authors": [{"name": node.text} for node in xml.findall(f".//{dc}creator")],
                    "narrators": [],
                    "language": xml.findtext(f".//{dc}language"),
                    "publishedYear": xml.findtext(f".//{dc}date"),
                },
                "audioFiles": [],
            }
            media["ebookFile"] = next(
                {**file, "ebookFormat": "epub"}
                for file in files
                if file["metadata"]["ext"] == ".epub"
            )
            item_id = f"import-{index}"
            self.items[item_id] = {
                "id": item_id,
                "libraryId": self.library_id,
                "path": f"{self.backend_path}/{relative}",
                "mediaType": "book",
                "media": media,
                "libraryFiles": files,
            }

    async def handle(self, request):
        import json

        path = request.url.path
        if path == f"/api/libraries/{self.library_id}/scan":
            self.scan()
            return httpx.Response(200)
        if path == f"/api/libraries/{self.library_id}/items":
            return httpx.Response(
                200, json={"total": len(self.items), "results": [{"id": key} for key in self.items]}
            )
        if path == "/api/items/batch/get":
            return httpx.Response(
                200,
                json={
                    "libraryItems": [
                        self.items[key] for key in json.loads(request.content)["libraryItemIds"]
                    ]
                },
            )
        if path.startswith("/api/items/"):
            return httpx.Response(200, json=self.items[path.split("/")[-1]])
        return await super().handle(request)
