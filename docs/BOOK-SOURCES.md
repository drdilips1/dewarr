# Book source search and download preferences

September 18, 2026. Partial S06 implementation; the full PRD remains active.

## User experience

The book page now has a Sources tab. Opening it starts a search when no saved search exists; returning to it loads the user's latest search and continues observing pending work. The book's catalog versions and confirmed library availability stay separate from tracker releases. Wanted-book links carry the request and target through source inspection into the existing release-selection screen.

MAM and eligible Prowlarr indexers contribute to one ranked page. Results retain the source title, raw title, author, narrator, medium, reported formats, bytes and seed count. MAM descriptions, series, tags and media information remain available under original release details. Unknown values stay unknown. Each source shows its own progress, observation time and error; an outage does not erase successful siblings. Native MAM overlap is excluded through the existing Prowlarr capability rules.

Balanced preferences require no configuration: EPUB leads ebook formats, M4B leads audio formats, and MAM leads sources. The default ordered comparison is format, source, then seed count. Users can save private named profiles, reorder those criteria and preferred formats/sources, block formats, and optionally cap total transfer size. Advanced format controls stay collapsed. Explanations show the applied preferences and missing evidence.

Profiles affect the current source comparison and the selected acquisition. Sparse profile fields now inherit personal and installation defaults through [Download preferences](DOWNLOAD-PREFERENCES.md); complete request/list ranking and media/language inheritance remain pending. An edited profile receives a new generation; historical searches and selections retain their original snapshot. Selecting with an obsolete saved-profile generation requires refreshing it.

## Contracts and boundaries

- `POST /api/catalog/works/{id}/source-searches` atomically saves an owner-scoped operation and source jobs with an idempotency key. Repeating the same command does not create another search.
- `GET /api/catalog/works/{id}/source-searches/latest` and `GET /api/source-searches/{id}` expose persisted results. Reloading does not resubmit. Worker leases, generation fences and queue-state repair distinguish pending work from a stopped worker.
- Native MAM and Prowlarr have separate jobs. Prowlarr indexers are searched in sequence under the shared credential budget, with completed indexer results committed independently. Rate-limit retries preserve finished work and honor the adapter's retry delay within the bounded queue budget.
- A page requests up to 50 results per query/source/indexer, with up to 20 eligible Prowlarr indexers. [Series source search](SERIES-SOURCE-SEARCH.md) adds at most three catalog-derived series-name queries beside the entered query, with independent progress and release-ID deduplication. The UI identifies this as ranking the fetched page, not the entire tracker catalog. Further pages are explicit; unsupported pagination is reported per indexer. Searches/results expire after 25 minutes. Existing source-result retention can remove expired or excess cached rows.
- Source generation, user activation, library visibility and catalog identity are checked during execution and on result access. Changed identities and expired or reconfigured sources cannot be inspected through an old result. Private Prowlarr references remain encrypted.
- `POST /api/source-searches/{search}/results/{result}/artifact` uses the existing inspected-torrent path. It does not dispatch a download or create an edition. Supported manual selection still requires identity review, a compatible wanted target, a verified destination and downloader evidence.
- `GET/POST /api/acquisition/profiles` and `PUT /api/acquisition/profiles/{id}` enforce ownership and optimistic generations. Updating preferences does not rewrite committed acquisition policy.

Ranking compares source capability/blocked constraints and title/author agreement before the configurable criteria. Normalized title plus agreeing author is corroborating source evidence, never proof of actual file identity. A conflicting author remains unmatched regardless of seed count. Known zero seeds and unknown seeds remain distinct. Per-indexer ordering is supported in the API; the initial editor reorders MAM/Prowlarr only.

Selection freezes the profile and rechecks blocked formats against both source claims and the inspected torrent paths, plus total descriptor bytes. Import authority validation checks observed file extensions and aggregate file sizes again under the same frozen profile, including companions and excluded pack children. This applies to direct and administrator-handoff downloads. Separate content inspectors validate supported media before publication; filename preferences alone cannot establish readable content. Old selections without a profile keep their previous behavior.

