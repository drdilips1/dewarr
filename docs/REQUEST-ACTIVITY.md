# Requests in Activity

Activity now includes **Your media requests**, separate from physical downloads and background operations. It lists the current user's requests across books and lists, including requests that have not selected a release and requests already satisfied by the library. The default hides requests whose reasons have all been withdrawn; Include withdrawn requests exposes the retained history. This is not a count of torrents or missing books.

## Progress and actions

Each card shows the book, version description, and independent ebook/audio/either targets. A collapsed section exposes the accepted request scope, download constraints and effective preference provenance. The summary distinguishes Wanted, Release selected, Acquisition pending, Available, Check inventory, Paused and Cancelled. An acquisition pending label does not assert that a torrent is downloading: its actual association, transfer, import and library-confirmation details remain in Downloads.

`TargetView.next_action` is an explicit server projection:

| Value | Meaning and destination |
|---|---|
| `search` | Missing requested media has no prepared or committed selection; open Sources with this request and target slot |
| `selected-release` | This user owns the prepared selection; open its existing artifact |
| `downloads` | This user owns a committed selection; inspect download activity rather than starting another acquisition |
| `book` | Review the valid request's book/inventory or open available copies |
| `none` | No continuation is offered, including withdrawn targets, failed request access checks, or another user's private shared selection |

The book-page saved-request section uses the same action component and status labels. Request previews have no saved continuation and keep their existing preview behavior. `RequestView.can_open_book` gates these links after the current request authorization check; failure retains the masked/paused request projection. Action links do not grant authority: source selection, artifact access, download operations and filesystem actions still perform their own current checks.

Each reason has its own explicit Withdraw action. Withdrawing a manual reason does not cancel a surviving list reason, another request, a shared transfer or seeded/library files. Existing request cancellation rules and API transactions remain authoritative. Once the last active reason is withdrawn the card leaves the default view and remains in history. There is no generic Retry download action on a request card.

## Listing and freshness

`GET /api/requests` adds optional `active_only` (default false for compatibility). It filters with an owner-scoped active-reason existence condition before counting and pagination. Fulfilled requests with an active reason remain included. Pagination is ten requests per Activity page; existing API work filtering and bounds remain unchanged.

Request cards refresh every fifteen seconds. Downloads and background activity retain faster polling while active and now continue polling every fifteen seconds while idle, so an open Activity page can discover externally initiated list work. Inactive caches are discarded. Errors hide cached request cards/download controls/operation rows and offer a read retry. Retrying the view does not retry acquisition or import. Browsing and expanding requirements do not create jobs, requests or transfers.

## Evidence and limits

PostgreSQL tests cover partially satisfied requests, stale inventory, withdrawn reasons, active filtering before pagination, retained fulfilled requests, independent list reasons, role changes, prepared/private shared selections, committed transfer continuations and read-only projection. Existing request, selection and download-attempt workflows are included in regression coverage. The browser journey creates real fixture-backed requests, pages through them, follows a bound source link, withdraws independent reasons, shows withdrawn history and verifies failed-refresh hiding/retry with unchanged transfer and library counts.

Exact test and runtime results are recorded in [Implementation status](IMPLEMENTATION-STATUS.md). This advances FR-35 and the request-to-acquisition alpha experience. It does not complete full Activity issue handling, reviewed request revision, production recovery, live-service qualification or other S00–S10 gates. No migration or dependency is added.
