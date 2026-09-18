"""Synthetic ABS HTTP endpoint for browser tests; never a compatibility certificate."""

import json
import sys
from email import policy
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from app.adapters.torrent_probe import describe
from app.config import get_settings

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.abs_import_fixture import ScanningBackend  # noqa: E402
from tests.mam_fixture import release_row, search_response  # noqa: E402
from tests.torrent_fixture import torrent_bytes  # noqa: E402

app = FastAPI()
catalog_state = {"narrator": "Sample Narrator"}
backend_state = {"watcher_enabled": True}
qbit_state = {"transfers": {}, "adds": 0}
mam_state = {"cookie": "browser-mam-fixture", "requests": 0}
item = json.loads(
    (Path(__file__).resolve().parents[1] / "tests/fixtures/audiobookshelf-item.json").read_text()
)
scanner = ScanningBackend(get_settings().import_destinations["ebooks"])
scanner.backend_path, scanner.library_id = "/fixture/books", "library-one"


@app.api_route("/qbit/api/v2/{path:path}", methods=["GET", "POST"])
async def qbit_fixture(path: str, request: Request):
    if path == "auth/login":
        credentials = parse_qs((await request.body()).decode())
        if credentials != {
            "username": ["browser-qbit-user"],
            "password": ["browser-qbit-password"],
        }:
            raise HTTPException(401)
        response = Response(status_code=204)
        response.set_cookie("SID", "browser-qbit-session", httponly=True)
        return response
    if request.cookies.get("SID") != "browser-qbit-session":
        raise HTTPException(403)
    if path == "app/version":
        return PlainTextResponse("v5.2.3")
    if path == "app/webapiVersion":
        return PlainTextResponse("2.15.1")
    if path == "torrents/add":
        message = BytesParser(policy=policy.default).parsebytes(
            ("Content-Type: " + request.headers["content-type"] + "\r\n\r\n").encode()
            + await request.body()
        )
        fields = {
            part.get_param("name", header="content-disposition"): part.get_payload(decode=True)
            for part in message.iter_parts()
        }
        descriptor = describe(fields["torrents"])
        digest = descriptor["infohash_v1"]
        if digest in qbit_state["transfers"]:
            raise HTTPException(409, "Duplicate synthetic add")
        qbit_state["adds"] += 1
        qbit_state["transfers"][digest] = {
            "row": {
                "hash": digest,
                "save_path": fields["savepath"].decode(),
                "tags": fields["tags"].decode(),
                "category": fields["category"].decode(),
                "auto_tmm": False,
                "state": "downloading",
                "amount_left": 18,
                "total_size": descriptor["content_bytes"],
                "progress": 0.25,
            },
            "descriptor": descriptor,
        }
        return PlainTextResponse("Ok.")
    if path == "torrents/info":
        return [
            value["row"]
            for digest, value in qbit_state["transfers"].items()
            if (not request.query_params.get("hashes") or request.query_params["hashes"] == digest)
            and (
                not request.query_params.get("tag")
                or request.query_params["tag"] == value["row"]["tags"]
            )
        ]
    if path in {"torrents/properties", "torrents/files"}:
        value = qbit_state["transfers"].get(request.query_params.get("hash"))
        if not value:
            raise HTTPException(404)
        descriptor = value["descriptor"]
        if path.endswith("properties"):
            return {
                "save_path": value["row"]["save_path"],
                "infohash_v1": descriptor["infohash_v1"],
                "infohash_v2": descriptor["infohash_v2"] or "",
            }
        return [
            {
                "index": item["index"],
                "name": item["path"],
                "size": item["size_bytes"],
                "priority": 1,
                "progress": 0.25,
            }
            for item in descriptor["files"]
        ]
    raise HTTPException(404, "Unknown synthetic downloader operation")


