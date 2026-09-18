# ruff: noqa: F401, F811
import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError

from app.db.models import (
    AcquisitionIntent,
    AcquisitionReason,
    ListAcquisitionBook,
    Operation,
    SeriesMembership,
    User,
)
from app.domain import acquisition, list_series, series_acquisition, series_requests
from app.domain.operations import transaction_lock
from tests.integration.test_acquisition import catalog, request
from tests.integration.test_acquisition_selections import selection_route
from tests.integration.test_automatic_dispatch import authorized
from tests.integration.test_automatic_pack_selection import series_pack
from tests.integration.test_automatic_selection import source
from tests.integration.test_list_policies import activate, add, policy_fixture, preview, tick

pytestmark = pytest.mark.integration
SERIES = "/api/catalog/series/hardcover/pack-series"


@pytest.fixture
async def scoped(client, database, policy_fixture, series_pack):
    async with database() as db:
        works = list(
            await db.scalars(
                select(SeriesMembership.work_id).where(SeriesMembership.series_id == series_pack)
            )
        )
    response = await client.post(
        SERIES + "/main-books",
        json={
            "work_ids": list(map(str, works)),
            "expected_generation": 1,
            "expected_review_id": None,
            "confirm_main_membership": True,
        },
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 201, response.text
    policy_fixture["config"]["preference_overrides"] = {"series_scope": "complete_series"}
    return {**policy_fixture, "works": works, "review": response.json()}


async def start(client, database, scoped):
    policy = await activate(client, scoped, await preview(client, scoped))
    await add(client, scoped)
    await tick(database, policy)
    async with database() as db:
        book = await db.scalar(select(ListAcquisitionBook))
        assert book.state == "pending", book.message
        parent = await db.get(Operation, UUID(book.progress["series_request_id"]))
    await series_requests.run(parent.id)
    async with database() as db:
        parent = await db.get(Operation, parent.id)
        assert parent.status == "completed", parent.message
        return policy, parent.id, UUID(parent.payload["acquisition_id"])


async def test_new_list_member_creates_bounded_series_with_original_authority(
    client, database, scoped
):
    policy, parent_id, controller_id = await start(client, database, scoped)
    async with database() as db:
        parent = await db.get(Operation, parent_id)
        controller = await db.get(Operation, controller_id)
        assert len(parent.payload["receipt"]) == 2
        assert parent.payload["list_origin"]["authority"]["policy_id"] == policy["id"]
        assert series_acquisition.proof(controller)["list_origin"] == parent.payload["list_origin"]
        assert parent.payload["list_origin"]["root_intent_id"] in {
            record["request_id"] for record in parent.payload["receipt"]
        }
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AcquisitionIntent)
                .where(
                    AcquisitionIntent.release_policy["preferences"]["series_scope"].astext
                    == "complete_series"
                )
            )
            == 2
        )
    await tick(database, policy, force_books=True)
    async with database() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(Operation)
                .where(Operation.kind == "series.requests")
            )
            == 1
        )


async def test_backlog_preview_freezes_reviewed_set(client, database, scoped):
    await add(client, scoped)
    plan = await preview(client, scoped, include_work_ids=[scoped["work"]])
    assert len(plan["records"][0]["series_scope"]["records"]) == 2
    policy = await activate(client, scoped, plan)
    assert (
        await client.delete(SERIES + "/main-books/" + scoped["review"]["id"])
    ).status_code == 200
    await tick(database, policy)
    async with database() as db:
        book = await db.scalar(select(ListAcquisitionBook))
        assert book.state == "pending", book.message
        parent = await db.get(Operation, UUID(book.progress["series_request_id"]))
        assert parent.payload["scope_review"]["id"] == scoped["review"]["id"]


async def test_paused_upstream_blocks_children_and_resume_preserves_scope(client, database, scoped):
    policy, parent_id, controller_id = await start(client, database, scoped)
    response = await client.post(
        f"/api/lists/{scoped['list']}/acquisition/pause",
        json={"expected_revision": policy["revision"]},
    )
    assert response.status_code == 200, response.text
    await series_acquisition.run(controller_id)
    async with database() as db:
        controller = await db.get(Operation, controller_id)
        assert controller.status == "held" and controller.payload["upstream_hold"]
    current = response.json()
    policy = await activate(
        client, scoped, await preview(client, scoped, expected_revision=current["revision"])
    )
    await tick(database, policy, force_books=True)
    async with database() as db:
        controller = await db.get(Operation, controller_id)
        assert controller.status in {"queued", "running"}, controller.message
        assert not controller.payload.get("upstream_hold")


