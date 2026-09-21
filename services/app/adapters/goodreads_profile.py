"""Discover public Goodreads shelves without credentials or arbitrary URL fetching."""

import re
from urllib.parse import parse_qsl, urlencode, urlsplit

from bs4 import BeautifulSoup
from defusedxml import ElementTree

from app.adapters.contracts import AdapterError, FailureKind
from app.adapters.goodreads import feed_url, fetch_document, parse_feed

MAX_SHELVES = 500


def profile_input(value):
    """Accept a user ID, profile, bookshelf or RSS link; never retain arbitrary URLs."""
    value = value.strip()
    if re.fullmatch(r"[1-9][0-9]{0,19}", value):
        return {"user_id": value, "key": None, "selected": None}
    try:
        parts = urlsplit(value)
        if (
            parts.scheme != "https"
            or parts.hostname not in {"goodreads.com", "www.goodreads.com"}
            or parts.port not in {None, 443}
            or parts.username is not None
            or parts.password is not None
            or parts.fragment
            or "\\" in value
            or len(value) > 2000
            or any(ord(c) < 33 for c in value)
        ):
            raise ValueError
        match = re.fullmatch(
            r"/(?:user/show|review/list|review/list_rss)/([1-9][0-9]{0,19})(?:-[\w-]+)?/?",
            parts.path,
        )
        if not match:
            raise ValueError
        query = parse_qsl(parts.query, keep_blank_values=True, max_num_fields=15)
        if len(dict(query)) != len(query) or any(len(v) > 300 for _, v in query):
            raise ValueError
        fields = dict(query)
        shelf = fields.get("shelf") or fields.get("tag")
        if shelf in {"all", "#ALL#"}:
            shelf = None
        if shelf and not valid_shelf(shelf):
            raise ValueError
        return {"user_id": match[1], "key": fields.get("key") or None, "selected": shelf}
    except ValueError:
        raise ValueError(
            "Paste a Goodreads profile, bookshelf, RSS link, or numeric user ID"
        ) from None


def valid_shelf(value):
    return bool(re.fullmatch(r"[\w-]{1,200}", value))


def shelf_name(shelf):
    return {
        "to-read": "Want to read",
        "currently-reading": "Currently reading",
        "read": "Read",
        "did-not-finish": "Did not finish",
    }.get(shelf, shelf.replace("-", " ").capitalize())


def shelf_url(config, shelf=None):
    query = {}
    if config.get("key"):
        query["key"] = config["key"]
    if shelf:
        query["shelf"] = shelf
    return feed_url(
        f"https://www.goodreads.com/review/list_rss/{config['user_id']}?{urlencode(query)}"
    )


def parse_profile(content, user_id):
    soup = BeautifulSoup(content, "html.parser")
    shelves = {}
    for link in soup.select("#shelves a[href]"):
        parts = urlsplit(link["href"])
        if parts.netloc and parts.hostname not in {"goodreads.com", "www.goodreads.com"}:
            continue
        if not re.fullmatch(rf"/review/list/{user_id}(?:-[\w-]+)?", parts.path):
            continue
        fields = dict(parse_qsl(parts.query))
        shelf = fields.get("shelf") or fields.get("tag")
        if not shelf or not valid_shelf(shelf):
            continue
        count = re.search(r"\(([\d,]+)\)", link.get_text())
        shelves[shelf] = {
            "external_id": shelf,
            "name": shelf_name(shelf),
            "count": int(count[1].replace(",", "")) if count else None,
        }
        if len(shelves) >= MAX_SHELVES:
            break
    heading = soup.select_one("h1.userProfileName")
    title = (
        heading.get_text(" ", strip=True)
        if heading
        else (soup.title.get_text(" ", strip=True) if soup.title else "")
    )
    name = re.sub(r"\s*\([^)]*books?\).*$", "", title).strip()[:200]
    return name, list(shelves.values())


async def discover(config):
    # Check an actual feed even if HTML discovery succeeds (private profiles can show HTML).
    feed = await fetch_document(shelf_url(config, config.get("selected")))
    records = parse_feed(feed.content)
    root = ElementTree.fromstring(feed.content, forbid_dtd=True)
    title = root.findtext("./channel/title", "Goodreads")
    name = title.split("'s bookshelf:")[0][:200]
    shelves = []
    warning = None
    try:
        document = await fetch_document(
            f"https://www.goodreads.com/user/show/{config['user_id']}",
            profile_id=config["user_id"],
        )
        profile_name, shelves = parse_profile(document.content, config["user_id"])
        if shelves:
            name = profile_name or name
    except AdapterError:
        pass  # Public profile HTML is optional; an accessible RSS link remains usable.
    if not shelves:
        warning = "Showing shelves found in this feed. Other or empty shelves may be missing."
    found = {s["external_id"]: s for s in shelves}
    observed = {config.get("selected")} if config.get("selected") else set()
    for item in root.findall("./channel/item"):
        observed.update(s.strip() for s in item.findtext("user_shelves", "").split(","))
    for shelf in sorted(observed):
        if valid_shelf(shelf) and shelf not in found and len(found) < MAX_SHELVES:
            found[shelf] = {
                "external_id": shelf,
                "name": shelf_name(shelf),
                "count": None,
            }
    if not found and not records:
        raise AdapterError(FailureKind.PARSER, "No shelves found. Try a link to a specific shelf.")
    return {
        **config,
        "name": name,
        "shelves": list(found.values()),
        "warning": warning,
    }
