"""Fill a synced audiobook when Hardcover has no unique match.

A unique ISBN hit is applied. A unique title-and-author hit waits for confirmation.
Two hits stay unconfirmed. An ebook never calls the provider. Empty narrator lists
do not replace narrators that are already known.
"""

import re
from types import SimpleNamespace

from app.domain.hardcover_matching import compatible
from app.domain.release_dates import assign_release

_ISBN = re.compile(r"\d{10}|\d{13}")


def narrators_to_write(existing, incoming):
    if not incoming:
        return None
    return list(incoming)


def agrees(evidence, hit):
    return compatible(
        evidence,
        SimpleNamespace(title=hit.title, authors=hit.authors, language=None, editions=[]),
    )


def evidence_isbn(evidence):
    for kind, value in evidence.identifiers:
        if kind in {"isbn", "isbn13"} and isinstance(value, str) and _ISBN.fullmatch(value):
            return value
    return None


def decide(evidence, hits, *, isbn_query):
    agreed = [hit for hit in hits if agrees(evidence, hit)]
    if isbn_query and len(hits) == 1 and len(agreed) == 1:
        return "apply", agreed[0], hits
    if not isbn_query and len(hits) == 1 and len(agreed) == 1:
        return "confirm", agreed[0], hits
    if hits:
        return "unconfirmed", None, hits[:8]
    return "unmatched", None, []


def candidate_payload(hit):
    return {
        "title": hit.title,
        "authors": hit.authors,
        "narrators": hit.narrators,
        "isbn": hit.isbn,
        "cover_url": hit.cover_url,
        "coming_soon": hit.coming_soon,
    }


def _keep_checked(fields, libro):
    checked = ((fields or {}).get("libro") or {}).get("checked_at")
    if checked:
        libro["checked_at"] = checked
    return libro


def applied_metadata(fields, hit, publication, known_narrators):
    """Title, authors, cover, and ISBN come from the hit. A year-only page does not invent a day."""
    extra = {
        "isbn": hit.isbn,
        "publisher": publication.publisher,
        "series": publication.series,
    }
    updated = assign_release(
        fields,
        publication.date,
        "audiobook" if publication.date else "unknown",
        coming_soon=hit.coming_soon,
        source="librofm",
        extra=extra,
    )
    narrators = narrators_to_write(known_narrators, hit.narrators)
    libro = _keep_checked(
        fields,
        {
            "isbn": hit.isbn,
            "narrators": narrators or [],
            "confirmed": True,
            "candidates": [],
        },
    )
    updated = {**updated, "libro": libro}
    description = publication.description
    return {
        "fields": updated,
        "title": hit.title,
        "authors": hit.authors,
        "cover_url": hit.cover_url,
        "description": description,
        "publication_year": publication.date.year if publication.date else publication.year,
        "narrators": narrators,
        "isbn": hit.isbn,
        "release_date": publication.date,
        "coming_soon": hit.coming_soon,
    }


def candidate_metadata(fields, status, hits):
    updated = dict(fields or {})
    updated["libro"] = _keep_checked(
        fields,
        {
            "confirmed": False,
            "candidates": [candidate_payload(hit) for hit in hits],
            "status": status,
        },
    )
    return updated


async def prepare(evidence, *, medium, search, publication):
    """Resolve a match without writing. An ebook does not call the provider."""
    if medium != "audio":
        return {"status": "skipped", "called": False, "candidates": []}
    isbn = evidence_isbn(evidence)
    query = isbn or f"{evidence.title} {evidence.authors[0] if evidence.authors else ''}".strip()
    hits = await search(query, isbn=bool(isbn))
    action, hit, shown = decide(evidence, hits, isbn_query=bool(isbn))
    if action != "apply" or hit is None:
        return {"status": action, "called": True, "candidates": shown, "hit": hit}
    page = await publication(hit.isbn)
    return {"status": "matched", "called": True, "candidates": [hit], "hit": hit, "page": page}


def field_locked(fields, name):
    entry = ((fields or {}).get("fields") or {}).get(name) or {}
    return isinstance(entry, dict) and bool(entry.get("locked"))


def stage(work, result, known_narrators):
    """Apply a prepared result. Returns the library write, or None when it stays unconfirmed."""
    if result.get("status") == "skipped":
        return None
    if result.get("status") != "matched":
        work.metadata_fields = candidate_metadata(
            work.metadata_fields,
            result.get("status") or "unmatched",
            result.get("candidates") or [],
        )
        return None
    applied = applied_metadata(work.metadata_fields, result["hit"], result["page"], known_narrators)
    if not field_locked(work.metadata_fields, "title"):
        work.title = applied["title"]
    if not field_locked(work.metadata_fields, "authors"):
        work.authors = applied["authors"]
    if applied["cover_url"] and not field_locked(work.metadata_fields, "cover_url"):
        work.cover_url = applied["cover_url"]
    if (
        applied["description"]
        and not getattr(work, "description", None)
        and not field_locked(work.metadata_fields, "description")
    ):
        work.description = applied["description"]
    if (
        applied["publication_year"]
        and applied["release_date"]
        and not field_locked(work.metadata_fields, "publication_year")
    ):
        work.publication_year = applied["publication_year"]
    work.metadata_fields = applied["fields"]
    return applied


async def enrich(
    work, *, medium, evidence, known_narrators, search, publication, write, cover=None
):
    """Search, and write the library item only after a confirmed audiobook match."""
    result = await prepare(evidence, medium=medium, search=search, publication=publication)
    if not result["called"]:
        return result
    applied = stage(work, result, known_narrators)
    if applied:
        await write(
            title=work.title,
            authors=list(work.authors),
            narrators=applied["narrators"],
            cover=None if field_locked(work.metadata_fields, "cover_url") else cover,
        )
        result["release_date"] = applied["release_date"]
    return result
