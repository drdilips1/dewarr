"""Narrator policies survive inheritance, ownership checks and frozen selection."""

# ruff: noqa: F401, F811
from uuid import UUID

import pytest
from sqlalchemy import select

from app.db.models import (
    AcquisitionReservation,
    AcquisitionSelection,
    AcquisitionTarget,
    AssetContains,
    LibraryAsset,
    Version,
)
from tests.integration.test_acquisition import body, catalog, request
from tests.integration.test_acquisition_defaults import save as defaults
from tests.integration.test_acquisition_selections import prepare, selection_route
from tests.integration.test_request_scope import accept, plan

pytestmark = pytest.mark.integration


async def test_required_narrators_inherit_clear_freeze_and_preserve_overall_ownership(
    client, admin, catalog, database
):
    await defaults(
        client,
        {
            "desired_media": "both",
            "required_narrators": ["Reader B"],
            "preferred_narrators": ["Reader A"],
        },
    )
    body, previewed = await plan(client, catalog["work"])
    assert previewed["specification"]["required_narrators"] == ["Reader B"]
    assert previewed["release_policy"]["scope_origins"]["required_narrators"] == "Personal default"
    assert {t["slot"]: t["state"] for t in previewed["targets"]} == {
        "ebook": "satisfied",
        "audio": "wanted",
    }
    saved = await accept(client, body, previewed)
    assert saved.status_code == 202, saved.text
    async with database() as db, db.begin():
        asset = LibraryAsset(
            library_id=catalog["library"],
            external_id="audio",
            version_id=catalog["versions"][1],
            medium="audio",
            state="present",
            full_content=True,
        )
        db.add(asset)
        await db.flush()
        db.add(AssetContains(asset_id=asset.id, work_id=catalog["work"], verified=True))
    _, wrong = await plan(client, catalog["work"])
    assert wrong["targets"][1]["state"] == "wanted"
    _, cleared = await plan(client, catalog["work"], {"required_narrators": []})
    assert all(t["state"] == "satisfied" for t in cleared["targets"])
    assert (await client.get(f"/api/catalog/works/{catalog['work']}")).json()["availability"][
        "owned"
    ]
    await defaults(client, {"desired_media": "audio", "required_narrators": ["Reader A"]})
    current = (await client.get("/api/requests/" + saved.json()["request"]["id"])).json()
    assert current["specification"]["required_narrators"] == ["Reader B"]
    assert current["release_policy"]["preferences"]["preferred_narrators"] == ["Reader A"]


async def test_exact_recording_conflicting_with_required_narrator_is_rejected(
    client, admin, catalog
):
    response = await client.post(
        "/api/requests/preview",
        json=body(
            catalog,
            "audio",
            audio_version_id=str(catalog["versions"][1]),
            required_narrators=["Reader B"],
        ),
    )
    assert response.status_code == 422 and "required narrator" in response.text


@pytest.mark.parametrize("exact", [False, True])
async def test_stricter_later_narrator_shares_only_a_proven_frozen_recording(
    client, admin, catalog, database, selection_route, exact
):
    if exact:
        saved = await request(
            client,
            body(
                catalog,
                "audio",
                audio_library_id=str(catalog["library"]),
                audio_version_id=str(catalog["versions"][1]),
            ),
        )
        selection_route["intent_id"] = saved["request"]["id"]
    selected = await prepare(client, selection_route)
    assert selected.status_code == 201, selected.text
    later = await request(
        client,
        body(
            catalog,
            "audio",
            audio_library_id=str(catalog["library"]),
            required_narrators=["Reader A"],
        ),
    )
    async with database() as db:
        selection = await db.get(AcquisitionSelection, UUID(selected.json()["id"]))
        target = await db.scalar(
            select(AcquisitionTarget).where(
                AcquisitionTarget.intent_id == UUID(later["request"]["id"])
            )
        )
        assert (selection.reservation_id == target.reservation_id) is exact
        assert "required_narrators" not in selection.frozen["requirements"]
        reservation = await db.get(AcquisitionReservation, selection.reservation_id)
        assert "required_narrators" not in reservation.requirements


async def test_missing_required_source_narrator_blocks_manual_selection(
    client, admin, catalog, selection_route
):
    saved = await request(
        client,
        body(
            catalog,
            "audio",
            audio_library_id=str(catalog["library"]),
            required_narrators=["Reader B"],
        ),
    )
    selection_route["intent_id"] = saved["request"]["id"]
    response = await prepare(client, selection_route)
    assert response.status_code == 422 and "required narrator" in response.text
