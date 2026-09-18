from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.adapters.audiobookshelf import ABSFile, ABSItem
from app.importing.execution import matches
from app.importing.publication import PublicationError, PublicationSpec, PublishFile


@pytest.mark.parametrize("indices", [(2, 1), (None, None), (1, 1), (1, None)])
def test_incorrect_or_unverified_playback_order_cannot_confirm(indices):
    files = [
        ABSFile(path=f"/books/Harbor/{number}.mp3", size=100, format="mp3", playback_index=index)
        for number, index in zip((1, 2), indices, strict=True)
    ]
    spec = PublicationSpec(
        entry_id=uuid4(),
        plan_revision="a" * 64,
        source_root="/downloads",
        source_relative="pack",
        source_directory={},
        destination_root="/library",
        staging_root="/staging",
        folder="Harbor",
        files=[
            PublishFile(
                source=f"{number}.mp3",
                name=f"{number}.mp3",
                sha256="b" * 64,
                identity={"size": 100},
            )
            for number in (1, 2)
        ],
    )
    entry = SimpleNamespace(
        specification=spec.model_dump(mode="json"),
        configuration={"destination": {"backend_path": "/books"}},
        expected_metadata={
            "medium": "audio",
            "title": "Harbor",
            "authors": [],
            "narrators": [],
            "recording_year": None,
            "audio_order": [file.path for file in files],
        },
    )
    item = ABSItem(
        id="item",
        library_id="library",
        title="Harbor",
        authors=[],
        narrators=[],
        audio=files,
        library_files=files,
        full_audio=True,
        path="/books/Harbor",
    )
    with pytest.raises(PublicationError, match="playback order"):
        matches(entry, item)
    for index, file in enumerate(item.audio, start=1):
        file.playback_index = index
    # API list order itself is not authoritative; explicit playback indices are.
    item.audio.reverse()
    assert matches(entry, item)
