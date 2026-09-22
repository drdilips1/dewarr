from app.domain.release_profiles import ReleasePreferences
from app.domain.source_strategy import (
    outcome,
    ready_for_next_source,
    review_message,
    search_order,
)


def test_soulseek_is_a_source_priority():
    preferences = ReleasePreferences(source_order=["slskd", "mam"], source_strategy="rank_all")
    assert preferences.source_order[0] == "slskd"
    assert preferences.model_dump()["source_strategy"] == "rank_all"
    assert "source_strategy" not in ReleasePreferences().model_dump()


def test_priority_walks_connected_roots_then_other_sources():
    assert search_order(["slskd", "prowlarr:7", "mam"], {"mam", "prowlarr", "audiobookbay"}) == [
        "prowlarr",
        "mam",
        "audiobookbay",
    ]
    assert search_order(["slskd", "mam"], {"slskd", "mam"}) == ["slskd", "mam"]


def test_fallback_moves_to_the_next_source_only_for_priority():
    assert outcome("priority", True, 0, 2, found=False) == "next"
    assert outcome("priority", True, 0, 2, found=True) == "use"
    assert outcome("priority", False, 0, 2, found=False) == "review"
    assert outcome("priority", True, 1, 2, found=False) == "review"
    assert outcome("rank_all", True, 0, 2, found=False) == "review"


def test_both_formats_leave_a_source_together():
    waiting = {"audio": {"wants_next": True}, "ebook": {}}
    assert ready_for_next_source(waiting) is False
    ready = {"audio": {"wants_next": True}, "ebook": {"done": True}}
    assert ready_for_next_source(ready) is True
    assert ready_for_next_source({"audio": {"done": True}}) is False


def test_review_message_names_the_miss():
    text = review_message([{"name": "Soulseek", "message": "No eligible release"}])
    assert text.startswith("Request added. No automatic release was found")
    assert "Soulseek: No eligible release" in text
