# Reviewed source selection

A wanted request can now be connected to a saved MAM torrent manifest and a verified download-to-library route. On a book page, choose **Choose a source release**, inspect a result, confirm which wanted book it contains, and save the selection. The matching request travels through search into the manifest page. A single tested downloader and matching verified destination are selected by default; more choices remain explicit.

This is a preparation record. It neither submits a torrent nor establishes that a tracker posting really contains the requested book or exact version. The entire artifact is selected, including collection files. Actual child coverage, standalone status, abridgment and edition/recording identity still require file inspection and review. Only ABS-confirmed complete assets establish ownership.

For a collection, save separate selections for its wanted books, then use [reviewed shared downloads](SHARED-DOWNLOADS.md) to submit compatible selections as one physical transfer. Each must belong to the requester and use the same artifact, medium and verified route. Choosing a different request from a request-bound source page uses that request's saved preferences, without carrying over the first book's search policy.

## Frozen handoff

`AcquisitionSelection` stores the actor, initiating request/target, shared reservation, source artifact, downloader and destination. Its immutable document includes:

- Canonical and original work IDs, requested medium, language, version, abridgment and standalone requirements.
- Exact catalog-version evidence when a version was requested.
- Artifact checksum, native descriptor, sanitized source snapshot and source generation.
- Downloader generation, category/save path, worker mapping and destination configuration.
- The user's candidate-to-book confirmation, explicitly distinct from verified content coverage.

Preparation rechecks active request reasons, current inventory, actor authority, artifact ownership/integrity, source generation, downloader diagnostics/path mappings, library grants and the actual destination probe contract. A required library cannot be replaced with a different destination. The probe must cover the downloader's worker source root, no-replace publication, selected hardlink/copy mode and ABS root mapping. No credentials or absolute filesystem paths are returned in the selection/options responses.

Known medium/language/narrator conflicts are rejected. Unknown or incomplete content claims are not converted into verified coverage. [Download preferences](DOWNLOAD-PREFERENCES.md) and bounded [automatic selection](AUTOMATIC-SELECTION.md) have separate implementation checkpoints; complete series coverage ranking remains pending. A saved selection alone is not proof that an automatic acquisition is eligible.

## Reservation behavior

| State | Behavior |
|---|---|
| `planned` | Compatible wanted requirements may be combined and recomputed |
| `selected` | Requirements are frozen by a prepared selection; compatible broader requests may join without changing them |
| `committed` | A durable download attempt owns the frozen reservation until completed transfer and confirmed fulfillment permit retirement |
| `released` | No active planned use remains |

Committed reservations, then selected reservations, are considered before planned reservations across either-medium alternatives. A stricter or incompatible later request receives a separate planned reservation; it cannot modify a prepared choice. A deliberate manual choice can use the other medium for an Either request. Reconciliation preserves that selected medium.

A selection has states `prepared`, `committed`, `fulfilled` and `cancelled`. Preparation cancellation applies only before commitment. Cancelling it returns still-needed requirements to planning. If the initiating target becomes satisfied, loses authority or loses its last active reason, reconciliation cancels preparation. Remaining compatible requests retain their own reasons and are replanned. Canonical merge/undo cancels affected preparation before rebuilding reservations; historical documents remain unchanged.

These cancellation rules are safe because preparation performs no external mutation. **They must not be reused for a submitted or uncertain download.** The [download-attempt ledger](DOWNLOAD-ATTEMPTS.md) now supplies a distinct irreversible boundary, attempt identity, leases and observation-based recovery. Neither a cancelled selection nor a released planned reservation authorizes deleting a torrent or media.

## Commands, history and privacy

Preparation uses the shared actor/idempotency-key operation lock. Every accepted key receives a durable completed `acquisition.select` receipt, including a new key that resolves to an identical existing selection. Reusing a key with different input conflicts. Replaying an old command returns its historical selection, including cancellation; it cannot reactivate it. No worker job is enqueued by preparation.

One partial unique index permits one prepared or committed selection per reservation. Request reconciliation, selection and cancellation share canonical work locks. Owner-only read/list/cancel endpoints hide another account's selection even from a different administrator. Shared reservations disclose only a generic selected status to other request owners, without source-artifact IDs or another user's history.

A later source/downloader/destination/mount/version change makes the saved configuration stale. The manifest page shows this explicitly. This read projection is not dispatch authorization: a dispatcher must recheck inventory, active reasons, permissions, requirements and current settings immediately before its side-effect boundary.

## API

- `GET /api/acquisition/selections/options`: member-visible, credential-free downloader choices and granted destinations.
- `POST /api/acquisition/selections`: prepare with an `Idempotency-Key`; origin and CSRF protections apply.
- `GET /api/acquisition/selections`: owner-scoped, paginated history, optionally filtered by artifact.
- `GET /api/acquisition/selections/{id}`: owned immutable choice with current-configuration status.
- `DELETE /api/acquisition/selections/{id}`: cancel preparation without changing external files/transfers.

Request views include their book title and, only for the selection owner, a link to the saved source artifact. Activity identifies completed preparation separately from download activity. Migration `0017_selections` guards populated history against lossy downgrade; retain a pre-upgrade backup.

## Evidence and next dependency

Twenty-one API/database cases cover concurrent/replayed commands, receipt binding, cancellation, no downloader jobs, fixed requirements, broader/stricter sharing, Either-medium selection, inventory satisfaction, actor/library/artifact ownership, settings and recording changes, canonical merging, pagination and downgrade protection. The browser journey follows a new ebook request through MAM detail, native artifact inspection, a previously verified library route, saved selection, reload and cancellation. Source/downloader responses are synthetic; the existing import journey performs the filesystem and synthetic ABS route probe.

The opt-in [download lifecycle](DOWNLOAD-ATTEMPTS.md) consumes this selection with persisted dispatch and recovery. Reviewed same-owner pack grouping now uses that same path. Automatic pack scope/coverage, later compatible sharing, live certification and the complete transfer-to-library gate remain required for S05/S06. List automation uses this acquisition workflow rather than bypassing preparation or import verification.
