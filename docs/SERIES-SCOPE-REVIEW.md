# Reusable main-book reviews

A Hardcover series page can save an explicit, finite main-book selection independently of a request. This supplies user-reviewed membership evidence for the next series-policy work. Saving it creates no acquisition, reservation, queued job or download. A request or list policy must separately authorize acquisition.

## User behavior

Select books, open **Reusable main-book selection**, confirm the selection and save. Published, complete, non-compilation and non-merged source evidence is required for each selected work. The selection may contain up to 100 distinct canonical works; this is a review limit, not an increase to automatic pack size or expansion limits. Decimal, duplicate and unknown positions remain observations. None proves or disproves main membership; duplicate positions remain visible as warnings for the reviewer.

The saved panel lists the finite set and its revision. **Select reviewed main books** restores that selection. A **Complete reviewed main-book set** request may explicitly use the current saved review instead of repeating its one-off main-book confirmation. Its selected work IDs must exactly equal the saved set. The request preview displays the reused review revision and still needs ordinary request acceptance, media/preferences and any automatic-route approval.

Replacing or withdrawing a review prevents its use for new acceptance. Withdrawal does not resurrect an older review. Already accepted requests retain their frozen set and independent acquisition reasons; cancel those requests separately to withdraw acquisition authority. Saving an ordinary one-off series request never creates a reusable review.

## Evidence and validity

The immutable review payload records owner, series ID/provider namespace, catalog generation and observation time, selected canonical identity snapshots, original provider membership records, omitted books, review revision and a content fingerprint. The fingerprint includes provider membership/book IDs, canonical work identity, source title/authors, positions/details, publication, partial/compilation and merge facts. Decorative cover changes and catalog generation alone do not invalidate it.

New catalog members never enlarge the reviewed set. An identical successful refresh keeps it reusable. Changed or removed selected membership, identity correction/merge or changed selected evidence requires a new review. Observations older than 24 hours require catalog refresh before reuse; an unchanged refreshed observation restores validity without repeating the review. Failed observations preserve the previous catalog and its age.

API states distinguish not reviewed, current, changed, needs refresh, withdrawn and superseded. No state asserts that Hardcover classified these as main books. Evidence is explicitly `user-reviewed-main-books`.

## Persistence, concurrency and acceptance

Reviews use `Operation(kind="series.scope-review")` plus audit events. No new schema migration is needed beyond the current `0037_download_joins` baseline. Revisions are assigned under an owner/series advisory lock; the latest query includes withdrawn records. Save requires both the displayed catalog generation and previous review ID. Idempotency keys preserve replay, reject changed commands and return an old receipt as superseded when appropriate.

Series request/review context acquires the owner/series scope lock, then the catalog-observation advisory lock, before user/catalog rows and graph locks. This serializes with catalog publication before retaining a row lock that could obstruct its commit. Commands that have idempotency locks obtain them first; existing series workers reserve their child command locks first. Request acceptance and review withdrawal/replacement serialize through the same scope lock. Before acceptance the request rechecks the latest review, exact selected set and saved fingerprint. After acceptance the request's independent authority and existing worker checks apply; review validity does not become a hidden ongoing cancellation switch.

The API and worker must be updated together. Older binaries do not understand the new request proof/command field. Preserve a matching database/key backup for binary rollback; the absence of a new table does not imply payload compatibility with older code. Existing catalog downgrade protection prevents dropping populated series history.

## API

All routes are owner-scoped and require an active non-viewer account:

- `GET /api/catalog/series/hardcover/{external_id}/main-books`: latest review and current validity.
- `POST /api/catalog/series/hardcover/{external_id}/main-books`: explicit confirmation, distinct work IDs, expected catalog generation and previous review ID, with an idempotency key.
- `DELETE /api/catalog/series/hardcover/{external_id}/main-books/{review_id}`: replay-safe withdrawal of the current review; an older ID cannot withdraw its replacement.
- Existing series request preview accepts optional `scope_review_id` for the complete reviewed set and returns the frozen review ID/revision.

## Remaining scope

This is membership evidence and reusable reviewed-request behavior. Inherited Just book / Prefer packs / Complete series settings, standing-list-derived authority, bounded automatic expansion and its full lifecycle remain required. Future consumers must separately validate current list/request authority, scope limits, pack coverage, child version/routes and final ABS confirmation. A review is neither permission to download nor proof that a pack contains its books.

Verification and its limits are recorded in [Implementation status](IMPLEMENTATION-STATUS.md). The complete requested product remains governed by the [PRD](../PRD.md) and [current execution packets](../IMPLEMENTATION-PLAN.md#next-reviewable-packets-series-scope-and-list-expansion).
