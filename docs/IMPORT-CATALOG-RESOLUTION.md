# Catalog resolution before automatic import

An approved automatic import can now resolve an edition that is missing from the local catalog. The worker searches the requester's configured catalog, loads edition metadata, attaches a qualifying source through the existing provenance resolver, and resumes the same automatic importer. This replaces the earlier requirement to add every edition manually before a qualifying acquisition could proceed.

## When a lookup runs

The completed files must already pass the automatic import's manifest and completeness checks. One unresolved group must have valid embedded identifiers and title/author evidence agreeing with the requested work. An existing conflicting identifier match, ambiguous local identity, unsupported content or additional collection title is not bypassed by trying another provider.

**Metadata → Advanced provider preferences → Look up missing editions before automatic import** controls this behavior and defaults on. It is separate from secondary description/cover enrichment. A destination still requires its own automatic-import approval; the metadata setting cannot start downloads or authorize a different library.

Hardcover uses the original requester's enabled catalog account, never another household member's token. Public Open Library is available for ebooks; it does not establish recording identity. The configured primary goes first among providers capable of the requested medium. A provider failure or no compatible result can use the other capable provider. An ambiguous or explicitly rejected match stays for review.

## Evidence and bounds

The resolver reuses the existing [Hardcover catalog adapter](METADATA-INTEGRATION.md) and [Open Library work/edition API](https://openlibrary.org/dev/docs/api/books). It uses accepted work links where available; otherwise a bounded search must yield one matching title/author identity with no unobserved search pages. Provider detail is checked independently of search results.

Up to ten pages of fifty editions are inspected per provider. Lookup stops for review if more remain, the work redirects, or the provider changes identity/edition evidence during pagination. The complete bounded edition set must contain one compatible identifier match, including the existing language, narrator, year and abridgment checks. A title match, a tracker format label or an Open Library scan never turns an unknown/print edition into an ebook or recording.

Validated provider editions use the existing source attachment, metadata precedence and protected-edit rules. The local file matcher then runs again before freezing the import plan. Exact identifier candidates now precede title-only suggestions, so a fifty-candidate display limit cannot hide the requested edition. If identifier candidates themselves exceed that limit, uniqueness is not asserted. Duplicate identifiers still require review.

## Jobs, authority and recovery

`metadata.resolve-import` is a durable requester-owned operation linked from the automatic-import record. Its creation and queue insertion commit together. It records input revisions and a run token, releases the database transaction during provider I/O, then rechecks route approval, requester/reviewer authority, active reasons, inspection/grouping, work identity, accepted/rejected sources, catalog account generation, endpoint configuration and preferences.

Result application holds the existing inspection/work and authority locks, plus the catalog-account/preferences locks. Token rotation, disabled lookup, revoked access or a changed identity during the network call leaves the result unapplied. Protected descriptive edits remain protected. A newer execution fences an older response; replay after completion does not attach a second source or submit another torrent.

Provider caches and credential budgets are shared with ordinary catalog browsing. Stale fallback data cannot establish a new match. Transient failures have at most five network attempts and respect provider cooldowns. While the catalog job remains queued/running, automatic-import recovery waits for it rather than repeatedly starting planning. A terminal lookup schedules continuation atomically; lost continuation is repaired by the existing automatic-import scheduler. Exhausted or orphaned lookup work reaches review without resetting its retry budget.

## Evidence and remaining scope

HTTP/PostgreSQL fixtures exercise Hardcover's second edition page, ebook and audio identity, public ebook fallback without borrowed credentials, ambiguous/truncated catalogs, wrong narrator/title, stale results, rate limits and rejected sources. Real temporary-file acquisition workflows exercise missing catalog editions through worker lookup, catalog attachment, source-preserving hardlink publication and fixture ABS confirmation. Mid-lookup token rotation, requester revocation and disabled preferences prevent publication; a quota outage followed by concurrent continuation produces one attachment and one transfer.

These tests do not certify a live Hardcover account or live MAM/qBittorrent acquisition. Lookup without valid embedded identifiers, edition aliases/translations, cross-provider version reconciliation, broader collection/omnibus coverage and full service compatibility remain work under S02–S06. External-list acquisition remains S07. No complete stage gate is implied by this checkpoint.
