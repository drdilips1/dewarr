# Download defaults and profile inheritance

Release preferences resolve per field: request overrides → list overrides → selected profile → personal defaults → installation defaults → built-in Balanced values. Leaving a field unset inherits it. Editing one field in the UI records only that override; “Use inherited …” removes it again. Existing profiles with complete stored preferences remain explicit and keep their previous values.

This applies to ebook/audio format order, source order, ranking criteria, preferred narrators, blocked formats and maximum transfer bytes, plus the supported [request scope](REQUEST-SCOPE.md): desired media, Either's first medium, language, abridgment, required narrators, standalone copies and library choices. Empty format/source preference lists are invalid. An explicit empty blocked-format list clears an inherited preference; an explicit null maximum removes an inherited profile limit. These are ordinary preferences. Independent request restrictions, administrator-approved destinations, permissions and installation capacity limits remain enforced and cannot be relaxed here. Ownership is unchanged.

Open **Personal and installation download defaults** from a book's Sources preferences, or `/download-preferences`. Members edit their own defaults. Administrators additionally edit installation defaults. Saved profiles are still private. The editor keeps inherited values visible, and the effective-preferences view shows the source of each value. Changing defaults does not rewrite files or replace running torrents.

## Acquisition behavior

Request previews, saved requests, manual list batches, source search, reviewed selection and list activation use the same resolver. Their snapshots include effective values, field origins and an effective revision. The browser sends that revision when starting search, selecting an inspected release or previewing a list policy; stale resolved preferences return a conflict instead of silently using new values. Replaying an already accepted idempotent search still returns its original receipt and frozen preferences.

Automatic selection and pre-dispatch authorization compare current effective preferences with the original snapshot. A changed effective policy holds an unsubmitted automatic acquisition. An existing external transfer keeps its original selection and is observed without a replacement download. A changed default used by a standing list requires another activation preview. Existing submitted acquisition/import decisions continue to retain their original snapshots.

A fully explicit profile masks changes to lower-level defaults. Sparse profiles inherit changes only for fields they omit. Older receipts without field origins remain readable; matching compares their actual saved values and profile identity/generation rather than requiring newly added presentation fields.

## Concurrent requests and settings changes

The resolver reads installation defaults, personal defaults and the selected profile in one database statement. It observes a consistent committed snapshot without retaining configuration locks while callers acquire list or book locks. It does not promise one snapshot across a whole multi-statement transaction. Frozen request/search receipts and revision checks retain their existing behavior. Settings writes still serialize and reject stale revisions.

Automatic dispatch has a narrower fence: immediately before the final authority check and durable submission marker, the download worker takes the same configuration lock used by settings writers. It holds that lock until the marker commits, then releases the transaction before qBittorrent I/O. A settings edit that commits first is visible to the final check and can hold the unsubmitted acquisition. An edit that obtains the lock afterwards cannot retroactively cancel a submission already recorded as possibly external. Subsequent runs observe that transfer without adding it again. This is a database decision boundary, not an atomic transaction spanning PostgreSQL and qBittorrent.

