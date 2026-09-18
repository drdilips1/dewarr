# Acquisition requests and inventory satisfaction

This implements part of S01 and the request contracts needed by S05–S07. It saves wanted media and evaluates fulfillment against the current library. Native MAM browsing/artifacts, reviewed release selection and manual importing now have separate implementations. An opt-in durable transfer workflow now consumes selections; the complete acquisition/import gate, quality profiles and external-list automation remain unfinished. A saved request is not a torrent submission.

## Persisted model

- `AcquisitionIntent`: an owner's normalized work/media/version/destination requirements. Equivalent specifications reuse one intent.
- `AcquisitionReason`: an independent manual or owned-local-list reason. Removing a membership or deleting a list withdraws only that list's reason; history remains available.
- `AcquisitionTarget`: ebook, audio, or either. Both creates two independently satisfied targets. Each target records state and any confirmed satisfying asset.
- `AcquisitionReservation`: a planned, compatible fulfillment shared by targets with the same destination scope. Unconfigured destinations are isolated by owner. Selected reservations have a frozen candidate/route handoff; committed reservations are retained by the [download-attempt ledger](DOWNLOAD-ATTEMPTS.md), including uncertain submissions. See [Release selection](RELEASE-SELECTION.md).

Exact edition/recording IDs require accepted catalog or accessible inventory evidence. An arbitrary UUID is insufficient. Required language, known abridgment and standalone-copy constraints are checked independently. An unknown language cannot satisfy an explicit required language. An inseparable multi-work asset cannot satisfy a standalone-copy request.

Overall work ownership remains separate: a complete ebook or audiobook can keep the work's in-library badge while another medium or recording remains wanted. Companion documents and unverified coverage do not satisfy targets.

## States and reconciliation

| State | Meaning |
|---|---|
| `wanted` | No compatible accessible complete asset or relevant missing-history hold; a planned reservation may be used later |
| `satisfied` | A present, complete, verified and accessible asset satisfies this target |
| `awaiting-inventory` | Compatible historical inventory is stale, suspected missing or unavailable in the current scope |
| `paused` | Confirmed/intentionally removed media needs an explicit replacement decision, or request authorization needs attention |
| `cancelled` | No active request reasons remain |

Request submission evaluates immediately and atomically creates an `acquisition.evaluate` operation/job. Workers recheck current authority and inventory under a per-work transaction lock. GET and preview endpoints derive fresh user-visible results; they never dispatch work.

The periodic `acquisition.reconcile` task runs every five minutes while the worker is healthy. It repairs persisted target/reservation state after inventory, permissions, list membership or metadata changes, including requests whose original evaluation operation already completed. It uses a finite UUID high-water mark, keyset pages of 100 IDs and one transaction per intent. Retry starts a safe reevaluation, not an external side effect. Newly created requests evaluate during submission even if inserted behind a running sweep's cursor. Recovery mode suppresses reconciliation and new request submission.

The sweep is eventual repair, not authorization for future dispatch. Selection and downloading must recheck current inventory, grants, suppressions and requirements immediately before external effects. Performance on the full PRD reference dataset remains an S09 gate; the current tests prove traversal beyond one page, not production capacity.

## Concurrency and privacy

An idempotency key binds to the actor, operation kind and canonical command. A different command under the same key returns a conflict. Replaying a completed command cannot reactivate a cancelled reason; a new deliberate command can. Account authority is refreshed after acquiring the command lock.

List-backed submission acquires the list row before the work lock, matching list deletion/membership removal. Reservation mutations serialize under the work lock. The domain changes and Procrastinate enqueue share a database transaction; rollback cannot leave an orphan job.

Compatible broad and exact requests can share a planned reservation. Its requirements are their intersection: an incompatible recording or language creates a separate reservation. Cancelling a stricter requirement recomputes the intersection from remaining active wanted targets. Cancelling the last requirement releases the reservation. Reconciliation never deletes media or client transfers.

Shared destination reservations do not share request API access. Users receive only their own intents, list labels and reasons. Only granted libraries can satisfy their requests. Reservation identifiers, other users' reasons and private holdings are not included in response payloads.

