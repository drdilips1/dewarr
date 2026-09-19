from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.adapters.contracts import AdapterError, FailureKind, MutationError
from app.adapters.hardcover_writeback import (
    ADD,
    MEMBERSHIP,
    OWNERSHIP,
    REMOVE,
    Decision,
    Membership,
    Observation,
    decide,
    mutate,
    observe,
    owned_list,
)


def entry(key=1, edition=None):
    return Membership(id=key, list_id=9, book_id=42, edition_id=edition)


def snapshot(*entries):
    return Observation(list_id=9, owner_id=7, book_id=42, memberships=tuple(entries))


def reply(*entries):
    return {
        "me": [{"id": 7}],
        "lists": [
            {
                "id": 9,
                "name": "My shelf",
                "user_id": 7,
                "list_books": [row.model_dump() for row in entries],
            }
        ],
    }


async def test_owned_list_and_membership_are_bounded_and_keep_edition_identity():
    calls = []

    async def query(document, variables):
        calls.append((document, variables))
        return reply(entry(11, 70), entry(12, 71))

    owner = await owned_list(query, 9)
    assert owner.owner_id == 7 and owner.name == "My shelf"
    state = await observe(query, 9, 42)
    assert state == snapshot(entry(11, 70), entry(12, 71))
    assert calls == [(OWNERSHIP, {"list": 9}), (MEMBERSHIP, {"list": 9, "book": 42})]


@pytest.mark.parametrize(
    "edit",
    [
        lambda r: r.update(me=[]),
        lambda r: r["me"][0].update(id=True),
        lambda r: r.update(lists=[]),
        lambda r: r["lists"][0].update(id=10),
        lambda r: r["lists"][0].update(user_id=8),
        lambda r: r["lists"][0].update(name=None),
        lambda r: r["lists"][0].update(list_books=None),
        lambda r: r["lists"][0].update(list_books=[entry().model_dump()] * 2),
        lambda r: r["lists"][0].update(list_books=[entry(2).model_dump(), entry(1).model_dump()]),
        lambda r: r["lists"][0]["list_books"][0].update(list_id=10),
        lambda r: r["lists"][0]["list_books"][0].update(book_id=99),
        lambda r: r["lists"][0]["list_books"][0].update(edition_id=True),
        lambda r: r["lists"][0].update(list_books=[entry(n).model_dump() for n in range(1, 102)]),
    ],
)
async def test_invalid_and_unowned_observations_never_prove_absence(edit):
    data = reply(entry())
    edit(data)

    async def query(*args):
        return data

    with pytest.raises(AdapterError):
        await observe(query, 9, 42)


@pytest.mark.parametrize(
    "list_id,book_id", [(True, 42), (9, False), (0, 42), (9, 2147483648), ("9", 42)]
)
async def test_invalid_identifiers_fail_before_io(list_id, book_id):
    async def query(*args):
        pytest.fail("Invalid identifiers must not reach Hardcover")

    with pytest.raises(ValueError):
        await observe(query, list_id, book_id)


@pytest.mark.parametrize(
    "base,current,desired,uncertain,expected",
    [
        (snapshot(), snapshot(), True, False, "add"),
        (snapshot(), snapshot(entry()), True, False, "confirmed"),
        (snapshot(), snapshot(entry()), True, True, "confirmed"),
        (snapshot(entry()), snapshot(), False, True, "confirmed"),
        (snapshot(entry()), snapshot(entry()), False, False, "remove"),
        (snapshot(entry()), snapshot(entry()), False, True, "reconcile"),
        (snapshot(), snapshot(), True, True, "reconcile"),
        (snapshot(entry()), snapshot(), True, False, "conflict"),
        (snapshot(entry()), snapshot(entry(2)), False, False, "conflict"),
        (snapshot(entry(1, 70)), snapshot(entry(1, 71)), False, False, "conflict"),
        (snapshot(entry(1), entry(2)), snapshot(entry(2)), False, False, "remove"),
        (snapshot(), snapshot(entry()), False, False, "conflict"),
    ],
)
def test_desired_state_and_membership_episode_decisions(
    base, current, desired, uncertain, expected
):
    decision = decide(base, current, desired, uncertain=uncertain)
    assert decision.action == expected
    if expected == "remove":
        assert decision.entry_id == current.memberships[0].id