async def test_removed_root_revokes_derived_reasons_even_with_other_manual_reason(
    client, database, scoped, admin
):
    policy, parent_id, controller_id = await start(client, database, scoped)
    # An independently requested sibling remains valid without replacing the list proof.
    sibling = next(w for w in scoped["works"] if str(w) != scoped["work"])
    await request(client, {"work_id": str(sibling), "specification": {"mode": "audio"}})
    response = await client.delete(f"/api/lists/{scoped['list']}/entries/{scoped['work']}")
    assert response.status_code == 204, response.text
    async with database() as db, db.begin():
        user = await db.get(User, UUID(admin["id"]))
        intents = list(await db.scalars(select(AcquisitionIntent)))
        for intent in intents:
            await acquisition.evaluate(db, user, intent)
        reasons = list(await db.scalars(select(AcquisitionReason)))
        assert all(not r.active for r in reasons if r.kind == "series")
        assert any(r.active and r.kind == "manual" for r in reasons)
    await series_acquisition.run(controller_id)
    async with database() as db:
        controller = await db.get(Operation, controller_id)
        assert controller.status == "held"


async def test_missing_review_holds_only_the_series_root(client, database, scoped):
    await client.delete(SERIES + "/main-books/" + scoped["review"]["id"])
    policy = await activate(client, scoped, await preview(client, scoped))
    await add(client, scoped)
    await tick(database, policy)
    async with database() as db:
        book = await db.scalar(select(ListAcquisitionBook))
        assert book.state == "held" and book.next_check_at
        assert not book.intent_id
        assert (
            await db.scalar(
                select(func.count())
                .select_from(Operation)
                .where(Operation.kind == "series.requests")
            )
            == 0
        )
    saved = await client.post(
        SERIES + "/main-books",
        json={
            "work_ids": list(map(str, scoped["works"])),
            "expected_generation": 1,
            "expected_review_id": scoped["review"]["id"],
            "confirm_main_membership": True,
        },
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert saved.status_code == 201, saved.text
    await tick(database, policy, force_books=True)
    async with database() as db:
        book = await db.scalar(select(ListAcquisitionBook))
        assert book.progress.get("series_request_id"), book.message
        parent = await db.get(Operation, UUID(book.progress["series_request_id"]))
        assert parent.payload["scope_review"]["id"] == saved.json()["id"]


async def test_changed_review_rejects_unaccepted_backlog_preview(client, database, scoped):
    await add(client, scoped)
    planned = await preview(client, scoped, include_work_ids=[scoped["work"]])
    await client.delete(SERIES + "/main-books/" + scoped["review"]["id"])
    response = await client.post(
        f"/api/lists/{scoped['list']}/acquisition/previews/{planned['id']}/activate"
    )
    assert response.status_code == 409, response.text
    assert "scope changed" in response.json()["detail"]
    async with database() as db:
        assert not await db.scalar(select(ListAcquisitionBook.id))


async def test_readdition_cannot_revive_old_derived_authority(client, database, scoped, admin):
    policy, parent_id, controller_id = await start(client, database, scoped)
    async with database() as db:
        old = await db.get(Operation, parent_id)
        saved_origin = old.payload["list_origin"]
    assert (
        await client.delete(f"/api/lists/{scoped['list']}/entries/{scoped['work']}")
    ).status_code == 204
    await add(client, scoped)
    await tick(database, policy, force_books=True)
    async with database() as db, db.begin():
        book = await db.scalar(select(ListAcquisitionBook))
        assert book.progress["series_request_id"] != str(parent_id), book.message
        assert book.progress["activation"] != saved_origin["activation"]
        with pytest.raises(HTTPException):
            await list_series.require_origin(db, UUID(admin["id"]), saved_origin)
        current = await db.get(Operation, UUID(book.progress["series_request_id"]))
        await list_series.require_origin(db, UUID(admin["id"]), current.payload["list_origin"])
    await series_acquisition.run(controller_id)
    async with database() as db:
        old_controller = await db.get(Operation, controller_id)
        assert old_controller.status == "held"


async def test_pause_before_child_creation_resumes_the_same_frozen_parent(client, database, scoped):
    policy = await activate(client, scoped, await preview(client, scoped))
    await add(client, scoped)
    await tick(database, policy, worker=False)
    async with database() as db:
        book = await db.scalar(select(ListAcquisitionBook))
        parent_id = UUID(book.progress["series_request_id"])
    paused = await client.post(
        f"/api/lists/{scoped['list']}/acquisition/pause",
        json={"expected_revision": policy["revision"]},
    )
    assert paused.status_code == 200
    await series_requests.run(parent_id)
    async with database() as db:
        parent = await db.get(Operation, parent_id)
        assert parent.status == "failed" and parent.payload["upstream_hold"]
        assert not parent.payload.get("receipt")
    resumed = await activate(
        client, scoped, await preview(client, scoped, expected_revision=paused.json()["revision"])
    )
    await tick(database, resumed)
    async with database() as db:
        book = await db.scalar(select(ListAcquisitionBook))
        parent = await db.get(Operation, parent_id)
        assert book.progress["series_request_id"] == str(parent_id)
        assert parent.status == "completed", parent.message
        assert len(parent.payload["receipt"]) == 2


async def test_scope_planning_does_not_wait_on_catalog_publication(database, scoped, admin):
    async with database() as first, first.begin():
        await transaction_lock(first, f"series-catalog:{admin['id']}:pack-series")
        async with database() as second, second.begin():
            user = await second.get(User, UUID(admin["id"]))
            planned = await asyncio.wait_for(
                list_series.plan(second, user, UUID(scoped["work"])), timeout=2
            )
            assert planned["state"] == "busy"


async def test_manual_complete_scope_cannot_silently_submit_only_root(client, scoped):
    command = {
        "work_id": scoped["work"],
        "specification": {"mode": "audio"},
        "release_preferences": {"overrides": {"series_scope": "complete_series"}},
    }
    preview_response = await client.post("/api/requests/preview", json=command)
    assert preview_response.status_code == 200, preview_response.text
    assert preview_response.json()["series_scope"]["state"] == "ready"
    response = await client.post(
        "/api/requests", json=command, headers={"Idempotency-Key": str(uuid4())}
    )
    assert response.status_code == 409, response.text
    assert "reviewed series request page" in response.json()["detail"]


async def test_publication_holds_root_and_child_reasons_until_guard_exits(
    client, database, scoped, admin
):
    from app.domain.automatic_dispatch import lock_group_principals

    _, parent_id, controller_id = await start(client, database, scoped)
    async with database() as db:
        parent = await db.get(Operation, parent_id)
        controller = await db.get(Operation, controller_id)
        root_id = UUID(parent.payload["list_origin"]["root_intent_id"])
        sibling_id = next(
            UUID(r["request_id"])
            for r in parent.payload["receipt"]
            if UUID(r["request_id"]) != root_id
        )
        selection = SimpleNamespace(
            owner_id=UUID(admin["id"]),
            intent_id=sibling_id,
            frozen={
                "automatic_selection": {"series_authority": series_acquisition.proof(controller)}
            },
        )

    async def revoke(intent_id):
        async with database() as db, db.begin():
            await db.execute(text("SET LOCAL lock_timeout = '100ms'"))
            await db.execute(
                text("UPDATE acquisition_reasons SET active=false WHERE intent_id=:id"),
                {"id": intent_id},
            )

    async with database() as db, db.begin():
        await lock_group_principals(db, [selection])
        await list_series.lock_import_reasons(db, [selection])
        await list_series.require_import_authority(db, selection)
        for intent_id in (root_id, sibling_id):
            with pytest.raises(OperationalError, match="lock timeout"):
                await revoke(intent_id)
    await revoke(root_id)
    async with database() as db:
        with pytest.raises(HTTPException, match="withdrawn before import"):
            await list_series.require_import_authority(db, selection)
