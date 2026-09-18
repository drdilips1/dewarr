"""Certify a pinned, disposable real ABS server with original synthetic media.

Requires an external ABS checkout and its installed server dependencies. No ABS
code or media is bundled, and this script never connects to an existing server.
"""

import argparse
import asyncio
import hashlib
import json
import os
import platform
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from cryptography.fernet import Fernet

from app.adapters.audiobookshelf import Audiobookshelf
from app.importing.backend import verify_backend
from app.importing.inspection import inspect_download
from app.importing.metadata import ExportMetadata, initial_sidecars
from app.importing.naming import NamingMetadata, fingerprint
from app.importing.publication import PublicationSpec, PublishFile, publish_item

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.media_fixtures import audio, epub  # noqa: E402

ABS_COMMIT = "4b67c170ce46fd6ba770dc55c189ca13fef89b02"


def publish_fixture(root, name, folder, *, title="First Harbor", narrator=None, tracks=1):
    source = root / "downloads"
    pack = source / name
    if narrator:
        for number in range(1, tracks + 1):
            audio(
                pack / f"{number:03}.mp3",
                title="Embedded title must not win",
                narrator=narrator,
                track=number,
            )
    else:
        epub(pack / "book.epub", title=title)
    snapshot = inspect_download(source, name)
    files = [
        PublishFile(
            source=file["path"],
            name=Path(file["path"]).name,
            sha256=file["sha256"],
            identity=file["identity"],
        )
        for file in snapshot["files"]
    ]
    spec = PublicationSpec(
        entry_id=uuid4(),
        plan_revision=fingerprint({"fixture": name}),
        source_root=source,
        source_relative=name,
        source_directory=snapshot["directory_identity"],
        destination_root=root / "library",
        staging_root=root / "staging",
        folder=folder,
        files=files,
        sidecars=initial_sidecars(
            ExportMetadata(
                medium="audio" if narrator else "ebook",
                naming=NamingMetadata(
                    title=title,
                    authors=["Alex Morgan"],
                    narrators=[narrator] if narrator else [],
                    series="Harbor Stories",
                    sequence="1.5" if tracks > 1 else "1",
                    language="en",
                    recording_year=2024 if narrator else None,
                    edition_year=None if narrator else 2024,
                ),
            )
        ),
    )
    receipt = publish_item(spec)
    assert receipt["state"] == "published"
    assert publish_item(spec) == receipt
    for file in files:
        original = pack / file.source
        destination = root / "library" / folder / file.name
        assert original.stat().st_ino == destination.stat().st_ino
        assert hashlib.sha256(original.read_bytes()).hexdigest() == file.sha256
    return {"folder": folder, "title": title, "narrator": narrator, "tracks": tracks}


