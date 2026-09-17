from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.adapters.catalog_providers import Hardcover
from app.adapters.catalog_types import BookData, EditionData
from app.db.models import IdentityChange, LibraryAsset, Version, Work
from tests.contracts.test_audiobookshelf import ABSFixture, book, connect, sync

pytestmark = pytest.mark.integration


async def asset_fixture(client):
    connection = await connect(client)
    fixture = ABSFixture({"one": book("one")})
    await sync(client, connection, fixture, "identity-initial-sync")
    asset = (await client.get("/api/library/assets")).json()["items"][0]
    return connection, fixture, asset


async def history(client, *, asset=None, work=None):
    result = await client.get(
        "/api/identity/changes", params={"entity_id": asset} if asset else {"work_id": work}
    )
    assert result.status_code == 200, result.text
    return result.json()["items"]


async def test_asset_correction_and_unmatch_are_reversible_and_survive_sync(
    client, admin, database
):
    connection, fixture, asset = await asset_fixture(client)
    original_id, original_version = asset["work_ids"][0], asset["version_id"]
    target = (
        await client.post(
            "/api/catalog/works", json={"title": "Chosen book", "authors": ["Writer"]}
        )
    ).json()
    response = await client.post(
        f"/api/library/assets/{asset['id']}/match",
        json={"work_id": target["id"], "expected_revision": asset["match_revision"]},
    )
    assert response.status_code == 204, response.text
    corrected = (await client.get("/api/library/assets")).json()["items"][0]
    assert corrected["work_ids"] == [target["id"]]
    first = (await history(client, asset=asset["id"]))[0]
    assert first["can_undo"]
    # Repeating the same decision neither creates another recording nor another journal row.
    await client.post(f"/api/library/assets/{asset['id']}/match", json={"work_id": target["id"]})
    assert len(await history(client, asset=asset["id"])) == 1
    await sync(client, connection, fixture, "identity-sync-after-correction")
    assert (await history(client, asset=asset["id"]))[0]["can_undo"]
    undo = await client.post(f"/api/identity/changes/{first['id']}/undo")
    assert undo.status_code == 204, undo.text
    restored = (await client.get("/api/library/assets")).json()["items"][0]
    assert restored["work_ids"] == [original_id]
    assert restored["version_id"] == original_version
    assert (await client.get(f"/api/catalog/works/{original_id}")).json()["availability"]["owned"]
    assert not (await client.get(f"/api/catalog/works/{target['id']}")).json()["availability"][
        "owned"
    ]
    response = await client.post(
        f"/api/library/assets/{asset['id']}/match",
        json={"work_id": None, "expected_revision": restored["match_revision"]},
    )
    assert response.status_code == 204
    assert not (await client.get(f"/api/catalog/works/{original_id}")).json()["availability"][
        "owned"
    ]
    last = (await history(client, asset=asset["id"]))[0]
    assert (await client.post(f"/api/identity/changes/{last['id']}/undo")).status_code == 204
    assert (await client.post(f"/api/identity/changes/{last['id']}/undo")).status_code == 204
    assert (await client.get(f"/api/catalog/works/{original_id}")).json()["availability"]["owned"]
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(IdentityChange)) == 2
        assert await db.scalar(select(func.count()).select_from(Version)) == 2


async def test_old_asset_decision_cannot_overwrite_new_decision_or_changed_evidence(client, admin):
    connection, fixture, asset = await asset_fixture(client)
    targets = [
        (await client.post("/api/catalog/works", json={"title": name})).json()["id"]
        for name in ["First", "Second"]
    ]
    endpoint = f"/api/library/assets/{asset['id']}/match"
    assert (
        await client.post(
            endpoint, json={"work_id": targets[0], "expected_revision": asset["match_revision"]}
        )
    ).status_code == 204
    first = (await history(client, asset=asset["id"]))[0]
    assert (
        await client.post(
            endpoint, json={"work_id": targets[1], "expected_revision": asset["match_revision"]}
        )
    ).status_code == 409
    assert (await client.post(endpoint, json={"work_id": targets[1]})).status_code == 204
    assert (await client.post(f"/api/identity/changes/{first['id']}/undo")).status_code == 409
    newest = (await history(client, asset=asset["id"]))[0]
    fixture.items["one"] = book("one", narrator="Changed narrator")
    await sync(client, connection, fixture, "changed-evidence-after-correction")
    assert not (await history(client, asset=asset["id"]))[0]["can_undo"]
    assert (await client.post(f"/api/identity/changes/{newest['id']}/undo")).status_code == 409


