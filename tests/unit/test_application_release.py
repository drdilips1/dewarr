from types import SimpleNamespace

import httpx
import pytest

from app.api import application_release as release


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    release._cache.clear()
    release._history.clear()
    config = SimpleNamespace(build_version="v1.9.0", release_repository="owner/book-search")
    monkeypatch.setattr(release, "get_settings", lambda: config)
    return config


@pytest.mark.parametrize(
    ("installed", "latest", "available"),
    [
        ("v1.9.0", "v1.10.0", True),
        ("1.10.0", "v1.10.0", False),
        ("v2.0.0", "v1.10.0", False),
        ("1.0.0-dev", "v1.10.0", False),
    ],
)
def test_versions_and_cache(monkeypatch, settings, installed, latest, available):
    settings.build_version = installed
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        return httpx.Response(200, json={"tag_name": latest}, request=httpx.Request("GET", url))

    monkeypatch.setattr(release.httpx, "get", get)
    data = release.application_release()
    assert data.update_available is available
    assert data.release_url == f"https://github.com/owner/book-search/releases/tag/{latest}"
    assert release.application_release() == data
    assert len(calls) == 1


def test_failed_check_preserves_installed_version(monkeypatch):
    def get(*args, **kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(release.httpx, "get", get)
    data = release.application_release()
    assert data.installed_version == "v1.9.0"
    assert data.status == "unavailable"
    assert not data.update_available


def test_unconfigured_does_not_contact_github(monkeypatch, settings):
    settings.release_repository = ""
    monkeypatch.setattr(release.httpx, "get", lambda *args, **kwargs: pytest.fail("network"))
    data = release.application_release()
    assert data.status == "unconfigured"
    assert data.release_url is None


def test_release_history_notes_and_cache(monkeypatch):
    calls = []
    payload = [
        {
            "tag_name": "v1.10.0",
            "name": "Dewarr v1.10.0",
            "body": "## Features\n\n- Lists",
            "html_url": "https://github.com/owner/book-search/releases/tag/v1.10.0",
            "published_at": "2026-09-21T13:58:30Z",
            "draft": False,
            "prerelease": False,
        },
        {"tag_name": "v1.9.0", "draft": True, "body": "hidden"},
        {
            "tag_name": "v1.8.0",
            "body": None,
            "html_url": "https://evil.example/phish",
            "prerelease": True,
        },
        {"tag_name": "../secret", "body": "nope"},
        {"tag_name": "v1.7.0", "body": "x" * 20_000},
    ]

    def get(url, **kwargs):
        calls.append((url, kwargs.get("params")))
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(release.httpx, "get", get)
    data = release.application_releases()
    assert data.status == "checked"
    assert [item.version for item in data.releases] == ["v1.10.0", "v1.8.0", "v1.7.0"]
    assert data.releases[0].name == "Dewarr v1.10.0"
    assert data.releases[0].notes == "## Features\n\n- Lists"
    assert data.releases[0].published_at == "2026-09-21T13:58:30Z"
    assert data.releases[0].url.endswith("/releases/tag/v1.10.0")
    assert data.releases[1].prerelease
    assert data.releases[1].notes == ""
    assert data.releases[1].url == "https://github.com/owner/book-search/releases/tag/v1.8.0"
    assert data.releases[2].notes.endswith("…")
    assert len(data.releases[2].notes) < 20_000
    assert release.application_releases() == data
    assert calls == [("https://api.github.com/repos/owner/book-search/releases", {"per_page": 20})]


def test_release_history_unconfigured_does_not_contact_github(monkeypatch, settings):
    settings.release_repository = ""
    monkeypatch.setattr(release.httpx, "get", lambda *args, **kwargs: pytest.fail("network"))
    data = release.application_releases()
    assert data.status == "unconfigured"
    assert data.releases == []


def test_release_history_failure(monkeypatch):
    def get(*args, **kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(release.httpx, "get", get)
    data = release.application_releases()
    assert data.status == "unavailable"
    assert data.releases == []


@pytest.mark.parametrize("payload", [{}, []])
def test_release_history_without_notes(monkeypatch, payload):
    monkeypatch.setattr(
        release.httpx,
        "get",
        lambda url, **kwargs: httpx.Response(200, json=payload, request=httpx.Request("GET", url)),
    )
    data = release.application_releases()
    assert data.releases == []
    assert data.status == ("unavailable" if isinstance(payload, dict) else "no-release")


@pytest.mark.parametrize(
    "payload", [{"tag_name": "v2.0.0-rc.1"}, {"tag_name": "v2.0.0", "draft": True}, []]
)
def test_invalid_or_unstable_release(monkeypatch, payload):
    monkeypatch.setattr(
        release.httpx,
        "get",
        lambda url, **kwargs: httpx.Response(200, json=payload, request=httpx.Request("GET", url)),
    )
    assert not release.application_release().update_available
