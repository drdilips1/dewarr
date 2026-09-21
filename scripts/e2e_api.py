"""Browser API with deterministic public discovery data; never contact Goodreads."""

from copy import deepcopy
from urllib.parse import urlsplit

from app.config import get_settings
from app.domain import discovery_pages
from app.domain.discovery_catalog import catalog
from app.main import app  # noqa: F401

if not urlsplit(get_settings().database_url.get_secret_value()).path.endswith("_browser_test"):
    raise SystemExit("Fixture API requires the disposable browser database")


async def collection_page(url, page):
    snapshot = next(value for value in catalog().values() if value["source_url"] == url)
    books = deepcopy(snapshot["books"])
    return {
        "books": books[(page - 1) * 100 : page * 100],
        "count": len(books),
        "has_more": page * 100 < len(books),
    }


discovery_pages.fetch_collection_page = collection_page
