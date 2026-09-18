# ruff: noqa: F811
import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text

from app.db.models import (
    AcquisitionProfile,
    AcquisitionSelection,
    Operation,
    SourceConnection,
    SourceResult,
    User,
    Work,
)
from app.domain import book_sources
from app.domain.book_sources import SearchInput
from app.jobs.retry import SourceSearchRetry
from tests.integration.test_acquisition import catalog  # noqa: F401
from tests.integration.test_acquisition_selections import prepare, selection_route  # noqa: F401
from tests.integration.test_mam_sources import configure as configure_mam  # noqa: F401
from tests.integration.test_mam_sources import source_http  # noqa: F401
from tests.integration.test_prowlarr_sources import configure as configure_prowlarr  # noqa: F401
from tests.integration.test_prowlarr_sources import prowlarr_http  # noqa: F401
from tests.mam_fixture import release_row, search_response
from tests.prowlarr_fixture import release

pytestmark = pytest.mark.integration


async def begin(client, catalog, key="book-search-fixture", **body):
    response = await client.post(
        f"/api/catalog/works/{catalog['work']}/source-searches",
        json=body,
        headers={"Idempotency-Key": key},
    )
    assert response.status_code == 202, response.text
    return response.json()


async def read(client, identifier):
    return await client.get(f"/api/source-searches/{identifier}")


async def test_incremental_ranked_private_results_preserve_mam_fields_and_ownership(
    client, admin, database, catalog, source_http, prowlarr_http
):
    await configure_mam(client)
    await configure_prowlarr(client)
    source_http["body"] = search_response(
        data=[release_row(title="Harbor", author_info='{"1":"Writer"}')]
    )
    prowlarr_http["releases"] = [release(title="Harbor")]
    saved = await begin(client, catalog)
    identifier = UUID(saved["id"])
    await book_sources.run(identifier, "mam")
    partial = (await read(client, identifier)).json()
    assert partial["status"] == "running" and len(partial["items"]) == 1
    assert partial["items"][0]["release"]["narrators"] == ["Jordan Lee"]
    assert partial["items"][0]["release"]["series"][0]["name"] == "Harbor Stories"
    await book_sources.run(identifier, "prowlarr")
    await book_sources.run(identifier, "mam")
    complete = (await read(client, identifier)).json()
    assert complete["status"] == "completed" and len(complete["items"]) == 2
    assert complete["items"][0]["release"]["source"] == "mam"
    assert complete["items"][0]["assessment"]["identity"] == "corroborated"
    assert {i["release"]["source"] for i in complete["items"]} == {"mam", "prowlarr"}
    assert "secret_proxy_link" not in str(complete)
    assert (await client.get(f"/api/catalog/works/{catalog['work']}")).json()["availability"][
        "ebook"
    ]
    again = await begin(client, catalog)
    assert again["id"] == saved["id"]
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(SourceResult)) == 2
        stored = await db.get(Operation, identifier)
        assert len(stored.payload["workers"]) == 2
        assert (
            await db.scalar(
                text(
                    "SELECT count(*) FROM book_queue.procrastinate_jobs "
                    "WHERE task_name='sources.search'"
                )
            )
            == 2
        )
    source_row = next(i for i in complete["items"] if i["release"]["source"] == "prowlarr")
    artifact = await client.post(
        f"/api/source-searches/{identifier}/results/{source_row['id']}/artifact"
    )
    assert artifact.status_code == 200, artifact.text
    assert artifact.json()["source_key"] == "prowlarr"


async def test_source_failure_retains_completed_sibling(
    client, admin, catalog, source_http, prowlarr_http
):
    await configure_mam(client)
    await configure_prowlarr(client)
    saved = await begin(client, catalog)
    await book_sources.run(UUID(saved["id"]), "mam")
    prowlarr_http["status"] = 503
    await book_sources.run(UUID(saved["id"]), "prowlarr")
    complete = (await read(client, saved["id"])).json()
    assert complete["status"] == "completed" and len(complete["items"]) == 1
    assert any(s["state"] == "failed" and s["key"] == "prowlarr" for s in complete["sources"])


