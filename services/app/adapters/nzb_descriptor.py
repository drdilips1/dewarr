"""Bounded, offline NZB inspection. No Usenet connection is opened."""

import hashlib
import re
from typing import Literal

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from pydantic import BaseModel, ConfigDict, Field

from app.adapters.contracts import AdapterError, FailureKind
from app.adapters.torrent_descriptor import TorrentDescriptor

MAX_NZB_BYTES = 8 * 1024 * 1024
MAX_FILES = 10000


class NzbFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int = Field(ge=0)
    path: str = Field(min_length=1, max_length=2048)
    size_bytes: int = Field(ge=0)


class NzbDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol: Literal["nzb"] = "nzb"
    name: str = Field(min_length=1, max_length=255)
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_bytes: int = Field(ge=0)
    nzb_bytes: int = Field(ge=1)
    files: list[NzbFile] = Field(min_length=1, max_length=MAX_FILES)
    parser: str


def load_descriptor(value):
    if isinstance(value, dict) and value.get("protocol") == "nzb":
        return NzbDescriptor.model_validate(value)
    return TorrentDescriptor.model_validate(value)


def local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def file_name(subject):
    if not isinstance(subject, str) or len(subject) > 2000:
        return None
    quoted = re.search(r'"([^"\r\n]{1,240})"', subject)
    raw = quoted.group(1) if quoted else None
    if raw is None:
        match = re.search(r"([^\s\"']+\.[A-Za-z0-9]{1,8})", subject)
        raw = match.group(1) if match else None
    if not raw:
        return None
    raw = raw.replace("\\", "/").split("/")[-1].strip()
    if (
        not raw
        or raw in {".", ".."}
        or ":" in raw
        or len(raw) > 240
        or any(ord(character) < 32 or ord(character) == 127 for character in raw)
    ):
        return None
    return raw


def folder_name(value, fallback):
    cleaned = "".join(
        character if character.isprintable() and character not in '\\/:*?"<>|' else " "
        for character in (value or fallback)
    )
    cleaned = " ".join(cleaned.split())[:120].strip(" .")
    return cleaned or "release"


def segment_bytes(value):
    if value is None:
        return 0
    if not isinstance(value, str) or not value.isdigit():
        raise AdapterError(FailureKind.PARSER, "NZB segment size could not be read.")
    number = int(value)
    if number > 2**63 - 1:
        raise AdapterError(FailureKind.PARSER, "NZB segment size exceeds the limit.")
    return number


def inspect_nzb(data: bytes) -> NzbDescriptor:
    if not data or len(data) > MAX_NZB_BYTES:
        raise AdapterError(FailureKind.PARSER, "NZB is empty or exceeds the size limit.")
    stripped = data.lstrip(b"\xef\xbb\xbf \t\r\n")
    if not stripped.startswith(b"<"):
        raise AdapterError(FailureKind.PARSER, "NZB metadata could not be validated.")
    try:
        root = ElementTree.fromstring(data)
    except (ElementTree.ParseError, DefusedXmlException) as error:
        raise AdapterError(FailureKind.PARSER, "NZB metadata could not be validated.") from error
    if local(root.tag) != "nzb":
        raise AdapterError(FailureKind.PARSER, "NZB metadata could not be validated.")
    meta_name = None
    found = []
    for child in list(root):
        kind = local(child.tag)
        if kind == "head":
            for meta in child:
                if local(meta.tag) == "meta" and meta.get("type") == "name" and meta.text:
                    meta_name = meta.text.strip()[:300]
        elif kind == "file":
            if len(found) >= MAX_FILES:
                raise AdapterError(FailureKind.PARSER, "NZB lists too many files.")
            name = file_name(child.get("subject") or "")
            if not name:
                continue
            size, segments = 0, 0
            for node in child.iter():
                if local(node.tag) != "segment":
                    continue
                segments += 1
                if segments > 100000:
                    raise AdapterError(FailureKind.PARSER, "NZB lists too many segments.")
                size += segment_bytes(node.get("bytes"))
                if size > 2**63 - 1:
                    raise AdapterError(FailureKind.PARSER, "NZB file size exceeds the limit.")
            if segments:
                found.append((name, size))
    if not found:
        raise AdapterError(FailureKind.PARSER, "NZB does not list any files.")
    folder = folder_name(meta_name, found[0][0].rsplit(".", 1)[0])
    files, seen = [], set()
    for index, (name, size) in enumerate(found):
        path = f"{folder}/{name}"
        if path in seen:
            stem, dot, extension = name.rpartition(".")
            unique = f"{stem}-{index}.{extension}" if dot else f"{name}-{index}"
            path = f"{folder}/{unique}"
        seen.add(path)
        files.append(NzbFile(index=index, path=path, size_bytes=size))
    return NzbDescriptor(
        name=folder,
        artifact_sha256=hashlib.sha256(data).hexdigest(),
        content_bytes=sum(item.size_bytes for item in files),
        nzb_bytes=len(data),
        files=files,
        parser="nzb-xml",
    )
