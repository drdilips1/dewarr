# ruff: noqa: F401, F811
"""An atomic list addition uses the ordinary automatic acquisition and import path."""

import pytest
from sqlalchemy import func, select

from app.db.models import DownloadAttempt
from tests.integration.test_automatic_acquisition import (
    destination_route,
    ready_route,
    review_account,
)
from tests.integration.test_automatic_acquisition import (
    test_search_to_automatic_download_and_confirmed_member_library as acquire,
)
from tests.integration.test_list_curation import edit

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("medium", ["ebook", "audio"])
async def test_curation_addition_reaches_library_once_and_removal_preserves_media(
    client, admin, database, ready_route, review_account, monkeypatch, medium
):
    class Origin:
        shelf = None
        work_id = None
        receipt = None

        async def create(self, work_id):
            self.work_id = work_id
            self.shelf = (
                await client.post("/api/lists", json={"name": "Curated acquisitions"})
            ).json()["id"]
            return self.shelf

        async def add(self, shelf, work_id):
            response = await edit(client, shelf, "add", [work_id], key="curated-new-member")
            assert response.status_code == 200, response.text
            self.receipt = response.json()
            replay = await edit(client, shelf, "add", [work_id], key="curated-new-member")
            assert replay.json() == self.receipt

    origin = Origin()
    await acquire(
        client,
        admin,
        database,
        ready_route,
        review_account,
        monkeypatch,
        medium=medium,
        delayed_backend=True,
        request_limits=True,
        via_list=True,
        list_origin=origin,
    )
    removed = await edit(client, origin.shelf, "remove", [origin.work_id])
    assert removed.status_code == 200 and removed.json()["changed"] == 1
    # Replaying the original addition cannot resurrect a later removed membership.
    replay = await edit(client, origin.shelf, "add", [origin.work_id], key="curated-new-member")
    assert replay.json() == origin.receipt
    assert (await client.get(f"/api/lists/{origin.shelf}")).json()["count"] == 0
    available = (await client.get(f"/api/catalog/works/{origin.work_id}")).json()["availability"]
    assert available["owned"] and available[medium]
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(DownloadAttempt)) == 1
