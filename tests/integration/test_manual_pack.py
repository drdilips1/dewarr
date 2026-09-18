# ruff: noqa: F401, F811
"""Finite reviewed preparation composes the existing manual selection and transfer APIs."""

import asyncio
import base64
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text

from app.adapters.torrent_descriptor import inspect_torrent
from app.db.models import (
    AcquisitionIntent,
    AcquisitionSelection,
    AssetContains,
    DownloadAttempt,
    LibraryAsset,
    LibraryGrant,
    Operation,
    SeriesMembership,
    SourceArtifact,
    User,
    Version,
    Work,
)
from app.domain import acquisition_selection
from app.domain.work_graph import acquisition_lock
from app.security import encrypt_secrets, hash_password
from tests.integration.test_acquisition import catalog
from tests.integration.test_acquisition_defaults import save as save_preferences
from tests.integration.test_acquisition_selections import prepare, selection_route
from tests.integration.test_automatic_pack_selection import series_pack
from tests.integration.test_automatic_selection import source
from tests.integration.test_pack_expansion import review
from tests.torrent_fixture import torrent_bytes

pytestmark = pytest.mark.integration


@pytest.fixture
async def pack(client, database, admin, catalog, selection_route, series_pack):
    await review(client, database, series_pack)
    selected = await prepare(client, selection_route)
    assert selected.status_code == 201, selected.text
    root = selected.json()
    async with database() as db, db.begin():
        user = await db.get(User, UUID(admin["id"]))
        user.role, user.can_automate = "member", False
        db.add(LibraryGrant(user_id=user.id, library_id=catalog["library"]))
    return root


async def scope(client, pack):
    result = await client.get(f"/api/acquisition/selections/{pack['id']}/pack-preview")
    assert result.status_code == 200, result.text
    return result.json()


async def accept(client, pack, preview, *, key=None, ids=None):
    return await client.post(
        f"/api/acquisition/selections/{pack['id']}/pack-selections",
        headers={"Idempotency-Key": key or str(uuid4())},
        json={
            "revision": preview["revision"],
            "work_ids": ids if ids is not None else [r["work_id"] for r in preview["records"]],
        },
    )


async def test_review_is_read_only_and_acceptance_prepares_group_without_download(
    client, database, pack
):
    preview = await scope(client, pack)
    assert preview["state"] == "ready" and len(preview["records"]) == 1
    assert preview["records"][0]["title"] == "Roads"
    assert preview["records"][0]["state"] == "wanted"
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(AcquisitionIntent)) == 1
        assert await db.scalar(select(func.count()).select_from(AcquisitionSelection)) == 1
    accepted = await accept(client, pack, preview)
    assert accepted.status_code == 201, accepted.text
    result = accepted.json()
    assert len(result["selections"]) == 2
    assert {r["title"] for r in result["selections"]} == {"Harbor", "Roads"}
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(AcquisitionIntent)) == 2
        assert not await db.scalar(select(DownloadAttempt.id))
        assert {s.state for s in await db.scalars(select(AcquisitionSelection))} == {"prepared"}
    parent = await client.get(
        f"/api/catalog/series/hardcover/pack-series/requests/{result['request_id']}"
    )
    assert parent.status_code == 200, parent.text
    assert not parent.json()["automatic"] and len(parent.json()["records"]) == 1


async def test_concurrent_duplicate_commands_and_new_key_replay_are_idempotent(
    client, database, pack
):
    preview = await scope(client, pack)
    responses = await asyncio.gather(
        *(accept(client, pack, preview, key="same-manual-pack-command") for _ in range(2))
    )
    assert all(r.status_code == 201 for r in responses), [r.text for r in responses]
    replay = await accept(client, pack, preview, key="alias-manual-pack-command")
    assert replay.status_code == 201 and replay.json() == responses[0].json(), replay.text
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(AcquisitionSelection)) == 2
        assert (
            await db.scalar(
                select(func.count())
                .select_from(Operation)
                .where(Operation.kind == "series.requests")
            )
            == 1
        )


@pytest.mark.parametrize(
    "change", ["withdraw_review", "cancel_root", "wrong_revision", "outside", "duplicate"]
)
async def test_changed_or_outside_scope_cannot_prepare_children(client, database, pack, change):
    preview = await scope(client, pack)
    ids = None
    if change == "withdraw_review":
        saved = (await client.get("/api/catalog/series/hardcover/pack-series/main-books")).json()
        assert (
            await client.delete(
                f"/api/catalog/series/hardcover/pack-series/main-books/{saved['id']}"
            )
        ).status_code == 200
    elif change == "cancel_root":
        assert (await client.delete(f"/api/acquisition/selections/{pack['id']}")).status_code == 200
    elif change == "wrong_revision":
        preview["revision"] = "0" * 64
    elif change == "outside":
        ids = [str(uuid4())]
    else:
        ids = [preview["records"][0]["work_id"]] * 2
    response = await accept(client, pack, preview, ids=ids)
    assert response.status_code in {409, 422}, response.text
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(AcquisitionIntent)) == 1
        assert not await db.scalar(select(DownloadAttempt.id))


