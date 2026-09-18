# ruff: noqa: F401, F811
"""Accepted finite pack scope and release-source constraints."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.db.models import AcquisitionSelection, Operation, SeriesMembership, SourceResult, User
from app.domain import automatic_selection as automatic
from app.domain import pack_expansion, series_acquisition, series_requests
from app.domain.release_profiles import ProfileSnapshot
from tests.integration.test_acquisition import catalog
from tests.integration.test_acquisition_selections import selection_route
from tests.integration.test_automatic_dispatch import authorized
from tests.integration.test_automatic_pack_selection import series_pack
from tests.integration.test_automatic_selection import detail, source, start

pytestmark = pytest.mark.integration
SERIES = "/api/catalog/series/hardcover/pack-series"


async def review(client, database, series_id, *, root_only=False, root_id=None):
    async with database() as db:
        ids = list(
            await db.scalars(
                select(SeriesMembership.work_id).where(SeriesMembership.series_id == series_id)
            )
        )
    response = await client.post(
        SERIES + "/main-books",
        json={
            "work_ids": [str(root_id)] if root_only else list(map(str, ids)),
            "expected_generation": 1,
            "expected_review_id": None,
            "confirm_main_membership": True,
        },
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize("scope", ["none", "root", "all"])
async def test_pack_expansion_intersects_review_and_replays_once(
    client, database, admin, catalog, series_pack, authorized, scope
):
    if scope != "none":
        await review(
            client, database, series_pack, root_only=scope == "root", root_id=catalog["work"]
        )
    saved = await start(client, authorized)
    await automatic.run(UUID(saved["id"]))
    value = await detail(client, saved["id"])
    assert value["selection_id"], value
    expected = {"none": "review", "root": "empty", "all": "accepted"}[scope]
    assert value["pack_expansion"]["state"] == expected
    async with database() as db, db.begin():
        operation = await db.get(Operation, UUID(value["id"]))
        selection = await db.get(AcquisitionSelection, UUID(value["selection_id"]))
        # Replaying the acceptance step must never generate another parent/job.
        await pack_expansion.create(
            db,
            await db.get(User, UUID(admin["id"])),
            operation,
            selection,
            selection.frozen["automatic_selection"]["coverage"],
        )
        parents = list(
            await db.scalars(select(Operation).where(Operation.kind == "series.requests"))
        )
        assert len(parents) == (1 if scope == "all" else 0)
        if parents:
            parent = parents[0]
            assert len(parent.payload["records"]) == 1
            assert parent.payload["records"][0]["work_id"] != str(catalog["work"])
            assert parent.payload["effective_specification"]["mode"] == "audio"
            assert parent.payload["pack_origin"]["artifact_id"] == value["artifact_id"]
    await automatic.run(UUID(saved["id"]))
    assert len(authorized["resolver"].calls) == 1


async def test_extra_children_reject_other_sources_before_resolving_them(
    client, database, admin, catalog, series_pack, authorized
):
    await review(client, database, series_pack)
    saved = await start(client, authorized)
    await automatic.run(UUID(saved["id"]))
    value = await detail(client, saved["id"])
    async with database() as db, db.begin():
        parent = await db.get(Operation, UUID(value["pack_expansion"]["request_id"]))
        root = await db.get(Operation, UUID(value["id"]))
        selection = await db.get(AcquisitionSelection, UUID(value["selection_id"]))
        root.payload = {
            **root.payload,
            "series_authority": {"pack_origin": parent.payload["pack_origin"]},
        }
        original = await db.get(SourceResult, authorized["result"])
        other = SourceResult(
            owner_id=original.owner_id,
            operation_id=original.operation_id,
            source_key=original.source_key,
            source_generation=original.source_generation,
            expires_at=original.expires_at,
            encrypted_reference=original.encrypted_reference,
            release_snapshot={
                **original.release_snapshot,
                "source_id": "different",
                "seeders": 99999,
            },
        )
        db.add(other)
        await db.flush()
        from app.domain.work_graph import canonical_work

        work = await canonical_work(db, UUID(selection.frozen["work_id"]))
        ranked = await automatic.candidates(
            db,
            root,
            work,
            ProfileSnapshot.model_validate(root.payload["profile"]),
            selection.frozen["requirements"],
            None,
        )
        rejected = next(problems for _, row, _, problems in ranked if row.id == other.id)
        assert "Additional pack books must use their originally selected torrent" in rejected
        assert not next(problems for _, row, _, problems in ranked if row.id == original.id)


async def verify_pack_locks(database, root_intent_id, child_selection_id):
    """A late child join fences its absent root and publication fences reasons."""
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    from app.db.models import AcquisitionIntent
    from app.domain import download_memberships, list_series
    from app.domain.automatic_dispatch import lock_group_principals
    from app.domain.work_graph import acquisition_lock

    async with database() as db:
        root = await db.get(AcquisitionIntent, root_intent_id)

    async def cancel_root_lock():
        async with database() as writer, writer.begin():
            await writer.execute(text("SET LOCAL lock_timeout = '100ms'"))
            await acquisition_lock(writer, root.work_id)

    async with database() as reader, reader.begin():
        child = await reader.get(AcquisitionSelection, child_selection_id)
        await download_memberships.lock(reader, [child])
        with pytest.raises(OperationalError, match="lock timeout"):
            await cancel_root_lock()
    await cancel_root_lock()

    async def withdraw_root():
        async with database() as writer, writer.begin():
            await writer.execute(text("SET LOCAL lock_timeout = '100ms'"))
            await writer.execute(
                text("UPDATE acquisition_reasons SET active=false WHERE intent_id=:id"),
                {"id": root_intent_id},
            )

    async with database() as reader, reader.begin():
        child = await reader.get(AcquisitionSelection, child_selection_id)
        await lock_group_principals(reader, [child])
        await list_series.lock_import_reasons(reader, [child])
        await list_series.require_import_authority(reader, child)
        with pytest.raises(OperationalError, match="lock timeout"):
            await withdraw_root()


async def test_owned_covered_child_is_recorded_without_another_download(
    client, database, admin, catalog, series_pack, authorized
):
    from app.db.models import AssetContains, ImportDestination, LibraryAsset, Version

    await review(client, database, series_pack)
    saved = await start(client, authorized)
    await automatic.run(UUID(saved["id"]))
    value = await detail(client, saved["id"])
    parent_id = UUID(value["pack_expansion"]["request_id"])
    async with database() as db, db.begin():
        parent = await db.get(Operation, parent_id)
        work_id = UUID(parent.payload["records"][0]["work_id"])
        destination = await db.get(ImportDestination, UUID(authorized["body"]["destination_id"]))
        version = Version(
            work_id=work_id, title="Roads", medium="audio", language="en", narrators=[]
        )
        db.add(version)
        await db.flush()
        asset = LibraryAsset(
            library_id=destination.library_id,
            external_id="already-owned-pack-child",
            version_id=version.id,
            medium="audio",
            state="present",
            full_content=True,
        )
        db.add(asset)
        await db.flush()
        db.add(AssetContains(asset_id=asset.id, work_id=work_id, verified=True))
    await series_requests.run(parent_id)
    async with database() as db:
        parent = await db.get(Operation, parent_id)
        controller_id = UUID(parent.payload["acquisition_id"])
    await series_acquisition.run(controller_id)
    value = (await client.get(f"{SERIES}/requests/{parent_id}")).json()
    assert value["counts"]["satisfied"] == 1, value
    assert value["acquisition_status"] == "completed", value
    async with database() as db:
        assert (
            await db.scalar(
                select(func.count()).select_from(Operation).where(Operation.kind == automatic.KIND)
            )
            == 1
        )
    assert not authorized["qbit"].calls


async def test_child_uses_saved_pack_observation_without_another_network_job(
    client, database, admin, catalog, series_pack, authorized
):
    from sqlalchemy import text

    from app.db.models import SourceArtifact

    await review(client, database, series_pack)
    saved = await start(client, authorized)
    await automatic.run(UUID(saved["id"]))
    value = await detail(client, saved["id"])
    parent_id = UUID(value["pack_expansion"]["request_id"])
    await series_requests.run(parent_id)
    async with database() as db:
        parent = await db.get(Operation, parent_id)
        controller_id = UUID(parent.payload["acquisition_id"])
        count = await db.scalar(
            text(
                "SELECT count(*) FROM book_queue.procrastinate_jobs "
                "WHERE task_name='sources.search'"
            )
        )
    await series_acquisition.run(controller_id)
    async with database() as db:
        search = await db.scalar(
            select(Operation).where(
                Operation.kind == "sources.search",
                Operation.payload["command"]["pack_origin"]["selection_id"].astext
                == value["selection_id"],
            )
        )
        assert search is not None
        assert search.status == "completed" and not search.job_id
        assert search.payload["workers"] == {}
        result = await db.scalar(select(SourceResult).where(SourceResult.operation_id == search.id))
        artifact = await db.get(SourceArtifact, UUID(value["artifact_id"]))
        assert result.release_snapshot == artifact.release_snapshot
        assert (
            await db.scalar(
                text(
                    "SELECT count(*) FROM book_queue.procrastinate_jobs "
                    "WHERE task_name='sources.search'"
                )
            )
            == count
        )
