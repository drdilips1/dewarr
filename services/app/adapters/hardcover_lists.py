"""Authorized Hardcover lists, using documented GraphQL fields and keyset pages."""

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, Field, ValidationError

from app.adapters.catalog_providers import contributors, identifier
from app.adapters.contracts import AdapterError, FailureKind

PAGE_SIZE = 100
MAX_MEMBERS = 5000
FIELDS = "id name books_count updated_at public user_id"
PAGE = """query ListMembershipPage($id: Int!, $after: Int!) {
 lists(where: {id: {_eq: $id}}, limit: 1) {
  id name books_count updated_at public user_id
  list_books(where: {id: {_gt: $after}}, order_by: {id: asc}, limit: 100) {
   id book_id edition_id position date_added
   book { id title cached_contributors }
  }
 }
}"""


class ListChoice(BaseModel):
    external_id: str
    name: str = Field(min_length=1, max_length=600)
    count: int = Field(ge=0)
    public: bool
    owner_id: str


class ChoicePage(BaseModel):
    items: list[ListChoice]
    next_cursor: int | None = None


@dataclass
class ListPage:
    info: dict
    items: list[dict]
    cursor: int


def invalid():
    return AdapterError(
        FailureKind.PARSER,
        "Hardcover returned an incomplete or changed list; previous memberships are preserved",
    )


def positive(value):
    if type(value) is not int:
        raise invalid()
    return int(identifier("hardcover", str(value)))


def info(row):
    count = row["books_count"]
    if type(count) is not int or count < 0 or type(row["public"]) is not bool:
        raise invalid()
    updated = row["updated_at"]
    if updated is not None:
        if (
            not isinstance(updated, str)
            or not datetime.fromisoformat(updated.replace("Z", "+00:00")).tzinfo
        ):
            raise invalid()
    return {
        "external_id": str(positive(row["id"])),
        "name": ListChoice(
            external_id=str(row["id"]),
            name=row["name"],
            count=count,
            public=row["public"],
            owner_id=str(positive(row["user_id"])),
        ).name,
        "count": count,
        "updated_at": updated,
        "public": row["public"],
        "owner_id": str(row["user_id"]),
    }


async def page(query, external_id, cursor):
    identifier("hardcover", external_id)
    data = await query(PAGE, {"id": int(external_id), "after": cursor})
    try:
        rows = data["lists"]
        if rows == []:
            raise AdapterError(
                FailureKind.PERMISSION,
                "Hardcover denied or could not find this list; check access and list scopes",
            )
        if not isinstance(rows, list) or len(rows) != 1:
            raise invalid()
        header = info(rows[0])
        if header["external_id"] != external_id or header["count"] > MAX_MEMBERS:
            raise AdapterError(
                FailureKind.PARSER,
                "Hardcover lists support at most 5,000 memberships; existing books are preserved",
            )
        members = rows[0]["list_books"]
        if not isinstance(members, list) or len(members) > PAGE_SIZE:
            raise invalid()
        records = []
        for member in members:
            member_id = positive(member["id"])
            if member_id <= cursor:
                raise invalid()
            cursor = member_id
            book = member["book"]
            book_id = str(positive(member["book_id"]))
            if str(positive(book["id"])) != book_id:
                raise invalid()
            title = book["title"]
            authors = contributors(book["cached_contributors"], "Author")
            if (
                not isinstance(title, str)
                or not title.strip()
                or len(title) > 600
                or len(authors) > 100
                or any(len(a) > 300 for a in authors)
            ):
                raise invalid()
            edition = member["edition_id"]
            if edition is not None:
                positive(edition)
            position = member["position"]
            if position is not None and type(position) is not int:
                raise invalid()
            date = member["date_added"]
            if date is not None and (
                not isinstance(date, str)
                or not datetime.fromisoformat(date.replace("Z", "+00:00")).tzinfo
            ):
                raise invalid()
            records.append(
                {
                    "entry_id": member_id,
                    "external_id": book_id,
                    "title": title.strip(),
                    "authors": authors,
                    "edition_id": str(edition) if edition else None,
                    "position": position,
                    "date_added": date,
                    "isbn": None,
                    "isbn13": None,
                }
            )
        return ListPage(header, records, cursor)
    except (KeyError, TypeError, ValueError, AttributeError, ValidationError):
        raise invalid() from None


async def choices(query, mode, cursor):
    if mode == "public":
        document = f"""query DiscoverLists($after: Int!) {{
 lists(where: {{public: {{_eq: true}}, id: {{_gt: $after}}}},
 order_by: {{id: asc}}, limit: 26) {{ {FIELDS} }} }}"""
    elif mode == "owned":
        document = f"""query MyLists($after: Int!) {{ me {{ id
 lists(where: {{id: {{_gt: $after}}}}, order_by: {{id: asc}}, limit: 26)
 {{ {FIELDS} }} }} }}"""
    else:
        document = f"""query FollowedLists($after: Int!) {{ me {{ id
 followed_lists(where: {{id: {{_gt: $after}}}}, order_by: {{id: asc}}, limit: 26)
 {{ id list {{ {FIELDS} }} }} }} }}"""
    data = await query(document, {"after": cursor})
    try:
        if mode == "public":
            rows = data["lists"]
        else:
            me = data["me"]
            if not isinstance(me, list) or len(me) != 1:
                raise invalid()
            owner = str(positive(me[0]["id"]))
            rows = me[0]["lists" if mode == "owned" else "followed_lists"]
        if not isinstance(rows, list) or len(rows) > 26:
            raise invalid()
        items = []
        for row in rows:
            key = positive(row["id"])
            if key <= cursor:
                raise invalid()
            cursor = key
            header = info(row["list"] if mode == "followed" else row)
            if mode == "owned" and header["owner_id"] != owner:
                raise invalid()
            if mode == "public" and not header["public"]:
                raise invalid()
            items.append((key, ListChoice.model_validate(header)))
        return ChoicePage(
            items=[v for _, v in items[:25]], next_cursor=items[24][0] if len(items) > 25 else None
        )
    except (KeyError, TypeError, ValueError, AttributeError, ValidationError):
        raise invalid() from None
