# Administrator review of member downloads

Completed member-owned acquisitions now have an administrator review queue in Activity. This closes the authorization handoff from a member's download to the existing reviewed importer. It does not yet enable unattended import or automatic external-list acquisition.

## User flow

1. A member's associated transfer completes. Their Activity shows that administrator inspection is needed, without a link to an administrator-only inspection.
2. An administrator opens **Download import reviews** and chooses **Review this download**. The queue exposes the work, medium and operational status, not the member's private lists, account credentials or unrelated source searches.
3. The worker inspects the selected completed file/directory. The administrator opens the existing grouping, catalog matching and naming preview, freezes a plan and starts import into the acquisition's selected destination.
4. The importer preserves the seeded source, publishes the reviewed items and waits for Audiobookshelf confirmation. Fulfillment remains attached to the original member; their availability projection uses their current library grants.

If inspection fails, its assigned administrator can correct the issue and choose **Retry file inspection**. Retrying retains the failed inspection in history and creates one new authorized inspection. Another administrator may reassign an unstarted review. The previous inspection and plan lose authority; a stale worker cannot publish its snapshot. Reassignment is refused while an import reserves files or after any child has been published. Resolve or finish the existing import instead of moving responsibility during publication.

## Authority and durability

Migration `0021_handoffs` stores immutable assignment history with one active handoff per attempt. Inspection, reviewer receipt, assignment, audit and queued inspection commit together. Command-key replay and revision checks prevent duplicate or competing assignments. The original request, selected release and transfer claims are preserved; assigning review performs no downloader submission or torrent modification.

Requester authority is checked at claim, before inspection, before recording inspection results, when freezing/starting an import, and at the final publication guard. The destination must match the original acquisition. Medium, language, abridgment and an exact requested edition/recording remain constraints. Explicitly reviewed additional pack children may use their own catalog works in the same authorized medium and destination.

The final guard locks both principals in stable order before the existing backend/library locks. It holds the relevant grant and active request-reason rows through publication, so a concurrent revocation cannot commit between the authority check and rename. No acquisition work lock is taken from inside the publication guard. Withdrawal or loss of authority holds unpublished work without deleting source or already published files. A reviewer cannot replace the requester's grant with their own broader access.

Ordinary administrator-owned imports retain their existing behavior. General download, selection and source-artifact endpoints remain owner-only; the operational queue is a separate administrator capability. Recovery mode blocks new claims. A populated handoff history blocks lossy migration downgrade; use a pre-upgrade backup and external-state reconciliation for rollback.

## Verification and boundaries

- Sixteen PostgreSQL/API cases cover private projections, repeated/concurrent commands, competing reviewers, reassignment, failed-inspection retry, stale workers, permissions, mapping changes, recovery mode, queue rollback, destination/version rules, inspection-time revocation, actual database lock exclusion and the populated downgrade guard.
- Twelve single-file acquisition/import cases cover the original two administrator workflows, two member-to-administrator workflows, and eight final-publication revocations across root/nested downloads. Successful member cases confirm the asset, original request fulfillment, source-preserving hardlink, retained torrent claim and one submission. Reserved imports reject reassignment; wrong exact-version plans are rejected.
- The browser exercises claim failure/retry with the same command key, assigned-review navigation, reload, mobile layout and member exclusion using an explicitly mocked review API contract. Real review mutations and filesystem behavior are covered by the separate integration cases above.
- Existing native ABS scanner and application import certification is rerun as a regression; it does not certify a live MAM account or real qBittorrent transfer.

Remaining acquisition work includes automatic continuation for unambiguous supported imports, broader source-to-catalog/pack resolution, changed-endpoint/path recovery, withdrawn-owner resolution, shared-pack reuse and live-client qualification. This checkpoint does not close the complete S05 gate or the full PRD.