async def exercise(base, root, process, workflow=False):
    async with httpx.AsyncClient(base_url=base, trust_env=False, timeout=30) as client:
        deadline = time.monotonic() + 45
        while True:
            if process.poll() is not None:
                raise RuntimeError("Disposable ABS exited; inspect its local server log")
            try:
                response = await client.get("status")
                response.raise_for_status()
                status = response.json()
                break
            except httpx.TransportError:
                if time.monotonic() > deadline:
                    raise RuntimeError("Disposable ABS did not become ready") from None
                await asyncio.sleep(0.25)
        assert status["serverVersion"] == "2.36.1" and not status["isInit"]
        password = secrets.token_urlsafe(32)
        response = await client.post(
            "init", json={"newRoot": {"username": "fixture-root", "password": password}}
        )
        response.raise_for_status()
        response = await client.post(
            "login", json={"username": "fixture-root", "password": password}
        )
        response.raise_for_status()
        token = response.json()["user"]["accessToken"]
        client.headers["Authorization"] = f"Bearer {token}"
        response = await client.post(
            "api/libraries",
            json={
                "name": "Original synthetic certification media",
                "folders": [{"fullPath": str(root / "library")}],
                "mediaType": "book",
                "settings": {"audiobooksOnly": False, "disableWatcher": True},
            },
        )
        response.raise_for_status()
        library_id = response.json()["id"]
        expected = []
        for edition in ("First edition", "Revised edition"):
            expected.append(
                publish_fixture(root, edition, f"Alex Morgan/Harbor Stories/01 - {edition}")
            )
        for narrator in ("Jordan Lee", "Casey Reed"):
            expected.append(
                publish_fixture(
                    root,
                    narrator,
                    f"Alex Morgan/Harbor Stories/01 - First Harbor {{{narrator}}}",
                    narrator=narrator,
                )
            )
        expected.append(
            publish_fixture(
                root,
                "multiple-tracks",
                "Alex Morgan/Harbor Stories/01.5 - Beyond the Harbor {Jordan Lee}",
                title="Beyond the Harbor",
                narrator="Jordan Lee",
                tracks=2,
            )
        )
        for narrator in ("Jordan Lee", "Casey Reed"):
            expected.append(
                publish_fixture(
                    root,
                    "nested-" + narrator,
                    f"Alex Morgan/Harbor Stories/Book container/2024 - {narrator}",
                    narrator=narrator,
                )
            )
        expected.append(
            publish_fixture(
                root, "unicode", "Alex Morgan/Harbor Stories/海と港", title="海と港 & Roads <One>"
            )
        )
        async with Audiobookshelf(base, token) as adapter:
            backend_report = await verify_backend(
                adapter, library_id, str(root / "library"), root / "library", "ebook"
            )
            capabilities, _ = await adapter.authorize()
            assert "scan" in capabilities.operations
            assert [item["id"] for item in await adapter.libraries()] == [library_id]
            await adapter.scan(library_id)
            deadline = time.monotonic() + 45
            while True:
                page, total = await adapter.page(library_id, 0)
                if total == len(expected):
                    break
                if time.monotonic() > deadline:
                    raise AssertionError(f"Expected {len(expected)} ABS items; got {total}")
                await asyncio.sleep(0.25)
            items = await adapter.expanded([item["id"] for item in page])
            report = []
            for case in expected:
                folder = root / "library" / case["folder"]
                matches = [
                    item
                    for item in items
                    if any(Path(file.path).parent == folder for file in item.audio + item.ebook)
                ]
                assert len(matches) == 1, case["folder"]
                item = matches[0]
                assert item.title == case["title"] and item.authors == ["Alex Morgan"]
                assert item.narrators == ([case["narrator"]] if case["narrator"] else [])
                assert item.year == 2024 and not item.invalid and not item.missing
                assert item.full_audio == bool(case["narrator"])
                assert item.full_ebook == (not case["narrator"])
                assert len(item.audio) == (case["tracks"] if case["narrator"] else 0)
                assert await adapter.item(item.id) == item
                response = await client.get(f"api/items/{item.id}", params={"expanded": 1})
                response.raise_for_status()
                raw = response.json()
                series = raw["media"]["metadata"]["series"]
                assert len(series) == 1 and series[0]["name"] == "Harbor Stories"
                assert str(series[0]["sequence"]) == ("1.5" if case["tracks"] > 1 else "1")
                report.append({**case, "audio": item.full_audio, "ebook": item.full_ebook})
            await adapter.scan(library_id)
            second_page, second_total = await adapter.page(library_id, 0)
            assert second_total == total
            assert {row["id"] for row in page} == {row["id"] for row in second_page}
            workflow_report = None
            if workflow:
                from certify_import_workflow import certify_workflow

                workflow_report = {
                    medium: await certify_workflow(base, token, root, client, medium)
                    for medium in ("ebook", "audio")
                }
            return {
                "server_version": status["serverVersion"],
                "cases": report,
                "application_workflow": workflow_report,
                "backend_checks": {
                    "root_mapping": backend_report["root_mapping"],
                    "scan_capable": backend_report["scan_capable"],
                },
            }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / ".local/reference/audiobookshelf")
    parser.add_argument("--node", default="node", help="ABS-compatible Node executable")
    parser.add_argument(
        "--workflow-database", help="Optional disposable PostgreSQL URL ending _abs_test"
    )
    parser.add_argument("--evidence", type=Path, default=ROOT / ".local/evidence/abs-native.json")
    args = parser.parse_args()
    if args.workflow_database:
        if not urlsplit(args.workflow_database).path.endswith("_abs_test"):
            raise SystemExit("Workflow certification requires a disposable _abs_test database")
        os.environ.update(
            {
                "BOOK_ENV_FILE": "",
                "BOOK_DATABASE_URL": args.workflow_database,
                "BOOK_SECRET_KEY": Fernet.generate_key().decode(),
                "BOOK_BOOTSTRAP_TOKEN": secrets.token_urlsafe(24),
                "BOOK_PUBLIC_URL": "http://native-fixture",
                "BOOK_COOKIE_SECURE": "false",
            }
        )
        subprocess.run(["uv", "run", "alembic", "upgrade", "head"], cwd=ROOT, check=True)
    source = args.source.resolve(strict=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    if commit != ABS_COMMIT:
        raise SystemExit("Use the pinned, unmodified ABS v2.36.1 checkout")
    if subprocess.check_output(["git", "diff", "HEAD", "--"], cwd=source):
        raise SystemExit("ABS tracked source must be unmodified")
    for binary in (args.node, "ffmpeg", "ffprobe"):
        if not shutil.which(binary):
            raise SystemExit(f"Required certification binary unavailable: {binary}")
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="abs-certification-", dir=ROOT / ".local") as name:
        root = Path(name).resolve()
        for folder in ("downloads", "library", "staging", "config", "metadata"):
            (root / folder).mkdir(mode=0o700)
        with socket.socket() as available:
            available.bind(("127.0.0.1", 0))
            port = available.getsockname()[1]
        environment = {
            "PATH": os.environ["PATH"],
            "HOME": str(root),
            "NODE_ENV": "production",
            "CONFIG_PATH": str(root / "config"),
            "METADATA_PATH": str(root / "metadata"),
            "PORT": str(port),
            "HOST": "127.0.0.1",
            "ROUTER_BASE_PATH": "/certification",
            "SKIP_BINARIES_CHECK": "1",
            "FFMPEG_PATH": shutil.which("ffmpeg"),
            "FFPROBE_PATH": shutil.which("ffprobe"),
        }
        log_path = args.evidence.with_suffix(".log")
        with log_path.open("w") as log:
            os.chmod(log_path, 0o600)
            process = subprocess.Popen(
                [args.node, "index.js"], cwd=source, env=environment, stdout=log, stderr=log
            )
            try:
                report = asyncio.run(
                    exercise(
                        f"http://127.0.0.1:{port}/certification/",
                        root,
                        process,
                        bool(args.workflow_database),
                    )
                )
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        report.update(
            source_commit=commit,
            node=subprocess.check_output([args.node, "--version"], text=True).strip(),
            platform=platform.platform(),
            boundaries="Native server/API/manual scanner and selected application workflow"
            if args.workflow_database
            else "Native server/API/manual scanner and publisher primitives only",
            exclusions=["watcher", "Docker", "complete compatibility matrix"],
        )
        args.evidence.write_text(json.dumps(report, indent=2) + "\n")
        print(f"ABS {report['server_version']}: {len(report['cases'])} cases passed")


if __name__ == "__main__":
    main()
