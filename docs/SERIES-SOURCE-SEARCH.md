# Catalog-derived series source searches

Book Sources now searches the entered title plus up to three known series names. This implements the series-name discovery portion of FR-24 and S06-05. It does not establish main-series membership, pack contents, additional download authority or library ownership.

## Defaults and customization

`search_series` defaults to true. It uses the existing precedence: request override, list override, saved profile, personal default, installation default, built-in default. The Series search section of the shared preference editor supports an explicit false value and reset to inheritance. On Book Sources, Search options can override the current search to use title and known series names or only the entered query. This preference changes search scope; Just book / Prefer packs / Complete series acquisition policy remains a separate pending contract.

Request-bound searches retain accepted list/request overrides and ordinary profile validation. Standing list searches use the same resolver and query builder. A saved search freezes its terms and source evidence. Editing defaults does not retroactively expand an in-flight search. The next fresh search resolves the current permitted policy, and acquisition still revalidates the accepted policy before dispatch.

## Query evidence and bounds

The planner reads accepted metadata for accessible origins of the canonical work, plus the observing account's fetched series catalogs where that work is a current member. It never takes names from unaccepted matches, another account's private series catalog, an inaccessible merged origin, or a tracker result from a prior query. Metadata compilation entries are excluded from automatic query expansion. Names are search aliases only; two provider IDs sharing a normalized name remain distinct evidence even when one HTTP query serves both.

Case/Unicode/whitespace normalization removes duplicate queries, including a series name equal to the entered query. Valid names retain their human-readable spelling. Overlong or unusable names are skipped with a visible explanation. Limits: three series queries plus the entered query; 50 accepted metadata records and 50 observed series membership records; 50 series names per metadata record; 50 results per query/source/indexer; at most 20 eligible Prowlarr indexers. Overflow is disclosed, with direct custom searches available. These bounds permit up to 200 results from MAM and 4,000 Prowlarr results before deduplication per page. Existing source rate budgets, native-MAM exclusion, leases and the 25-minute search expiry still apply.

The operation stores every term's key, kind, query text and provider evidence, including record/series/member identifiers and observation time. A new series relationship, changed name, removed source acceptance or lost access invalidates an old query plan. Merely refreshing identical metadata does not invalidate it; the original observation evidence stays frozen. Invalidation stops publication/inspection through that saved search and hides its series query/provenance projection until a fresh search is made. No network request holds a database transaction open.

## Independent progress and result identity

One durable worker per connected source runs the bounded queries sequentially under the existing source credential budget. Prowlarr discovery records separate indexer/query units. Each unit commits its results and progress atomically. A failed query does not erase successful siblings; rate-limit retries resume pending units without repeating completed queries. Expired or replaced worker leases cannot publish results. Legacy searches without a query plan retain their original single-query behavior.

Results deduplicate within the search by source, original indexer ID and source release ID. The first observed snapshot/reference remains authoritative; later matching hits add query keys without replacing that snapshot. Different indexers stay distinct, even when their release IDs match. This is release identity deduplication, not torrent-hash deduplication or version matching. Per-query counts report that query's unique hits; the displayed results list has installation-source identities deduplicated across queries. The UI shows which queries found each result and the evidence behind the query plan. Detailed source progress is collapsed, and ranked releases render in groups of 50 with next/previous controls and focus restored to the result counter. These display pages are separate from fetching the next tracker page; the API still returns the bounded search result set, so large-response performance qualification remains open.

Catalog title/author assessment, format and narrator rules still evaluate the release itself. A hit from a series query does not become a corroborated match to the requested book merely because the query used that series name. Automatic eligibility continues to hold unverified collections for coverage review. Further pages use the requested offset for every participating query; non-paginating indexers report that limitation independently.

## Storage and operation

Migration `0035_source_queries` adds `source_results.query_keys` with an empty default for historical/direct-search rows. New query plans live in the existing operation payload. Back up the database and restart API and worker together after migration. Populated query history blocks lossy downgrade; use the pre-upgrade backup for rollback. New preference snapshots include `search_series`; old binaries cannot be assumed to understand them. No new service, token or queue is required.

Backend and browser evidence is recorded in [Implementation Status](IMPLEMENTATION-STATUS.md). Live MAM/Prowlarr account qualification, automatic bounded pack coverage selection, shared child reservations and verified per-child/omnibus fulfillment remain required before claiming complete series acquisition.