@app.api_route("/mam/{path:path}", methods=["GET", "POST"])
async def mam_fixture(path: str, request: Request):
    if request.cookies.get("mam_id") != mam_state["cookie"]:
        raise HTTPException(401)
    mam_state["requests"] += 1
    mam_state["cookie"] = f"browser-mam-rotated-{mam_state['requests']}"
    if path == "tor/download.php/fixture-private-download-token":
        if dict(request.query_params) not in ({"tid": "501"}, {"tid": "502"}):
            raise HTTPException(400)
        content = (
            torrent_bytes(name=b"The Next Harbor", files=[{b"length": 24, b"path": [b"book.epub"]}])
            if request.query_params["tid"] == "502"
            else torrent_bytes()
        )
        response = Response(content, media_type="application/x-bittorrent")
        response.set_cookie("mam_id", mam_state["cookie"], httponly=True)
        return response
    if path == "jsonLoad.php":
        body = {"uid": 99, "username": "Synthetic MAM account"}
    elif path == "tor/js/loadSearchJSONbasic.php":
        query = await request.json()
        body = (
            {"error": "Nothing returned, out of 0"}
            if query["tor"].get("text") == "No source matches"
            else search_response()
        )
        if query["tor"].get("id") == 502 or query["tor"].get("text") == "The Next Harbor":
            body = search_response(
                data=[
                    release_row(
                        id=502,
                        title="The Next Harbor",
                        main_cat=14,
                        filetype="EPUB",
                        narrator_info="{}",
                        catname="Ebooks - Fiction",
                    )
                ]
            )
    else:
        raise HTTPException(404)
    response = JSONResponse(body)
    response.set_cookie("mam_id", mam_state["cookie"], httponly=True)
    return response


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
                "disableWatcher": not backend_state["watcher_enabled"],
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
        return {
            "results": [
                {"id": row["id"], "updatedAt": 1} for row in [item, *scanner.items.values()]
            ],
            "total": 1 + len(scanner.items),
        }
    if path == "api/items/batch/get":
        body = await request.json()
        records = {item["id"]: item, **scanner.items}
        return {"libraryItems": [records[key] for key in body["libraryItemIds"]]}
    if path == f"api/items/{item['id']}":
        return item
    if path == "api/libraries/library-one/scan":
        scanner.scan()
        return {}
    if path.startswith("api/items/") and path.split("/")[-1] in scanner.items:
        return scanner.items[path.split("/")[-1]]
    raise HTTPException(404)


@app.post("/fixture/scan")
async def fixture_watch():
    scanner.scan()
    return {"items": len(scanner.items)}


@app.post("/fixture/watcher")
async def fixture_watcher(request: Request):
    body = await request.json()
    backend_state["watcher_enabled"] = body["enabled"] is True
    return backend_state


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
                        "isbn_13": "9781234567897",
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


@app.get("/prowlarr/{path:path}")
async def prowlarr_fixture(path: str, request: Request):
    from tests.prowlarr_fixture import indexer, release

    if request.headers.get("x-api-key") != "browser-prowlarr-key":
        raise HTTPException(401)
    if path == "api/v1/system/status":
        return {"version": "2.3.0-fixture"}
    if path == "api/v1/indexer":
        return [
            indexer(),
            indexer(id=8, name="Unavailable tracker"),
            indexer(id=9, name="NZB books", protocol="usenet"),
            indexer(id=10, name="MAM duplicate", definitionName="MyAnonamouse"),
        ]
    if path == "api/v1/search":
        identifier = int(request.query_params["indexerIds"])
        if identifier == 8:
            raise HTTPException(503, "Synthetic source outage")
        return [
            release(
                indexerId=identifier,
                indexer="NZB books" if identifier == 9 else "Book tracker",
                title="Prowlarr browser audiobook" if identifier == 7 else "Unsupported NZB book",
                protocol="usenet" if identifier == 9 else "torrent",
                downloadUrl=f"http://127.0.0.1:13379/prowlarr/{identifier}/download?apikey=browser-prowlarr-key&link=private_fixture&file=book",
            )
        ]
    if path == "7/download":
        if request.query_params.get("link") != "private_fixture":
            raise HTTPException(404)
        return Response(torrent_bytes(), media_type="application/x-bittorrent")
    raise HTTPException(404)


shelf_state = {"version": 1, "mode": "normal"}


@app.post("/goodreads/control")
async def shelf_control(request: Request):
    body = await request.json()
    shelf_state.update(body)
    return shelf_state


@app.get("/goodreads/rss")
async def shelf_fixture(request: Request):
    from xml.sax.saxutils import escape

    if shelf_state["mode"] == "outage":
        return Response(status_code=503)
    etag = f'"shelf-{shelf_state["version"]}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    titles = [(100, "Goodreads Shelf Arrival"), (101, "Goodreads Next Read")]
    if shelf_state["mode"] == "omission":
        titles = titles[1:]
    if shelf_state["mode"] == "addition":
        titles.append((102, "Goodreads Later Addition"))
    items = "".join(
        f"<item><book_id>{titles_id}</book_id><title>{escape(title)}</title>"
        "<author_name>Fixture Shelf Author</author_name></item>"
        for titles_id, title in titles
    )
    return Response(
        '<rss version="2.0"><channel><title>Fixture shelf</title>'
        "<link>https://www.goodreads.com/review/list/123</link>" + items + "</channel></rss>",
        media_type="application/rss+xml",
        headers={"ETag": etag},
    )
