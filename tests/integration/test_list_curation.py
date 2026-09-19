# ruff: noqa: F811
import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select

from app.db.models import (
    AcquisitionIntent,
    AcquisitionReason,
    ListEntry,
    ListObservation,
    ListSubscription,
    Operation,
    Work,
)
from app.domain import list_curation, list_requests
from tests.integration.test_acquisition import catalog  # noqa: F401
from tests.integration.test_discovery import add_owned
from tests.integration.test_list_requests import preview, submit

pytestmark = pytest.mark.integration


async def book(client, name):
    response = await client.post("/api/catalog/works", json={"title": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def new_list(client):
    return (
        await client.post(
            "/api/lists", json={"name": "Curation", "description": "Keep this description"}
        )
    ).json()


async def edit(client, identifier, action, ids, key=None, **fields):
    return await client.post(
        f"/api/lists/{identifier}/curation",
        json={"action": action, "work_ids": ids, **fields},
        headers={"Idempotency-Key": key or str(uuid4())},
    )


async def details(client, identifier):
    response = await client.get(f"/api/lists/{identifier}")
    assert response.status_code == 200, response.text
    return response.json()


async def test_partial_details_edits_preserve_other_fields_and_detect_stale_settings(client, admin):
    item = await new_list(client)
    path = f"/api/lists/{item['id']}"
    updated = await client.patch(
        path, json={"shared": True, "expected_settings_revision": item["settings_revision"]}
    )
    assert updated.status_code == 200
    assert (
        updated.json()["name"] == "Curation"
        and updated.json()["description"] == "Keep this description"
    )
    assert updated.json()["settings_revision"] != item["settings_revision"]
    stale = await client.patch(
        path, json={"name": "Lost update", "expected_settings_revision": item["settings_revision"]}
    )
    assert stale.status_code == 409
    renamed = await client.patch(path, json={"name": "Renamed", "description": None})
    assert renamed.json()["shared"] is True and renamed.json()["description"] is None
    assert renamed.json()["name"] == "Renamed"
    for value in ({"name": None}, {"name": "  "}, {"shared": None}, {"unknown": "no"}):
        assert (await client.patch(path, json=value)).status_code == 422


async def test_concurrent_add_is_atomic_and_replay_cannot_readd_removed_members(
    client, admin, database
):
    item = await new_list(client)
    ids = [await book(client, name) for name in ["First", "Second"]]
    first, second = await asyncio.gather(
        *[edit(client, item["id"], "add", ids, key="same-curation-add") for _ in range(2)]
    )
    assert first.status_code == second.status_code == 200, (first.text, second.text)
    assert first.json() == second.json()
    assert first.json()["changed"] == 2
    assert [w["id"] for w in (await details(client, item["id"]))["items"]] == ids
    assert (await edit(client, item["id"], "remove", ids)).status_code == 200
    replay = await edit(client, item["id"], "add", ids, key="same-curation-add")
    assert replay.json() == first.json()
    assert (await details(client, item["id"]))["count"] == 0
    assert (
        await edit(client, item["id"], "add", ids[:1], key="same-curation-add")
    ).status_code == 409
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(AcquisitionIntent)) == 0
        assert (
            await db.scalar(
                select(func.count()).select_from(Operation).where(Operation.kind == "lists.curate")
            )
            == 2
        )


async def test_remove_receipt_and_membership_revision_protect_readded_episode(client, admin):
    item = await new_list(client)
    ids = [await book(client, "Book")]
    await edit(client, item["id"], "add", ids)
    before = await details(client, item["id"])
    first = await edit(
        client,
        item["id"],
        "remove",
        ids,
        key="same-removal",
        expected_revision=before["content_revision"],
    )
    assert first.status_code == 200, first.text
    await edit(client, item["id"], "add", ids)
    after = await details(client, item["id"])
    assert after["content_revision"] != before["content_revision"]
    replay = await edit(
        client,
        item["id"],
        "remove",
        ids,
        key="same-removal",
        expected_revision=before["content_revision"],
    )
    assert replay.json() == first.json()
    assert (await details(client, item["id"]))["count"] == 1
    assert (
        await edit(client, item["id"], "remove", ids, expected_revision=before["content_revision"])
    ).status_code == 409


async def test_reordering_checks_current_membership_and_order(client, admin):
    item = await new_list(client)
    ids = [await book(client, name) for name in ["First", "Second"]]
    await edit(client, item["id"], "add", ids)
    revision = (await details(client, item["id"]))["content_revision"]
    path = f"/api/lists/{item['id']}/order"
    assert (
        await client.put(
            path, json={"work_ids": list(reversed(ids)), "expected_revision": revision}
        )
    ).status_code == 204
    assert (
        await client.put(path, json={"work_ids": ids, "expected_revision": revision})
    ).status_code == 409
    assert [w["id"] for w in (await details(client, item["id"]))["items"]] == list(reversed(ids))


async def test_canonical_batch_membership_and_durable_external_exclusions(client, admin, database):
    item = await new_list(client)
    origin, root = [UUID(await book(client, name)) for name in ["Origin", "Canonical"]]
    async with database() as db, db.begin():
        (await db.get(Work, origin)).redirect_to = root
        sub = ListSubscription(list_id=UUID(item["id"]), encrypted_config="opaque-config")
        db.add(sub)
        await db.flush()
        db.add(
            ListObservation(
                subscription_id=sub.id,
                external_id="99",
                work_id=origin,
                snapshot={},
                last_seen_at=datetime.now(UTC),
            )
        )
    added = await edit(client, item["id"], "add", list(map(str, [origin, root])))
    assert added.status_code == 200, added.text
    assert added.json()["changed"] == added.json()["selected"] == 1
    assert (await details(client, item["id"]))["items"][0]["id"] == str(root)
    removed = await edit(client, item["id"], "remove", [str(root)])
    assert removed.json()["changed"] == 1
    async with database() as db:
        assert (await db.scalar(select(ListObservation))).excluded is True
        assert await db.scalar(select(func.count()).select_from(ListEntry)) == 0
    await edit(client, item["id"], "add", [str(origin)])
    async with database() as db:
        assert (await db.scalar(select(ListEntry))).locally_added is True
        assert (await db.scalar(select(ListObservation))).excluded is True


async def test_invalid_batch_has_no_partial_effect_and_failed_withdrawal_rolls_back(
    client, admin, database, monkeypatch
):
    item = await new_list(client)
    ids = [await book(client, name) for name in ["First", "Second"]]
    assert (await edit(client, item["id"], "add", [ids[0], str(uuid4())])).status_code == 404
    assert (await details(client, item["id"]))["count"] == 0
    await edit(client, item["id"], "add", ids)
    real = list_curation.withdraw_list_reasons
    calls = 0

    async def failing(*args):
        nonlocal calls
        calls += 1
        await real(*args)
        if calls == 2:
            raise RuntimeError("injected rollback")

    monkeypatch.setattr(list_curation, "withdraw_list_reasons", failing)
    with pytest.raises(RuntimeError, match="injected rollback"):
        await edit(client, item["id"], "remove", ids, key="rollback-removal")
    assert (await details(client, item["id"]))["count"] == 2
    async with database() as db:
        assert (
            await db.scalar(
                select(Operation).where(Operation.idempotency_key == "rollback-removal")
            )
            is None
        )


async def test_bulk_removal_withdraws_only_its_list_reason(client, admin, catalog, database):
    first, second = await new_list(client), await new_list(client)
    for item in [first, second]:
        await edit(client, item["id"], "add", [str(catalog["work"])])
        batch = await preview(client, item["id"], [catalog["work"]], mode="audio")
        await submit(client, item["id"], batch)
        await list_requests.run(UUID(batch["id"]))
    response = await edit(client, first["id"], "remove", [str(catalog["work"])])
    assert response.status_code == 200, response.text
    async with database() as db:
        reasons = list(await db.scalars(select(AcquisitionReason)))
        assert next(r for r in reasons if r.reference == first["id"]).active is False
        assert next(r for r in reasons if r.reference == second["id"]).active is True
        assert await db.scalar(select(func.count()).select_from(AcquisitionIntent)) == 1
    assert (await details(client, second["id"]))["count"] == 1


@pytest.mark.parametrize("role", ["member", "viewer"])
async def test_shared_list_is_read_only_with_scoped_ownership_and_no_private_connections(
    client, admin, database, role
):
    item = await new_list(client)
    async with database() as db, db.begin():
        work = Work(
            title="Private catalog book", catalog_public=False, catalog_owner_id=UUID(admin["id"])
        )
        db.add(work)
        await db.flush()
        await add_owned(db, work)
        work_id = str(work.id)
    await edit(client, item["id"], "add", [work_id])
    response = await client.post(
        "/api/auth/users",
        json={
            "username": "sharedreader",
            "display_name": "Shared Reader",
            "role": role,
            "password": "shared reader password",
        },
    )
    assert response.status_code == 201, response.text
    from app.main import create_app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()),
        base_url="http://testserver",
        headers={"Origin": "http://testserver"},
    ) as reader:
        login = await reader.post(
            "/api/auth/login",
            json={"username": "sharedreader", "password": "shared reader password"},
        )
        reader.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        path = f"/api/lists/{item['id']}"
        assert (await reader.get(path)).status_code == 404
        await client.patch(path, json={"shared": True})
        shared = await reader.get(path)
        assert shared.status_code == 200 and shared.json()["editable"] is False
        assert shared.json()["items"][0]["availability"]["owned"] is False
        assert "no-store" in shared.headers["cache-control"]
        expected = 403 if role == "viewer" else 404
        assert (await edit(reader, item["id"], "add", [work_id])).status_code == expected
        assert (await reader.patch(path, json={"name": "Hijacked"})).status_code == expected
        assert (
            await reader.put(path + "/order", json={"work_ids": [work_id]})
        ).status_code == expected
        for suffix in ["/subscription", "/acquisition", "/requests"]:
            assert (await reader.get(path + suffix)).status_code in {403, 404}
        await client.patch(path, json={"shared": False})
        assert (await reader.get(path)).status_code == 404
        assert (await reader.get("/api/lists")).json() == []
        assert (await reader.get("/api/catalog/works/" + work_id)).status_code == 404


