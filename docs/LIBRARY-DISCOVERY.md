# Recent library additions

Discover includes **Recent library additions**, separate from recent catalog entries. It shows complete books confirmed in the current user's accessible libraries, with Ebook and Audio ownership badges and links to their ordinary book pages. Choose all media, ebooks or audiobooks. The default page contains twelve distinct canonical books.

## Dates and identity

The order uses the newest first-observed library-copy timestamp for each book, limited to the selected medium and accessible libraries. A later version or copy can bring a title back to the shelf. Initial inventory brings existing books into view; the date does not claim that a book was just published, downloaded, read or added to Audiobookshelf. Repeated inventory updates change last-seen evidence without changing this first-observed timestamp. Matching an existing item later uses that item's original observation date.

Canonical aliases and multiple versions collapse into one title before pagination. The same shared availability relation used by book pages excludes incomplete companion files, unverified containment, missing/suspected/moved items, inaccessible libraries, disabled connections and libraries without the user's grant. A verified omnibus may supply several distinct child books. Stale holdings retain their last-known ownership and explicit stale badge. The media filter chooses which copy observations qualify for this shelf; each card still shows all of that user's owned media for the work.

The timestamps and ordering never depend on a newer copy in an inaccessible library. Unowned catalog entries and metadata-provider search results cannot appear simply because their catalog records are recent. Private metadata and canonical identity use the existing visibility rules.

## API and interface

`GET /api/discovery/library` requires authentication and supports `medium=any|ebook|audio`, `page=1..100` and `limit=1..24` (default 12). It returns a `LibraryDiscoveryShelf` with an `observed_at` timestamp per item. Ordering is observation descending, title and stable work ID. Filtering and canonical grouping happen in PostgreSQL before the page limit; one extra row determines `has_more`, and only the returned page receives batched availability projections. The bounded shelf links to My Library for the full library view.

This endpoint reads local inventory and makes no metadata-provider or player requests, creates no catalog entries or operations and starts no downloads. It works without Hardcover credentials. Existing discovery endpoints and schemas are unchanged; the new response extends their shape.

The shelf loads independently from live provider recommendations and refreshes once a minute and on remount/focus. Changing the medium resets its page. It retains no inactive query cache. A refresh error hides previously shown cards and offers a retry instead of implying current ownership or an empty successful result. Empty results explain inventory/matching and medium selection. Browser-local date formatting is used for observation labels.

## Qualification

Integration tests cover observation chronology, canonical version grouping, media filtering before pagination, empty pages, access grants and revocation, disabled/inaccessible libraries, private-copy timestamp isolation, stale holdings, excluded asset states, companion documents, verified collection children, authentication, parameter bounds and read-only behavior. The browser journey traverses the real fixture-backed shelf, media changes, page/reset controls, outage/retry, book navigation and mobile layout. Its small fixture overrides only `has_more` to expose the next-page control; actual page boundaries are covered by PostgreSQL tests.

Exact results belong in [Implementation status](IMPLEMENTATION-STATUS.md). This is S08-01 / FR-11 discovery progress. It does not certify live inventory, full reference-load performance, the complete S08 gate or the remaining PRD. No database migration or dependency is added.