async def test_stale_generation_and_identity_never_publish_new_results(
    client, admin, database, catalog, source_http
):
    await configure_mam(client)
    saved = await begin(client, catalog)
    await configure_mam(client, expected_generation=1)
    await book_sources.run(UUID(saved["id"]), "mam")
    stale = (await read(client, saved["id"])).json()
    assert stale["sources"][0]["state"] == "failed" and not stale["items"]
    assert not source_http["calls"]
    newer = await begin(client, catalog, key="new-search-fixture")
    async with database() as db, db.begin():
        (await db.get(Work, catalog["work"])).title = "Changed title"
    await book_sources.run(UUID(newer["id"]), "mam")
    stale = (await read(client, newer["id"])).json()
    assert stale["stale_identity"] and not stale["items"]


async def test_rate_limit_retry_preserves_progress_and_is_bounded(
    client, admin, database, catalog, source_http
):
    await configure_mam(client)
    saved = await begin(client, catalog)
    identifier = UUID(saved["id"])
    source_http.update(status=429, headers={"Retry-After": "30"})
    with pytest.raises(SourceSearchRetry):
        await book_sources.run(identifier, "mam")
    state = (await read(client, identifier)).json()
    assert state["sources"][0]["state"] == "queued"
    async with database() as db, db.begin():
        connection = await db.get(SourceConnection, "mam")
        connection.blocked_until = None
        connection.next_request_at = None
    source_http.update(status=200, headers={})
    await book_sources.run(identifier, "mam")
    assert len((await read(client, identifier)).json()["items"]) == 1
    await book_sources.run(identifier, "mam")
    assert len(source_http["calls"]) == 2


async def test_active_and_expired_worker_leases_and_exhausted_queue_projection(
    client, admin, database, catalog, prowlarr_http
):
    await configure_prowlarr(client)
    saved = await begin(client, catalog)
    identifier = UUID(saved["id"])
    async with database() as db, db.begin():
        op = await db.get(Operation, identifier)
        payload = deepcopy(op.payload)
        payload["workers"]["prowlarr"].update(
            token=str(uuid4()), until=(datetime.now(UTC) + timedelta(seconds=30)).isoformat()
        )
        op.payload = payload
    with pytest.raises(SourceSearchRetry):
        await book_sources.run(identifier, "prowlarr")
    assert not prowlarr_http["calls"]
    async with database() as db, db.begin():
        op = await db.get(Operation, identifier)
        payload = deepcopy(op.payload)
        payload["workers"]["prowlarr"]["until"] = (
            datetime.now(UTC) - timedelta(seconds=1)
        ).isoformat()
        op.payload = payload
    await book_sources.run(identifier, "prowlarr")
    assert (await read(client, identifier)).json()["status"] == "completed"
    newer = await begin(client, catalog, key="failed-search-fixture")
    async with database() as db, db.begin():
        op = await db.get(Operation, UUID(newer["id"]))
        await db.execute(
            text("UPDATE book_queue.procrastinate_jobs SET status='aborted' WHERE id=:id"),
            {"id": op.job_id},
        )
    failed = (await read(client, newer["id"])).json()
    assert failed["status"] == "completed" and failed["sources"][0]["state"] == "failed"


async def test_search_owner_and_revocation_checks(client, admin, database, catalog, prowlarr_http):
    await configure_prowlarr(client)
    saved = await begin(client, catalog)
    prowlarr_http["gate"] = asyncio.Event()
    task = asyncio.create_task(book_sources.run(UUID(saved["id"]), "prowlarr"))
    await asyncio.wait_for(prowlarr_http["entered"].wait(), 5)
    async with database() as db, db.begin():
        (await db.get(User, UUID(admin["id"]))).active = False
    prowlarr_http["gate"].set()
    await task
    assert (await read(client, saved["id"])).status_code == 401
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(SourceResult)) == 0
        operation = await db.get(Operation, UUID(saved["id"]))
        assert operation.status == "completed"


