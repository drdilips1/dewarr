import asyncio
import subprocess
from uuid import UUID

import pytest
from sqlalchemy import select, text

from app.db.models import IdentityChange, LibraryAsset
from tests.integration.test_containment import setup

pytestmark = pytest.mark.integration


async def migrate(*arguments):
    return await asyncio.to_thread(
        subprocess.run, ["uv", "run", "alembic", *arguments], capture_output=True, text=True
    )


async def test_ordinary_assets_round_trip_but_live_or_historical_contents_prevent_downgrade(
    client, admin, database
):
    _, _, asset, _ = await setup(client)
    async with database() as db:
        original_revision = await db.scalar(text("SELECT version_num FROM alembic_version"))
    try:
        lowered = await migrate("downgrade", "0037_download_joins")
        assert lowered.returncode == 0, lowered.stderr
        raised = await migrate("upgrade", "head")
        assert raised.returncode == 0, raised.stderr
        async with database() as db, db.begin():
            record = await db.get(LibraryAsset, UUID(asset["id"]))
            assert record.title == asset["title"] and record.containment is None
            assert str(record.version_id) == asset["version_id"]
            record.containment = {"valid": True, "evidence": "migration-fixture", "work_ids": []}
        rejected = await migrate("downgrade", "0037_download_joins")
        assert rejected.returncode != 0
        assert "pre-upgrade backup" in rejected.stderr
        async with database() as db, db.begin():
            record = await db.get(LibraryAsset, UUID(asset["id"]))
            previous = record.containment
            record.containment = None
            db.add(
                IdentityChange(
                    actor_id=UUID(admin["id"]),
                    kind="asset_match",
                    entity_id=record.id,
                    before={"containment": previous},
                    after={"containment": None},
                    summary="Historical collection",
                )
            )
            await db.flush()
            assert (
                await db.scalar(select(LibraryAsset.id).where(LibraryAsset.containment.is_(None)))
                == record.id
            )
        rejected = await migrate("downgrade", "0037_download_joins")
        assert rejected.returncode != 0 and "pre-upgrade backup" in rejected.stderr
        async with database() as db:
            assert (
                await db.scalar(text("SELECT version_num FROM alembic_version"))
                == original_revision
            )
    finally:
        raised = await migrate("upgrade", "head")
        assert raised.returncode == 0, raised.stderr
