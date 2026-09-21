"""Persistent UI-managed mounts, shared by API, worker and recovery tooling."""

from app.config import get_settings
from app.db.models import ImportStorageSettings


def apply_storage(settings, destinations, staging_root):
    from pathlib import Path

    return settings.model_copy(
        update={
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
        apply_storage(get_settings(), row.destinations, row.staging_root) if row else get_settings()
    )
