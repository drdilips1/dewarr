"""Installed build identity and a cached check of public GitHub releases."""

import re
import threading
from importlib.metadata import version
from time import monotonic
from urllib.parse import quote

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from app.config import get_settings

router = APIRouter()
_lock = threading.Lock()
_cache: dict[str, tuple[float, str | None, str]] = {}
_history: dict[str, tuple[float, str, list["ApplicationReleaseNote"]]] = {}
_NOTES_LIMIT = 16_000
_HISTORY_LIMIT = 20
_PUBLISHED = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z")
_TAG = re.compile(r"[A-Za-z0-9_.+-]{1,80}")


def stable_version(tag: str) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:\+[\w.-]+)?", tag)
    return tuple(map(int, match.groups())) if match else None


class ApplicationRelease(BaseModel):
    installed_version: str
    installed_url: str | None
    latest_version: str | None
    release_url: str | None
    update_available: bool
    status: str


@router.get("/application/release", response_model=ApplicationRelease)
def application_release() -> ApplicationRelease:
    settings = get_settings()
    installed = settings.build_version or f"{version('dewarr')}-dev"
    repository = settings.release_repository
    base = f"https://github.com/{repository}/releases" if repository else None
    latest = None
    status = "unconfigured"
    if repository:
        with _lock:
            cached = _cache.get(repository)
            if cached is None or cached[0] <= monotonic():
                status = "unavailable"
                try:
                    response = httpx.get(
                        f"https://api.github.com/repos/{repository}/releases/latest",
                        headers={"Accept": "application/vnd.github+json"},
                        timeout=5,
                    )
                    if response.status_code == 404:
                        status = "no-release"
                    else:
                        response.raise_for_status()
                        data = response.json()
                        tag = data.get("tag_name")
                        if (
                            isinstance(tag, str)
                            and stable_version(tag)
                            and not data.get("draft")
                            and not data.get("prerelease")
                        ):
                            latest = tag
                            status = "checked"
                except (httpx.HTTPError, ValueError, AttributeError):
                    pass
                _cache[repository] = (monotonic() + 3600, latest, status)
            else:
                _, latest, status = cached
    current = stable_version(installed)
    newer = stable_version(latest) if latest else None
    return ApplicationRelease(
        installed_version=installed,
        installed_url=f"{base}/tag/{quote(installed, safe='')}" if base and current else base,
        latest_version=latest,
        release_url=f"{base}/tag/{quote(latest, safe='')}" if base and latest else base,
        update_available=bool(current and newer and newer > current),
        status=status,
    )


class ApplicationReleaseNote(BaseModel):
    version: str
    name: str
    notes: str
    url: str
    published_at: str | None
    prerelease: bool


class ApplicationReleaseHistory(BaseModel):
    installed_version: str
    status: str
    releases: list[ApplicationReleaseNote]


def release_url(repository: str, tag: str, provided: object) -> str:
    prefix = f"https://github.com/{repository}/"
    if (
        isinstance(provided, str)
        and provided.startswith(prefix)
        and " " not in provided
        and len(provided) <= 500
    ):
        return provided
    return f"{prefix}releases/tag/{quote(tag, safe='')}"


def release_note(repository: str, item: object) -> ApplicationReleaseNote | None:
    if not isinstance(item, dict) or item.get("draft"):
        return None
    tag = item.get("tag_name")
    if not isinstance(tag, str) or not _TAG.fullmatch(tag):
        return None
    name = item.get("name")
    title = name.strip() if isinstance(name, str) and name.strip() else tag
    body = item.get("body")
    notes = body.replace("\r\n", "\n").replace("\x00", "").strip() if isinstance(body, str) else ""
    if len(notes) > _NOTES_LIMIT:
        notes = notes[:_NOTES_LIMIT].rstrip() + "…"
    published = item.get("published_at")
    when = published if isinstance(published, str) and _PUBLISHED.fullmatch(published) else None
    return ApplicationReleaseNote(
        version=tag,
        name=title[:200],
        notes=notes,
        url=release_url(repository, tag, item.get("html_url")),
        published_at=when,
        prerelease=bool(item.get("prerelease")),
    )


def load_release_history(repository: str) -> tuple[str, list[ApplicationReleaseNote]]:
    with _lock:
        cached = _history.get(repository)
        if cached is not None and cached[0] > monotonic():
            return cached[1], list(cached[2])
        status = "unavailable"
        notes: list[ApplicationReleaseNote] = []
        try:
            response = httpx.get(
                f"https://api.github.com/repos/{repository}/releases",
                params={"per_page": _HISTORY_LIMIT},
                headers={"Accept": "application/vnd.github+json"},
                timeout=5,
            )
            if response.status_code == 404:
                status = "no-release"
            else:
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, list):
                    notes = [
                        note
                        for item in payload
                        if (note := release_note(repository, item)) is not None
                    ]
                    status = "checked" if notes else "no-release"
        except (httpx.HTTPError, ValueError, AttributeError):
            pass
        _history[repository] = (monotonic() + 3600, status, notes)
        return status, list(notes)


@router.get("/application/releases", response_model=ApplicationReleaseHistory)
def application_releases() -> ApplicationReleaseHistory:
    settings = get_settings()
    installed = settings.build_version or f"{version('dewarr')}-dev"
    repository = settings.release_repository
    if not repository:
        return ApplicationReleaseHistory(
            installed_version=installed, status="unconfigured", releases=[]
        )
    status, releases = load_release_history(repository)
    return ApplicationReleaseHistory(installed_version=installed, status=status, releases=releases)
