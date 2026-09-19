# Community-list discovery and following

Discover → **Explore community lists** opens public Hardcover lists. The default page orders lists by reported follower count; title/theme search uses Hardcover's list search and preserves its relevance order. Cards show a few covers, book count, known follower count and whether this user already follows the list locally. A numeric public list ID can also open its preview.

The preview reuses ordinary catalog and library projections. Accepted accessible Hardcover bindings show protected local titles and ebook/audio/collection availability. An unknown match says **Library match not established**; a search result alone never proves a book is missing or owned. Unknown books open the existing catalog preview. Loading another page does not import its books or create acquisition requests.

## Follow and automation

**Follow list** atomically creates a private local list, an enabled 30-minute inbound subscription, a durable receipt and the initial sync job. It opens the local list, where sync progress and the existing request/policy controls are available. Download automation defaults off. Follow is local: it does not mutate a Hardcover follow relationship, share the list or change reading progress.

The existing Hardcover worker reads and verifies membership in two passes before publishing the first observation. A preview is not a baseline. Ordinary list settings then supply Browse, Manual and Automatic modes, desired media, profiles, future-only activation and reviewed backfill. Automatic requests use the same source selection, downloader, importer and ABS confirmation services as other lists. Overall ownership still requires a confirmed full medium; another requested medium can remain missing.

Repeated or concurrent Follow actions by the same user reuse their earliest existing Hardcover subscription for that external list. This preserves a renamed list, paused subscription and existing acquisition policy. Deliberately configuring separate local lists through the subscription settings remains possible. A deleted/detached subscription cannot be resurrected by replaying an old receipt; a fresh follow command is required.

New follows reject lists above the current 5,000-membership sync bound before creating local state. Such lists remain previewable, with the limitation stated. Lists that later grow beyond the bound retain prior memberships and show the existing sync failure. No partial prefix is silently accepted as a complete list.

## Provider contract

[Hardcover's search guide](https://docs.hardcover.app/api/guides/searching/) documents `search(query_type: "List")`. The implementation uses that operation, not disabled SQL-pattern operators. Search-index names/descriptions are never displayed directly: returned IDs are hydrated through fresh `public = true` list queries. Matches that disappeared or became private are omitted with a warning. Public browse/detail/follow lookups bypass provider response caching; account generations and current local permissions are rechecked after provider I/O.

Header/member-ID queries and book hydration are separate bounded operations, with no more than three field levels. Browse returns twenty lists plus a lookahead, samples four member IDs per displayed list, and hydrates at most eighty unique books. Search returns twenty hits, revalidates public headers and then hydrates their samples. Book previews use increasing membership IDs with twenty entries and one lookahead. Missing hydrated books are explicit; a preview does not claim authoritative coverage. Browse/search currently permits fifty pages; a narrower search or direct ID handles a list outside that browsing window.

All calls use the existing per-account gateway, shared credential budget, timeouts and safe error taxonomy. Search, quota, permission, malformed-response and unavailable states remain distinct. Tokens stay in the backend. Local follows are projected only for their owner, even when another user's local list is shared. Viewer accounts may browse but cannot follow.

The five new GraphQL queries validate against the official schema saved at documentation revision `e8d38c8b7bd53cada7e97121ab0cacfa0804013c`. The [getting-started restrictions](https://docs.hardcover.app/api/getting-started/) inform query depth, access and rate handling. Schema validation and synthetic HTTP tests do not certify actual-account access; live-account qualification remains open.

## Recovery and concurrency

A per-user/external-list advisory lock serializes Follow creation. Reused subscriptions follow the existing list → command → account → actor lock order; unrelated commands colliding on an idempotency key fail without deadlocking or mutating the existing list. The receipt and first job commit with local state. Enqueue failure rolls everything back. Account replacement, disabled access, role loss, unsupported size and recovery mode prevent new follows.

A sync failure leaves an actionable local subscription, not a false complete list. The existing subscription retry, pause, detach and exclusion behavior applies. Removing a subscription never deletes seeded or library files. Published assets and independently authorized request reasons keep their normal lifecycle.

## Deployment and evidence boundary

No migration, additional service or new secret is required. Deploy matching API/frontend/worker builds on schema `0038_asset_containment`. This feature does not enable installation-wide dispatch.

Verification covers the real API/database transaction and durable subscription worker with synthetic Hardcover responses; strict adapter parsing and query validation; cross-account projections; enqueue rollback; concurrent follows and command lock order; and recovery/access changes. The acquisition fixture follows a public list, activates future-only policy, adds an upstream book, then runs the existing selection/download/import workers over actual EPUB and audio files. It verifies delayed ABS confirmation, hardlink inode/byte preservation and one transfer after repeated sync/follow. External provider, qBittorrent and ABS observations in these tests are synthetic; native/backend compatibility retains its separate certification gate.

Browser verification exercises search, known ownership, unknown-book preview and focus restoration, Follow → synced private list, Browse policy defaults, existing-follow reopening and mobile layout. Exact run results are recorded in [Implementation status](IMPLEMENTATION-STATUS.md).

This completes a community-following increment of S08-02 and connects it to S07. Full S08 still requires series-continuation discovery, complete curation/sharing, supported optional write-back and task-based usability qualification. It does not close the full PRD.
