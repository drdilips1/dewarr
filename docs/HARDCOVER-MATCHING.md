# Library metadata matching

Library holdings, editions/recordings, local canonical works, and Hardcover works are separate identities. A saved Hardcover source provides metadata and reader details; it does not prove ownership of any edition listed by the provider.

## Evidence and decisions

- Collect identifiers only from verified, complete, present or stale library assets the reader can access. Never use arbitrary editions returned by catalog browsing as evidence of ownership.
- Validate ISBN checksums and normalize equivalent ISBN-10/ISBN-13 values. Normalize ASIN case and structure. Query Hardcover editions directly by these values rather than treating identifier search text as proof.
- Verify title and author compatibility and edition language. Conflicting identifiers, unrelated credits, or language conflicts require review. Reprint and recording years are not the original work's publication date and do not independently determine identity.
- Without a usable identifier match, normalize punctuation, whitespace, author initials, and known edition labels. Preserve meaningful subtitles and volume numbers. Require a unique compatible author/title result and fetch the full provider record to verify it.
- When broad search is truncated, use a bounded exact-title-prefix GraphQL lookup. Its results must still pass title/author checks. An incomplete result set does not prove uniqueness.
- Follow Hardcover canonical redirects with a hop limit and cycle detection. A lookup response must identify the requested record.
- Partial recordings, dramatizations, adaptations, summaries, and collections are not silently treated as the complete original book.
- Explicit rejection and disabled automatic enrichment prevent automatic matching. Metadata field locks survive successful linking. Evidence and access are rechecked after network I/O and before saving.

`GET /api/metadata/works/{id}/reader-match` is a read-only preview. It returns a reason and evidence basis. `POST /api/metadata/works/{id}/match-hardcover` is an administrator action that saves a verified source and writes an audit event. It never overwrites an existing Hardcover match. The Metadata tab exposes this action alongside explicit manual matching.

## Collection repair

Run `uv run python scripts/match_library_metadata.py` for a read-only report. Add `--apply` to persist only verified links. The command selects owned canonical works, requires a connected administrator (`--user-id` if multiple accounts qualify), respects the provider request budget, and stops on rate limiting. Each result is recorded in `.local/hardcover-match-report.json` (override with `--report`). Rerunning skips existing accepted links. Unmatched books remain available in the library and can be manually matched through Book metadata.

The matching batch does not merge local work records or alter library files, recording details, or library version associations.

After reviewing verified links, `uv run python scripts/consolidate_hardcover_matches.py --apply` reconciles owned duplicates with the same accepted Hardcover ID, the same known language, and identical normalized author credits. It skips rejected/conflicting source families and locked identity fields. This uses the existing reversible, revision-checked merge journal and preserves origin records, library versions, files, and external bindings. Outstanding acquisition reservations can block a merge; those remain in review. Results are written to `.local/hardcover-consolidation-report.json`.

Provider fields are based on Hardcover's [published GraphQL schema](https://github.com/hardcoverapp/hardcover-docs/blob/main/schema.graphql): `editions.isbn_10`, `isbn_13`, `asin`, `book_id`, and `books.canonical_id`.

The book metadata view shows ambiguous candidates directly for comparison. Manual search is prefilled and keeps its state within the metadata view; choosing a record refreshes the saved source and reader details. Full-cast dramatizations (including British `dramatisation` wording) are excluded from original-novel matches.
