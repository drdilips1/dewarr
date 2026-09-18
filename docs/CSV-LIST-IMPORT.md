# CSV list snapshots

September 18, 2026. Implements the reviewed CSV snapshot portion of S07-02 / FR-32. This is curation; external-list acquisition policies remain separate unfinished work.

## User workflow

Open an owned list, choose **Import a CSV**, upload an export and preview it. Standard Goodreads column names are mapped automatically. Custom files can map title, author, Goodreads ID, ISBN/ISBN-13 and shelf columns. Title is required; other fields are optional. File-format controls stay collapsed by default.

The preview shows each book, whether it matches an accessible catalog entry, and current library availability for that match. Existing catalog matches require an owner-scoped source binding or an ISBN corroborated by title and author. A title alone does not claim a match to the general catalog. Unknown books become private provisional catalog entries only when imported. CSV IDs and assertions do not create verified provider editions or owned assets.

Select individual rows, all books, or one exported shelf, then import. Shelf filtering alone does not change the selection; the selected count always covers all shelves. Equivalent repeated rows with the same source identity are combined. Conflicting assertions for the same Goodreads ID fail parsing or show an identity conflict to skip and resolve before import.

This is an additive snapshot, not a subscription or authoritative remote shelf replacement. Missing rows never remove existing memberships. “Owned Copies,” ratings, reading dates, reviews and private notes do not establish availability and are not retained. Imported shelf labels remain private preview data unless the user deliberately maps their contents to another field. Neither imports nor shelf labels change reading status or initiate downloads.

Completed receipts survive reload and uncertain browser responses. Replaying a completed import does not re-add a book removed afterward. Uploading a fresh preview is an explicit new addition request. Importing a source-linked book makes its membership local as well; excluding the RSS observation subsequently preserves that local membership. Ordinary removal from the list still uses the existing exclusion/request-reason rules.

## Parsing, privacy and limits

- At most 4 MiB, 2,000 rows and 80 named columns per snapshot. Oversized input is rejected, never silently truncated. Split larger exports before uploading.
- UTF-8 (with or without BOM) and BOM-marked UTF-16 are detected; Windows-1252 can be selected explicitly. Invalid encodings, NUL bytes, malformed quoting, duplicate column names and uneven rows are rejected.
- Comma, semicolon and tab delimiters are supported. CSV parsing uses the standard-library reader with strict quoting and its bounded field-size behavior.
- ISBN numeric text wrappers such as `="9780306406157"` are parsed as inert text and checksum-validated. Expressions are never evaluated. Book titles are rendered as React text, not HTML.
- Original uploads and ignored field values are not stored. Saved previews contain only mapped normalized book/shelf assertions, selected columns, match evidence and source row numbers. Source IDs/bindings and receipts are owner-only even when the resulting list is shared.
- Prepared previews expire after 24 hours; at most ten unsubmitted previews per owner are retained. Starting a new preview evicts older unsubmitted previews beyond that limit. Accepted/completed receipts remain available; the UI shows the ten most recent previews/imports.
- Without an external ID, a fingerprint of the normalized bibliographic assertion only deduplicates repeated owner-specific CSV input; it is not an assertion that every same-titled book or edition is identical.

## Durable commit contract

Preview does not mutate books or list memberships. Starting an import saves the selected row numbers and enqueues `lists.csv` in the same transaction. A preview accepts one immutable selection; different selections require a new preview. Retrying the same selection returns its existing operation or explicitly requeues a failed attempt within the preview lifetime.

The worker locks the list, checks current account authority, then takes the shared identity-graph and owner catalog locks. It resolves every selected identity again before additions. Lost access, changed matching, list deletion or account revocation fails the operation without publishing any books. Repeated concurrent workers refresh their operation after obtaining the lock, so they cannot replay a completed transaction.

All new books, bindings, memberships, the audit event and completed receipt commit together. An interrupted transaction leaves none of those additions; a retry repeats it. Existing canonical memberships are read once under those locks, avoiding a full identity-graph query for every imported row. No downloader or filesystem side effect occurs. The worker reuses visible existing books, preserves canonical grouping and creates no versions or ownership. CSV and Goodreads RSS share compatible owner catalog bindings; source observations and exclusions remain separate records.

## Delivery and evidence

Migration `0026_list_csv` adds `list_csv_imports` and `list_catalog_bindings`. Populated import/binding/operation history refuses lossy downgrade; use a pre-upgrade backup. API and worker must run the same revision. The API exposes preview, owner-only recent/detail resources and durable commit under `/api/lists/{list_id}/csv`.

Unit/API tests cover encodings, malformed/bounded input, mapping, duplicate/conflicting IDs, ignored private fields, subset imports, omissions, replay, atomic queue/worker rollback, expiry, retry repair, retention limits, account isolation, sharing, current availability, catalog changes, list deletion and RSS coexistence. The browser journey uses UTF-16 custom-column input, shelf selection, real API/worker import, saved receipts, repeated import and mobile layout. The maximum 2,000-row snapshot is also exercised against PostgreSQL without truncation; after removing repeated per-row identity-graph queries, its local test completed in about three seconds (not a deployment-wide performance guarantee). Current aggregate results are in [Implementation Status](IMPLEMENTATION-STATUS.md).

Fixtures are synthetic. Goodreads' [export page](https://www.goodreads.com/review/import) requires an account and was not available for live export certification. The parser follows [Python's CSV interface](https://docs.python.org/3.13/library/csv.html); no upstream app implementation was copied. Hardcover lists, complete provider identity reconciliation, larger-list pagination and automatic list acquisition remain unfinished PRD requirements.
