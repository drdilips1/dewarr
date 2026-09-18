"""Bounded, inert CSV snapshots. Only explicitly mapped bibliographic fields survive."""

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass

from app.domain.release_profiles import normalized
from app.importing.match_evidence import isbn_key

MAX_BYTES = 4 * 1024 * 1024
MAX_ROWS = 2000
FIELDS = {
    "title": ("title", "book title"),
    "author": ("author", "authors"),
    "goodreads_id": ("book id", "goodreads id"),
    "isbn": ("isbn",),
    "isbn13": ("isbn13", "isbn 13"),
    "shelves": ("bookshelves", "shelves"),
    "exclusive_shelf": ("exclusive shelf",),
}


@dataclass
class Snapshot:
    headers: list[str]
    mapping: dict[str, str]
    records: list[dict]
    duplicates: int
    shelves: list[str]
    needs_mapping: bool = False


def clean(value, length):
    value = " ".join(value.split())
    if len(value) > length or any(ord(c) < 32 for c in value):
        raise ValueError("A mapped field is too long or contains unsupported control characters")
    return value


def identifier(value):
    value = value.strip()
    # Goodreads exports may use Excel's textual-number wrapper. Never evaluate expressions.
    match = re.fullmatch(r'="([0-9Xx\s-]*)"', value)
    return isbn_key(match[1] if match else value)


def fingerprint(record):
    return hashlib.sha256(
        json.dumps(
            [
                normalized(record["title"]),
                sorted(normalized(a) for a in record["authors"]),
                record.get("isbn"),
                record.get("isbn13"),
            ],
            ensure_ascii=False,
        ).encode()
    ).hexdigest()


def parse_snapshot(content, *, mapping=None, encoding="auto", delimiter=","):
    if len(content) > MAX_BYTES:
        raise ValueError("CSV files must be no larger than 4 MiB")
    if encoding not in {"auto", "utf-8-sig", "cp1252"} or delimiter not in {",", ";", "\t"}:
        raise ValueError("Choose a supported CSV encoding and delimiter")
    codec = (
        ("utf-16" if content.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")
        if encoding == "auto"
        else encoding
    )
    try:
        decoded = content.decode(codec, errors="strict")
    except UnicodeError:
        raise ValueError(
            "The file encoding could not be read; try Windows-1252 or export UTF-8"
        ) from None
    if "\x00" in decoded:
        raise ValueError("The file contains NUL bytes; export a supported CSV encoding")
    try:
        reader = csv.reader(io.StringIO(decoded, newline=""), delimiter=delimiter, strict=True)
        headers = [clean(h, 120) for h in next(reader, [])]
        if not headers or len(headers) > 80 or any(not h for h in headers):
            raise ValueError("CSV requires 1–80 named columns")
        folded = [h.casefold() for h in headers]
        if len(set(folded)) != len(folded):
            raise ValueError("CSV column names must be unique")
        if mapping is None:
            mapping = {
                field: headers[folded.index(alias)]
                for field, aliases in FIELDS.items()
                for alias in aliases
                if alias in folded
            }
        if (
            not isinstance(mapping, dict)
            or any(
                key not in FIELDS or not isinstance(value, str) or value not in headers
                for key, value in mapping.items()
            )
            or len(set(mapping.values())) != len(mapping)
        ):
            raise ValueError("Map each supported field to a different existing column")
        records, shelves, seen, duplicates = [], set(), {}, 0
        positions = {key: headers.index(value) for key, value in mapping.items()}
        needs_mapping = "title" not in mapping
        for index, cells in enumerate(reader):
            if index >= MAX_ROWS:
                raise ValueError("CSV snapshots support at most 2,000 rows; split larger exports")
            if not cells or not any(cells):
                continue
            if len(cells) != len(headers):
                raise ValueError(f"CSV row {index + 2} does not match its columns")
            if needs_mapping:
                continue
            values = {key: cells[position] for key, position in positions.items()}
            title = clean(values.get("title", ""), 600)
            author = clean(values.get("author", ""), 300)
            external_id = values.get("goodreads_id", "").strip()
            if not title or (external_id and not re.fullmatch(r"[1-9][0-9]{0,19}", external_id)):
                raise ValueError(
                    f"CSV row {index + 2} needs a title and a valid mapped Goodreads ID"
                )
            row_shelves = sorted(
                {clean(s, 120) for s in values.get("shelves", "").split(",") if s.strip()}
                | (
                    {clean(values["exclusive_shelf"], 120)}
                    if values.get("exclusive_shelf", "").strip()
                    else set()
                )
            )
            shelves.update(row_shelves)
            record = {
                "title": title,
                "authors": [author] if author else [],
                "isbn": identifier(values.get("isbn", "")),
                "isbn13": identifier(values.get("isbn13", "")),
                "external_id": external_id or None,
                "shelves": row_shelves,
                "row_number": index + 2,
            }
            key = f"goodreads:{external_id}" if external_id else f"csv:{fingerprint(record)}"
            record["identity_key"] = key
            if key in seen:
                prior = seen[key]
                if fingerprint(prior) != fingerprint(record):
                    raise ValueError(
                        f"Conflicting CSV rows refer to the same book ID at row {index + 2}"
                    )
                prior["shelves"] = sorted(set(prior["shelves"]) | set(row_shelves))
                duplicates += 1
            else:
                seen[key] = record
                records.append(record)
        return Snapshot(headers, mapping, records, duplicates, sorted(shelves), needs_mapping)
    except csv.Error:
        raise ValueError(
            "The CSV quoting or field size is invalid; check the delimiter and export"
        ) from None
