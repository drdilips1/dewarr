import pytest
from pydantic import ValidationError

from app.domain.acquisition import RequestSpec, intersect_rules
from app.domain.request_constraints import PRIMARY_FORMATS, DownloadConstraints


def rule(**constraints):
    return RequestSpec(mode="audio", download_constraints=constraints).rule("audio")


def test_legacy_receipts_and_fingerprints_do_not_gain_a_null_or_empty_field():
    previous = RequestSpec(mode="audio").model_dump(mode="json")
    assert "download_constraints" not in previous
    assert RequestSpec(mode="audio", download_constraints={}).model_dump(mode="json") == previous
    assert "download_constraints" not in rule()


def test_constraints_are_canonical_and_intersection_never_relaxes_a_request():
    left = rule(blocked_formats=[".MP3", "flac", "mp3"], maximum_bytes=100)
    right = rule(blocked_formats=["aac"], maximum_bytes=200)
    assert left["download_constraints"]["blocked_formats"] == ["flac", "mp3"]
    assert intersect_rules(left, right) == intersect_rules(right, left)
    assert intersect_rules(left, right)["download_constraints"] == {
        "blocked_formats": ["aac", "flac", "mp3"],
        "maximum_bytes": 100,
    }
    assert intersect_rules(left, rule()) == left


def test_requests_with_no_common_primary_format_do_not_share_a_reservation():
    left = rule(blocked_formats=list(PRIMARY_FORMATS["audio"] - {"m4b"}))
    right = rule(blocked_formats=list(PRIMARY_FORMATS["audio"] - {"mp3"}))
    assert intersect_rules(left, right) is None


@pytest.mark.parametrize(
    "constraints",
    [
        {"blocked_formats": ["executable"]},
        {"maximum_bytes": 0},
        {"maximum_bytes": -1},
        {"maximum_bytes": 2**53},
        {"unknown": True},
    ],
)
def test_bad_constraints_are_rejected(constraints):
    with pytest.raises(ValidationError):
        DownloadConstraints.model_validate(constraints)


def test_no_requested_medium_can_block_every_supported_format():
    with pytest.raises(ValidationError, match="at least one format"):
        RequestSpec(
            mode="audio", download_constraints={"blocked_formats": list(PRIMARY_FORMATS["audio"])}
        )
