"""Bounded, offline torrent inspection. No libtorrent network session is created."""

import asyncio
import json
import sys
from contextlib import suppress

from pydantic import BaseModel, ConfigDict, Field

from app.adapters.contracts import AdapterError, FailureKind

MAX_TORRENT_BYTES = 8 * 1024 * 1024
MAX_FILES = 10000
MAX_RESULT_BYTES = 8 * 1024 * 1024
PROBE_TIMEOUT = 15


class TorrentFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int = Field(ge=0)
    path: str = Field(min_length=1, max_length=2048)
    size_bytes: int = Field(ge=0)


class TorrentDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    infohash_v1: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    infohash_v2: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    private: bool
    content_bytes: int = Field(ge=1)
    torrent_bytes: int = Field(ge=1)
    padding_bytes: int = Field(ge=0)
    files: list[TorrentFile] = Field(min_length=1, max_length=MAX_FILES)
    parser: str


async def inspect_torrent(data: bytes) -> TorrentDescriptor:
    if not data or len(data) > MAX_TORRENT_BYTES:
        raise AdapterError(
            FailureKind.PARSER, "Torrent metadata is empty or exceeds the size limit."
        )
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "app.adapters.torrent_probe",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        async with asyncio.timeout(PROBE_TIMEOUT):
            output, _ = await process.communicate(data)
        if process.returncode != 0 or len(output) > MAX_RESULT_BYTES:
            raise ValueError("Probe failed")
        result = json.loads(output)
        if not isinstance(result, dict):
            raise ValueError("Unexpected probe response")
        if result.get("error"):
            raise AdapterError(FailureKind.PARSER, result["error"])
        return TorrentDescriptor.model_validate(result)
    except (ValueError, TypeError) as error:
        raise AdapterError(
            FailureKind.PARSER, "Torrent metadata could not be validated."
        ) from error
    except TimeoutError as error:
        raise AdapterError(FailureKind.TIMEOUT, "Torrent metadata inspection timed out.") from error
    finally:
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
        await process.wait()
