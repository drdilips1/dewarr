# Reusing a saved pack download

A later automatic request can join a compatible saved pack transfer owned by the same user. A new Hardcover/Goodreads list addition uses the same path as an explicit automatic acquisition. The book must independently pass source selection, catalog/manifest coverage, current request constraints and automatic route approval. Series membership or a matching torrent hash alone does not supply authorization.

## Transfer identity and receipts

The first supported join requires the same saved source artifact, medium, descriptor, source generation, downloader configuration, path mapping and destination. The application searches its own active transfer claims. It never adopts an unrelated qBittorrent torrent merely because the endpoint and hash match.

Queued, preflight, downloading and completed attempts can accept a qualifying new member. An uncertain or held existing attempt needs reconciliation first. The membership limit remains 100 selections per physical transfer. Different owners, routes/media and equivalent artifacts from different source records remain separate qualification work.

Each join saves an independent `acquisition.download.join` operation, explicitly naming its new selections, earlier members, artifact and original automatic operations. `DownloadMembership.join_operation_id` records that provenance. Original download command payloads remain unchanged. The join commits its target reservations and memberships without adding another transfer, capacity record, identity claim or torrent-submission job.

Transfer workers acquire a membership lock before their existing list/principal/canonical-work locks. The automatic coordinator acquires compatible transfer membership locks before locking old and new participants. Current child authority is revalidated inside the join transaction. A failed join leaves the original attempt intact; coordinator replay does not add a second member or submit again.

## Importing from completed transfers

If the original transfer has not completed, its ordinary inspection/import flow sees the new member when the files become ready. If it has completed, the join gets an independent `AutomaticImportContinuation` and `organization.reuse` job. This preserves the earlier automatic import's run and publication guards, including when its first book is still awaiting ABS confirmation.

The continuation verifies the current automatic-import approval and a surviving authorized joined request. Books already confirmed in the accessible library need no new publication. Before reusing the saved inspection, it makes a read-only qBittorrent observation and checks the recorded association, completion, exact file paths/sizes and total bytes. The publisher still verifies actual file identity and bytes before creating hardlinks; a successful downloader observation is not a replacement for filesystem checks.

Planning is confined to the join's authorized selection IDs. It skips qualifying files already reserved by an existing import, holds ambiguous groups and never imports an unrequested sibling just because that sibling was downloaded. Separate run IDs retain publication history. Publication rechecks the continuation's own approved route and joined request scope; another historical member cannot supply permission for an unrelated book.

The existing importer applies naming, per-version boundaries, source-preserving hardlinks and ABS item verification. Transfer completion and import handoff do not establish ownership. Each book becomes available only through confirmed accessible inventory; delayed scans do not cause another download.

## Recovery and Activity

Activity identifies members that use an existing download and shows the additional import's progress independently. A stopped or invalid saved-transfer verification appears as needing attention with **Recheck saved files**. The ordinary recheck action retains the same join and transfer, queues at most one active continuation and records a new verification start time without rewriting its creation timestamp.

Verification waits are bounded to 15 minutes per attempt. Unexpected job exhaustion becomes a held continuation through the existing scheduler; it does not silently reset the retry budget. A changed approval cannot be renewed by clicking recheck. Current route authorization or administrator file review is required. Publication failures are distinguished from transfer-verification failures and direct the user to administrator file review. Confirmed joined holdings appear as confirmed even when the underlying continuation retains its historical import-handoff state.

## Migration and qualification

Apply `0037_download_joins` before starting the new API and worker together. The migration adds a nullable join receipt to existing memberships and a separate continuation table; old memberships retain their original history. Empty downgrade is supported. Once joins or continuations exist, downgrade refuses to discard their history and requires a compatible pre-upgrade backup and external-state reconciliation.

Automated evidence includes queued/downloading/completed reuse, concurrent replay, uncertain-transfer holds, approval changes, stopped jobs, bounded verification and recheck deduplication. Real EPUB workflows use the API, worker, database, filesystem and synthetic qBittorrent/ABS services to cover explicit requests and overlapping lists, immediate/delayed library confirmation, saved-file failures and recovery. These assert one submission, independent receipts, separate import runs, unchanged first-book publication, two final fulfillments and original seeded bytes/inodes. The browser recovery display uses an explicit response fixture; it does not claim live-provider or browser-driven two-book acquisition qualification.

Exact commands/results and deployment evidence belong in [Implementation Status](IMPLEMENTATION-STATUS.md). The full PRD remains active: broader source equivalence, cross-owner/mixed-route reuse, inherited complete-series scope, versions/omnibus handling, native ABB, live-service qualification, discovery, production gates and S10 are not completed by this increment.
