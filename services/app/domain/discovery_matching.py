"""Read-only matching of Goodreads collection identities to Hardcover records."""

from app.domain.hardcover_matching import MatchEvidence, matching_title
from app.importing.match_evidence import catalog_identifiers


def evidence_for(entry):
    # Goodreads appends series membership to titles. Only remove a single numbered
    # membership label; ranges, boxed sets, and meaningful subtitles remain intact.
    title = matching_title(entry.title)
    return MatchEvidence(
        title=title,
        authors=entry.authors,
        identifiers=sorted(catalog_identifiers(entry.identifiers)),
    )


async def resolve_entry(entry, call):
    """Resolve presentation only; never persist a catalog/ownership binding.

    Search can contain thousands of unrelated sequel hits. Verify exact title and
    author candidates from its bounded first page against full canonical records.
    Conflicting candidates remain choices instead of guessing a catalog identity.
    """
    from app.domain.hardcover_matching import MatchResult, compatible, lookup

    evidence = evidence_for(entry)
    if evidence.identifiers:
        return await lookup(evidence, call)
    if not evidence.authors:
        return MatchResult(reason="An author or ISBN is needed to identify this book.")
    page, stale, _ = await call("search", f"{evidence.title} {evidence.authors[0]}", 1, None)
    if stale:
        return MatchResult(reason="Hardcover results are stale. Retry book details shortly.")
    candidates = [b for b in page.items if compatible(evidence, b)]
    if not candidates or len(candidates) > 4:
        return MatchResult(candidates=page.items[:8], reason="Choose the matching Hardcover book.")
    matches = {}
    for candidate in candidates:
        seen = set()
        for _ in range(4):
            key = candidate.canonical_id or candidate.external_id
            if key in seen:
                return MatchResult(reason="Hardcover's book identity needs review.")
            seen.add(key)
            candidate, stale, _ = await call("fetch", key)
            if stale or candidate.external_id != key or not compatible(evidence, candidate):
                return MatchResult(reason="Hardcover details do not confirm this title and author.")
            if candidate.canonical_id in (None, key):
                matches[key] = candidate
                break
        else:
            return MatchResult(reason="Hardcover's book identity needs review.")
    if len(matches) != 1:
        return MatchResult(candidates=list(matches.values()), reason="Choose the matching edition.")
    return MatchResult(
        book=next(iter(matches.values())),
        status="matched",
        basis="discovery-title-author",
        reason="Title and author verified against the full Hardcover book record.",
    )