## Verification and migration

Unit and PostgreSQL/API cases cover ordered ranking, known/unknown facts, invalid settings, private profiles, stale generations, immutable snapshots, partial source failures, incremental persistence, repeated commands, atomic queue rollback, account/catalog changes during network work, worker lease recovery, source cooldowns, expired results and selection/import limits. The browser exercises the Sources-to-manifest-to-selection handoff, independent source errors, saved profile edits, reload and mobile layout using synthetic services.

Migration `0024_book_sources` adds private profiles and links cached results to search operations. Back up before upgrading. An isolated upgrade/downgrade-to-0023/re-upgrade and schema drift check pass. Populated profile/search history blocks lossy downgrade and requires a pre-upgrade backup. Current aggregate evidence is maintained in [Implementation Status](IMPLEMENTATION-STATUS.md).

## Remaining S06 work

Native AudiobookBay, cross-source release equivalence, full language/exact-version eligibility, verified series coverage and bounded pack expansion, source-local popularity, complete request/list policy inheritance, search cancellation, shared-transfer reuse and unattended source selection remain pending. This foundation does not claim automatic ranking is safe to dispatch without review. Live MAM/Prowlarr/qBittorrent certification, external Hardcover/Goodreads list automation and the remaining PRD stages remain unimplemented or uncertified as recorded in the status document.


## Automatic release preparation

Wanted-target source pages now offer [automatic release preparation](AUTOMATIC-SELECTION.md). It inspects bounded candidates, retains rejection reasons, ranks actual media formats and saves the best verified single-book candidate through the shared selector. The saved selection opens the existing explicit download action; no download is started by preparation. Series/recording coverage, ABB, capacity scheduling and automatic list activation remain required for full S06/S07.

[Series source search](SERIES-SOURCE-SEARCH.md) requires migration `0035_source_queries` and matching API/worker revisions. It uses inherited `search_series` preferences and retains query evidence without asserting pack coverage.

## Temporary result comparison · September 19, 2026

The Sources tab now provides **Sort this view** with profile ranking, most seeders, smallest/largest download and title ordering. A text filter searches loaded titles, raw titles, authors and narrators. Expand Filter loaded releases to choose a source/indexer or reported format, or hide blocked/expired rows. Identically named Prowlarr indexers remain separate by indexer ID. Unknown format is selectable; unknown seeds and sizes sort after known values in both directions, with zero retained as a known value.

Sorting and filtering apply to every loaded result before the 50-row display pagination. They do not fetch extra tracker pages or claim to compare the entire tracker catalog. Counts show total loaded releases and matching results. Changed controls return to the first display page; Reset result view restores profile order and clears all filters. Each row retains its position in the server's original profile ranking, including after manual sorting. Equal sort values retain that original order.

These are temporary local display controls. They send no command, update no profile, and do not affect automatic preparation or the policy frozen with an acquisition. Reload and a new search reset them. Filtering out a blocked result does not change its eligibility; showing it again leaves inspection disabled. A stale catalog identity also disables inspection. Existing source progress, raw descriptions, ranking explanations and pagination remain available independently of view controls. AudiobookBay has a direct settings/search link beside MAM and Prowlarr.

Saved profiles can also opt into [source-local popularity ranking](DOWNLOAD-PREFERENCES.md#source-local-popularity--september-19-2026). That is a policy change, unlike temporary view sorting. Currently MAM's completed-download count is supported and shown in original release details; other sources retain unknown popularity. The source criterion groups tracker/indexer origins before comparing their counts. Existing Balanced/profile choices keep their prior order unless this criterion is added explicitly.

Browser verification uses a completed real fixture search expanded to 55 synthetic display rows at the HTTP response boundary. It checks sorting across display pages, stable ties, zero/unknown values, source namespaces, format/text filters, disabled inspections, reset/reload, unchanged saved profiles and no view-generated API writes. This tests presentation, not the eligibility or dispatch of those synthetic rows. Current results are recorded in [Implementation status](IMPLEMENTATION-STATUS.md). No API, database migration or download-policy change is introduced.
