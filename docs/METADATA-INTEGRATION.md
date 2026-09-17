# Catalog metadata integration checkpoint

September 17, 2026. This is an implementation contract and evidence record, not completion of S02 or the full PRD.

## Implemented behavior

Hardcover catalog calls use a backend-only Bearer token stored encrypted per user. Tokens are write-only in the API. Account edits increment a generation; an in-flight response from the previous generation cannot be applied. Viewer accounts may configure their own catalog connection and browse; catalog additions require member access, while shared metadata edits/provider matching/preferences require administrator access.

Automatic search selects the configured primary when the user's Hardcover connection is enabled, otherwise Open Library. A failed Hardcover search can return attributed Open Library results with an explicit warning. Explicit provider searches return their own errors. HTTP-200 GraphQL failures, partial/error payloads and malformed responses are not treated as empty successful searches.

The independent adapters use [Hardcover's documented API](https://github.com/hardcoverapp/hardcover-docs/blob/main/src/content/docs/api/Getting-Started.mdx), its [published schema](https://github.com/hardcoverapp/hardcover-docs/blob/main/schema.graphql), and [Open Library search](https://openlibrary.org/dev/docs/api/search) and [book/work APIs](https://openlibrary.org/dev/docs/api/books). API queries and parser fixtures still require live Hardcover account certification; schema inspection is not evidence that an account grants a capability.

Search pages contain 20 results. A selected detail initially loads 50 editions; an administrator can load subsequent pages on demand. Normalized versions remain in the database across pages. A repeated catalog-add operation reuses the existing visible identity without resetting pagination or implicitly refreshing metadata. Concurrent adds are serialized. Queries are targeted, not a catalog harvest.

Author and narrator contributions are distinct. Catalog versions may be ebook, audio, print or unknown; none of those metadata records establishes library ownership. Open Library scans do not automatically turn a print record into an ebook edition. Existing edition identity is preserved when provider evidence changes; contradictory narrator/language/year/identifier evidence is flagged for review. Descriptive/cover-only changes do not create a version or a false identity conflict.

Automatic field resolution chooses accepted source values using the configured primary/field preferences, filling gaps from other accepted sources. Each chosen value records provenance. User-created fields and edited fields are protected, including an intentionally cleared description or cover. Unlocking a field reapplies accepted provider values. Cover choices are restricted to known image hosts and matched-source choices. Metadata changes do not edit Audiobookshelf or files.

Provider references are scoped to the app work. Automatic attachment requires title/author agreement or an existing accepted provider association. Contradictory provider work identity or a provider merge is held for review. Explicit matching requires a preview and confirmation. A private inventory work is never made public merely because metadata was attached. Public catalog versions are visible with their work; inventory-only versions and ownership require library access.

## Cache, budgets and recovery

PostgreSQL stores request caches and provider budgets. Hardcover cache keys include account/generation; public Open Library requests can share public cache entries. The rate-budget key is derived from the credential using the installation key, so two users supplying the same token share its request budget without exposing the token.

Requests are spaced at least 1.1 seconds per budget. Retry-After, exhausted RateLimit buckets and legacy reset headers extend cooldown. Search cache TTL is five minutes; detail TTL is one hour. Transient outages can serve data fetched within seven days with a stale warning. Authentication/permission errors do not use stale success. Explicit refresh refuses stale fallback rather than reporting it as refreshed. Parser failures invalidate the operation's cached responses.

No API database transaction is held over network I/O. Each lookup has a 60-second overall bound in addition to per-request timeouts and response-size limits. Network code refuses redirects and ignores ambient proxy variables. Provider endpoints are operator environment settings, not arbitrary user-entered URLs. `BOOK_HARDCOVER_URL` and `BOOK_OPENLIBRARY_URL` are used by the isolated browser fixture; normal defaults are the official endpoints.

## UI and verification

Search books supports provider selection, paginated results, focused preview and catalog add. Book details show catalog editions/recordings alongside the existing separately permissioned library copies. Metadata provenance, protected edits and cover choices use a collapsed advanced section. Metadata settings provide the private account connection and administrator defaults. Edition language preference orders matching language codes first; it does not rewrite or translate languages.

The 47-test backend suite includes metadata parsing, errors, caching/cooldown, encryption/account isolation, repeated/concurrent imports, protected edits, changed-version review, pagination, private inventory-version visibility and credential-generation fencing. The expanded Playwright journey exercises a synthetic Hardcover HTTP server, actual API/PostgreSQL, catalog search/import, editions and protected refresh, as well as earlier ABS/worker/list flows. Desktop/mobile screenshots were inspected. These fixtures do not certify live Hardcover or ABS scanner behavior.

A read-only live Open Library check returned 20 search results for Frankenstein/Mary Shelley, resolved the returned work and author, and loaded 50 editions with a continuation marker. This verifies that specific search/detail path, not all Open Library formats or records.

Migration 0004 adds accounts, settings, cache/budget and metadata-source records and permits print/unknown catalog versions. Four migrations pass upgrade/downgrade-to-base/upgrade and drift checking on an empty isolated database. Downgrade refuses to discard print/unknown version semantics; restore a pre-upgrade backup for incompatible data.

## Remaining stage work

- Live Hardcover token/scope/query verification and broader provider fixtures, including catalog aliases and merges.
- Automatically targeted secondary enrichment; currently resolution combines sources already explicitly matched. Search fallback is implemented separately.
- Cross-provider edition equivalence, reversible link/merge/unmatch and review resolution. Contradictions are currently held, not automatically repaired.
- Series navigation and richer identifier-based local search; current work detail shows provider series membership.
- More complete cover browsing across large edition sets and provider data-age propagation across multi-request snapshots.
- Complete local list management and later discovery/community lists, external subscriptions and acquisition automation.

No source download, qBittorrent dispatch, filesystem import, external list synchronization or recommendation engine is claimed by this metadata checkpoint. Their PRD scope remains active.
