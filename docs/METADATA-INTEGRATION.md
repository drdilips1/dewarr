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

Administrators can remove a catalog match and review changed recording/edition evidence through reversible corrections. See [Identity corrections](IDENTITY-CORRECTIONS.md) for the journal, stale-state checks and immutable asset-version behavior.

## Automatic secondary enrichment

With Hardcover as the selected primary, importing or refreshing a book schedules a durable Open Library lookup when description, original publication year or cover is missing and not protected. The default is enabled; Advanced provider preferences can disable it. Catalog addition returns without waiting for the secondary network lookup. Existing explicitly matched secondary sources already participate in resolution and do not trigger another automatic search.

The lookup uses one bounded title/author search page, requires a unique normalized title-and-author match, then independently validates the selected detail response. Incomplete search pages, ambiguous candidates, changed identity or conflicting known work languages require review. It does not infer recording identity from Open Library, search every edition, or automatically fill work language from an arbitrary edition. The validated secondary source then supplies missing fields through the existing provenance/lock resolver; valid primary values remain preferred unless the administrator explicitly configured a field override.

Jobs are enqueued in the catalog transaction. Repeated imports coalesce by owner and input fingerprint. Each execution claims a run token, releases the database transaction for network I/O, then rechecks current user authority, source identity, work identity and provider preferences before committing. Newer executions fence older responses. A rejected secondary source suppresses automatic reattachment. Changed settings or permissions cancel the pending application of results; protected field edits remain protected.

Transient failures use bounded queue retries and respect provider cooldown delays. Parser failures clear affected cache entries. Stale fallback responses remain useful for browsing but cannot establish a new automatic source association. Terminal or orphaned queue work exposes an explicit retry when the book still qualifies; a queued/live job is reused. Status is visible to the initiating user in book metadata and Activity without exposing another account's operation. This workflow performs public metadata reads and app-catalog writes only.

## Cache, budgets and recovery

Approved automatic imports can also perform a separate [edition-resolution lookup](IMPORT-CATALOG-RESOLUTION.md) when an inspected book has valid embedded identifiers but no matching local edition. This uses the original requester's catalog connection, complete bounded edition pages and the existing file matcher. Its advanced preference is independent of secondary work-field enrichment; both default on. New catalog metadata still establishes neither file completeness nor ownership.

PostgreSQL stores request caches and provider budgets. Hardcover cache keys include account/generation; public Open Library requests can share public cache entries. The rate-budget key is derived from the credential using the installation key, so two users supplying the same token share its request budget without exposing the token.

Requests are spaced at least 1.1 seconds per budget. Retry-After, exhausted RateLimit buckets and legacy reset headers extend cooldown. Search cache TTL is five minutes; detail TTL is one hour. Transient outages can serve data fetched within seven days with a stale warning. Authentication/permission errors do not use stale success. Explicit refresh refuses stale fallback rather than reporting it as refreshed. Parser failures invalidate the operation's cached responses.

No API database transaction is held over network I/O. Each lookup has a 60-second overall bound in addition to per-request timeouts and response-size limits. Network code refuses redirects and ignores ambient proxy variables. Provider endpoints are operator environment settings, not arbitrary user-entered URLs. `BOOK_HARDCOVER_URL` and `BOOK_OPENLIBRARY_URL` are used by the isolated browser fixture; normal defaults are the official endpoints.

## UI and verification

Search books supports provider selection, paginated results, focused preview and catalog add. Book details show catalog editions/recordings alongside the existing separately permissioned library copies. Metadata provenance, protected edits and cover choices use a collapsed advanced section. Metadata settings provide the private account connection and administrator defaults. Edition language preference orders matching language codes first; it does not rewrite or translate languages.

### Unified local and provider search · September 19, 2026

The header opens Search books with independent local and provider requests. Up to six local matches appear with ownership badges and a link to all paginated catalog matches. Local results remain usable while a provider is pending or unavailable. Local predicates cover visible canonical titles and authors, accepted metadata series names, the user's fetched series memberships, valid ISBN-10/ISBN-13 equivalents, ASINs and qualified `hardcover:`/`openlibrary:` work IDs. Queries escape SQL wildcard characters; arbitrary descriptions in source snapshots do not count as series matches. These extra local predicates do not imply identical search capabilities at each remote provider.