async def test_child_failure_rolls_back_requests_selections_and_parent(
    client, database, pack, monkeypatch
):
    preview = await scope(client, pack)
    original = acquisition_selection.prepare

    async def fail_after_prepare(*args, **kwargs):
        await original(*args, **kwargs)
        raise HTTPException(409, "Synthetic changed child route")

    monkeypatch.setattr(acquisition_selection, "prepare", fail_after_prepare)
    response = await accept(client, pack, preview)
    assert response.status_code == 409, response.text
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(AcquisitionIntent)) == 1
        assert await db.scalar(select(func.count()).select_from(AcquisitionSelection)) == 1
        assert not await db.scalar(select(Operation.id).where(Operation.kind == "series.requests"))


@pytest.mark.parametrize("change", ["preferences", "descriptor", "release", "ownership"])
async def test_changed_evidence_rejects_old_preview(client, database, catalog, pack, change):
    preview = await scope(client, pack)
    child_id = UUID(preview["records"][0]["work_id"])
    if change == "preferences":
        await save_preferences(client, {"audio_formats": ["mp3", "m4b"]})
    else:
        async with database() as db, db.begin():
            selected = await db.get(AcquisitionSelection, UUID(pack["id"]))
            artifact = await db.get(SourceArtifact, selected.artifact_id)
            if change == "descriptor":
                descriptor = dict(artifact.descriptor)
                descriptor["files"] = [dict(f) for f in descriptor["files"]]
                descriptor["files"][0]["path"] = "Coast/Different.m4b"
                artifact.descriptor = descriptor
            elif change == "release":
                artifact.release_snapshot = {**artifact.release_snapshot, "seeders": 999}
            else:
                version = Version(
                    work_id=child_id,
                    medium="audio",
                    language="en",
                    narrators=["Reader A"],
                    abridged=False,
                )
                db.add(version)
                await db.flush()
                asset = LibraryAsset(
                    library_id=catalog["library"],
                    external_id="owned-child",
                    version_id=version.id,
                    medium="audio",
                    state="present",
                    full_content=True,
                )
                db.add(asset)
                await db.flush()
                db.add(AssetContains(asset_id=asset.id, work_id=child_id, verified=True))
    response = await accept(client, pack, preview)
    assert response.status_code == 409, response.text
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(AcquisitionIntent)) == 1
    if change == "ownership":
        current = await scope(client, pack)
        assert current["records"][0]["state"] == "satisfied"
        receipt = await accept(client, pack, current)
        assert receipt.status_code == 201, receipt.text
        assert len(receipt.json()["selections"]) == 1
        assert receipt.json()["records"][0]["selection_id"] is None


async def test_prepared_automatic_selection_is_not_adopted_into_manual_group(
    client, database, pack
):
    first = await accept(client, pack, await scope(client, pack))
    assert first.status_code == 201, first.text
    child = first.json()["selections"][1]["id"]
    async with database() as db, db.begin():
        selected = await db.get(AcquisitionSelection, UUID(child))
        selected.frozen = {**selected.frozen, "automatic_selection": {"operation_id": str(uuid4())}}
    refreshed = await scope(client, pack)
    response = await accept(client, pack, refreshed)
    assert response.status_code == 201, response.text
    assert len(response.json()["selections"]) == 1
    assert response.json()["records"][0]["state"] == "pending"


async def test_corrupt_saved_bytes_have_actionable_error_and_no_partial_writes(
    client, database, pack
):
    preview = await scope(client, pack)
    async with database() as db, db.begin():
        selected = await db.get(AcquisitionSelection, UUID(pack["id"]))
        artifact = await db.get(SourceArtifact, selected.artifact_id)
        artifact.encrypted_content = encrypt_secrets({"torrent": "bm90IGEgdG9ycmVudA=="})
    for response in (
        await client.get(f"/api/acquisition/selections/{pack['id']}/pack-preview"),
        await accept(client, pack, preview),
    ):
        assert response.status_code == 502, response.text
        assert response.json()["detail"] == "Stored torrent integrity could not be verified."
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(AcquisitionSelection)) == 1
        assert not await db.scalar(select(Operation.id).where(Operation.kind == "series.requests"))


