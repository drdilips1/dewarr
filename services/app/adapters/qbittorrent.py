"""qBittorrent 5.x transport and observation contract.

Submission is not association or completion. Callers must journal dispatch before
calling submit, then reconcile identity, tag and destination before importing.
No implicit retries, existing-torrent mutations or source-file operations live here.
"""

import asyncio
import base64
import json
import math
import re
from urllib.parse import parse_qs, urlsplit

import httpx
from pydantic import Field

from app.adapters.contracts import (
    AdapterError,
    Capabilities,
    DownloadFile,
    DownloadState,
    FailureKind,
    SubmissionReceipt,
)
from app.adapters.http import configured_url

MAX_RESPONSE = 16 * 1024 * 1024
MAX_ARTIFACT = 16 * 1024 * 1024
READY_STATES = {"uploading", "stalledUP", "queuedUP", "stoppedUP", "forcedUP"}


def hash_value(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", value):
        raise ValueError("Expected a torrent info hash")
    return value.lower()


def validate_attempt_tag(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"book-search:[a-zA-Z0-9_-]{1,80}", value):
        raise ValueError("Expected an application attempt tag")
    return value


def absolute_path(value: str) -> str:
    # The supported deployment contract is a POSIX qBit container. A Windows
    # backend needs an explicit path dialect, not host-dependent normalization.
    if (
        not isinstance(value, str)
        or not value.startswith("/")
        or "\\" in value
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
        or value != value.strip()
        or any(p in {".", "..", ""} for p in value.rstrip("/")[1:].split("/"))
    ):
        raise ValueError("Expected an absolute POSIX download path")
    return value.rstrip("/")


def magnet_hashes(value: str) -> set[str]:
    """Accept one magnet; remote .torrent URLs must be resolved by source adapters."""
    if (
        len(value) > 32768
        or any(ord(c) < 33 or ord(c) == 127 for c in value)
        or not value.startswith("magnet:?")
    ):
        raise ValueError("Expected one magnet URI")
    parts = urlsplit(value)
    if parts.netloc or parts.fragment:
        raise ValueError("Invalid magnet URI")
    identities = set()
    by_kind = {}
    for xt in parse_qs(parts.query, max_num_fields=100).get("xt", []):
        if xt.lower().startswith("urn:btih:"):
            digest = xt[9:]
            if re.fullmatch(r"[a-zA-Z2-7]{32}", digest):
                digest = base64.b32decode(digest.upper()).hex()
            if not re.fullmatch(r"[a-fA-F0-9]{40}", digest):
                raise ValueError("Invalid v1 magnet identity")
            kind = "v1"
        elif xt.lower().startswith("urn:btmh:1220"):
            digest = xt[13:]
            if not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
                raise ValueError("Invalid v2 magnet identity")
            kind = "v2"
        else:
            raise ValueError("Unsupported magnet identity")
        digest = digest.lower()
        if kind in by_kind and by_kind[kind] != digest:
            raise ValueError("Conflicting magnet identities")
        by_kind[kind] = digest
        identities.add(digest)
    if not identities:
        raise ValueError("Magnet has no supported torrent identity")
    return identities


class QbitState(DownloadState):
    infohash_v1: str | None = None
    infohash_v2: str | None = None
    tags: set[str] = Field(default_factory=set)
    category: str
    auto_managed: bool
    progress: float
    total_bytes: int
    all_files_selected: bool
    reported_complete: bool = False

    @property
    def identities(self) -> set[str]:
        # The qBit API key is not necessarily a v1 hash. In particular v2 uses
        # a truncated key; only properties provide the full protocol identity.
        return {value for value in (self.infohash_v1, self.infohash_v2) if value}


def verify_association(
    states: list[QbitState], *, tag: str, hashes: set[str], save_path: str, category: str
) -> QbitState | None:
    """None means not observed, never permission to retry an uncertain submission."""
    tag, save_path = validate_attempt_tag(tag), absolute_path(save_path)
    hashes = {hash_value(value) for value in hashes}
    if not hashes:
        raise ValueError("Association requires artifact identity")
    if not states:
        return None
    if len(states) != 1:
        raise AdapterError(FailureKind.UNCERTAIN, "More than one transfer matches this attempt.")
    state = states[0]
    if (
        tag not in state.tags
        or not hashes.issubset(state.identities)
        or state.save_path != save_path
        or state.category != category
        or state.auto_managed
    ):
        raise AdapterError(
            FailureKind.UNCERTAIN,
            "The existing transfer does not match the recorded attempt and destination.",
        )
    return state.model_copy(update={"association_verified": True})


def integer(value):
    if type(value) is not int or not 0 <= value <= 2**63 - 1:
        raise ValueError("Invalid integer")
    return value


def progress(value):
    if type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("Invalid progress")
    return float(value)


def parse_state(row: dict, properties: dict, files: list) -> QbitState:
    try:
        key = hash_value(row["hash"])
        hashes = []
        for field, length in (("infohash_v1", 40), ("infohash_v2", 64)):
            value = properties[field]
            if value:
                value = hash_value(value)
                if len(value) != length:
                    raise ValueError("Incorrect hash type")
            elif value != "":
                raise ValueError("Invalid missing hash")
            hashes.append(value or None)
        if not any(hashes) or key not in {h[:40] for h in hashes if h}:
            raise ValueError("Inconsistent API key and identity")
        path = absolute_path(row["save_path"])
        if absolute_path(properties["save_path"]) != path:
            raise ValueError("Download moved during observation")
        if not isinstance(row["tags"], str) or not isinstance(row["category"], str):
            raise ValueError("Missing association fields")
        if type(row["auto_tmm"]) is not bool or not isinstance(row["state"], str):
            raise ValueError("Invalid state")
        amount_left, total = integer(row["amount_left"]), integer(row["total_size"])
        completed = progress(row["progress"])
        if not isinstance(files, list) or len(files) > 100000:
            raise ValueError("Invalid file list")
        parsed, names, indexes = [], set(), set()
        all_selected = bool(files)
        for file in files:
            name = file["name"]
            if (
                not isinstance(name, str)
                or name.startswith("/")
                or "\\" in name
                or ":" in name
                or any(ord(c) < 32 or ord(c) == 127 for c in name)
                or any(part in {".", "..", ""} for part in name.split("/"))
            ):
                raise ValueError("Unsafe file path")
            index = integer(file["index"])
            if name in names or index in indexes:
                raise ValueError("Duplicate file")
            names.add(name)
            indexes.add(index)
            priority = integer(file["priority"])
            if priority not in {0, 1, 6, 7}:
                raise ValueError("Unknown file priority")
            all_selected &= priority != 0
            parsed.append(
                DownloadFile(
                    relative_path=name,
                    size_bytes=integer(file["size"]),
                    complete=progress(file["progress"]) == 1,
                )
            )
        reported_complete = (
            row["state"] in READY_STATES
            and completed == 1
            and amount_left == 0
            and total > 0
            and all_selected
            and all(f.complete for f in parsed)
        )
        return QbitState(
            reported_complete=reported_complete,
            external_id=key,
            state=row["state"],
            completed=(reported_complete and sum(f.size_bytes for f in parsed) == total),
            save_path=path,
            files=parsed,
            infohash_v1=hashes[0],
            infohash_v2=hashes[1],
            tags={tag.strip() for tag in row["tags"].split(",") if tag.strip()},
            category=row["category"],
            auto_managed=row["auto_tmm"],
            progress=completed,
            total_bytes=total,
            all_files_selected=all_selected,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise AdapterError(
            FailureKind.PARSER, "qBittorrent returned incomplete or inconsistent transfer evidence."
        ) from error


class QbitClient:
    def __init__(self, base_url: str, username: str, password: str, *, transport=None):
        endpoint = configured_url(base_url)
        origin = urlsplit(endpoint)
        self._username, self._password = username, password
        self._authenticated = False
        self._capabilities = None
        self.client = httpx.AsyncClient(
            base_url=endpoint + "/api/v2/",
            headers={
                "Origin": f"{origin.scheme}://{origin.netloc}",
                "Referer": endpoint + "/",
                "User-Agent": "BookSearch/0.1",
            },
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(30, connect=10),
            transport=transport,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.client.aclose()

    async def _request(self, method, path, *, mutating=False, **kwargs):
        try:
            async with (
                asyncio.timeout(45),
                self.client.stream(method, path, **kwargs) as response,
            ):
                status = response.status_code
                if status in {401, 403}:
                    self._authenticated = False
                    raise AdapterError(
                        FailureKind.AUTHENTICATION,
                        "qBittorrent rejected authentication or access. Check the connection.",
                    )
                if mutating and status in {400, 415}:
                    raise AdapterError(
                        FailureKind.PARSER, "qBittorrent rejected the torrent input."
                    )
                if 300 <= status < 400:
                    raise AdapterError(
                        FailureKind.UNCERTAIN if mutating else FailureKind.ROUTE,
                        "qBittorrent redirected the operation. Check its final URL and reconcile.",
                    )
                if status == 404 and not mutating:
                    raise AdapterError(FailureKind.NOT_FOUND, "qBittorrent resource was not found.")
                accepted = {200, 202} if mutating else {200}
                if path == "auth/login":
                    accepted.add(204)
                if status not in accepted:
                    raise AdapterError(
                        FailureKind.UNCERTAIN if mutating else FailureKind.UNAVAILABLE,
                        "Submission was not confirmed. Reconcile before submitting again."
                        if mutating
                        else "qBittorrent could not complete the request.",
                    )
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_RESPONSE:
                        raise AdapterError(
                            FailureKind.UNCERTAIN if mutating else FailureKind.PARSER,
                            "qBittorrent response exceeded the size limit.",
                        )
                return status, bytes(content)
        except (httpx.HTTPError, TimeoutError) as error:
            raise AdapterError(
                FailureKind.UNCERTAIN if mutating else FailureKind.ROUTE,
                "qBittorrent submission outcome is unknown. Reconcile before submitting again."
                if mutating
                else "qBittorrent could not be reached.",
            ) from error

    async def _login(self):
        if self._authenticated:
            return
        status, result = await self._request(
            "POST", "auth/login", data={"username": self._username, "password": self._password}
        )
        if not (status == 204 and not result) and result.strip() != b"Ok.":
            raise AdapterError(FailureKind.AUTHENTICATION, "qBittorrent login was not accepted.")
        self._authenticated = True

    async def capabilities(self) -> Capabilities:
        if self._capabilities:
            return self._capabilities
        await self._login()
        _, raw = await self._request("GET", "app/version")
        if not re.fullmatch(rb"v?5\.\d+\.\d+(?:[a-zA-Z0-9.+-]*)?", raw.strip()):
            raise AdapterError(FailureKind.UNSUPPORTED, "This adapter requires qBittorrent 5.x.")
        _, api = await self._request("GET", "app/webapiVersion")
        if not re.fullmatch(rb"2\.\d+\.\d+", api.strip()):
            raise AdapterError(FailureKind.UNSUPPORTED, "Unsupported qBittorrent Web API.")
        self._capabilities = Capabilities(
            version=raw.strip().decode(),
            operations={"submit", "find", "status", "files"},
            protocols={"torrent"},
            limitations=["POSIX paths; actual server compatibility requires certification."],
        )
        return self._capabilities

    async def _json(self, path, **params):
        await self._login()
        _, raw = await self._request("GET", path, params=params)
        try:
            return json.loads(raw)
        except (ValueError, UnicodeError) as error:
            raise AdapterError(
                FailureKind.PARSER, "qBittorrent returned unreadable data."
            ) from error

    async def _rows(self, **params):
        value = await self._json("torrents/info", limit=3, **params)
        if (
            not isinstance(value, list)
            or len(value) > 2
            or any(not isinstance(row, dict) for row in value)
        ):
            raise AdapterError(FailureKind.PARSER, "qBittorrent returned an invalid match set.")
        return value

    async def _observe(self, row):
        try:
            key = hash_value(row["hash"])
        except (KeyError, ValueError) as error:
            raise AdapterError(
                FailureKind.PARSER, "qBittorrent returned an invalid key."
            ) from error
        properties = await self._json("torrents/properties", hash=key)
        files = await self._json("torrents/files", hash=key)
        return parse_state(row, properties, files)

    async def find(self, *, attempt_tag: str, torrent_hash: str | None) -> list[QbitState]:
        tag = validate_attempt_tag(attempt_tag)
        digest = hash_value(torrent_hash) if torrent_hash else None
        # Query separately: combining filters would hide a hash collision with an
        # unrelated untagged transfer. Full v2 identity is checked via properties.
        rows = await self._rows(tag=tag)
        if digest:
            rows += await self._rows(hashes=digest[:40])
        result = {}
        for row in rows:
            if isinstance(row.get("hash"), str) and row["hash"].lower() in result:
                continue
            state = await self._observe(row)
            if tag in state.tags or (digest and digest in state.identities):
                result[state.external_id] = state
            else:
                raise AdapterError(FailureKind.PARSER, "qBittorrent returned an unrelated match.")
        return list(result.values())

    async def status(self, external_id: str) -> QbitState:
        key = hash_value(external_id)
        rows = await self._rows(hashes=key)
        if not rows:
            raise AdapterError(FailureKind.NOT_FOUND, "The recorded transfer is no longer visible.")
        if len(rows) != 1:
            raise AdapterError(
                FailureKind.PARSER, "qBittorrent returned multiple transfer records."
            )
        state = await self._observe(rows[0])
        if state.external_id != key:
            raise AdapterError(FailureKind.PARSER, "qBittorrent returned a different transfer.")
        return state

    async def submit(
        self,
        artifact: bytes | str,
        *,
        attempt_tag: str,
        save_path: str,
        category: str = "book-search",
    ) -> SubmissionReceipt:
        tag, path = validate_attempt_tag(attempt_tag), absolute_path(save_path)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", category):
            raise ValueError("Use one simple download category")
        fields = {
            "tags": tag,
            "category": category,
            "savepath": path,
            "autoTMM": "false",
            "skip_checking": "false",
            "stopped": "false",
            "contentLayout": "Original",
        }
        kwargs = {"data": fields}
        if isinstance(artifact, str):
            magnet_hashes(artifact)
            fields["urls"] = artifact
        elif isinstance(artifact, bytes) and 0 < len(artifact) <= MAX_ARTIFACT:
            kwargs["files"] = {"torrents": ("book.torrent", artifact, "application/x-bittorrent")}
        else:
            raise ValueError("Expected one bounded torrent artifact")
        await self.capabilities()
        await self._login()
        status, result = await self._request("POST", "torrents/add", mutating=True, **kwargs)
        if status == 200 and result.strip() == b"Ok.":
            return SubmissionReceipt()
        # 5.2.3 uses a structured acknowledgement. Earlier 5.x returns Ok.
        # Neither form establishes ownership or a confirmed client association.
        try:
            receipt = json.loads(result)
            success = integer(receipt["success_count"])
            pending = integer(receipt["pending_count"])
            failed = integer(receipt["failure_count"])
            ids = receipt["added_torrent_ids"]
            if (
                failed != 0
                or success + pending != 1
                or not isinstance(ids, list)
                or len(ids) != success
                or any(len(hash_value(key)) != 40 for key in ids)
                or (pending == 1) != (status == 202)
            ):
                raise ValueError("Unexpected single-artifact receipt")
            return SubmissionReceipt(
                external_ids=[key.lower() for key in ids], pending=bool(pending)
            )
        except (ValueError, KeyError, TypeError) as error:
            raise AdapterError(
                FailureKind.UNCERTAIN,
                "qBittorrent did not confirm submission. Reconcile before submitting again.",
            ) from error
