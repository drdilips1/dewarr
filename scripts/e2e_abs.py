"""Synthetic ABS HTTP endpoint for browser tests; never a compatibility certificate."""

import json
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request

from app.config import get_settings

app = FastAPI()
catalog_state = {"narrator": "Sample Narrator"}
item = json.loads(
    (Path(__file__).resolve().parents[1] / "tests/fixtures/audiobookshelf-item.json").read_text()
)


@app.api_route("/abs/{path:path}", methods=["GET", "POST"])
async def endpoint(path: str, request: Request, authorization: str = Header(default="")):
    if authorization != "Bearer browser-abs-fixture-token":
        raise HTTPException(401)
    if path == "api/authorize":
        return {
            "user": {"id": "fixture-user", "type": "user", "permissions": {}},
            "serverVersion": "2.36.1",
        }
    if path == "api/libraries":
        return {"libraries": [{"id": "library-one", "name": "Fixture books", "mediaType": "book"}]}
    if path == "status":
        return {"app": "audiobookshelf", "serverVersion": "2.36.1"}
    if path == "api/libraries/library-one":
        return {
            "id": "library-one",
            "mediaType": "book",
            "folders": [{"fullPath": "/fixture/books"}],
            "settings": {
                "audiobooksOnly": False,
                "disableWatcher": False,
                "metadataPrecedence": [
                    "folderStructure",
                    "audioMetatags",
                    "opfFile",
                    "absMetadata",
                ],
            },
        }
    if path == "api/filesystem/pathexists":
        body = await request.json()
        if (
            body["folderPath"] != "/fixture/books"
            or not body["directory"].startswith("book-search-check-")
            or "/" in body["directory"]
        ):
            raise HTTPException(400)
        return {
            "exists": (get_settings().import_destinations["ebooks"] / body["directory"]).is_dir()
        }
    if path == "api/libraries/library-one/items":
        return {"results": [{"id": item["id"], "updatedAt": 1}], "total": 1}
    if path == "api/items/batch/get":
        return {"libraryItems": [item]}
    if path == f"api/items/{item['id']}":
        return item
    raise HTTPException(404)


@app.post("/catalog/v1/graphql")
async def catalog(request: Request, authorization: str = Header(default="")):
    if authorization != "Bearer browser-hardcover-token":
        raise HTTPException(401)
    body = await request.json()
    query = body.get("query", "")
    if "CatalogBook(" in query:
        return {
            "data": {
                "books": [
                    {
                        "id": 42,
                        "title": "The Catalog Journey",
                        "description": "A synthetic book for catalog and metadata verification.",
                        "cached_contributors": [{"author": {"name": "Catalog Author"}}],
                        "book_series": [
                            {
                                "position": 1,
                                "compilation": False,
                                "series": {"id": 10, "name": "The Journey Series"},
                            }
                        ],
                    }
                ]
            }
        }
    if "CatalogEditions(" in query:
        return {
            "data": {
                "editions": [
                    {
                        "id": 51,
                        "book_id": 42,
                        "title": "The Catalog Journey",
                        "reading_format": {"format": "Ebook"},
                        "language": {"code2": "en"},
                    },
                    {
                        "id": 52,
                        "book_id": 42,
                        "title": "The Catalog Journey",
                        "reading_format": {"format": "Audio"},
                        "language": {"code2": "en"},
                        "cached_contributors": [
                            {
                                "contribution": "Narrator",
                                "author": {"name": catalog_state["narrator"]},
                            }
                        ],
                    },
                ]
            }
        }
    if "CatalogSearch(" in query:
        return {
            "data": {
                "search": {
                    "results": {
                        "found": 1,
                        "hits": [
                            {
                                "document": {
                                    "id": 42,
                                    "title": "The Catalog Journey",
                                    "author_names": ["Catalog Author"],
                                    "contribution_types": ["Author"],
                                    "release_year": 2020,
                                }
                            }
                        ],
                    }
                }
            }
        }
    raise HTTPException(400)


@app.post("/fixture/catalog/narrator")
async def set_fixture_narrator(request: Request):
    body = await request.json()
    catalog_state["narrator"] = body["narrator"]
    return {"status": "updated"}


@app.get("/openlibrary/{path:path}")
async def secondary_catalog(path: str):
    if path == "search.json":
        return {
            "numFound": 1,
            "docs": [
                {
                    "key": "/works/OL1W",
                    "title": "The Catalog Journey",
                    "author_name": ["Catalog Author"],
                }
            ],
        }
    if path == "works/OL1W.json":
        return {
            "key": "/works/OL1W",
            "title": "The Catalog Journey",
            "authors": [{"author": {"key": "/authors/OL1A"}}],
            "first_publish_date": "2020",
            "description": "Secondary fixture description",
        }
    if path == "authors/OL1A.json":
        return {"name": "Catalog Author"}
    if path == "works/OL1W/editions.json":
        return {"entries": []}
    raise HTTPException(404)
