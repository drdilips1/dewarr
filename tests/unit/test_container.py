import os
import subprocess
import sys
import threading
import time
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.engine import make_url

from app.container import configure_environment, ensure_key, run_migrations, supervise


@pytest.fixture
def environment(monkeypatch, tmp_path):
    monkeypatch.setattr(os, "environ", os.environ.copy())
    for key in list(os.environ):
        if key.startswith(("BOOK_", "DB_")) or key in {"CONFIG_DIR", "PUBLIC_URL"}:
            monkeypatch.delenv(key)
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("DB_PASSWORD", "test/password@with:special#characters%")
    return tmp_path


def test_inline_database_password_is_encoded_and_https_uses_secure_cookies(
    environment, monkeypatch
):
    monkeypatch.setenv("PUBLIC_URL", "https://books.example.com")
    assert configure_environment() == environment
    url = make_url(os.environ["BOOK_DATABASE_URL"])
    assert url.password == "test/password@with:special#characters%"
    assert url.host == "postgres"
    assert os.environ["BOOK_COOKIE_SECURE"] == "true"
    assert os.environ["BOOK_SECRET_KEY_FILE"] == str(environment / "app_key")


def test_existing_book_settings_take_precedence(environment, monkeypatch):
    monkeypatch.setenv("BOOK_DATABASE_URL", "postgresql+psycopg://existing/db")
    monkeypatch.setenv("BOOK_PUBLIC_URL", "http://existing:8000")
    monkeypatch.setenv("BOOK_SECRET_KEY_FILE", "/run/secrets/app_key")
    configure_environment()
    assert os.environ["BOOK_DATABASE_URL"] == "postgresql+psycopg://existing/db"
    assert os.environ["BOOK_PUBLIC_URL"] == "http://existing:8000"
    assert os.environ["BOOK_SECRET_KEY_FILE"] == "/run/secrets/app_key"


def test_config_key_is_created_once_and_keeps_credentials_decryptable(environment):
    configure_environment()
    database = MagicMock()
    database.execute.return_value.fetchone.return_value = [False]
    ensure_key(database, environment)
    path = environment / "app_key"
    key = path.read_bytes().strip()
    assert path.stat().st_mode & 0o777 == 0o600
    encrypted = Fernet(key).encrypt(b"saved provider credential")
    ensure_key(database, environment)
    assert Fernet(path.read_bytes().strip()).decrypt(encrypted) == b"saved provider credential"
    assert path.read_bytes().strip() == key


def test_missing_config_cannot_silently_replace_an_existing_database_key(environment):
    configure_environment()
    database = MagicMock()
    database.execute.return_value.fetchone.return_value = [True]
    with pytest.raises(RuntimeError, match="restore the original encryption key"):
        ensure_key(database, environment)
    assert not (environment / "app_key").exists()


def test_explicit_missing_key_is_not_replaced(environment, monkeypatch):
    monkeypatch.setenv("BOOK_SECRET_KEY_FILE", str(environment / "missing"))
    configure_environment()
    with pytest.raises(RuntimeError, match="does not exist"):
        ensure_key(MagicMock(), environment)


def test_failed_migration_is_fatal_and_releases_lock(monkeypatch):
    database = MagicMock()
    database.execute.return_value.fetchone.return_value = [True]
    child = MagicMock()
    child.poll.return_value = child.returncode = 1
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: child)
    with pytest.raises(RuntimeError, match="migration failed"):
        run_migrations(database, threading.Event())
    assert "pg_advisory_unlock" in database.execute.call_args.args[0]


def wait_for_file(path):
    deadline = time.monotonic() + 5
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert path.exists()


def test_service_failure_stops_sibling_and_returns_failure(tmp_path):
    marker = tmp_path / "worker-stopped"
    ready = tmp_path / "worker-ready"
    worker = (
        "import signal,time; from pathlib import Path; "
        f"signal.signal(signal.SIGTERM, lambda *_: (Path({str(marker)!r}).touch(), exit(0))); "
        f"Path({str(ready)!r}).touch(); time.sleep(30)"
    )
    failed = (
        "import time; from pathlib import Path; "
        f"p=Path({str(ready)!r}); "
        "\nwhile not p.exists(): time.sleep(0.02)\nraise SystemExit(7)"
    )
    assert (
        supervise(
            [[sys.executable, "-c", worker], [sys.executable, "-c", failed]], threading.Event()
        )
        == 7
    )
    assert marker.exists()


def test_stop_event_gracefully_terminates_both_services(tmp_path):
    stop = threading.Event()
    commands = []
    for name in ("api", "worker"):
        commands.append(
            [
                sys.executable,
                "-c",
                (
                    "import signal,time; from pathlib import Path; "
                    "signal.signal(signal.SIGTERM, lambda *_: "
                    f"(Path({str(tmp_path / (name + '-stopped'))!r}).touch(), exit(0))); "
                    f"Path({str(tmp_path / (name + '-ready'))!r}).touch(); time.sleep(30)"
                ),
            ]
        )
    thread = threading.Thread(
        target=lambda: (
            wait_for_file(tmp_path / "api-ready"),
            wait_for_file(tmp_path / "worker-ready"),
            stop.set(),
        )
    )
    thread.start()
    try:
        assert supervise(commands, stop) == 0
    finally:
        stop.set()
        thread.join(timeout=6)
    assert (tmp_path / "api-stopped").exists()
    assert (tmp_path / "worker-stopped").exists()
