import asyncio
from uuid import UUID

import httpx
import pytest
from sqlalchemy import func, select, text

from app.adapters.catalog_types import BookData, EditionData
from app.db.models import (
    AcquisitionReservation,
    AcquisitionTarget,
    AssetContains,
    LibraryAsset,
    LibraryGrant,
    ListEntry,
    ProviderObject,
    User,
    Version,
    Work,
    WorkMetadataSource,
)
from app.domain.catalog_metadata import attach_source
from app.security import hash_password
from tests.integration.test_acquisition import body, request
from tests.integration.test_acquisition import catalog as catalog

pytestmark = pytest.mark.integration


async def book(client, title="Main catalog title"):
    response = await client.post("/api/catalog/works", json={"title": title, "authors": ["Writer"]})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def preview(client, source, target):
    response = await client.post(
        "/api/identity/works/merge/preview",
        json={"source_id": str(source), "target_id": str(target)},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def merge(client, source, target):
    plan = await preview(client, source, target)
    response = await client.post(
        "/api/identity/works/merge",
        json={
            "source_id": str(source),
            "target_id": str(target),
            "expected_revision": plan["revision"],
        },
    )
    assert response.status_code == 204, response.text
    history = (await client.get("/api/identity/changes", params={"work_id": str(target)})).json()
    return next(
        row
        for row in history["items"]
        if row["kind"] == "work_merge" and row["entity_id"] == str(source)
    )


async def test_merge_and_undo_preserve_origins_and_aggregate_lists_inventory_and_requests(
    client, admin, catalog, database
):
    source = str(catalog["work"])
    target = await book(client)
    listing = (await client.post("/api/lists", json={"name": "Both records"})).json()["id"]
    for work in (source, target):
        assert (
            await client.post(f"/api/lists/{listing}/entries", json={"work_id": work})
        ).status_code == 204
        await request(client, {"work_id": work, "specification": {"mode": "both"}})
    change = await merge(client, source, target)
    assert change["can_undo"]
    detail = (await client.get(f"/api/catalog/works/{source}")).json()
    assert detail["id"] == target and detail["title"] == "Main catalog title"
    assert detail["availability"]["ebook"] and not detail["availability"]["audio"]
    search = (await client.get("/api/catalog/works", params={"q": "Harbor"})).json()
    assert [row["id"] for row in search["items"]] == [target]
    assert (await client.get(f"/api/lists/{listing}")).json()["count"] == 1
    assert (await client.get("/api/lists")).json()[0]["count"] == 1
    metadata = (await client.get(f"/api/metadata/works/{target}")).json()
    assert metadata["versions_total"] == 4
    assert metadata["sources"][0]["provider"] == "hardcover"
    assets = (await client.get("/api/library/assets", params={"work_id": target})).json()
    assert len(assets["items"]) == 1 and assets["items"][0]["work_ids"] == [target]
    requests = (await client.get("/api/requests", params={"work_id": target})).json()
    assert requests["total"] == 2
    assert all(
        row["work_id"] == target and row["targets"][0]["state"] == "satisfied"
        for row in requests["items"]
    )
    async with database() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AcquisitionReservation)
                .where(AcquisitionReservation.state == "planned")
            )
            == 1
        )
        assert await db.scalar(select(func.count()).select_from(ListEntry)) == 2
        assert {v.work_id for v in (await db.scalars(select(Version))).all()} == {catalog["work"]}
        assert (await db.get(LibraryAsset, catalog["asset"])).version_id == catalog["versions"][0]
    assert (await client.post(f"/api/identity/changes/{change['id']}/undo")).status_code == 204
    assert (await client.get(f"/api/lists/{listing}")).json()["count"] == 2
    assert not (await client.get(f"/api/catalog/works/{target}")).json()["availability"]["owned"]
    assert (await client.get(f"/api/catalog/works/{source}")).json()["availability"]["owned"]
    async with database() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AcquisitionReservation)
                .where(AcquisitionReservation.state == "planned")
            )
            == 3
        )


async def test_refresh_merged_source_keeps_version_ids_and_source_namespace(
    client, admin, catalog, database
):
    target = UUID(await book(client))
    change = await merge(client, catalog["work"], target)
    async with database() as db, db.begin():
        source = await db.scalar(select(WorkMetadataSource))
        original_source = source.id
        links = (await db.scalars(select(ProviderObject))).all()
        before = {link.id: link.version_id for link in links}
        snapshot = BookData.model_validate(source.snapshot)
        editions = []
        for link in links:
            version = await db.get(Version, link.version_id)
            edition = EditionData(
                external_id=link.external_id,
                title=version.title,
                medium=version.medium,
                language=version.language,
                narrators=version.narrators,
                abridged=version.abridged,
                publication_year=version.publication_year,
                identifiers=version.identifiers,
            )
            link.snapshot = edition.model_dump(mode="json")
            editions.append(edition)
        snapshot = snapshot.model_copy(update={"editions": editions})
        await attach_source(db, await db.get(Work, target), snapshot)
        assert source.id == original_source and source.work_id == catalog["work"]
        assert {
            link.id: link.version_id for link in (await db.scalars(select(ProviderObject))).all()
        } == before
    assert (await client.post(f"/api/identity/changes/{change['id']}/undo")).status_code == 204
    async with database() as db:
        assert (await db.get(Work, target)).title == "Main catalog title"