Search and preview project accepted provider identities onto accessible canonical works, only when the identity resolves to one visible root. Private or rejected associations and ambiguous multiple roots cannot establish a known-book badge. Same-title results alone do not establish identity. This projection is shared with discovery and does not mutate matches or catalog records. Ownership is freshly derived from the requesting user's accessible ABS holdings; it is never stored in the provider cache. Ebook or audio holdings give the overall In library state while medium, collection and stale detail remains visible.

Known provider results link directly to the existing book. A provider result already represented in the displayed local matches is omitted from the provider section. Other results retain the focused preview; the preview rechecks identity before offering a catalog addition. Unmatched results say Library match not established, rather than asserting that the user lacks the book. Explicit administrator matching remains available in the correction flow. Search submits no acquisition request and changes no external library or files.

The API adds `known_works` to metadata search and optional `work` to preview; existing provider result fields remain. This requires no database migration. Integration coverage includes visibility across merged aliases, rejected evidence, provider namespaces, fresh grants/ownership with cached provider data, ISBN equivalence and series filtering. Browser coverage and exact build evidence are recorded in [Implementation status](IMPLEMENTATION-STATUS.md). Reference-load query performance, live-provider quality and complete S02/AT-04 acceptance remain separate qualification work.

The backend suite includes metadata parsing, errors, caching/cooldown, encryption/account isolation, repeated/concurrent imports, protected edits, changed-version review, pagination, private inventory-version visibility and credential-generation fencing. Secondary-enrichment tests also exercise a real queue worker, transaction rollback, ambiguous/incomplete responses, concurrent claim fencing, in-flight authority changes, rejected-source suppression, retry exhaustion, orphan recovery and provider-directed retry scheduling. Current totals are in [Implementation status](IMPLEMENTATION-STATUS.md).

The expanded Playwright journey exercises synthetic Hardcover/Open Library HTTP servers, actual API/PostgreSQL/worker, automatic gap filling, primary-value preservation, editions, protected refresh and correction undo, alongside earlier ABS/list flows. Desktop/mobile screenshots were inspected. These fixtures do not certify live Hardcover or ABS scanner behavior.

A read-only live Open Library check returned 20 search results for Frankenstein/Mary Shelley, resolved the returned work and author, and loaded 50 editions with a continuation marker. This verifies that specific search/detail path, not all Open Library formats or records.

Migration 0004 adds accounts, settings, cache/budget and metadata-source records and permits print/unknown catalog versions. Migration 0005 adds reversible corrections and explicit edition-source associations. Empty-schema migration round trips and drift checking pass; populated downgrade guards preserve semantics/history. Restore a pre-upgrade backup for incompatible data.

## Remaining stage work

- Live Hardcover token/scope/query verification and broader provider fixtures, including catalog aliases and merges.
- Cross-provider edition equivalence and selective work splitting. Canonical grouping/undo, source unmatch and changed-edition review are implemented, but original source attachment and complete identity reconciliation still need reversible handling. Grouped provider sources retain their original work namespace so refreshing an inherited source preserves edition IDs.
- Broader secondary lookup strategies where justified by identity evidence. The current automatic path deliberately covers targeted Hardcover → Open Library work-field gaps; it does not promise complete recording enrichment or translate metadata languages.
- Broader series/provider search capability and reference-load qualification. Local series/identifier search is implemented above; later series navigation and curation are tracked in [Series catalog](SERIES-CATALOG.md).
- More complete cover browsing across large edition sets and provider data-age propagation across multi-request snapshots.
- Complete local list management and later discovery/community lists, external subscriptions and acquisition automation.

No source download, qBittorrent dispatch, filesystem import, external list synchronization or recommendation engine is claimed by this metadata checkpoint. Their PRD scope remains active.