@pytest.fixture
async def catalog_book(client, admin, monkeypatch):
    state = {"narrator": "Original narrator"}

    async def fetch(self, external_id, edition_offset=0):
        return BookData(
            provider="hardcover",
            external_id=external_id,
            title="Catalog book",
            authors=["Author"],
            description="Catalog description",
            editions=[
                EditionData(
                    external_id="71",
                    title="Catalog book",
                    medium="audio",
                    narrators=[state["narrator"]],
                    language="en",
                )
            ],
        )

    monkeypatch.setattr(Hardcover, "fetch", fetch)
    await client.put("/api/metadata/account", json={"token": "test-catalog-token"})
    response = await client.post("/api/metadata/books/hardcover/42/import")
    assert response.status_code == 200, response.text
    return response.json(), state


async def test_source_unmatch_hides_wrong_editions_preserves_manual_fields_and_can_undo(
    client, admin, database, catalog_book
):
    work, state = catalog_book
    endpoint = f"/api/metadata/works/{work['id']}"
    await client.patch(endpoint, json={"values": {"description": "Protected description"}})
    source = (await client.get(endpoint)).json()["sources"][0]
    response = await client.post(
        f"/api/identity/sources/{source['id']}/unmatch",
        json={"expected_revision": source["revision"]},
    )
    assert response.status_code == 204, response.text
    metadata = (await client.get(endpoint)).json()
    assert not metadata["sources"]
    assert not metadata["versions"]
    assert metadata["fields"]["title"]["provider"] == "unmatched"
    assert (await client.get(f"/api/catalog/works/{work['id']}")).json()[
        "description"
    ] == "Protected description"
    assert (await client.post("/api/metadata/books/hardcover/42/import")).status_code == 409
    entry = (await history(client, work=work["id"]))[0]
    assert entry["can_undo"]
    assert (await client.post(f"/api/identity/changes/{entry['id']}/undo")).status_code == 204
    restored = (await client.get(endpoint)).json()
    assert len(restored["versions"]) == 1
    assert restored["fields"]["title"]["provider"] == "hardcover"
    assert restored["fields"]["description"]["locked"]
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(Work)) == 1


async def test_metadata_edit_after_unmatch_blocks_stale_undo(client, admin, catalog_book):
    work, _ = catalog_book
    endpoint = f"/api/metadata/works/{work['id']}"
    source = (await client.get(endpoint)).json()["sources"][0]
    await client.post(
        f"/api/identity/sources/{source['id']}/unmatch",
        json={"expected_revision": source["revision"]},
    )
    entry = (await history(client, work=work["id"]))[0]
    await client.patch(endpoint, json={"values": {"title": "A newer user decision"}})
    assert (await client.post(f"/api/identity/changes/{entry['id']}/undo")).status_code == 409
    assert (await client.get(f"/api/catalog/works/{work['id']}")).json()[
        "title"
    ] == "A newer user decision"


async def test_changed_catalog_version_can_be_kept_or_separated_without_rewriting_assets(
    client, admin, database, catalog_book
):
    work, state = catalog_book
    endpoint = f"/api/metadata/works/{work['id']}"
    old_version = (await client.get(endpoint)).json()["versions"][0]["id"]
    _, _, asset = await asset_fixture(client)
    async with database() as db:
        from sqlalchemy import delete

        from app.db.models import AssetContains

        record = await db.get(LibraryAsset, UUID(asset["id"]))
        record.version_id = UUID(old_version)
        await db.execute(delete(AssetContains).where(AssetContains.asset_id == record.id))
        db.add(AssetContains(asset_id=record.id, work_id=UUID(work["id"]), verified=True))
        await db.commit()
    state["narrator"] = "New narrator"
    response = await client.post(
        endpoint + "/source", json={"provider": "hardcover", "external_id": "42"}
    )
    assert response.status_code == 200
    review = (await client.get(f"/api/identity/works/{work['id']}/version-reviews")).json()[0]
    assert review["proposed"]["narrators"] == ["New narrator"]
    resolved = await client.post(
        f"/api/identity/versions/{review['id']}/review",
        json={"decision": "keep", "expected_revision": review["revision"]},
    )
    assert resolved.status_code == 204, resolved.text
    await client.post(endpoint + "/source", json={"provider": "hardcover", "external_id": "42"})
    assert not (await client.get(f"/api/identity/works/{work['id']}/version-reviews")).json()
    entry = (await history(client, work=work["id"]))[0]
    assert (await client.post(f"/api/identity/changes/{entry['id']}/undo")).status_code == 204
    review = (await client.get(f"/api/identity/works/{work['id']}/version-reviews")).json()[0]
    assert (
        await client.post(
            f"/api/identity/versions/{review['id']}/review",
            json={"decision": "separate", "expected_revision": review["revision"]},
        )
    ).status_code == 204
    versions = (await client.get(endpoint)).json()["versions"]
    assert len(versions) == 2
    assert next(v for v in versions if v["id"] == old_version)["owned"]
    new_version = next(v for v in versions if v["id"] != old_version)
    assert not new_version["owned"]
    assert new_version["narrators"] == ["New narrator"]
    entry = (await history(client, work=work["id"]))[0]
    assert (await client.post(f"/api/identity/changes/{entry['id']}/undo")).status_code == 204
    assert len((await client.get(endpoint)).json()["versions"]) == 1
    async with database() as db:
        assert (await db.get(LibraryAsset, UUID(asset["id"]))).version_id == UUID(old_version)


