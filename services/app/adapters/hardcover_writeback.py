"""Narrow Hardcover list mutations and membership-episode reconciliation.

The mutation reply is an acknowledgement, never confirmed membership. The caller
must persist each attempt, then read through an uncached Hardcover query adapter.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.adapters.contracts import AdapterError, FailureKind, MutationError

SCHEMA_REVISION = "e8d38c8b7bd53cada7e97121ab0cacfa0804013c"
MAX_MEMBERSHIPS = 100
OWNERSHIP = """query WritableListOwner($list: Int!) {
 me { id }
 lists(where: {id: {_eq: $list}}, limit: 1) { id name user_id }
}"""
MEMBERSHIP = """query WritableListMembership($list: Int!, $book: Int!) {
 me { id }
 lists(where: {id: {_eq: $list}}, limit: 1) {
  id name user_id
  list_books(where: {book_id: {_eq: $book}}, order_by: {id: asc}, limit: 101) {
   id list_id book_id edition_id
  }
 }
}"""
ADD = """mutation AddListMembership($list: Int!, $book: Int!) {
 insert_list_book(object: {list_id: $list, book_id: $book}) {
  id list_book { id list_id book_id edition_id }
 }
}"""
REMOVE = """mutation RemoveListMembership($entry: Int!) {
 delete_list_book(id: $entry) { id list_id }
}"""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Membership(StrictModel):
    id: int = Field(ge=1, le=2147483647)
    list_id: int = Field(ge=1, le=2147483647)
    book_id: int = Field(ge=1, le=2147483647)
    edition_id: int | None = Field(default=None, ge=1, le=2147483647)


class OwnedList(StrictModel):
    id: int = Field(ge=1, le=2147483647)
    owner_id: int = Field(ge=1, le=2147483647)
    name: str = Field(min_length=1, max_length=600)


class Observation(StrictModel):
    list_id: int = Field(ge=1, le=2147483647)
    owner_id: int = Field(ge=1, le=2147483647)
    book_id: int = Field(ge=1, le=2147483647)
    memberships: tuple[Membership, ...]

    @model_validator(mode="after")
    def coherent(self):
        if len(self.memberships) > MAX_MEMBERSHIPS:
            raise ValueError("Too many memberships to establish complete coverage")
        ids = [entry.id for entry in self.memberships]
        if len(set(ids)) != len(ids) or ids != sorted(ids):
            raise ValueError("Membership order or identity is inconsistent")
        if any(
            entry.list_id != self.list_id or entry.book_id != self.book_id
            for entry in self.memberships
        ):
            raise ValueError("Memberships do not belong to the requested book and list")
        return self


class Decision(StrictModel):
    action: Literal["confirmed", "add", "remove", "conflict", "reconcile"]
    entry_id: int | None = None
    message: str


def invalid():
    return AdapterError(
        FailureKind.PARSER,
        "Hardcover membership could not be verified; no absence or write is inferred",
    )


def positive(value):
    if type(value) is not int or not 1 <= value <= 2147483647:
        raise ValueError("Invalid provider identifier")
    return value


def parse_owner(data, list_id):
    try:
        me, rows = data["me"], data["lists"]
        if not isinstance(me, list) or len(me) != 1:
            raise invalid()
        user_id = positive(me[0]["id"])
        if rows == []:
            raise AdapterError(
                FailureKind.PERMISSION, "This Hardcover list is no longer accessible"
            )
        if not isinstance(rows, list) or len(rows) != 1:
            raise invalid()
        row = rows[0]
        result = OwnedList(id=row["id"], name=row["name"], owner_id=row["user_id"])
        if result.id != list_id:
            raise invalid()
        if result.owner_id != user_id:
            raise AdapterError(
                FailureKind.PERMISSION,
                "Write-back is available only for lists owned by your connected Hardcover account",
            )
        return result
    except (KeyError, TypeError, ValueError, ValidationError):
        raise invalid() from None


async def owned_list(query, list_id):
    positive(list_id)
    return parse_owner(await query(OWNERSHIP, {"list": list_id}), list_id)


async def observe(query, list_id, book_id):
    positive(list_id)
    positive(book_id)
    data = await query(MEMBERSHIP, {"list": list_id, "book": book_id})
    owner = parse_owner(data, list_id)
    try:
        rows = data["lists"][0]["list_books"]
        if not isinstance(rows, list):
            raise invalid()
        return Observation(
            list_id=list_id,
            owner_id=owner.owner_id,
            book_id=book_id,
            memberships=tuple(Membership.model_validate(row) for row in rows),
        )
    except (KeyError, TypeError, ValueError, ValidationError):
        raise invalid() from None


def decide(base: Observation, current: Observation, desired: bool, *, uncertain=False):
    """Decide one narrow effect from complete observations of the same target.

    A removed/re-added or edition-rebound remote membership is a new episode.
    Unknown attempts never become automatically replayable just because the old
    state is still visible; a delayed server action could otherwise execute twice.
    """
    if type(desired) is not bool or type(uncertain) is not bool:
        raise ValueError("Membership intent and uncertainty must be explicit booleans")
    if (base.list_id, base.owner_id, base.book_id) != (
        current.list_id,
        current.owner_id,
        current.book_id,
    ):
        return Decision(action="conflict", message="Hardcover account or list identity changed")
    if desired and current.memberships:
        return Decision(action="confirmed", message="Book is present on the Hardcover list")
    if not desired and not current.memberships:
        return Decision(action="confirmed", message="Book is absent from the Hardcover list")
    old = {entry.id: entry for entry in base.memberships}
    if any(old.get(entry.id) != entry for entry in current.memberships):
        return Decision(
            action="conflict", message="Hardcover membership changed; review the difference"
        )
    if uncertain:
        return Decision(
            action="reconcile", message="Previous write is unconfirmed; checking remote state"
        )
    if desired:
        if base.memberships:
            return Decision(
                action="conflict",
                message="Book was removed on Hardcover; review before adding it again",
            )
        return Decision(action="add", message="Add this book to the Hardcover list")
    return Decision(
        action="remove",
        entry_id=current.memberships[0].id,
        message="Remove the previously observed Hardcover membership",
    )


async def mutate(send, observation: Observation, decision: Decision):
    """Send exactly one explicit membership operation; never retry in the adapter."""
    if decision.action == "add" and not observation.memberships:
        document, variables, field = (
            ADD,
            {
                "list": observation.list_id,
                "book": observation.book_id,
            },
            "insert_list_book",
        )
    elif decision.action == "remove" and decision.entry_id in {
        entry.id for entry in observation.memberships
    }:
        document, variables, field = REMOVE, {"entry": decision.entry_id}, "delete_list_book"
    else:
        raise ValueError("Only a planned add or observed membership removal may be sent")
    try:
        response = await send(document, variables)
    except MutationError:
        raise
    except AdapterError as error:
        raise MutationError(
            error.kind, str(error), may_have_applied=True, retry_after=error.retry_after
        ) from None
    if isinstance(response, dict):
        errors = response.get("errors")
        data = response.get("data")
        no_result = data is None or (isinstance(data, dict) and data.get(field) is None)
        if (
            no_result
            and isinstance(errors, list)
            and errors
            and all(
                isinstance(error, dict)
                and isinstance(error.get("extensions"), dict)
                and error["extensions"].get("code")
                in {"access-denied", "permission-error", "insufficient_scope"}
                for error in errors
            )
        ):
            raise MutationError(
                FailureKind.PERMISSION,
                "Hardcover rejected this list change; check list ownership and write:lists scope",
                may_have_applied=False,
            )
    try:
        if not isinstance(response, dict) or response.get("errors") or response.get("error"):
            raise ValueError("Unconfirmed mutation reply")
        value = response["data"][field]
        returned_id = positive(value["id"])
        if decision.action == "add":
            entry = Membership.model_validate(value["list_book"])
            if (returned_id, observation.list_id, observation.book_id) != (
                entry.id,
                entry.list_id,
                entry.book_id,
            ):
                raise ValueError("Unrelated mutation acknowledgement")
        elif returned_id != decision.entry_id or positive(value["list_id"]) != observation.list_id:
            raise ValueError("Unrelated deletion acknowledgement")
        return returned_id
    except (KeyError, TypeError, ValueError, ValidationError):
        raise MutationError(
            FailureKind.UNCERTAIN,
            "Hardcover write response is unconfirmed; reconcile membership before retrying",
            may_have_applied=True,
        ) from None
