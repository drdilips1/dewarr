"""Synthetic ABS HTTP endpoint for browser tests; never a compatibility certificate."""

import json
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException

app = FastAPI()
item = json.loads(
    (Path(__file__).resolve().parents[1] / "tests/fixtures/audiobookshelf-item.json").read_text()
)


@app.api_route("/abs/{path:path}", methods=["GET", "POST"])
async def endpoint(path: str, authorization: str = Header(default="")):
    if authorization != "Bearer browser-abs-fixture-token":
        raise HTTPException(401)
    if path == "api/authorize":
        return {
            "user": {"id": "fixture-user", "type": "user", "permissions": {}},
            "serverVersion": "2.36.1",
        }
    if path == "api/libraries":
        return {"libraries": [{"id": "library-one", "name": "Fixture books", "mediaType": "book"}]}
    if path == "api/libraries/library-one/items":
        return {"results": [{"id": item["id"], "updatedAt": 1}], "total": 1}
    if path == "api/items/batch/get":
        return {"libraryItems": [item]}
    if path == f"api/items/{item['id']}":
        return item
    raise HTTPException(404)