Keep ordinary profile reads free of transaction-scoped configuration locks. The final dispatch transaction already owns its list/principal/book/attempt locks before taking the configuration fence; configuration writers must not start acquiring those workflow locks while holding it. Changing these boundaries requires cross-workflow concurrency tests. PostgreSQL documents statement snapshots under [Read Committed](https://www.postgresql.org/docs/16/transaction-iso.html#XACT-READ-COMMITTED) and transaction lock lifetimes in [Explicit Locking](https://www.postgresql.org/docs/16/explicit-locking.html).

The current slice does **not** claim the entire FR-20 inheritance contract. Supported request scope and narrator preferences use the same precedence model, with [route defaults](ROUTE-DEFAULTS.md) and [inherited series scope](LIST-SERIES.md) documented separately. Prefer-pack incidental expansion and reviewed scope changes for already-unsatisfied requests remain follow-ups. Exact recording requests and required library choices do not substitute for those capabilities. Full S06/S07 acceptance remains open.

## Narrator ranking

Preferred narrators are ordered names, not a filter. The earliest matching name receives the best narrator rank. Unknown and unlisted narrators remain eligible but do not receive a preference. This criterion has no effect on ebook ranking. Empty `preferred_narrators` explicitly clears inheritance.

Existing profiles keep their three-criterion ranking order. Narrator preference breaks remaining ties before stable source identifiers. **Rank narrator preference first** adds `narrator` to the movable ranking priorities; it can then be placed before or after format, source and seeders. **Use narrator preference only to break ties** restores the three-criterion form. Required narrators filter candidates before any soft preference or seed count can affect selection.

## Request and list overrides

A list policy has a collapsed **List download overrides** editor. A manual title request or list batch has **Download preferences for this request**, initially set to inherit. Both editors expose the release-preference fields and supported scope choices, with reset-to-inherited actions. Request previews and saved receipts retain effective values and their origins; previews show resolved request scope separately from release ordering.

Each new acquisition intent and reason keeps its accepted release-policy snapshot. Requests with different effective policies retain separate histories, while compatible targets can still share a transfer. Existing legacy requests remain readable without an invented historical snapshot. Changing defaults does not rewrite accepted history. New searches revalidate the selected base profile and retain the accepted list/request overrides; automatic selection checks current authority before dispatch.

Source searches opened from a wanted request are bound to that request. Polling and reload retrieve that request's latest search, so another search for the same book cannot replace its policy. Selection retains the saved search policy and rejects a search bound to another request. Independent request size/format restrictions remain enforced during ranking and selection, even when an ordinary preference explicitly clears its own limit.

Manual list previews freeze both effective preferences and the resulting request specification. Changing the list's effective preferences before submission requires a new preview. An accepted batch passes the same snapshot to each child request. Automatic lists pass their policy snapshot through the existing search, selection and download workflow.

## API and storage

| Route | Behavior |
|---|---|
| `GET /api/acquisition/preferences/personal` | Own explicit overrides, effective/inherited values, field origins and edit revision |
| `PUT /api/acquisition/preferences/personal` | Replace own sparse overrides with expected revision |
| `GET/PUT /api/acquisition/preferences/installation` | Same contract, administrator only |
| `/api/acquisition/profiles` | Existing profile routes now persist sparse preferences and return their resolved snapshot |
| `POST /api/requests/preview` and `/api/requests` | Optional `release_preferences` with selected profile and sparse `overrides`; submission accepts `expected_preference_revision` |
| List policy preview | Optional sparse `preference_overrides` layer |
| List request preview | Optional `release_preferences`; accepted batch retains the resolved snapshot |
| Book source searches | Optional `request_id` binds search and latest-result lookup to a private request |
| Release selection | Optional `search_id` preserves the saved search's effective policy |

Replacing overrides with `{}` restores inheritance. Revision checks include the edited layer's generation and inherited effective values, so stale concurrent edits and an edit made before installation defaults changed are rejected. Profile/search/selection generation checks remain active. No API accepts a target user ID for personal settings.

Migration `0031_acquisition_defaults` adds installation/personal override records. Existing complete profile JSON is not rewritten. Populated defaults block downgrade to avoid dropping preferences; recover from a pre-upgrade backup. Restart API and worker together after migration. No additional service or secret is needed. Older standing-list configurations may request reactivation when their stored snapshot lacks the new resolution evidence; this preserves their authority boundary instead of silently adopting changed defaults.

Migration `0032_request_release_policy` adds nullable policy snapshots to intents and reasons. It does not backfill unknown historical choices. A populated snapshot blocks downgrade; use a pre-upgrade backup rather than discarding acquisition evidence.

## Evidence boundaries

Integration coverage exercises precedence, explicit clearing and restoration, sparse profile persistence, invalid values, concurrent/stale edits, private scopes, administrator/member/viewer authorization, frozen search replay, old snapshot compatibility, list authority changes, unsubmitted versus already-running automatic transfers, and the populated downgrade guard. Browser coverage is recorded separately in [Implementation Status](IMPLEMENTATION-STATUS.md). Fixture qBittorrent/source traffic is not live account certification. Full policy inheritance, collection/recording automation and remaining production qualification remain in scope.

Deterministic PostgreSQL tests reproduce the former manual-request/list-batch deadlock and verify the corrected interleaving for request creation, reviewed selection and automatic preparation. Additional cases cover committed/rolled-back multi-layer settings, one winning profile edit, edits during network preflight, and a real settings-writer lock wait through the final submission marker. These prove the specified workflows; they are not a blanket concurrency certification of every acquisition/import path.

## Series search preference

`search_series` defaults to true and uses the same sparse inheritance, explicit false override, snapshots and field-origin display as other download preferences. [Series source search](SERIES-SOURCE-SEARCH.md) explains its bounded catalog-derived terms and provenance. It controls discovery queries; acquisition scope and pack coverage remain separate requirements.


## Series acquisition scope

`series_scope` selects Just this book, Prefer series packs or Complete reviewed series. The shared resolver preserves legacy pack booleans and unchanged historical snapshots. Automatic lists can derive a finite reviewed main-book set; manual Complete-series previews lead to the series request page. See [List series](LIST-SERIES.md) for authority, lifecycle, limits and remaining expansion work.
