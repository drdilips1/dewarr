# Book source search and download preferences

September 18, 2026. Partial S06 implementation; the full PRD remains active.

## User experience

The book page now has a Sources tab. Opening it starts a search when no saved search exists; returning to it loads the user's latest search and continues observing pending work. The book's catalog versions and confirmed library availability stay separate from tracker releases. Wanted-book links carry the request and target through source inspection into the existing release-selection screen.

MAM and eligible Prowlarr indexers contribute to one ranked page. Results retain the source title, raw title, author, narrator, medium, reported formats, bytes and seed count. MAM descriptions, series, tags and media information remain available under original release details. Unknown values stay unknown. Each source shows its own progress, observation time and error; an outage does not erase successful siblings. Native MAM overlap is excluded through the existing Prowlarr capability rules.

Balanced preferences require no configuration: EPUB leads ebook formats, M4B leads audio formats, and MAM leads sources. The default ordered comparison is format, source, then seed count. Users can save private named profiles, reorder those criteria and preferred formats/sources, block formats, and optionally cap total transfer size. Advanced format controls stay collapsed. Explanations show the applied preferences and missing evidence.

Profiles affect the current source comparison and the selected acquisition. They do not yet inherit from account, request or list defaults. An edited profile receives a new generation; historical searches and selections retain their original snapshot. Selecting with an obsolete saved-profile generation requires refreshing it.

## Contracts and boundaries

- `POST /api/catalog/works/{id}/source-searches` atomically saves an owner-scoped operation and source jobs with an idempotency key. Repeating the same command does not create another search.
- `GET /api/catalog/works/{id}/source-searches/latest` and `GET /api/source-searches/{id}` expose persisted results. Reloading does not resubmit. Worker leases, generation fences and queue-state repair distinguish pending work from a stopped worker.
- Native MAM and Prowlarr have separate jobs. Prowlarr indexers are searched in sequence under the shared credential budget, with completed indexer results committed independently. Rate-limit retries preserve finished work and honor the adapter's retry delay within the bounded queue budget.
- A page requests up to 50 results per participating source/indexer, with up to 20 eligible Prowlarr indexers. The UI identifies this as ranking the fetched page, not the entire tracker catalog. Further pages are explicit; unsupported pagination is reported per indexer. Searches/results expire after 25 minutes. Existing source-result retention can remove expired or excess cached rows.
- Source generation, user activation, library visibility and catalog identity are checked during execution and on result access. Changed identities and expired or reconfigured sources cannot be inspected through an old result. Private Prowlarr references remain encrypted.
- `POST /api/source-searches/{search}/results/{result}/artifact` uses the existing inspected-torrent path. It does not dispatch a download or create an edition. Supported manual selection still requires identity review, a compatible wanted target, a verified destination and downloader evidence.
- `GET/POST /api/acquisition/profiles` and `PUT /api/acquisition/profiles/{id}` enforce ownership and optimistic generations. Updating preferences does not rewrite committed acquisition policy.

Ranking compares source capability/blocked constraints and title/author agreement before the configurable criteria. Normalized title plus agreeing author is corroborating source evidence, never proof of actual file identity. A conflicting author remains unmatched regardless of seed count. Known zero seeds and unknown seeds remain distinct. Per-indexer ordering is supported in the API; the initial editor reorders MAM/Prowlarr only.

Selection freezes the profile and rechecks blocked formats against both source claims and the inspected torrent paths, plus total descriptor bytes. Import authority validation checks observed file extensions and aggregate file sizes again under the same frozen profile, including companions and excluded pack children. This applies to direct and administrator-handoff downloads. Separate content inspectors validate supported media before publication; filename preferences alone cannot establish readable content. Old selections without a profile keep their previous behavior.

## Verification and migration

Unit and PostgreSQL/API cases cover ordered ranking, known/unknown facts, invalid settings, private profiles, stale generations, immutable snapshots, partial source failures, incremental persistence, repeated commands, atomic queue rollback, account/catalog changes during network work, worker lease recovery, source cooldowns, expired results and selection/import limits. The browser exercises the Sources-to-manifest-to-selection handoff, independent source errors, saved profile edits, reload and mobile layout using synthetic services.

Migration `0024_book_sources` adds private profiles and links cached results to search operations. Back up before upgrading. An isolated upgrade/downgrade-to-0023/re-upgrade and schema drift check pass. Populated profile/search history blocks lossy downgrade and requires a pre-upgrade backup. Current aggregate evidence is maintained in [Implementation Status](IMPLEMENTATION-STATUS.md).

## Remaining S06 work

Native AudiobookBay, cross-source release equivalence, full language/exact-version eligibility, verified series coverage and bounded pack expansion, source-local popularity, profile inheritance/default management, search cancellation, shared-transfer reuse and unattended source selection remain pending. This foundation does not claim automatic ranking is safe to dispatch without review. Live MAM/Prowlarr/qBittorrent certification, external Hardcover/Goodreads list automation and the remaining PRD stages remain unimplemented or uncertified as recorded in the status document.