async def test_distinct_subsets_of_pending_pack_do_not_collide(
    client, database, admin, catalog, selection_route, series_pack, source
):
    async with database() as db, db.begin():
        third = Work(title="Shores", authors=["Writer"], catalog_owner_id=UUID(admin["id"]))
        db.add(third)
        await db.flush()
        db.add(
            SeriesMembership(
                series_id=series_pack,
                work_id=third.id,
                external_id="3",
                snapshot={
                    "entry_id": "3",
                    "book": {
                        "provider": "hardcover",
                        "external_id": "3",
                        "title": "Shores",
                        "authors": ["Writer"],
                    },
                    "position": "3",
                    "release_date": "2020-01-01",
                    "compilation": False,
                    "partial": False,
                    "canonical_id": None,
                },
            )
        )
    raw = torrent_bytes(
        name=b"Coast",
        files=[
            {b"length": 12, b"path": [name]}
            for name in (b"Harbor.m4b", b"Roads.m4b", b"Shores.m4b")
        ],
    )
    descriptor = await inspect_torrent(raw)
    async with database() as db, db.begin():
        artifact = await db.get(SourceArtifact, source["artifact"])
        artifact.sha256 = descriptor.artifact_sha256
        artifact.descriptor = descriptor.model_dump(mode="json")
        artifact.encrypted_content = encrypt_secrets({"torrent": base64.b64encode(raw).decode()})
    await review(client, database, series_pack)
    response = await prepare(client, selection_route)
    assert response.status_code == 201, response.text
    root = response.json()
    accepted = await accept(client, root, await scope(client, root))
    assert accepted.status_code == 201, accepted.text
    assert len(accepted.json()["selections"]) == 3
    pending = await scope(client, root)
    assert {r["state"] for r in pending["records"]} == {"pending"}
    for record in pending["records"]:
        receipt = await accept(client, root, pending, ids=[record["work_id"]])
        assert receipt.status_code == 201, receipt.text
        assert len(receipt.json()["selections"]) == 2
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(AcquisitionSelection)) == 3
        assert (
            await db.scalar(
                select(func.count())
                .select_from(Operation)
                .where(Operation.kind == "series.requests")
            )
            == 3
        )


async def test_foreign_user_cannot_read_prepare_or_replay_pack(client, database, pack):
    preview = await scope(client, pack)
    result = await accept(client, pack, preview, key="private-pack-command")
    assert result.status_code == 201, result.text
    async with database() as db, db.begin():
        db.add(
            User(
                username="other-pack-user",
                display_name="Other",
                role="member",
                password_hash=hash_password("other pack password"),
            )
        )
    async with httpx.AsyncClient(
        transport=client._transport,
        base_url="http://testserver",
        headers={"Origin": "http://testserver"},
    ) as other:
        login = await other.post(
            "/api/auth/login",
            json={"username": "other-pack-user", "password": "other pack password"},
        )
        assert login.status_code == 200, login.text
        other.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        assert (
            await other.get(f"/api/acquisition/selections/{pack['id']}/pack-preview")
        ).status_code == 404
        response = await accept(other, pack, preview, key="private-pack-command")
        assert response.status_code == 404, response.text


async def test_root_cancellation_wins_while_batch_waits_for_work_lock(client, database, pack):
    preview = await scope(client, pack)
    task = None
    try:
        async with database() as blocker, blocker.begin():
            await acquisition_lock(blocker, UUID(pack["work_id"]))
            pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
            task = asyncio.create_task(accept(client, pack, preview))
            async with asyncio.timeout(5):
                while True:
                    assert not task.done(), "Preparation bypassed the root work lock"
                    waiting = await blocker.scalar(
                        text(
                            "SELECT EXISTS(SELECT 1 FROM pg_locks waiting JOIN pg_locks held USING "
                            "(locktype, database, classid, objid, objsubid) WHERE held.pid=:pid "
                            "AND held.granted AND NOT waiting.granted AND held.locktype='advisory')"
                        ),
                        {"pid": pid},
                    )
                    if waiting:
                        break
                    await asyncio.sleep(0.01)
            selected = await blocker.get(AcquisitionSelection, UUID(pack["id"]))
            actor = await blocker.get(User, selected.owner_id)
            await acquisition_selection.cancel(blocker, actor, selected)
        async with asyncio.timeout(5):
            response = await task
            assert response.status_code == 409, response.text
        async with database() as db:
            assert await db.scalar(select(func.count()).select_from(AcquisitionSelection)) == 1
            assert not await db.scalar(
                select(Operation.id).where(Operation.kind == "series.requests")
            )
    finally:
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
