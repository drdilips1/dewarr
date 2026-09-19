# Review existing Hardcover list differences

This extends [optional Hardcover write-back](LIST-WRITEBACK.md) within S08-03 / FR-34 / AT-23. The initial enablement preview now compares existing memberships before future write-back can be enabled. An enabled list also offers **Compare existing books**. Comparison alone changes neither list and sends no outbound mutation.

## User flow

1. Expand **Sync local changes back to Hardcover** and choose **Review enablement**. The app verifies remote ownership and queues a read-only comparison. Wait for the complete result before choosing **Enable future changes**.
2. Review counts and pages for books only on this local list, only on Hardcover, on both lists, or needing matching. Search and filter without losing selected row identities across pages. Selection starts empty and is limited to 100 differences per action.
3. **Apply local state to selected** queues the selected additions/removals through the existing write-back worker. It requires current enabled write-back. The worker reads current remote membership again before any mutation, and still holds conflicts or uncertain earlier effects.
4. **Keep Hardcover state for selected** applies the reviewed remote state to this local list without emitting an outbound echo. A previously unknown remote book becomes a private provisional catalog record only after this explicit selection. A remote book without a matched catalog identity cannot authorize a remote removal.
5. Refresh the comparison after applying a selection. A comparison can be consumed once; the same command receipt replays without another change. Further batches use current memberships and identities.

Keeping remote state is a local curation command. Existing acquisition policies can subsequently act on resulting local additions under their own rules; this command does not create a separate downloader path. Membership changes do not delete library files or alter reading progress. Work availability and exact-version requirements remain independent.

Books with competing or changed accepted identifiers remain unresolved. Multiple remote edition memberships for one Hardcover book produce one work-level row with the actual membership IDs retained. Groups beyond the supported 100 memberships per book are held individually while unrelated books remain reviewable. Title similarity does not establish an external identity or prove a book absent.

## Snapshot and consistency contract

The comparison reuses the existing Hardcover keyset page adapter and two-pass verification. A complete matching second pass is required before publishing rows. It does not call the inbound subscriber's membership application step: exclusions, inbound timestamps and local entries are preserved by the comparison itself. Remote ownership must match the account verified in the enablement preview.

The worker freezes the local content revision, account generation, subscription ID and external list ID. Short transactions and a persisted lease protect each page; network reads occur outside database locks. A waiting worker refreshes cached operation state after acquiring the list lock, and only the current lease token can publish progress. Account/list changes or incomplete remote data produce a failed/stale comparison, never a fabricated empty remote list. Worker recovery and rate limiting reuse the existing queue and account budget.

Local and remote catalog mappings use accepted provider metadata, the owner's catalog bindings and unchanged subscription observations, resolved through canonical work identities. Set-based queries build this bounded identity projection. Reads and selected actions recheck current scope and the identity fingerprint; a merge, changed binding, access revocation, membership edit or reordered list invalidates an old review.

Comparisons support up to 5,000 local books and the existing 5,000 remote-membership limit. They can contain up to 10,000 rows. These are explicit limits, not silent truncation. Completed rows have separate storage and paged/searchable API responses; the identity projection still checks the bounded relevant catalog on each read/action. This is not a claim that the full NFR reference-load benchmark has passed.

A completed snapshot is reviewable for 15 minutes. An unfinished comparison also has a 15-minute execution deadline. Initial enablement retains its separate ten-minute ownership-preview deadline. Selected rows are validated together, including unresolved previous writes, before local edits or outbound intentions commit. A queue insertion failure rolls back the entire selected batch. Policy generation is checked explicitly; enabling future write-back does not implicitly select the snapshot's historic differences.

There is no atomic transaction with Hardcover. Another client may edit remotely after snapshot verification. Outbound actions re-observe and perform only the narrowly authorized membership changes; **Keep Hardcover state** adopts the displayed verified snapshot once. Neither action promises continuous whole-list mirroring or an upstream compare-and-swap guarantee.

## API and deployment

`POST /api/lists/{list_id}/writeback/preview` now returns `comparison_id` and schedules `lists.writeback.compare`. `GET /api/lists/{list_id}/writeback/differences/{comparison_id}` exposes status, counts and bounded pages with state/search filters. `POST .../{comparison_id}/resolve` accepts explicit row UUIDs, action, expected policy generation and an idempotency key. All controls, rows and receipts are private to the local list owner; sharing a list does not share provider authority.

Old ownership previews without a comparison cannot enable write-back. API clients must request a new preview, wait for its comparison to complete, then submit the ordinary configure request. Existing enabled policies continue to use their established future-change behavior.

Migration `0040_list_comparisons` adds `list_comparison_rows`; metadata/progress and receipts use the existing operation ledger. Back up the database, key and configuration, stop old API/worker processes, migrate, deploy matching frontend/API/worker builds and restart both backend processes. No extra service, dependency or secret is introduced. Populated comparison history prevents destructive downgrade and requires backup-based rollback. Download dispatch remains separately controlled.

Recovery mode holds comparison workers and selected reconciliation. Full populated backup/restore and actual Hardcover account compatibility remain release qualification gates. The current contract does not introduce automatic available-list or reading-status writes. Exact automated evidence and deployment checks are recorded in [implementation status](IMPLEMENTATION-STATUS.md).
