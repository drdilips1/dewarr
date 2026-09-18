# Download fulfillment and request closure

Acquisition now records historical target satisfaction separately from download state and current library availability. This implements part of the PRD acquisition-closure contract; it does not complete S05 or enable normal download dispatch.

## Evidence and authority

Request evaluation uses the existing scoped inventory rules: confirmed full content, verified work coverage, accessible library, enabled backend, requested medium, language, exact version, abridgment and standalone requirements. An ebook does not satisfy an audio target, and another narrator cannot satisfy an exact-recording target. Existing account, active-reason and destination permissions still apply.

For an associated attempt, a `DownloadFulfillment` records the target, qualifying asset, original requirements and observation time. When a confirmed import entry from the attempt's inspection produced that asset, its entry ID is retained. Otherwise the evidence is explicitly `existing-library`; satisfying a request does not invent import provenance. Compatible targets that still share a reservation get independent records under their own permission checks. Historical evidence is not overwritten on subsequent evaluation.

The original selected target can be reconciled even when an older implementation already cleared its reservation binding. Unknown historical membership of other detached requests is not reconstructed from title similarity or presumed compatibility.

## Closing a reservation

A reservation closes only when the download is complete, the original selected target has fulfillment evidence and remains satisfied, and other targets have detached after their own evaluation. The selection becomes `fulfilled` and the fulfillment reservation becomes `released`. A single audit event records that transition.

`DownloadAttempt.state` continues to describe the transfer. Its sticky submission marker, receipts, observations and active torrent identity claims are retained. An uncertain or still-downloading attempt may have a satisfied request, but retains its committed reservation until the transfer is reconciled. No add, remove, retag, rename or seeding command is issued by fulfillment reconciliation.

Completed historical acquisitions no longer permanently block canonical book merging. Active or uncertain committed reservations still do. Merge history preserves the original selection and satisfaction evidence.

## Delivery and user interface

Successful ABS import confirmation atomically enqueues `acquisition.fulfillment`. The job acquires the canonical work lock and reevaluates that work's requests in a separate transaction, avoiding reversed importer/work lock order. The existing five-minute request sweep repairs missed observations and evaluates external inventory changes. Worker recovery includes the new idempotent task.

The completed download's **Check library availability** action performs scoped request reconciliation without contacting qBittorrent. It works with new dispatch disabled, respects recovery mode and account permissions, and has a one-minute cooldown. Other attempts retain their existing transfer-check action.

Activity shows whether fulfillment came from this import or an already-available library copy. Its `available_now` projection checks current scoped inventory, rather than trusting the historical record. Missing assets or revoked library grants therefore remove the current Available label without deleting acquisition history. No other request owner's requirements, private library identifiers or raw evidence are exposed through the download response.

## Migration and verification

Migration `0019_fulfillment` adds the ledger and fulfilled selection state. It does not assume that old completed transfers are available; normal reconciliation supplies current evidence. A populated ledger refuses lossy downgrade and requires a pre-upgrade backup for rollback.

Integration tests cover concurrent closure, shared generic/exact targets, existing-asset provenance, wrong medium/narrator, stale or incomplete assets, inaccessible libraries, disabled accounts, retained uncertain claims, legacy detached targets, dispatch-disabled recheck/cooldown, merge preservation and guarded downgrade. The two single-file acquisition-to-library tests now verify the actual import-entry link, reservation retirement and retained torrent claims through worker execution.

[Reviewed connection repair](DOWNLOAD-REPAIRS.md) now handles updated credential generations on the same route. Remaining work includes changed-endpoint/path reconciliation, member-to-administrator import handoff, reuse of verified pack files across different work requests, full per-child acquisition projections and live MAM/qBittorrent certification. If the original requester withdraws or loses access before satisfaction, the attempt stays committed for explicit resolution; another request's success is not misreported as that user's fulfillment. These limitations remain in the S05/S06 recovery and sharing gates.