async def test_correction_history_and_commands_are_admin_only(
    client, admin, database, catalog_book
):
    from app.db.models import User
    from app.security import hash_password

    work, _ = catalog_book
    async with database() as db:
        db.add(
            User(
                username="member",
                display_name="Member",
                password_hash=hash_password("member-test-password"),
                role="member",
            )
        )
        await db.commit()
    await client.post("/api/auth/logout")
    login = await client.post(
        "/api/auth/login", json={"username": "member", "password": "member-test-password"}
    )
    client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
    assert (
        await client.get("/api/identity/changes", params={"work_id": work["id"]})
    ).status_code == 403
    assert (
        await client.get(f"/api/identity/works/{work['id']}/version-reviews")
    ).status_code == 403
    metadata = (await client.get(f"/api/metadata/works/{work['id']}")).json()
    assert metadata["sources"][0]["revision"] is None
    assert (
        await client.post(
            f"/api/identity/sources/{metadata['sources'][0]['id']}/unmatch",
            json={"expected_revision": "0" * 64},
        )
    ).status_code == 403


async def test_concurrent_undo_is_idempotent_and_reapplying_reuses_the_recording(
    client, admin, database
):
    import asyncio

    _, _, asset = await asset_fixture(client)
    target = (await client.post("/api/catalog/works", json={"title": "Corrected title"})).json()
    endpoint = f"/api/library/assets/{asset['id']}/match"
    await client.post(endpoint, json={"work_id": target["id"]})
    corrected = (await client.get("/api/library/assets")).json()["items"][0]
    entry = (await history(client, asset=asset["id"]))[0]
    responses = await asyncio.gather(
        *[client.post(f"/api/identity/changes/{entry['id']}/undo") for _ in range(3)]
    )
    assert [response.status_code for response in responses] == [204, 204, 204]
    await client.post(endpoint, json={"work_id": target["id"]})
    repeated = (await client.get("/api/library/assets")).json()["items"][0]
    assert repeated["version_id"] == corrected["version_id"]
    async with database() as db:
        from app.db.models import AuditEvent

        assert await db.scalar(select(func.count()).select_from(Version)) == 2
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "identity.correction.undone")
            )
            == 1
        )


async def test_lookup_cannot_force_a_match_after_the_work_changes_while_waiting(
    client, admin, database, monkeypatch
):
    import asyncio

    from sqlalchemy import text

    from app.domain.identity import work_key

    async def fetch(self, external_id, edition_offset=0):
        return BookData(
            provider="hardcover",
            external_id=external_id,
            title="Original catalog title",
            authors=["Author"],
        )

    monkeypatch.setattr(Hardcover, "fetch", fetch)
    await client.put("/api/metadata/account", json={"token": "test-catalog-token"})
    work = (
        await client.post(
            "/api/catalog/works", json={"title": "Original catalog title", "authors": ["Author"]}
        )
    ).json()
    async with database() as editor:
        edited = await editor.get(Work, UUID(work["id"]), with_for_update=True)
        pending = asyncio.create_task(client.post("/api/metadata/books/hardcover/42/import"))
        try:
            async with asyncio.timeout(3):
                while True:
                    async with database() as observer:
                        waiting = await observer.scalar(
                            text(
                                "SELECT count(*) FROM pg_stat_activity "
                                "WHERE datname = current_database() AND wait_event_type = 'Lock'"
                            )
                        )
                    if waiting:
                        break
                    await asyncio.sleep(0.02)
            edited.title = "A different book"
            edited.match_key = work_key(edited.title, edited.authors)
            await editor.commit()
            response = await pending
            assert response.status_code == 409, response.text
        finally:
            await editor.rollback()
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
    result = (await client.get(f"/api/catalog/works/{work['id']}")).json()
    assert result["title"] == "A different book"
    assert not (await client.get(f"/api/metadata/works/{work['id']}")).json()["sources"]