async def test_nested_merges_require_dependency_order_to_undo_and_prevent_cycles(client, admin):
    a, b, c = [await book(client, title) for title in ("A", "B", "C")]
    first = await merge(client, a, b)
    second = await merge(client, b, c)
    assert (await client.get(f"/api/catalog/works/{a}")).json()["id"] == c
    assert (await client.post(f"/api/identity/changes/{first['id']}/undo")).status_code == 409
    bad = await client.post(
        "/api/identity/works/merge/preview", json={"source_id": c, "target_id": a}
    )
    assert bad.status_code in (409, 422)
    assert (await client.post(f"/api/identity/changes/{second['id']}/undo")).status_code == 204
    assert (await client.post(f"/api/identity/changes/{first['id']}/undo")).status_code == 204
    assert (await client.get("/api/catalog/works")).json()["total"] == 3


async def test_concurrent_opposite_merges_and_stale_previews(client, admin):
    a, b = await book(client, "A"), await book(client, "B")
    plans = [await preview(client, a, b), await preview(client, b, a)]
    responses = await asyncio.gather(
        *[
            client.post(
                "/api/identity/works/merge",
                json={
                    "source_id": p["source_id"],
                    "target_id": p["target_id"],
                    "expected_revision": p["revision"],
                },
            )
            for p in plans
        ]
    )
    assert sorted(r.status_code for r in responses) == [204, 409]
    assert (await client.get("/api/catalog/works")).json()["total"] == 1


async def test_merging_private_origin_preserves_library_and_catalog_version_grants(
    client, admin, catalog, database
):
    target = await book(client)
    async with database() as db, db.begin():
        (await db.get(Work, catalog["work"])).catalog_public = False
        user = User(
            username="guest",
            display_name="Guest",
            role="member",
            password_hash=hash_password("guest merge password"),
        )
        db.add(user)
        await db.flush()
        user_id = user.id
    await merge(client, catalog["work"], target)
    from app.main import create_app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()),
        base_url="http://testserver",
        headers={"Origin": "http://testserver"},
    ) as other:
        login = await other.post(
            "/api/auth/login", json={"username": "guest", "password": "guest merge password"}
        )
        other.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        assert not (await other.get(f"/api/catalog/works/{target}")).json()["availability"]["owned"]
        metadata = (await other.get(f"/api/metadata/works/{target}")).json()
        assert metadata["versions_total"] == 0 and metadata["sources"] == []
        denied = await other.post(
            "/api/requests/preview",
            json={
                "work_id": target,
                "specification": {"mode": "audio", "audio_version_id": str(catalog["versions"][1])},
            },
        )
        assert denied.status_code == 404
        assert (
            await other.post(
                "/api/identity/works/merge/preview",
                json={"source_id": target, "target_id": str(catalog["work"])},
            )
        ).status_code == 403
        async with database() as db, db.begin():
            db.add(LibraryGrant(user_id=user_id, library_id=catalog["library"]))
        assert (await other.get(f"/api/catalog/works/{target}")).json()["availability"]["owned"]
        assert (await other.get(f"/api/metadata/works/{target}")).json()["versions_total"] == 4


async def test_list_removal_after_merge_removes_group_memberships_and_only_list_reasons(
    client, admin, catalog
):
    target = await book(client)
    list_id = (await client.post("/api/lists", json={"name": "Following"})).json()["id"]
    for work in (str(catalog["work"]), target):
        await client.post(f"/api/lists/{list_id}/entries", json={"work_id": work})
        await request(
            client,
            {"work_id": work, "specification": {"mode": "audio"}, "reason": {"list_id": list_id}},
        )
    await merge(client, catalog["work"], target)
    await request(client, {"work_id": target, "specification": {"mode": "audio"}})
    assert (
        await client.put(f"/api/lists/{list_id}/order", json={"work_ids": [target]})
    ).status_code == 204
    assert (await client.delete(f"/api/lists/{list_id}/entries/{target}")).status_code == 204
    assert (await client.get(f"/api/lists/{list_id}")).json()["count"] == 0
    requests = (await client.get("/api/requests", params={"work_id": target})).json()["items"]
    assert sum(reason["active"] for row in requests for reason in row["reasons"]) == 1


async def test_merge_history_blocks_unsafe_schema_downgrade(client, admin, database):
    from app.db.session import get_engine
    from tests.integration.test_correction_migration import migrate

    a, b = await book(client, "A"), await book(client, "B")
    await merge(client, a, b)
    await get_engine().dispose()
    try:
        refused = await migrate("downgrade", "0006_acquisition")
        assert (
            refused.returncode != 0
            and "Canonical work relationships cannot be preserved" in refused.stderr
        )
        async with database() as db:
            assert (
                await db.scalar(text("SELECT version_num FROM alembic_version"))
                == "0007_work_merges"
            )
    finally:
        restored = await migrate("upgrade", "head")
        assert restored.returncode == 0, restored.stderr
        await get_engine().dispose()


