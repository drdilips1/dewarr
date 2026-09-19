# Followed lists in Discover

Discover includes **Your followed lists**, a local view of the current user's Hardcover and Goodreads subscriptions. It links browsing back to list curation and acquisition settings. Community-list discovery remains a separate provider-backed experience.

Four lists appear per page, newest subscription first. The source filter applies before counts and pagination. Paused and failed subscriptions remain visible with their saved status and last successful observation; a detached subscription leaves this shelf without deleting its local list. Empty subscriptions remain visible so setup and observation problems are not mistaken for missing lists.

Each card previews the first three accessible canonical books in local list order. Counts include all accessible saved memberships, including local additions and retained Goodreads RSS observations. An RSS feed is not a complete shelf snapshot; feed omissions do not remove retained books. Provisional titles are counted and identified as needing catalog matching.

An ebook or audiobook counts a book as in the library. Multiple recordings, formats and canonical aliases do not inflate this total. Verified complete omnibus children count through the shared availability relation; companions, unverified children, missing files and inaccessible libraries do not. Stale copies retain last-known ownership and produce a card-level warning even when the affected title is outside the preview. Each preview also uses the ordinary format, collection and stale badges.

## Contract and permissions

`GET /api/discovery/followed-lists` accepts `provider=all|hardcover|goodreads`, nonnegative `offset` and `limit=1..12` (default 4). It returns a total, page coordinates and cards with subscription status, last success, full membership/ownership/provisional counts and up to three book previews.

Only the current user's subscriptions appear, including for administrators. Sharing a local list does not expose its owner's subscription here. Ordinary catalog visibility and current library grants apply to titles, counts and previews. No encrypted feed configuration is read or returned. The endpoint does not repair jobs, observe providers, enqueue work, edit lists or create acquisition requests.

The implementation pages subscriptions first, aggregates canonical memberships and scoped ownership in PostgreSQL, and selects the preview with a partitioned row number. It hydrates at most three books per returned list and batches availability. Database read count does not grow with the number of cards. This does not establish the full reference-load performance target.

The independent frontend query refreshes every minute and on remount/focus, retains no inactive cache, resets pagination when the source changes, and hides previous cards on retrieval failure. Retry only reloads the shelf. Following, observing a list and automatic acquisition retain their existing separate controls. The shelf displays no claim that a paused observation also pauses acquisition.

## Verification and remaining scope

PostgreSQL tests cover canonical grouping, ordered bounded previews, complete collection children, both media, private titles, owner-only subscriptions, member/viewer grants and revocation, inaccessible or disabled libraries, provisional and stale data, provider filtering, paused/failed/empty/detached subscriptions, pagination, bounds, authentication and absence of read-side mutations. A 1,255-membership fixture verifies bounded hydration and fixed query count.

The browser journey uses saved fixture subscriptions and real fixture-backed library holdings to check ownership, source filtering, pagination reset, paused/never-observed status, outage hiding/retry, mobile layout and keyboard navigation into curation. Actual Goodreads/Hardcover accounts and external list behavior remain separate qualification gates. Exact results are recorded in [implementation status](IMPLEMENTATION-STATUS.md).

This advances S08-01 / FR-11. It adds no migration or dependency. Full discovery usefulness, whole-library series enrichment, live list qualification, production gates and S10 remain open.