Canonical work grouping uses a shared graph lock followed by the canonical work lock for reservation mutations. Grouping/undo takes the exclusive graph lock and rebuilds affected planned reservations. Historical intents retain origin IDs; new intents bind to the chosen canonical record, so undo preserves their meaning. Fulfillment checks include accessible assets across the canonical group. See [Identity corrections](IDENTITY-CORRECTIONS.md).

Reviewed selection adds a `selected` state and immutable requirements/route handoff. Broader compatible targets may share it. A target with stricter download restrictions can share an inspected release only when its frozen manifest proves those restrictions; it cannot rewrite the selection. The attempt ledger supplies the distinct external-side-effect boundary. A reservation that already caused a client mutation must never use preparation cancellation or planned-rule recomputation.

## Request download restrictions

`RequestSpec.download_constraints` optionally stores `blocked_formats` and `maximum_bytes`. Empty restrictions are normalized away so existing request fingerprints and idempotency receipts remain compatible. Format names are normalized and the size ceiling uses whole-torrent bytes, including padding and extras. Restrictions that leave no possible primary format for a requested medium are rejected.

Each intent retains its own restrictions. Compatible planned reservations combine blocked formats and take the lowest size ceiling; withdrawing a reason recomputes the remaining unselected requirements. Incompatible format sets require separate reservations. Manual selection and automatic eligibility both enforce the shared restrictions. The selected profile carries them into actual-file validation, so a later profile change or request withdrawal cannot relax the frozen import decision.

These are acquisition restrictions, not ownership criteria or soft ranking preferences. An existing complete accessible ebook still satisfies an ebook request even when its format is excluded from future downloads. This avoids silently turning a preference change into a replacement request. Source order, format preference order and seed ranking remain in the release profile.

The API accepts restrictions for individual requests and reviewed list batches. Wanted history, saved list previews and automatic-selection receipts display them. Standing list policies will snapshot the selected profile's hard limits into these fields; policy activation and scheduled acquisition remain unfinished. This checkpoint does not add a second profile editor to the request form.

Migration `0029_request_constraints` adds the persisted JSON contract. Legacy requests survive upgrade and replay. Downgrade is refused after new restriction-bearing intent, reservation or selection records exist; restore the pre-upgrade backup instead of discarding their meaning.

## API and UI

- `POST /api/requests/preview`: evaluate a specification without persistence.
- `POST /api/requests`: save an authorized request with `Idempotency-Key`; return its durable evaluation operation.
- `GET /api/requests`: owner-scoped, paginated request listing, optionally filtered by work.
- `GET /api/requests/{id}`: owner-scoped current projection.
- `DELETE /api/requests/{id}/reasons/{reason_id}`: withdraw one reason and recompute fulfillment.

Book detail provides Wanted media, explicit ebook/audio/both/either selection, inventory preview, saved-request history and reason cancellation. Edition/recording cards can populate an exact-version request. Either asks which medium to prefer when both are missing; either existing full medium still satisfies it. Saving a wanted request does not download it. The Sources panel provides the separate [automatic selection and download](AUTOMATIC-SELECTION.md) action for qualified routes.

## Verification and remaining work

Integration cases cover normalized/repeated/concurrent commands, transaction rollback and real worker redelivery, recording/language incompatibility, both/either ownership, uncertain/missing inventory, omnibus restrictions, list deletion/cancellation, cross-account destination sharing, grant revocation, periodic repair and recovery mode. The browser journey saves, reloads, cancels and requests an exact recording at desktop/mobile widths.

Migration `0006_acquisition` adds the four tables. Empty-schema downgrade is supported. Downgrade with saved intents is refused because the previous schema cannot preserve request history; restore a pre-upgrade backup instead.

Next dependencies include canonical work/version corrections involving these records, explicit replacement/suppression commands, source/format profiles and frozen selection, qBittorrent submission reconciliation, per-child imports and external membership reasons. Those features must use these contracts rather than introducing an independent list downloader.
