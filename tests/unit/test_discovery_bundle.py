"""Required startup collections must be present in a clean checkout/package."""

import json
from importlib.resources import files


def test_bundled_discovery_collections_have_books_and_public_sources():
    root = files("app").joinpath("data/discovery")
    for name in (
        "gr-list-19341.json",
        "gr-award-readers-favorite-fiction-books-2025.json",
    ):
        collection = json.loads(root.joinpath(name).read_text())
        assert collection["books"]
        assert collection["source_url"].startswith("https://www.goodreads.com/")
        assert all(book["external_id"] and book["title"] for book in collection["books"])
