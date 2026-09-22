"""Persistent UI-managed mounts, shared by API, worker and recovery tooling."""

import re
from pathlib import Path

from app.config import get_settings
from app.db.models import ImportStorageSettings

_KEY = re.compile(r"^[a-z0-9_-]{1,60}$")


def apply_storage(settings, destinations, staging_root, sources=None):
    merged = dict(settings.import_sources)
    for key, path in (sources or {}).items():
        candidate = Path(path)
        if (
            isinstance(key, str)
            and _KEY.fullmatch(key)
            and key not in merged
            and candidate.is_absolute()
            and str(candidate) != "/"
            and ".." not in candidate.parts
        ):
            merged[key] = candidate
    return settings.model_copy(
        update={
            "import_sources": merged,
            "import_destinations": {
                **settings.import_destinations,
                **{key: Path(path) for key, path in destinations.items()},
            },
            "import_staging_root": Path(staging_root)
            if staging_root
            else settings.import_staging_root,
        }
    )


async def storage_settings(db):
    row = await db.get(ImportStorageSettings, 1, populate_existing=True)
    return (
        apply_storage(get_settings(), row.destinations, row.staging_root, row.sources)
        if row
        else get_settings()
    )


async def import_sources(db):
    return (await storage_settings(db)).import_sources
