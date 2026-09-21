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