async def test_batch_validation_and_deleted_list_receipt(client, admin):
    item = await new_list(client)
    identifier = await book(client, "One")
    for ids in [[], [identifier, identifier], [str(uuid4()) for _ in range(101)]]:
        assert (await edit(client, item["id"], "add", ids)).status_code == 422
    await edit(client, item["id"], "add", [identifier], key="receipt-before-delete")
    await client.delete(f"/api/lists/{item['id']}")
    assert (
        await edit(client, item["id"], "add", [identifier], key="receipt-before-delete")
    ).status_code == 404


async def test_read_projects_one_order_revision_while_a_writer_waits(client, admin, monkeypatch):
    from app.api import lists

    item = await new_list(client)
    ids = [await book(client, name) for name in ["First", "Second"]]
    await edit(client, item["id"], "add", ids)
    before = await details(client, item["id"])
    real_availability = lists.availability_for
    real_context = list_curation.owner_context
    reached = asyncio.Event()
    writer = None

    async def context(*args):
        reached.set()
        return await real_context(*args)

    async def availability(*args):
        nonlocal writer
        writer = asyncio.create_task(
            client.put(f"/api/lists/{item['id']}/order", json={"work_ids": list(reversed(ids))})
        )
        await asyncio.wait_for(reached.wait(), timeout=5)
        assert not writer.done()
        return await real_availability(*args)

    monkeypatch.setattr(list_curation, "owner_context", context)
    monkeypatch.setattr(lists, "availability_for", availability)
    observed = await details(client, item["id"])
    assert observed["content_revision"] == before["content_revision"]
    assert [w["id"] for w in observed["items"]] == ids
    assert (await asyncio.wait_for(writer, timeout=5)).status_code == 204
    monkeypatch.setattr(lists, "availability_for", real_availability)
    assert [w["id"] for w in (await details(client, item["id"]))["items"]] == list(reversed(ids))


