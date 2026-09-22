from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domain.automatic_routes import AutomaticRoutes, selection_clients
from app.domain.automatic_selection import AutomaticSelectionInput
from app.domain.downloaders import client_protocol

REVISION = "ab" * 32


def test_client_protocol_follows_the_download_kind():
    assert client_protocol("qbittorrent") == "torrent"
    assert client_protocol("sabnzbd") == "nzb"
    assert client_protocol("nzbget") == "nzb"
    assert client_protocol("other") is None


def test_unset_fallback_stays_out_of_route_snapshots():
    assert AutomaticRoutes().model_dump() == {
        "downloader_id": None,
        "downloader_generation": None,
        "routes": {},
    }


def test_selection_command_omits_an_incomplete_fallback_and_keeps_a_complete_one():
    primary = uuid4()
    destination = uuid4()
    with pytest.raises(ValidationError):
        AutomaticSelectionInput(
            intent_id=uuid4(),
            slot="audio",
            search_id=uuid4(),
            downloader_id=primary,
            downloader_generation=1,
            destination_id=destination,
            destination_revision=REVISION,
            alternate_downloader_id=uuid4(),
        )
    alternate = uuid4()
    other = uuid4()
    body = AutomaticSelectionInput(
        intent_id=uuid4(),
        slot="audio",
        search_id=uuid4(),
        downloader_id=primary,
        downloader_generation=1,
        destination_id=destination,
        destination_revision=REVISION,
        alternate_downloader_id=alternate,
        alternate_downloader_generation=2,
        alternate_destination_id=other,
        alternate_destination_revision=REVISION,
    )
    dumped = body.model_dump(mode="json", exclude_none=True)
    assert dumped["alternate_downloader_id"] == str(alternate)
    assert "result_id" not in dumped
    routes = AutomaticRoutes(
        downloader_id=primary,
        downloader_generation=1,
        routes={"audio": {"destination_id": destination, "destination_revision": REVISION}},
        alternate_downloader_id=alternate,
        alternate_downloader_generation=2,
        alternate_routes={"audio": {"destination_id": other, "destination_revision": REVISION}},
    )
    assert selection_clients(routes, "audio")["alternate_destination_id"] == other
