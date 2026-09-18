from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.adapters.mam import release
from app.adapters.torrent_descriptor import inspect_torrent
from app.domain.release_profiles import (
    PreferenceOverrides,
    ProfileSnapshot,
    ReleasePreferences,
    assess_release,
    enforce_inspected_profile,
    enforce_profile,
    overlay_profile,
    ranking_key,
    resolve_preferences,
)
from tests.mam_fixture import release_row
from tests.torrent_fixture import torrent_bytes

WORK = {"title": "Harbor", "authors": ["Writer"]}


def test_series_scope_inheritance_and_legacy_boolean_compatibility():
    defaults = ReleasePreferences()
    assert "series_scope" not in defaults.model_dump(mode="json")
    assert defaults.effective_series_scope == "prefer_packs"
    preferences, origins = resolve_preferences(
        [
            ("Installation default", {"series_scope": "complete_series"}),
            ("Personal default", {"prefer_series_packs": False}),
        ]
    )
    assert preferences.effective_series_scope == "just_book"
    assert not preferences.allows_series_packs and "series_scope" not in origins
    result = overlay_profile(
        ProfileSnapshot(preferences=preferences, origins=origins),
        list_overrides={"series_scope": "complete_series"},
    )
    assert result.preferences.effective_series_scope == "complete_series"
    assert result.origins["series_scope"] == "List override"
    result = overlay_profile(result, request_overrides={"series_scope": "just_book"})
    assert not result.preferences.allows_series_packs
    assert result.origins["series_scope"] == "Request override"
    cleared = overlay_profile(result, request_overrides={"series_scope": None})
    assert cleared.preferences.effective_series_scope == "just_book"
    assert cleared.request_overrides.model_dump(mode="json") == {"series_scope": None}


def test_route_layers_preserve_explicit_clearing_and_legacy_unset_snapshots():
    fields = {"downloader_id", "ebook_destination_id", "audio_destination_id"}
    assert not fields & ReleasePreferences().model_dump(mode="json").keys()
    installation, personal, saved, listed, requested = [str(uuid4()) for _ in range(5)]
    preferences, origins = resolve_preferences(
        [
            (
                "Installation default",
                {"ebook_destination_id": installation, "audio_destination_id": installation},
            ),
            ("Personal default", {"ebook_destination_id": personal}),
            ("Profile", {"ebook_destination_id": saved}),
        ]
    )
    base = ProfileSnapshot(preferences=preferences, origins=origins)
    result = overlay_profile(
        base,
        list_overrides={"ebook_destination_id": listed},
        request_overrides={"ebook_destination_id": requested},
    )
    assert str(result.preferences.ebook_destination_id) == requested
    assert result.origins["ebook_destination_id"] == "Request override"
    assert str(result.preferences.audio_destination_id) == installation
    cleared = overlay_profile(base, request_overrides={"ebook_destination_id": None})
    assert cleared.preferences.ebook_destination_id is None
    assert cleared.request_overrides.model_dump(mode="json") == {"ebook_destination_id": None}
    assert PreferenceOverrides.model_validate(
        cleared.request_overrides.model_dump()
    ).model_fields_set == {"ebook_destination_id"}


def candidate(**changes):
    return release(
        release_row(title="Harbor", author_info='{"1":"Writer"}', **changes), datetime.now(UTC)
    )


def ordered(candidates, preferences):
    return sorted(
        candidates, key=lambda r: ranking_key(r, assess_release(r, WORK, preferences), preferences)
    )


def test_identity_and_blocked_formats_precede_seeds():
    right = candidate(id=1, seeders=0, filetype="M4B")
    wrong = candidate(id=2, seeders=100000).model_copy(update={"title": "Different book"})
    blocked = candidate(id=3, seeders=90000, filetype="MP3")
    preferences = ReleasePreferences(
        criteria=["seeders", "format", "source"], blocked_formats=["mp3"]
    )
    assert ordered([wrong, blocked, right], preferences)[0].source_id == "1"
    assert assess_release(blocked, WORK, preferences).blocked
    assert assess_release(wrong, WORK, preferences).identity == "unmatched"


def test_format_priority_source_priority_and_known_zero_seeds():
    m4b = candidate(id=1, seeders=None, filetype="M4B")
    mp3 = candidate(id=2, seeders=100, filetype="MP3")
    assert ordered([mp3, m4b], ReleasePreferences())[0].source_id == "1"
    assert (
        ordered([mp3, m4b], ReleasePreferences(criteria=["seeders", "format", "source"]))[
            0
        ].source_id
        == "2"
    )
    known = candidate(id=3, seeders=0, filetype="M4B")
    assert ordered([m4b, known], ReleasePreferences())[0].source_id == "3"
    remote = known.model_copy(update={"source": "prowlarr", "indexer_id": "7"})
    preferences = ReleasePreferences(
        source_order=["prowlarr:7", "mam", "prowlarr"], criteria=["source", "format", "seeders"]
    )
    assert ordered([known, remote], preferences)[0].source == "prowlarr"


def test_unknowns_are_not_ownership_or_automatic_eligibility():
    assessment = assess_release(
        candidate(filetype=None, size=None, seeders=None),
        WORK,
        ReleasePreferences(maximum_bytes=1000),
    )
    assert assessment.formats == [] and len(assessment.review) == 2
    assert "Seed count unknown" in assessment.explanation
    assert not hasattr(assessment, "owned")


@pytest.mark.parametrize(
    "options",
    [
        {"criteria": ["format"]},
        {"criteria": ["format", "format", "source"]},
        {"ebook_formats": []},
        {"ebook_formats": ["mp3"]},
        {"audio_formats": ["epub"]},
        {"blocked_formats": ["exe"]},
        {"source_order": ["http://unsafe"]},
        {"source_order": ["mam", "mam"]},
        {"maximum_bytes": 0},
    ],
)
def test_invalid_profile_preferences(options):
    with pytest.raises(ValidationError):
        ReleasePreferences(**options)


async def test_actual_manifest_formats_and_size_override_incomplete_source_claims():
    descriptor = await inspect_torrent(torrent_bytes())
    source = candidate(filetype=None, size=None)
    extensions = {f.path.rsplit(".", 1)[-1].lower() for f in descriptor.files}
    blocked = next(iter(extensions & {"m4b", "mp3", "epub", "pdf"}))
    with pytest.raises(HTTPException, match="blocked format"):
        enforce_profile(
            source,
            descriptor,
            ProfileSnapshot(preferences=ReleasePreferences(blocked_formats=[blocked])),
        )
    with pytest.raises(HTTPException, match="size limit"):
        enforce_profile(
            source, descriptor, ProfileSnapshot(preferences=ReleasePreferences(maximum_bytes=1))
        )


def test_observed_companion_formats_and_total_transfer_size_are_enforced():
    files = [
        {"extension": "m4b", "identity": {"size": 100}},
        {"extension": "pdf", "identity": {"size": 10}},
    ]
    with pytest.raises(HTTPException, match="blocked format: pdf"):
        enforce_inspected_profile(
            files, ProfileSnapshot(preferences=ReleasePreferences(blocked_formats=["pdf"]))
        )
    with pytest.raises(HTTPException, match="size limit"):
        enforce_inspected_profile(
            files, ProfileSnapshot(preferences=ReleasePreferences(maximum_bytes=105))
        )
    enforce_inspected_profile(
        files, ProfileSnapshot(preferences=ReleasePreferences(maximum_bytes=110))
    )
