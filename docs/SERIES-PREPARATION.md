# Automatic series metadata preparation

Book source searches now load missing or stale Hardcover series catalogs before executing source queries when the inherited `prefer_series_packs` preference is enabled. This removes the manual catalog-refresh prerequisite for the existing automatic pack selector. It does not authorize additional series books or group automatic requests into a transfer.

## Execution contract

The source-search operation saves its requester, work identity, effective preferences, configured source generations and supported series references. A durable `sources.prepare` job runs on the metadata queue. Source jobs are not enqueued until preparation finishes. The existing `catalog.series.refresh` worker supplies pagination verification, staged publication, provider rate budgets and access checks; the preparation worker does not implement another provider client.

References come from accepted Hardcover metadata visible to the requester or the requester's observed memberships. At most three supported numeric series IDs are considered. Catalogs fetched within 24 hours are reused. Missing or stale catalogs share an active same-account, same-endpoint refresh, including a manually started refresh. Explicit manual refresh commands retain their supersession behavior. Recent failed/cancelled observations created within 15 minutes are reused as a fallback explanation instead of immediately creating another lookup.

Preparation waits at most ten minutes from command creation. Dependency retries do not consume the source-network retry budget. A disabled, replaced or missing catalog connection, a failed lookup, a provider cooldown beyond the deadline, or an elapsed deadline permits ordinary source search with a visible warning. Work identity changes, inaccessible books and removed frozen series references stop the search. Refreshing the search creates a new command with current authority.

After preparation, the operation computes and freezes the final catalog-backed query plan, retains the originally selected source generations, starts source workers transactionally, and resets their result lifetime to 25 minutes. Replaying preparation after launch is a no-op. It cannot silently add newly configured sources. Source settings and catalog evidence remain checked by the existing search, selection and dispatch paths.

A late background catalog publication may change the frozen search scope. The existing identity/scope checks then require a fresh search; they do not silently rewrite executed queries. A timed-out parent does not cancel a catalog observation that another search or the user may still need.

## UI and pack eligibility

Book Sources shows a collapsed series-metadata summary with state, per-series outcome and warnings. Query provenance appears only once preparation has finished. Queue truth detects a stopped preparation job and provides a refresh instruction. The worker's stalled-job recovery includes both preparation and catalog-refresh tasks.

Automatic pack coverage now requires catalogs fetched within 24 hours. Stale memberships remain browsable but cannot authorize an automatic pack. Current catalog membership and torrent filenames/folders only establish candidate coverage; downloaded contents, per-version requirements, import authority and Audiobookshelf confirmation remain separate checks. See [Automatic pack coverage](AUTOMATIC-PACK-COVERAGE.md).

No schema migration, new external service or installation dispatch change is required. Deploy the API and worker together: an older worker cannot execute the new queue task. Drain pending preparation jobs before rollback or restore a compatible pre-deployment backup with dispatch paused.

## Evidence boundaries

Integration tests cover catalog hydration before source queries, replay, shared refreshes, freshness, opt-out, unavailable connections, changed identity, provider cooldowns, stopped jobs and frozen source generations. The real PostgreSQL worker test exercises the durable parent retry, catalog jobs and subsequent MAM queries with synthetic provider responses. The browser journey exercises automatic preparation without pressing the manual series-refresh button, then reloads its receipt and uses the observed series for curation.

This is a prerequisite of S06/S07. Automatic multi-target authorization, overlapping-list pack reuse, full series/destination inheritance, additional versions, omnibuses, native Audiobook Bay, live-provider certification, discovery, production gates and S10 remain pending.
