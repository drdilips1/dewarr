# Paginated lists and consistent selections

Lists, book/series destination selectors, local curation, manual requests and automatic-policy backlog selectors now use bounded server pages. A large catalog list no longer needs to fit into the first 200 lists or the first 10,000 detail entries to be browsed and curated.

## API contract

- `GET /api/lists/page` returns `items`, `total`, `offset` and `limit`. The default page is 25 lists, maximum 100. `q` searches literal list-name text, and `editable=true` limits destinations to the current owner's lists. Visibility is applied before counting/pagination. Ordering is creation time descending, then UUID. Membership counts are hydrated only for the selected list page. This is a live index, not a frozen snapshot across separate HTTP requests.
- The older array-shaped `GET /api/lists` accepts the same search/owner filter and offset paging, with a default of 50 and a maximum of 200. App list selectors use the envelope endpoint; they never silently stop at the array response bound.
- `GET /api/lists/{id}` returns at most 50 books by default, maximum 100. `count` is all accessible canonical members; `matched` is the count after title/author filtering. `offset`, `limit` and `content_revision` describe the response. The actual book metadata and availability hydration are limited to that page. Canonical aliases count once, ordered by their earliest membership position and UUID.
- Optional `expected_revision` on detail requests rejects changed membership/order with 409. The shared list and identity locks keep the rendered page and revision coherent with list/merge writers. This is a membership/order contract; it does not freeze metadata edits or library availability across requests. Every response computes current authorized visibility.
- `GET /api/lists/{id}/catalog` provides bounded catalog search plus `member_ids` for the returned work IDs, checked against the entire list. A book on an unloaded list page is still labeled **In this list**. Private or inaccessible identities cannot appear through this check.
- `POST /api/lists/{id}/move` takes one canonical work ID, direction `-1` or `1`, and the displayed `expected_revision`. It finds the adjacent visible member on the server, normalizes ranks and swaps the pair while preserving hidden slots and alias membership grouping. It works across page boundaries and tied source positions. A retry after a completed move conflicts with the changed revision instead of moving the book twice. The full-order endpoint remains available for older clients.

The membership fingerprint is aggregated in PostgreSQL rather than loading every entry into application memory. It includes membership UUIDs, original/canonical identities and positions. The internal digest is an opaque change marker, not an authorization capability. Its version changed in this increment: an already-open older editor may need a refresh. Saved exact command receipts retain their replay behavior.

## Reader behavior

The list index and destination dropdowns have name search and pages. A selected destination remains selected when searching another page; the mutation always rechecks actual ownership. Indexes are live, so concurrent creation/removal can change a later page; selection remains by explicit UUID, never by row number. Previous-page controls remain available after an index page becomes empty.

The book grid loads 50 records at a time and offers **Search this list**. Up to 100 selections survive page and search changes. A changed membership revision requires the user to clear/review that selection. Relative order controls are available without a search filter, where their neighbors are unambiguous to the reader. Removing entries retains library media and independent acquisition reasons.

Manual request and backlog selectors share title/author search and 25-book pages; their limits remain 100 and 25 selected books respectively. The first selection captures the content revision. Further pages are checked against it; conflicts show a refresh/clear action and disable preview. Request and policy preview commands also accept `expected_content_revision` and reject a stale selection under the existing list/identity locks. Thus a membership removed and re-added between selection and preview is not silently treated as the same episode. Preview retries still reuse their saved exact receipts.

## Evidence and remaining limits

The affected backend corpus covers browsing beyond 200 lists and 10,000 memberships, filtering/counts, bounded availability hydration, relative moves across page boundaries, tied positions, hidden memberships, stale pages and stale request/policy previews. Existing curation, canonical merge, request/policy and automation tests remain part of regression. Browser evidence covers cross-page bulk selection, unloaded membership badges, searchable request/backlog/destination selectors and responsive layouts. Exact results belong in [Implementation Status](IMPLEMENTATION-STATUS.md).

Automatic policy activation retains its explicit 10,000-entry limit and finite backlog/transfer budgets; this browsing change does not expand automation authority or make whole-list downloads implicit. Index/detail counts and fingerprints still perform database work proportional to relevant membership. Passing bounded hydration tests is not certification of the full PRD performance dataset. Actual provider compatibility, optional Hardcover writes, full usability and all remaining S00–S10 gates remain in scope.

No migration, runtime dependency or new credential is introduced. Deploy the generated OpenAPI client/frontend with the matching API/worker on `0038_asset_containment`.
