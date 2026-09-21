"""Evidence-based Hardcover work matching; edition ownership is never inferred."""

import re
import unicodedata

from pydantic import BaseModel, Field

from app.adapters.catalog_types import BookData
from app.adapters.contracts import AdapterError, FailureKind
from app.domain.catalog_language import catalog_language
from app.domain.catalog_titles import display_title, distinct_work_subtitle
from app.importing.match_evidence import catalog_identifiers


class MatchEvidence(BaseModel):
    title: str
    authors: list[str]
    language: str | None = None
    identifiers: list[tuple[str, str]] = Field(default_factory=list)


class MatchResult(BaseModel):
    book: BookData | None = None
    candidates: list[BookData] = Field(default_factory=list)
    status: str = "unmatched"
    basis: str | None = None
    reason: str = "No confident Hardcover match was found."


def words(value):
    value = unicodedata.normalize("NFKD", value.casefold())
    return " ".join(
        re.findall(r"[^\W_]+", "".join(c for c in value if not unicodedata.combining(c)))
    )


def authors_key(values):
    return {words(value).replace(" ", "") for value in values if words(value)}


SERIES_SUFFIX = re.compile(r"\s*\(([^()#]+?),?\s+#(\d+(?:\.\d+)?)\)\s*$")


def matching_title(value):
    # A single Goodreads series membership is not part of the book title.
    # Ranges/sets and unnumbered parentheses remain identity-bearing text.
    return SERIES_SUFFIX.sub("", value).strip()


def title_parts(value):
    # Only known edition labels are removed. Volume numbers, adaptations, and
    # arbitrary subtitles are not silently erased.
    value = display_title(matching_title(value))
    parts = re.split(r":\s+", value, maxsplit=1)
    return words(parts[0]), words(parts[1]) if len(parts) > 1 else ""


def compatible(evidence, book, *, identified=False):
    left_series = SERIES_SUFFIX.search(evidence.title)
    right_series = SERIES_SUFFIX.search(book.title)
    if (
        left_series
        and right_series
        and (
            words(left_series[1].rstrip(",")) != words(right_series[1].rstrip(","))
            or left_series[2] != right_series[2]
        )
    ):
        return False
    if (
        distinct_work_subtitle(evidence.title) or distinct_work_subtitle(book.title)
    ) and display_title(evidence.title) != display_title(book.title):
        return False
    if re.search(
        r"\b(?:\d+\s+of\s+\d+|dramati[sz](?:ed|ation)|full[ -]cast|adaptation|summary|study guide|"
        r"graphic novel|box set|omnibus)\b",
        evidence.title + " " + book.title,
        re.I,
    ):
        return False
    left, right = title_parts(evidence.title), title_parts(book.title)
    # A missing subtitle colon is punctuation, not a different title.
    complete_title_equal = words(display_title(matching_title(evidence.title))) == words(
        display_title(matching_title(book.title))
    )
    if not complete_title_equal and (
        left[0] != right[0] or (left[1] and right[1] and left[1] != right[1])
    ):
        return False
    a, b = authors_key(evidence.authors), authors_key(book.authors)
    if not a or not b or (not (a & b) if identified else a != b):
        return False
    language = catalog_language(evidence.language)
    if language and book.language and language != catalog_language(book.language):
        return False
    if language and book.editions and not identified:
        languages = {
            catalog_language(edition.language) for edition in book.editions if edition.language
        }
        if languages and language not in languages:
            return False
    return True


async def lookup(evidence, call):
    async def canonical(book):
        seen = set()
        for _ in range(4):
            key = book.canonical_id or book.external_id
            if key in seen:
                return None
            seen.add(key)
            book, stale, _ = await call("fetch", key)
            if stale or book.external_id != key:
                return None
            if book.canonical_id in (None, book.external_id):
                return book
        return None

    if evidence.identifiers:
        page, stale, _ = await call("identifier_search", evidence.identifiers)
        if stale or page.has_more:
            return MatchResult(
                reason="Identifier results were incomplete or stale; review the match."
            )
        if page.items:
            matches = {}
            for candidate in page.items:
                candidate_ids = set().union(
                    *(catalog_identifiers(e.identifiers) for e in candidate.editions)
                )
                if not candidate_ids.intersection(evidence.identifiers):
                    return MatchResult(
                        reason="Hardcover returned an edition without matching identifiers."
                    )
                book = await canonical(candidate)
                if not book or not compatible(evidence, book, identified=True):
                    return MatchResult(
                        reason="Identifiers conflict with the title or author; review the match."
                    )
                language = catalog_language(evidence.language)
                matching_editions = [
                    e
                    for e in candidate.editions
                    if catalog_identifiers(e.identifiers).intersection(evidence.identifiers)
                ]
                if language and any(
                    e.language and catalog_language(e.language) != language
                    for e in matching_editions
                ):
                    return MatchResult(
                        reason="The identified edition has a different language; review the match."
                    )
                if candidate.external_id == book.external_id:
                    known = {edition.external_id for edition in book.editions}
                    book.editions.extend(
                        edition for edition in matching_editions if edition.external_id not in known
                    )
                matches[book.external_id] = book
            if len(matches) == 1:
                return MatchResult(
                    book=next(iter(matches.values())),
                    status="matched",
                    basis="identifier",
                    reason=(
                        "Verified ISBN/ASIN with compatible title and author, "
                        "resolved to the current Hardcover book."
                    ),
                )
            return MatchResult(
                reason="The supplied identifiers point to different books; review the match."
            )
    if not evidence.authors:
        return MatchResult(
            reason="An author or verified identifier is needed to identify this book."
        )
    search_title = display_title(matching_title(evidence.title)).split(":", 1)[0]
    try:
        page, stale, _ = await call("search", f"{search_title} {evidence.authors[0]}", 1, None)
    except AdapterError as error:
        if error.kind != FailureKind.PARSER:
            raise
        # Malformed unrelated search hits must not prevent a bounded title lookup.
        page, stale, _ = await call("title_search", search_title)
    else:
        if not stale and page.has_more:
            page, stale, _ = await call("title_search", search_title)
    if stale or page.has_more:
        return MatchResult(reason="Search results are incomplete; a unique match needs review.")
    candidates = [item for item in page.items if compatible(evidence, item)]
    # A bounded search never fetches every near-match from a broad result set.
    if not candidates or len(candidates) > 4:
        return MatchResult(
            candidates=page.items[:8],
            reason="No unique title-and-author match was found. Review the catalog candidates.",
        )
    matches = {}
    for candidate in candidates:
        book = await canonical(candidate)
        if not book or not compatible(evidence, book):
            return MatchResult(
                reason="The provider’s full book details conflict with the search result."
            )
        matches[book.external_id] = book
    if len(matches) != 1:
        return MatchResult(
            candidates=list(matches.values()),
            reason="More than one Hardcover book fits the title and author; review the match.",
        )
    return MatchResult(
        book=next(iter(matches.values())),
        status="matched",
        basis="title-author",
        reason=(
            "Verified a unique normalized title and author against the full Hardcover book record."
        ),
    )