@pytest.mark.parametrize("field", ["owner_id", "list_id", "book_id"])
def test_identity_changes_are_conflicts_even_when_desired_state_looks_satisfied(field):
    current = snapshot().model_copy(update={field: 99})
    assert decide(snapshot(), current, False).action == "conflict"


async def test_mutations_use_only_the_explicit_work_or_membership_and_require_confirmation():
    calls = []

    async def send(document, variables):
        calls.append((document, variables))
        if document == ADD:
            return {"data": {"insert_list_book": {"id": 5, "list_book": entry(5).model_dump()}}}
        return {"data": {"delete_list_book": {"id": 5, "list_id": 9}}}

    empty, present = snapshot(), snapshot(entry(5))
    assert await mutate(send, empty, decide(empty, empty, True)) == 5
    assert await mutate(send, present, decide(present, present, False)) == 5
    assert calls == [(ADD, {"list": 9, "book": 42}), (REMOVE, {"entry": 5})]
    for document, _ in calls:
        assert "user_book" not in document and "delete_list(" not in document


@pytest.mark.parametrize(
    "response",
    [
        {},
        None,
        {"errors": [{"message": "private upstream details"}]},
        {"data": {"insert_list_book": None}},
        {"data": {"insert_list_book": {"id": 1, "list_book": entry(2).model_dump()}}},
        {
            "data": {
                "insert_list_book": {"id": 1, "list_book": {**entry().model_dump(), "list_id": 99}}
            }
        },
        {
            "data": {"insert_list_book": {"id": 1, "list_book": entry().model_dump()}},
            "errors": [{}],
        },
    ],
)
async def test_partial_malformed_or_unrelated_acknowledgement_requires_reconciliation(response):
    calls = []

    async def send(*args):
        calls.append(args)
        return deepcopy(response)

    with pytest.raises(MutationError) as caught:
        await mutate(send, snapshot(), decide(snapshot(), snapshot(), True))
    assert caught.value.may_have_applied and len(calls) == 1
    assert "private upstream" not in str(caught.value)


async def test_invalid_write_decisions_fail_without_network_and_errors_are_not_retried():
    calls = []

    async def send(*args):
        calls.append(args)
        raise AdapterError(FailureKind.TIMEOUT, "No response")

    for state, decision in [
        (snapshot(), Decision(action="confirmed", message="Done")),
        (snapshot(entry()), Decision(action="remove", entry_id=99, message="Wrong row")),
        (snapshot(entry()), Decision(action="add", message="Already present")),
    ]:
        with pytest.raises(ValueError):
            await mutate(send, state, decision)
    assert not calls
    with pytest.raises(MutationError) as caught:
        await mutate(send, snapshot(), decide(snapshot(), snapshot(), True))
    assert caught.value.may_have_applied and len(calls) == 1


def test_persisted_observation_round_trip_retains_strict_identity():
    original = snapshot(entry(1, 70), entry(2, 71))
    assert Observation.model_validate_json(original.model_dump_json()) == original
    with pytest.raises(ValidationError):
        Membership(id=True, list_id=9, book_id=42)


@pytest.mark.parametrize("partial", [False, True])
async def test_scope_rejection_is_definite_only_without_a_partial_mutation_result(partial):
    async def send(*args):
        return {
            "data": {
                "insert_list_book": {"id": 1, "list_book": entry().model_dump()}
                if partial
                else None
            },
            "errors": [{"extensions": {"code": "insufficient_scope"}, "message": "private detail"}],
        }

    with pytest.raises(MutationError) as caught:
        await mutate(send, snapshot(), decide(snapshot(), snapshot(), True))
    assert caught.value.may_have_applied is partial
    assert "private detail" not in str(caught.value)
