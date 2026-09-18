# Goodreads shelf observation

September 18, 2026. Initial S07 RSS observation, separate from acquisition automation.

## Available workflow

Open a list you own and follow a Goodreads shelf using its RSS URL. The URL is encrypted and write-only because it may contain a private feed key. The first successful observation adds the visible books to the local list. New source identities become private provisional catalog entries; exact ISBN plus agreeing title and author may reuse an existing accessible catalog book. Earlier observations for the same Goodreads book ID can reuse the same owner's binding. No editions or owned media are invented from feed membership.

Book cards use the existing library availability projection. A matched title already present in an authorized Audiobookshelf library keeps its owned and medium indicators. Unknown identity remains provisional and can be matched to an existing catalog book from the observed-entry panel. Changed upstream bibliographic fields flag the entry for review without overwriting catalog metadata.

Observations run approximately every 30 minutes by default, with stable per-subscription jitter. The interval is adjustable from 30 minutes to one day. Refreshing a list is a durable operation, so leaving or reloading the page does not abandon it. The browser polls persisted status; it does not perform the scheduled work itself.

Removing a followed book through the normal list controls also records an exclusion. Refreshing cannot silently add it back. The observation panel can restore it. A source-specific exclusion preserves a separately added local membership. Pausing observation preserves all books, bindings and exclusions. Detaching keeps current books as local members and removes the subscription's observation/exclusion history; this effect is described beside the action.

Sharing a list deliberately exposes its private provisional book entries to the household. Unsharing removes that access. Feed keys and the subscription's observation controls remain owner-only. Previously linked catalog data is redacted if its library/catalog visibility is later lost. Installation administrators retain their existing catalog access; this is not encryption from the operator.

## Observation semantics

- Every feed is explicitly `partial-feed`. Omitted books remain members; an empty feed or 304 does not remove anything.
- A first successful observation records a baseline and freshness. It is not an assertion that the entire remote shelf was imported. A 304 cannot establish a missing baseline.
- HTTP ETag and Last-Modified validators are saved with the encrypted configuration. Replacing the URL/key clears them. A different user/shelf requires a new list or an explicit detach; it cannot silently reuse another shelf's observations.
- Response parsing accepts at most 4 MiB, 500 items and 20,000 XML elements. DTDs/entities, malformed RSS, missing book identity and conflicting duplicate IDs fail the observation. Existing memberships and the previous baseline survive failure.
- Only book IDs, titles, authors and valid ISBN assertions are retained. Reviews, reading history, private notes, ratings, arbitrary HTML and image URLs are not imported by this adapter.
- Requests accept only the Goodreads HTTPS shelf route. DNS is checked for public addresses and the actual connection is pinned while preserving TLS hostname verification. Redirects, private/mixed DNS and compressed response bodies are rejected. Logs suppress credential-bearing request URLs.
- All shelf subscriptions share a five-second request budget. HTTP 429 establishes a persisted shared cooldown. Ordinary errors use interval-based backoff with a one-day ceiling; a longer provider retry delay takes precedence. Queue retries also honor their recorded delay. Rate-budget or lease waits can retry beyond the normal queue attempt threshold; each retry rechecks authority, and an individual observation expires after seven days rather than waiting indefinitely. Unexpected exceptions remain bounded by the queue attempt limit, while actual HTTP errors record their separate persisted backoff. Redelivering a terminal operation cannot bypass that backoff.
- The scheduler checks at most 50 due subscriptions per pass. Durable job creation is atomic with its operation. Per-list locks, run tokens, leases, queue exhaustion repair, generation checks and final account checks prevent stale workers from publishing observations.

The source-of-membership record is separate from the local list entry. List deletion/detachment and observation changes do not delete media or cancel client torrents. Normal local removal still withdraws that list's request reasons using the existing acquisition rules.

## APIs, migration and evidence

The owner-only `/api/lists/{list_id}/subscription` resource supports reading, configuring and detaching a subscription. `/sync` queues an idempotent refresh. `/observations` returns paginated source entries; individual observations support catalog matching and exclusion/restore. Ordinary list and book APIs expose the resulting curated books and library availability.

Migration `0025_list_subscriptions` adds subscription/observation records, catalog ownership for private provisional books and local membership provenance. It preserves existing list entries as locally added. An isolated upgrade → downgrade to 0024 → upgrade and drift check pass. Populated source/privacy history blocks lossy downgrade; preserve a pre-upgrade database backup and the existing encryption key.

Tests exercise synthetic RSS/HTTP, PostgreSQL/API state, actual durable worker execution and browser interactions. Network unit tests check public DNS pinning, host/TLS routing, conditional requests, private-key redaction and typed failures. The browser uses a test-only worker transport confined to the disposable browser database; the production adapter has no local-host bypass. Aggregate counts and current results are in [Implementation Status](IMPLEMENTATION-STATUS.md). No user's Goodreads credentials or live feed was used; live shelf compatibility remains unverified.

## Remaining PRD work

[CSV snapshot import and mapping](CSV-LIST-IMPORT.md) and [Hardcover inbound subscriptions](HARDCOVER-LISTS.md) are now implemented separately. Subscriptions begin in Browse. Separate [list acquisition policies](LIST-POLICIES.md) now provide explicit future-only/backfill/catch-up activation, scheduled searches and qualified single-book automatic dispatch. Following a shelf alone creates no download. Complete large-list support, settings inheritance, richer identity/re-add reconciliation, series/recording handling and full S07–S08 qualification remain pending; Goodreads write-back is not part of the RSS contract.

Goodreads' own [RSS announcement](https://www.goodreads.com/blog/show/20-more-rss-feeds) documents shelf-addition feeds. It is a historical source, not a current stability or completeness guarantee. This adapter uses original code and synthetic interface fixtures; no Goodreads implementation or reader reviews are bundled.
