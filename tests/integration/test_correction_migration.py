"""Exercise the upgrade with legacy data and the guarded rollback on the isolated test DB."""

import asyncio
import subprocess
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from app.adapters.catalog_types import BookData
from app.db.models import IdentityChange, ProviderObject, User, Version, Work, WorkMetadataSource
from app.db.session import get_engine

pytestmark = pytest.mark.integration


async def migrate(*args):
    return await asyncio.to_thread(
        subprocess.run, ["uv", "run", "alembic", *args], capture_output=True, text=True
    )


async def test_correction_upgrade_backfills_sources_and_refuses_to_discard_history(database):
    async with database() as db:
        work = Work(title="Migration fixture", authors=["Writer"])
        db.add(work)
        await db.flush()
        source = WorkMetadataSource(
            work_id=work.id,
            provider="hardcover",
            external_id="42",
            snapshot=BookData(provider="hardcover", external_id="42", title=work.title).model_dump(
                mode="json"
            ),
            fetched_at=datetime.now(UTC),
        )
        version = Version(work_id=work.id, medium="audio")
        db.add_all([source, version])
        await db.flush()
        link = ProviderObject(
            provider=f"hardcover:{work.id}",
            kind="edition",
            external_id="71",
            work_id=work.id,
            version_id=version.id,
        )
        db.add(link)
        await db.commit()
        work_id, link_id, source_id = work.id, link.id, source.id
    await get_engine().dispose()
    try:
        previous = await migrate("downgrade", "0004_metadata")
        assert previous.returncode == 0, previous.stderr
        upgraded = await migrate("upgrade", "head")
        assert upgraded.returncode == 0, upgraded.stderr
        async with database() as db:
            upgraded_link = await db.get(ProviderObject, link_id)
            assert upgraded_link.metadata_source_id == source_id
            operator = User(
                username="migration-user",
                display_name="Fixture",
                role="admin",
                password_hash="not-a-login",
            )
            db.add(operator)
            await db.flush()
            db.add(
                IdentityChange(
                    kind="asset_match",
                    entity_id=uuid4(),
                    actor_id=operator.id,
                    work_id=work_id,
                    before={},
                    after={},
                    summary="Rollback fixture",
                )
            )
            await db.commit()
        await get_engine().dispose()
        async with database() as db:
            current_revision = await db.scalar(text("SELECT version_num FROM alembic_version"))
        refused = await migrate("downgrade", "0004_metadata")
        assert refused.returncode != 0
        assert "Correction history cannot be preserved" in refused.stderr
        async with database() as db:
            assert (
                await db.scalar(text("SELECT version_num FROM alembic_version")) == current_revision
            )
            assert await db.scalar(select(IdentityChange.id)) is not None
    finally:
        restored = await migrate("upgrade", "head")
        assert restored.returncode == 0, restored.stderr
        await get_engine().dispose()
