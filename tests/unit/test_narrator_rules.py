from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.domain import narrators, request_scope
from app.domain.acquisition import RequestOptions, RequestSpec, asset_satisfies, intersect_rules
from app.domain.acquisition_selection import release_compatible
from app.domain.automatic_eligibility import eligibility
from app.domain.release_profiles import ProfileSnapshot, ReleasePreferences, assess_release
from tests.unit.test_release_profiles import WORK, candidate, ordered


def test_name_matching_is_conservative_all_of_and_not_recording_identity():
    values = ReleasePreferences(required_narrators=["  Ｒeader   A ", "reader a", "Reader B"])
    assert values.required_narrators == ["Reader A", "Reader B"]
    assert narrators.accepts(values.required_narrators, ["reader a", "READER B", "Reader C"])
    assert not narrators.accepts(values.required_narrators, ["Reader A"])
    assert not narrators.accepts(["Reader A"], [])
    assert not narrators.accepts(["R. A."], ["R A"])


@pytest.mark.parametrize(
    "names", [[" "], ["A\x00B"], ["a" * 201], [str(i) for i in range(33)], None]
)
def test_invalid_names_cannot_be_saved(names):
    with pytest.raises(ValidationError):
        ReleasePreferences(required_narrators=names)


def test_explicit_empty_clears_inheritance_and_ebook_ignores_audio_defaults():
    profile = ProfileSnapshot(preferences=ReleasePreferences(required_narrators=["Reader A"]))
    resolved, _ = request_scope.specification(RequestOptions(mode="audio"), profile)
    assert resolved.required_narrators == ["Reader A"]
    cleared, _ = request_scope.specification(
        RequestOptions(mode="audio", required_narrators=[]), profile
    )
    assert cleared.required_narrators == []
    assert "required_narrators" not in cleared.rule("audio")
    assert "required_narrators" not in cleared.model_dump()
    ebook, origins = request_scope.specification(RequestOptions(mode="ebook"), profile)
    assert ebook.required_narrators == [] and origins["required_narrators"] == "Not applicable"
    with pytest.raises(HTTPException):
        request_scope.specification(
            RequestOptions(mode="ebook", required_narrators=["Reader A"]), profile
        )


def test_planned_requirements_combine_without_relaxing_and_do_not_affect_ebook():
    left = RequestSpec(mode="both", required_narrators=["Reader A"])
    right = RequestSpec(mode="audio", required_narrators=["Reader B", "Reader A"])
    combined = intersect_rules(left.rule("audio"), right.rule("audio"))
    assert combined["required_narrators"] == ["Reader A", "Reader B"]
    assert "required_narrators" not in left.rule("ebook")
    asset = SimpleNamespace(medium="audio")
    assert not asset_satisfies(
        asset, SimpleNamespace(language=None, narrators=["Reader A"]), 1, combined
    )
    assert asset_satisfies(
        asset, SimpleNamespace(language=None, narrators=["Reader A", "Reader B"]), 1, combined
    )


def test_required_names_filter_before_preference_or_seed_count_and_manual_selection():
    preferred = candidate(id=1, seeders=2).model_copy(
        update={"narrators": ["Reader A", "Reader B"]}
    )
    wrong = candidate(id=2, seeders=9999).model_copy(update={"narrators": ["Reader A"]})
    prefs = ReleasePreferences(
        required_narrators=["Reader A", "Reader B"], preferred_narrators=["Reader A"]
    )
    assert ordered([wrong, preferred], prefs)[0].source_id == "1"
    rule = RequestSpec(mode="audio", required_narrators=prefs.required_narrators).rule("audio")
    assert any("required narrator" in reason for reason in eligibility(wrong, WORK, rule, prefs))
    with pytest.raises(HTTPException, match="required narrator"):
        release_compatible(wrong, rule, None)
    release_compatible(preferred, rule, None)


def test_preference_is_ordered_soft_and_its_priority_can_be_moved():
    first = candidate(id=1, filetype="MP3").model_copy(update={"narrators": ["Reader B"]})
    second = candidate(id=2, filetype="M4B").model_copy(update={"narrators": ["Reader A"]})
    prefs = ReleasePreferences(
        preferred_narrators=["Reader B", "Reader A"],
        criteria=["narrator", "format", "source", "seeders"],
    )
    assert ordered([second, first], prefs)[0].source_id == "1"
    assert not assess_release(first, WORK, prefs).blocked
    unknown = first.model_copy(update={"narrators": []})
    assert not assess_release(unknown, WORK, prefs).blocked
    assert "Preferred narrator not established" in assess_release(unknown, WORK, prefs).explanation
    legacy = prefs.model_copy(update={"criteria": ["format", "source", "seeders"]})
    assert ordered([first, second], legacy)[0].source_id == "2"
    assert (
        ordered([second, first.model_copy(update={"formats": ["m4b"]})], legacy)[0].source_id == "1"
    )
    ebook = first.model_copy(update={"medium": "ebook", "formats": ["epub"], "narrators": []})
    assert not assess_release(
        ebook, WORK, prefs.model_copy(update={"required_narrators": ["X"]}), "ebook"
    ).blocked


def test_cleared_request_requirement_is_authoritative_over_search_scope_defaults():
    release = candidate().model_copy(update={"narrators": []})
    rule = RequestSpec(mode="audio").rule("audio")
    reasons = eligibility(release, WORK, rule, ReleasePreferences(required_narrators=["Reader A"]))
    assert not any("required narrator" in reason for reason in reasons)
