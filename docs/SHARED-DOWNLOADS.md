# Reviewed shared downloads

One reviewed source artifact can now serve several saved book selections through one qBittorrent attempt. Each selection retains its work, requested medium/version, frozen profile, reservation and independent request reasons. This is a bounded implementation of shared-pack acquisition, not automatic series coverage selection or a completed S06 gate.

## User flow

On an inspected source artifact, save a release selection for each wanted book the release contains. The confirmation is a candidate assertion; actual files and library inventory must still establish coverage. When choosing another request from a request-bound search, the form uses that request's saved preferences instead of applying the first book's search policy.

Under Saved selections, include the desired books in a shared download. The scope summary lists the selected titles before **Download selected books together**. The server accepts at most 100 selections owned by the requester, using the same artifact, medium, downloader and verified import route. Incompatible or stale selections fail atomically. Existing automatic-selection records cannot be repurposed into this reviewed batch.

Activity displays one physical transfer and its individual books, media, pending requirements and fulfillment. Selecting either member's download history resolves to the same attempt. Cancelling an unsent group is explicitly labelled as cancelling the entire transfer; withdrawing one book's request reason is a separate request action. After submission may have occurred, cancellation cannot discard the attempt or cause resubmission.

## Persistence and dispatch

Migration `0036_download_memberships` adds an immutable selection-to-attempt association. Existing attempts are backfilled as single-member transfers. `DownloadAttempt.selection_id` remains the original transport representative for historical compatibility; membership controls child lookup and fulfillment. A selection belongs to only one attempt. No existing record is expanded by guessing from titles or hashes.

`POST /api/acquisition/downloads` accepts `selection_id` and optional `additional_selection_ids`, plus the existing idempotency header. Membership is frozen in the accepted command. A changed group cannot reuse its command key. Replaying a member returns the existing attempt, but a new command cannot silently append another member to it.

Before creating an attempt, the service acquires the work-graph lock and canonical work locks in deterministic order. It rechecks every selected target's inventory, authority, artifact and route, then commits memberships, reservations, one physical capacity record, torrent identity claims and one worker job together. Distinct active attempts cannot claim the same normalized endpoint/hash. Matching an unrelated torrent remains a conflict, not permission to adopt it.

At the submission boundary, each still-wanted member is revalidated. Satisfying or withdrawing the representative book does not strand other wanted members. If no selected target remains wanted, the attempt is held before submission. Lost add responses use the existing sticky submission marker and reconciliation path; retries never call add again.

Repair records are resolved through membership so that all children reference the common repaired connection. Current repair scope still excludes moving an existing transfer to another server or changing its physical route.

## Import and fulfillment

The completed transfer produces one inspection. Under an approved automatic-import route, confidently matched EPUB/M4B/MP3 groups can proceed through the existing importer for their reviewed work scope. Without that approval, the existing administrator review flow applies. This feature adds no player or scanner implementation.

- Inspect and retain the whole downloaded manifest; preserve original seeding paths and bytes.
- Apply each member's frozen whole-transfer constraints and per-book medium, language, abridgment, exact-version and narrator requirements.
- Reassess current missing requirements before planning. An already-satisfied book does not acquire an unnecessary alternate version merely because the pack includes one.
- Hold unknown/unrequested groups. If multiple groups could satisfy one book, hold those groups while unrelated qualifying books proceed.
- Permit reviewed correction and import of a held child beside the unchanged published siblings.
- Confirm each expected ABS item and files before recording fulfillment or retiring that child's reservation. Keep the physical torrent identity claims and historical attempt.

An ebook may keep the overall work owned while its requested audio remains pending. Download completion, catalog matches and claimed pack contents alone never set an owned badge. An ambiguous or absent child stays wanted independently of completed siblings.

## Deployment and rollback

Stop the old API and worker, take the normal private database/journal backup, upgrade to `0036_download_memberships`, and restart both at the same revision. A mixed old/new deployment could create attempts without membership and is unsupported. No new service, secret or environment setting is required. Dispatch remains disabled by default.

The migration supports downgrade while all attempts retain the original single-member shape. Once a transfer has additional members, downgrade refuses to discard those associations; use the supported pre-upgrade backup/restore procedure. Restoring external side-effect history still requires reconciliation before dispatch resumes.

## Evidence and remaining work

`test_shared_downloads.py` covers concurrent/reversed grouping, durable command replay, member lookup, incompatible/foreign selections, atomic failure, cancellation, changed representative demand, child-scoped version/narrator checks, lost submission responses, withdrawn groups, backfill and guarded downgrade.

`test_shared_pack_import.py` uses actual synthetic EPUBs, the normal queue/importer and an ABS HTTP fixture. It covers multiple imports, ownership arriving after queueing, delayed backend detection, unrequested files, ambiguous alternatives, selective repair, source bytes/hardlinks and independent fulfillment. The scanning fixture now preserves item IDs when a newly published sibling sorts before an existing item. These are application/fixture checks, not live tracker/downloader or additional native ABS compatibility certification.

The browser journey saves two book selections, reviews the group, submits one synthetic transfer, reloads Activity and checks mobile/desktop display. See [implementation status](IMPLEMENTATION-STATUS.md) for the final run evidence.

Remaining required work includes inherited Just book / Prefer packs / Complete series policies, automatic claimed/corroborated coverage ranking, compatible reuse by later or cross-owner requests, mixed-route/media pack handling, broader recording equivalence, per-child provider resolution when local identifiers are insufficient, and truthful omnibus containment. Multi-member groups with unresolved catalog editions currently remain reviewable; the single-book provider-resolution path is unchanged. Native ABB, full list qualification, discovery, production readiness and S10 remain in the full PRD scope.
