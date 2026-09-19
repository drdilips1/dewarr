# Searchable background activity

Activity separates saved requests, physical downloads/import reviews and **Background activity**. The history now pages through all operations owned by the current user instead of stopping at the newest 100. It defaults to 25 operations per page, newest creation time first, with an ID tie-break. It describes recorded operation state; it is not an independent assertion about worker liveness or library ownership.

Search matches the saved message, raw task type or operation ID. Matching is case-insensitive and treats `%`, `_` and backslashes literally. Status and task-type filters apply before counts and pagination. Filter choices come only from the signed-in user's history. Search, filters and page position live in the URL and survive reload and browser Back; changing a filter resets the page. Reset affects the history controls, not request/download settings.

Each row shows its message, state and creation time. Operation ID and last-update time are available in a collapsed disclosure for diagnosis. Supported rows link to a currently accessible book or list, using the current title and canonical book identity. Metadata enrichment and book-source searches link to the book; known list observation/curation/request/CSV/write-back/comparison/follow operations link to the list. Administrators can open library connections from inventory-sync operations. Other operation kinds remain readable without a fabricated navigation target.

Links revalidate catalog/list visibility and current role on each history read. Deleted, malformed or inaccessible references yield no link; unknown operation kinds cannot supply arbitrary destinations. The destination's ordinary authorization and revision checks remain authoritative. Opening history or filtering it never retries, enqueues or modifies an operation. Retry activity only reloads the read; actual repair actions stay in their dedicated workflows.

## API and data handling

`GET /api/activity/page` accepts `q` (up to 300 characters), exact `status` (up to 40), exact `kind` (up to 60), nonnegative `offset`, and `limit=1..100` (default 25). It returns items, filtered total, page coordinates and owner-scoped distinct status/type options. Blank filters include everything; an unknown exact filter returns no matching rows. The existing `/api/activity` array endpoint remains unchanged for existing consumers.

The page query selects summary columns and extracts only known context IDs from JSON in PostgreSQL. It does not hydrate large operation payloads, manifests or private command data. List/work context is resolved in batches for the current page. Historical messages retain their established owner-only visibility; current referenced titles are disclosed only after current access checks. The endpoint does not read secrets or return arbitrary payload fields.

The independent React query uses two-second polling when the displayed page contains queued/running/retrying work and fifteen seconds otherwise. Filtered-out operations need not be active in the displayed page. Errors hide cached rows and navigation until a successful retry. A completed inventory sync in the displayed history retains the existing inventory-cache invalidation behavior. Inventory views also have their own refresh contracts.

## Verification and remaining scope

PostgreSQL tests cover access beyond 100 rows, filtering before counts/pages, stable ordering, literal and ID search, owner-scoped options for members/viewers, unchanged legacy responses, malformed/private/deleted context, canonical redirects, sharing revocation and summary-only hydration. The browser journey creates 30 real curation operations, exercises paging, filtering, ID search, reload/Back, operation details, keyboard list navigation, refresh failure/retry and mobile layout. Recorded test totals and deployment evidence are in [implementation status](IMPLEMENTATION-STATUS.md).

This advances FR-35 / AT-24. It does not claim every operation kind has a repair link, that every historical message is fully correlated to a book, or that all Activity/recovery acceptance cases are complete. Broader issue/repair surfaces, live-service qualification, S09 release gates and S10 remain in scope. No migration or dependency is required.
