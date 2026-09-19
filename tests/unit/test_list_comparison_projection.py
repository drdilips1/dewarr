from uuid import uuid4

from app.domain.list_comparisons import make_rows


def record(key="42", count=1):
    return {
        "external_id": key,
        "title": "Remote title",
        "authors": [],
        "isbn": None,
        "isbn13": None,
        "memberships": [
            {"entry_id": n + 1, "edition_id": str(100 + n), "position": n, "date_added": None}
            for n in range(count)
        ],
    }


def state(keys=("42",), local=True, changed=()):
    root = str(uuid4())
    return {
        "local": [root] if local else [],
        "works": {
            root: {"title": "Protected local title", "keys": list(keys), "changed": list(changed)}
        },
    }


def test_several_remote_editions_are_one_book_difference_with_exact_membership_ids():
    rows = make_rows(state(local=False), [record(count=3)], 9, 7)
    assert len(rows) == 1 and rows[0]["state"] == "remote_only"
    assert rows[0]["title"] == "Protected local title"
    assert [r["id"] for r in rows[0]["snapshot"]["observation"]["memberships"]] == [1, 2, 3]


def test_oversized_membership_group_is_held_without_hiding_other_books():
    rows = make_rows(state(), [record(count=101), record("43")], 9, 7)
    assert len(rows) == 2
    assert {r["state"] for r in rows} == {"unmatched", "remote_only"}
    held = next(r for r in rows if r["state"] == "unmatched")
    assert "100" in held["snapshot"]["reason"] and "observation" not in held["snapshot"]


def test_conflicting_provider_keys_do_not_turn_one_book_into_two_writable_differences():
    rows = make_rows(state(keys=("42", "43")), [record(), record("43")], 9, 7)
    assert rows and all(row["state"] == "unmatched" for row in rows)


def test_changed_identity_is_not_rehabilitated_by_a_remaining_binding():
    rows = make_rows(state(changed=("42",)), [record()], 9, 7)
    assert rows and all(row["state"] == "unmatched" for row in rows)