async def test_reordering_retains_inaccessible_memberships_without_exposing_ids(
    client, admin, database
):
    from tests.integration.test_discovery import login_member

    owner = await login_member(client)
    item = await new_list(client)
    ids = [UUID(await book(client, name)) for name in ["First", "Last"]]
    await edit(client, item["id"], "add", list(map(str, ids)))
    async with database() as db, db.begin():
        hidden = Work(
            title="Revoked private book", catalog_public=False, catalog_owner_id=UUID(admin["id"])
        )
        db.add(hidden)
        await db.flush()
        hidden_id = hidden.id
        entries = list(
            await db.scalars(
                select(ListEntry)
                .where(ListEntry.list_id == UUID(item["id"]))
                .order_by(ListEntry.position)
            )
        )
        entries[0].position, entries[1].position = 0, 2
        db.add(ListEntry(list_id=UUID(item["id"]), work_id=hidden.id, position=1))
    before = await details(client, item["id"])
    assert before["count"] == 2
    response = await client.put(
        f"/api/lists/{item['id']}/order",
        json={
            "work_ids": list(map(str, reversed(ids))),
            "expected_revision": before["content_revision"],
        },
    )
    assert response.status_code == 204, response.text
    after = await details(client, item["id"])
    assert [w["id"] for w in after["items"]] == list(map(str, reversed(ids)))
    assert hidden_id.hex not in str(after)
    async with database() as db:
        preserved = await db.scalar(select(ListEntry).where(ListEntry.work_id == hidden_id))
        assert preserved.position == 1
    assert owner != UUID(admin["id"])
