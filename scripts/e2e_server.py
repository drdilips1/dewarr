"""Run a disposable browser-test API and worker; never use an ordinary database."""

import json
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
from cryptography.fernet import Fernet

from app.db.models import Base

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from tests.media_fixtures import audio, epub, pdf  # noqa: E402

media_fixture = tempfile.TemporaryDirectory(prefix="book-search-browser-media-")
media_root = Path(media_fixture.name).resolve()
epub(media_root / "completed/book.epub", title="The Catalog Journey", author="Catalog Author")
destination_root = media_root / "library"
staging_root = media_root / "staging"
destination_root.mkdir()
staging_root.mkdir(mode=0o700)
download_root = media_root / "downloads"
download_root.mkdir()
(media_root / "completed").rename(download_root / "completed")
epub(
    download_root / "matched/book.epub",
    title="The Catalog Journey",
    author="Catalog Author",
    isbn="9781234567897",
)
epub(download_root / "formats/book.epub", title="Format Review", author="Catalog Author")
pdf(download_root / "formats/book.pdf", title="Format Review", author="Catalog Author")
audio(download_root / "companion/book.mp3", title="Companion Review", author="Catalog Author")
pdf(download_root / "companion/notes.pdf", title="Supporting notes", author="Catalog Author")
os.chdir(root)
url = os.environ.get(
    "BOOK_E2E_DATABASE_URL",
    "postgresql+psycopg://book@127.0.0.1:55438/book_search_browser_test",
)
if not urlsplit(url).path.endswith("_browser_test"):
    raise SystemExit("Browser tests require an isolated database ending in _browser_test")
os.environ.update(
    {
        "BOOK_ENV_FILE": "",
        "BOOK_DATABASE_URL": url,
        "BOOK_SECRET_KEY": Fernet.generate_key().decode(),
        "BOOK_BOOTSTRAP_TOKEN": "browser-test-bootstrap-token",
        "BOOK_PUBLIC_URL": "http://127.0.0.1:8001",
        "BOOK_COOKIE_SECURE": "false",
        "BOOK_DOWNLOAD_DISPATCH_ENABLED": "true",
        "BOOK_HARDCOVER_URL": "http://127.0.0.1:13379/catalog",
        "BOOK_OPENLIBRARY_URL": "http://127.0.0.1:13379/openlibrary",
        "BOOK_IMPORT_SOURCES": json.dumps({"synthetic": str(download_root)}),
        "BOOK_IMPORT_DESTINATIONS": json.dumps({"ebooks": str(destination_root)}),
        "BOOK_IMPORT_STAGING_ROOT": str(staging_root),
    }
)
subprocess.run(["uv", "run", "alembic", "upgrade", "head"], check=True)
# Reset only this specifically named, disposable test database.
with psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://")) as connection:
    tables = ", ".join(f'public."{name}"' for name in Base.metadata.tables)
    connection.execute(
        f"TRUNCATE {tables}, book_queue.procrastinate_jobs, "
        "book_queue.procrastinate_workers RESTART IDENTITY CASCADE"
    )
processes = [
    subprocess.Popen(
        [
            "uv",
            "run",
            "uvicorn",
            "e2e_abs:app",
            "--app-dir",
            "scripts",
            "--host",
            "127.0.0.1",
            "--port",
            "13379",
        ]
    ),
    subprocess.Popen(["uv", "run", "python", "scripts/e2e_worker.py"]),
    subprocess.Popen(
        [
            "uv",
            "run",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8001",
        ]
    ),
]


def shutdown(signum=None, frame=None):
    for process in processes:
        process.terminate()
    for process in processes:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)
try:
    processes[-1].wait()
finally:
    shutdown()
    media_fixture.cleanup()