async def test_requests_and_worker_redelivery_serialize_with_a_merge(
    client, admin, catalog, database
):
    from app.domain.acquisition import reconcile_requests
    from app.jobs.queue import get_queue

    target = await book(client)
    plan = await preview(client, catalog["work"], target)
    responses = await asyncio.gather(
        request(client, body(catalog, "audio")),
        request(client, {"work_id": target, "specification": {"mode": "audio"}}),
        client.post(
            "/api/identity/works/merge",
            json={
                "source_id": str(catalog["work"]),
                "target_id": target,
                "expected_revision": plan["revision"],
            },
        ),
    )
    assert responses[-1].status_code == 204
    await asyncio.wait_for(get_queue().run_worker_async(wait=False, concurrency=2), 15)
    await reconcile_requests()
    async with database() as db:
        reservations = (
            await db.scalars(
                select(AcquisitionReservation).where(AcquisitionReservation.state == "planned")
            )
        ).all()
        assert len(reservations) == 1
        targets = (await db.scalars(select(AcquisitionTarget))).all()
        assert all(t.reservation_id == reservations[0].id and t.state == "wanted" for t in targets)


async def test_preview_detects_changed_labels_and_prevents_private_metadata_promotion(
    client, admin, database
):
    source, target = await book(client, "Original"), await book(client, "Target")
    plan = await preview(client, source, target)
    async with database() as db, db.begin():
        (await db.get(Work, UUID(target))).title = "Changed since preview"
    response = await client.post(
        "/api/identity/works/merge",
        json={"source_id": source, "target_id": target, "expected_revision": plan["revision"]},
    )
    assert response.status_code == 409
    async with database() as db, db.begin():
        (await db.get(Work, UUID(target))).catalog_public = False
    response = await client.post(
        "/api/identity/works/merge/preview", json={"source_id": source, "target_id": target}
    )
    assert response.status_code == 422


async def test_alias_request_for_recording_and_omnibus_coverage_count_use_canonical_identity(
    client, admin, catalog, database
):
    target = await book(client)
    async with database() as db, db.begin():
        db.add(AssetContains(asset_id=catalog["asset"], work_id=UUID(target), verified=True))
    await merge(client, catalog["work"], target)
    # Two origin assertions about one canonical work do not invent omnibus contents.
    response = await client.post(
        "/api/requests/preview",
        json={
            "work_id": target,
            "specification": {
                "mode": "ebook",
                "ebook_version_id": str(catalog["versions"][0]),
                "standalone": True,
            },
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["targets"][0]["state"] == "satisfied"
    response = await client.post(
        "/api/requests/preview",
        json={
            "work_id": target,
            "specification": {"mode": "audio", "audio_version_id": str(catalog["versions"][1])},
        },
    )
    assert response.status_code == 200 and response.json()["targets"][0]["state"] == "wanted"


async def test_request_added_after_merge_stays_with_selected_record_after_undo(
    client, admin, catalog
):
    target = await book(client)
    original = await request(client, body(catalog, "audio"))
    change = await merge(client, catalog["work"], target)
    later = await request(client, {"work_id": target, "specification": {"mode": "audio"}})
    assert later["request"]["id"] != original["request"]["id"]
    assert (await client.post(f"/api/identity/changes/{change['id']}/undo")).status_code == 204
    original_view = (await client.get(f"/api/requests/{original['request']['id']}")).json()
    later_view = (await client.get(f"/api/requests/{later['request']['id']}")).json()
    assert original_view["work_id"] == str(catalog["work"])
    assert later_view["work_id"] == target


async def test_merge_preview_omits_other_users_private_curation_counts(
    client, admin, catalog, database
):
    from app.db.models import AcquisitionIntent, AcquisitionReason, BookList
    from app.domain.acquisition import RequestSpec

    target = await book(client)
    async with database() as db, db.begin():
        owner = User(
            username="private-curator",
            display_name="Private",
            role="member",
            password_hash="unused",
        )
        db.add(owner)
        await db.flush()
        listing = BookList(owner_id=owner.id, name="Private list")
        intent = AcquisitionIntent(
            owner_id=owner.id,
            work_id=catalog["work"],
            fingerprint="private-fixture",
            specification=RequestSpec(mode="audio").model_dump(mode="json"),
        )
        db.add_all([listing, intent])
        await db.flush()
        db.add(ListEntry(list_id=listing.id, work_id=catalog["work"]))
        db.add(AcquisitionReason(intent_id=intent.id, kind="manual", reference="manual"))
    plan = await preview(client, catalog["work"], target)
    assert plan["counts"]["list_memberships"] == plan["counts"]["requests"] == 0
    await merge(client, catalog["work"], target)
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(AcquisitionReason)) == 1
        assert await db.scalar(select(func.count()).select_from(ListEntry)) == 1
