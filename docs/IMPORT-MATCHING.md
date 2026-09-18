# Catalog matching for inspected downloads

The administrator import review now suggests catalog editions using inspected file metadata. This is the local identity-resolution portion of S04, not source selection or unattended acquisition. It neither downloads files nor marks a book as owned.

## Matching contract

Only media files contribute identity evidence; reviewed companion documents cannot change the recording's identity. EPUB inspection retains each identifier's explicit scheme. Audio inspection retains supported ISBN/ASIN, album/author/narrator, language, year and abridgment tags. PDF/CBZ metadata can produce title suggestions but does not acquire a fabricated edition identifier.

ISBNs are checksum validated. Equivalent ISBN-10 and 978 ISBN-13 values resolve to the same comparison key; 979 identifiers remain ISBN-13. ASINs require an explicit namespace and valid shape. Unlabelled ten-character strings and UUIDs are not promoted to ASINs. The identifier identifies an edition/format, not the abstract work; matching stays within the group's ebook/audio medium. [International ISBN Agency](https://www.isbn-international.org/index.php/node/10), [ISBN conversion](https://www.isbn-international.org/content/isbn-calculator).

A clear match requires exactly one identifier-matching usable catalog version, agreeing embedded title and authors, no contradictory inspected evidence and no pending identity conflict. Audio additionally requires matching narrator evidence. Known language, year or abridgment conflicts block automatic selection. Missing essential evidence, multiple versions sharing an identifier, inconsistent groups and truncated candidate results require review. Titles alone never establish an automatic edition match. Filenames remain grouping hints, not identity assertions.

Candidates come from accepted Hardcover/Open Library catalog sources or matched inventory on an accessible enabled connection. This endpoint is administrator-only and inspection-owner scoped. Canonical work grouping is respected while the chosen version's original work binding remains intact for correction history. No external metadata lookup occurs in this endpoint.

## Review and persistence

`GET /api/organization/inspections/{id}/matches` requires the current `grouping_revision` and returns a paginated report: ten groups by default, at most 25 per request and at most 50 candidates per group. Reports include reasons, conflicts, unknown values, truncation and a content revision tied to the inspection, grouping, candidate identities and matcher version.

The UI shows possible matches and lets the administrator use one clear match or all unselected clear matches on the current page. Bulk selection preserves existing manual choices. Applying a match leaves **complete book** unchecked; identity evidence is not proof that a file is complete. The normal manual book/version search remains available for ambiguous results.

An evidence-based selection includes `match_revision`. Saving recomputes the report and rejects stale evidence or a receipt used for a different version. The immutable plan stores the report under `matching_evidence`, keyed by import group ID. Changing a version, author, provider-conflict state, accepted source or candidate set requires another review. Group changes invalidate the receipt too. Explicit manual selections remain supported without an automatic-match receipt.

Publication continues through the existing version/source/configuration validation and ABS confirmation. A saved match or completed torrent never establishes ownership. ISBN aliases, including `isbn_10` and `isbn_13`, are normalized for the initial OPF export. No database migration is required: matching evidence is an additive frozen-document field, and older plans remain readable.

## Verification and limits

- Unit coverage exercises identifier normalization, scheme validation, real EPUB/audio inspection, companion exclusion and conflicting title/author/narrator/language/year/abridgment evidence.
- PostgreSQL/API coverage exercises deterministic reports, frozen evidence, stale/forged receipts, provider withdrawal/conflicts, duplicate identifiers, canonical works, candidate limits, pagination, inspection ownership and member denial.
- The browser journey applies a page of clear matches, verifies completeness remains unchecked, saves a held plan, confirms completeness, persists evidence and reloads the saved plan. It retains the manual matching flow and checks mobile overflow.
- The native ABS EPUB workflow seeds a synthetic catalog edition, resolves it through the matching API, publishes through the worker, confirms actual ABS ownership and repeats inventory/import without creating another version. Catalog seeding does not certify a live Hardcover API.

Broader source-to-catalog resolution, multi-author tag conventions, metadata-poor media, verified omnibus coverage and the complete international/format corpus remain unfinished. Ambiguous files have a manual review path; this checkpoint does not complete S04 or authorize list automation.
