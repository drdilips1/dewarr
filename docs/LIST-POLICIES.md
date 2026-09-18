# List acquisition policies

A list can remain browse-only, provide defaults for reviewed manual requests, or automatically acquire missing media. This implementation connects standing list authority to the existing source-search, automatic-selection, download and import services. It does not introduce a second downloader or importer.

## Setup and normal use

Open a list you own and choose **Acquisition policy**. Choose Browse, Manual or Automatic, then Ebook, Audiobook, Both or Either. Either also offers a first-medium preference. Select an existing download profile or keep Balanced. Advanced download restrictions retain independent blocked formats and a whole-transfer size limit.

Automatic mode requires a tested downloader and an administrator-approved, verified import route for each possible medium. Both and Either require ebook and audio routes. Administrators can grant or revoke **list automation** for members in Accounts; ordinary membership alone does not grant standing automatic authority. The owner still needs access to each destination library.

Preview the policy before activating it. Existing list books are not selected by default. Select up to 25 existing works per activation to acquire a deliberate backlog. The preview reports owned requested media and compatible owner-visible requests already in progress. Remaining members become the baseline; later additions are eligible under the saved policy. External subscriptions need a successful observation before automatic activation.

Manual list requests initialize media, destinations and effective download restrictions from the saved policy. The user can override them for that explicit request. Manual source selection remains a separate step; this does not claim complete user/installation/profile inheritance for every acquisition surface.

The monitored-books view shows baseline, wanted, searching, selecting, pending, available, held or removed states, with the next check and a reason. The policy summary and monitored entries refresh while automatic acquisition is active. Availability still comes from the connected library: a selected release, completed torrent or scan request cannot create a green library check.

## Standing authority and lifecycle

Activation stores a versioned policy, provider/profile and destination snapshots, and a durable per-book record. Policy revision changes on every control edit, including pause/resume; its generation changes when effective configuration changes. Acquisition reasons are specific to the policy generation and remain separate from ordinary manual-list reasons and other lists.

The scheduler processes at most 20 due policies per pass. A policy tick enrolls up to 25 previously unseen members and advances up to 25 due books. Pending transition checks align with minute boundaries so subsecond worker timing cannot skip the following cron tick. Queue receipts prevent concurrent cron calls from creating duplicate active ticks. Stopped ticks are recovered; policy jobs never perform network requests inside their database transaction.

For each authorized work, the shared request engine checks current accessible inventory and compatible reservations. Both creates independent media targets; an owned ebook satisfies its target while the audiobook remains wanted. Either accepts an already-owned qualifying medium. Without ownership or reusable pending work, it searches the preferred medium and can try the alternative after no eligible result. Compatible requests across lists reuse the same transfer.

The saved policy selects the profile and routes used by source search and automatic selection. Each reason retains its hard restrictions; one list cannot relax another list's format or transfer-size requirements. Frozen automatic-selection evidence carries internal list authority. It is checked during selection and immediately before external submission alongside current account/grant, route, profile, catalog and capacity checks. Public request bodies cannot supply this internal authority.

Pause stops new dispatch authorized by the list while membership observation continues. It does not cancel submitted transfers. Resume previews current memberships: additions observed while paused are not silently treated as newly authorized backlog. Previously authorized work can continue; an unsubmitted attempt held by a pause can reuse its original identity and capacity records after explicit resume. A held transfer from an older, changed policy generation remains visibly held in Activity; the new policy cannot adopt its obsolete authority.

Removing a list member or deleting its list withdraws that list's reasons while preserving independent manual and other-list reasons. Explicitly selecting a previously withdrawn book in a new activation creates a new command cycle, so an old idempotency receipt does not prevent deliberate reauthorization. A replay of the same completed activation receipt does not reactivate a paused policy.

Removing a member also marks its monitor removed immediately, including baseline books that have never created a request. Re-adding it under an active policy starts a new membership cycle; an already-owned qualifying medium is skipped and a compatible existing transfer is reused. Re-additions observed while paused remain baseline on resume unless explicitly selected for catch-up. A source-only Hardcover membership can follow the same remove/reappear lifecycle; a deliberate local exclusion still prevents reappearance from restoring membership.

Canonical book merges retain the original monitoring rows and request histories. Scheduling and the monitor view group those rows under the current canonical title, with one scheduling leader per title. Identity changes invalidate stale search progress; merge undo restores the original groups without rewriting their origins. A withdrawn request remains withdrawn and cannot block another active request in its merged group. The monitor API supplies the canonical title, including for removed entries no longer displayed in the list itself.

A missing release waits six hours after the first unsuccessful round, then daily through round eight and weekly afterward. Provider cooldowns and shared capacity remain authoritative. A profile, subscription configuration, destination or approval change requires a new activation preview; the scheduler displays the reason instead of silently expanding authority.

## API and persistence

Owner-only routes below `/api/lists/{list_id}/acquisition`:

| Route | Purpose |
|---|---|
| `GET` | Current policy, effective configuration and monitored state counts |
| `POST /preview` | Idempotent preview with expected policy revision and explicit backlog selection |
| `GET /previews/{id}` | Saved preview, paginated at 50 records by default |
| `POST /previews/{id}/activate` | Revalidate and apply the saved preview |
| `POST /pause` | Pause under an expected revision |
| `GET /books` | Paginated monitored books and next-check times |

`PUT /api/auth/users/{id}/automation` is administrator-only and uses the expected current permission value to reject stale edits. It grants automation capability, not library access or import-route approval.

Migration `0030_list_policies` adds policy and per-book scheduling records. Deleted lists leave historical policy records with a null list reference. Populated policy/preview history blocks downgrade; recover through a pre-upgrade backup instead of discarding acquisition authority records. Preview expiry is 15 minutes. This implementation explicitly rejects activation above 10,000 list entries rather than silently truncating the baseline.

## Verification boundary and remaining work

Integration tests cover baseline/backfill, stale previews, pause/catch-up, overlapping lists, independent withdrawal, changed permissions/configuration, scheduler enqueue rollback, retry timing, Both/Either decisions and activation history. Real generated EPUB/audio files also traverse the list scheduler, shared selection/download worker, hardlink publisher and synthetic ABS confirmation, including delayed detection. Browser coverage exercises Hardcover observation into a later automatic download, persistence, inherited manual media, member permission controls and mobile layout.

Additional lifecycle tests cover local and source-only membership re-additions, pause/catch-up, reuse of held or submitted attempts, owned-media skip, canonical merge/undo and independent withdrawn reasons. Source reappearance coverage calls the same membership functions used by the Hardcover observer; it does not establish live remote behavior.

Those tests use synthetic source/downloader/backend services and separately described real file operations. They do not establish live MAM, Goodreads or Hardcover account compatibility, nor a complete S07 release gate. Broader series-pack and exact-recording automation, full settings inheritance, very large lists, broader identity corrections and complete native/deployment qualification remain open. A conventional approved route and currently qualified single-book formats are still prerequisites for unattended imports. See [Implementation Status](IMPLEMENTATION-STATUS.md) for the actual passing checkpoint and [the full plan](../IMPLEMENTATION-PLAN.md) for remaining scope.