async def test_atomic_search_enqueue_rolls_back_and_profile_access_is_private(
    client, admin, database, catalog
):
    await configure_mam(client)
    async with database() as db:
        actor = await db.get(User, UUID(admin["id"]))
        await book_sources.start(db, actor, catalog["work"], SearchInput(), "rollback-search")
        await db.rollback()
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(Operation)) == 0
        assert (
            await db.scalar(
                text(
                    "SELECT count(*) FROM book_queue.procrastinate_jobs "
                    "WHERE task_name='sources.search'"
                )
            )
            == 0
        )
    profile = (
        await client.post("/api/acquisition/profiles", json={"name": "Private preferences"})
    ).json()
    async with database() as db, db.begin():
        other = User(
            username="other", display_name="Other", password_hash="not-a-login", role="member"
        )
        db.add(other)
        await db.flush()
        (await db.get(AcquisitionProfile, UUID(profile["id"]))).owner_id = other.id
    assert len((await client.get("/api/acquisition/profiles")).json()) == 1
    response = await client.post(
        f"/api/catalog/works/{catalog['work']}/source-searches",
        json={"profile_id": profile["id"]},
        headers={"Idempotency-Key": "private-profile-search"},
    )
    assert response.status_code == 404


async def test_profiles_enforce_selection_and_keep_frozen_preferences(
    client, admin, database, selection_route
):
    blocked = (
        await client.post(
            "/api/acquisition/profiles",
            json={"name": "Small transfers", "preferences": {"maximum_bytes": 1}},
        )
    ).json()
    selected = {**selection_route, "profile_id": blocked["id"], "profile_generation": 1}
    assert (await prepare(client, selected)).status_code == 422
    updated = await client.put(
        f"/api/acquisition/profiles/{blocked['id']}",
        json={"name": "My downloads", "preferences": {}, "expected_generation": 1},
    )
    assert updated.status_code == 200
    assert (await prepare(client, selected)).status_code == 409
    selected["profile_generation"] = 2
    accepted = await prepare(client, selected)
    assert accepted.status_code == 201, accepted.text
    async with database() as db:
        frozen = (await db.get(AcquisitionSelection, UUID(accepted.json()["id"]))).frozen["profile"]
    await client.put(
        f"/api/acquisition/profiles/{blocked['id']}",
        json={
            "name": "Changed later",
            "preferences": {"maximum_bytes": 1},
            "expected_generation": 2,
        },
    )
    async with database() as db:
        assert (await db.get(AcquisitionSelection, UUID(accepted.json()["id"]))).frozen[
            "profile"
        ] == frozen


async def test_identity_changed_during_indexer_discovery_reaches_terminal_state(
    client, admin, database, catalog, prowlarr_http
):
    await configure_prowlarr(client)
    saved = await begin(client, catalog)
    prowlarr_http["gate"] = asyncio.Event()
    task = asyncio.create_task(book_sources.run(UUID(saved["id"]), "prowlarr"))
    await asyncio.wait_for(prowlarr_http["entered"].wait(), 5)
    async with database() as db, db.begin():
        (await db.get(Work, catalog["work"])).title = "New identity"
    prowlarr_http["gate"].set()
    await task
    value = (await read(client, saved["id"])).json()
    assert value["status"] == "completed" and value["stale_identity"]
    assert value["sources"][0]["state"] == "failed"


async def test_result_expiry_and_other_owner_cannot_inspect(
    client, admin, database, catalog, prowlarr_http
):
    await configure_prowlarr(client)
    saved = await begin(client, catalog)
    await book_sources.run(UUID(saved["id"]), "prowlarr")
    value = (await read(client, saved["id"])).json()
    identifier = value["items"][0]["id"]
    async with database() as db, db.begin():
        (await db.get(SourceResult, UUID(identifier))).expires_at = datetime.now(UTC) - timedelta(
            seconds=1
        )
    assert (
        await client.post(f"/api/source-searches/{saved['id']}/results/{identifier}/artifact")
    ).status_code == 409
    async with database() as db, db.begin():
        other = User(
            username="other-searcher", display_name="Other", password_hash="no-login", role="member"
        )
        db.add(other)
        await db.flush()
        (await db.get(Operation, UUID(saved["id"]))).owner_id = other.id
    assert (await read(client, saved["id"])).status_code == 404


async def test_source_search_migration_guards_saved_profile_history(client, admin, database):
    from tests.integration.test_correction_migration import migrate

    async with database() as db:
        before = await db.scalar(text("SELECT version_num FROM alembic_version"))
    await client.post("/api/acquisition/profiles", json={"name": "Retain me"})
    downgraded = await migrate("downgrade", "0023_source_results")
    assert downgraded.returncode != 0 and "pre-upgrade backup" in downgraded.stderr
    async with database() as db:
        assert await db.scalar(text("SELECT version_num FROM alembic_version")) == before
