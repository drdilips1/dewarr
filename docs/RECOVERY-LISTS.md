# Reviewed external-list baselines after restore

This implements the inbound-list baseline portion of S09-02 / FR-36 / AT-25. It builds on [read-only observations](RECOVERY-OBSERVATIONS.md) and the shared [reviewed recovery engine](RECOVERY-RECONCILIATION.md). It does not resolve uncertain sent writes or provide controlled resume.

## Operator workflow

1. Start the restored API and restricted recovery worker using the [restore runbook](RECOVERY.md). Run fresh read-only checks.
2. Filter to **External lists** and inspect the membership findings. Choose **Review list baseline for …** on a completed list observation. Failed reads, a changed Hardcover write-back owner/target or a nonfresh RSS response cannot offer a baseline.
3. Review the counts of visible, new, returned, absent and excluded observations. Hardcover supplies a verified complete membership snapshot. Goodreads RSS supplies only visible entries, so omissions cannot remove a saved member.
4. Choose **Record list baseline**. The worker reads the provider again, verifies the exact reviewed evidence and current local context, then commits the selected lists together. The API supports 1–100 distinct subscriptions; the UI reviews one list at a time.
5. Recovered additions are available for browsing and deliberate catch-up selection after recovery. Acquisition and outbound list writes stay paused. Owners must use the existing policy-preview and write-back-confirmation flows before reactivating them. Synchronization has no automatic due time until a later explicit owner action or supported recovery/resume decision.

## Membership and acquisition rules

| Evidence | Local result |
|---|---|
| New or returned external member | Use the ordinary provider-aware catalog matching and private provisional-book rules. Preserve existing matches and exclusions. Add a nonexcluded member to its local list once. |
| Missing from a complete Hardcover snapshot | Mark the external observation absent. Remove only externally supplied membership when no other current, nonexcluded observation supports it. Preserve manually added entries. |
| Omitted from Goodreads RSS | Preserve the observation and local entry. The feed is not proof of a complete shelf or a deletion. |
| Last external membership removed and no manual entry remains | Deactivate only this list's request reasons and mark its membership episode removed. Preserve manual reasons and other lists' reasons. |
| Existing acquisition or reservation | Preserve its historical association. Do not reevaluate availability or release a reservation using unqualified restored inventory; current request/transfer reconciliation remains a separate obligation. |
| Recovered additions under an existing policy | Set the new baseline and create baseline monitoring rows without acquisition intents. Preserve existing request histories. Clear book polling times and pause the policy with a new revision. |
| Existing write-back policy | Disable it, advance its generation and clear its old confirmation. Preserve uncertain outbound operations and their sent-attempt evidence unchanged. |

Ordinary list removal now shares a pure reason-deactivation helper with recovery; its normal wrapper still evaluates affected requests. Recovery deliberately defers that evaluation. Removing a member never deletes media or asks the downloader to remove files.

The saved baseline time distinguishes catch-up from future membership. The monitoring service classifies recovered members as baseline, while a genuinely later addition can become wanted under a subsequently authorized policy. Baseline classification alone grants no dispatch authority. Existing exclusions, canonical book matching, local additions and independent request reasons remain meaningful.

## Freshness, atomicity and stale work

The read-only collector is shared by observations and accepted baseline actions. Hardcover keeps its bounded two-pass membership verification; RSS is fetched without restored conditional-cache validators. The Goodreads budget permits one short wait of up to 30 seconds, then holds if access is still unavailable. No provider write is made.

A preview binds the checkpoint, current designated administrator, latest completed scan, selected finding signatures, membership digest, local context and 15-minute expiry. The worker rechecks current owner/subscription access, reads outside the application transaction, compares the exact provider snapshot, and repeats the shared token/checkpoint/context guard before publication. A failure rolls back all selected list, catalog, membership, policy and audit updates.

The recovery context includes list entries, catalog bindings/source identity, acquisition policies/books/intents/reasons/reservations/targets and pending list-command projections. Old observation reports remain readable but need a fresh scan before authorizing changes under this build.

Each corrected subscription advances generation, drops its old run token, lease, operation association and automatic due time, and marks a previously running/queued sync as needing attention while retaining its staged evidence. Its old worker can no longer apply through ordinary subscription-context checks. The action similarly disconnects an old acquisition-policy tick. Broader historical request/series commands and uncertain outbound attempts still need their separate recovery packet before resume.

The dedicated worker registry contains exactly `recovery.scan`, `recovery.reconcile`, `recovery.inventory`, `recovery.publication` and `recovery.lists`. It has no ordinary acquisition, list-write, periodic scheduling or history-cleanup tasks. All accepted recovery actions exclude one another. A completed retry makes no further network calls or changes.

## API and deployment

- `POST /api/recovery/list-reconciliations`: prepare a preview from `scan_id` and `finding_ids`, with an idempotency header.
- `GET /api/recovery/list-reconciliations/{identifier}`: read the current operator's exact review and result.
- `POST /api/recovery/list-reconciliations/{identifier}/accept`: accept its revision with a new idempotency header.
- `GET /api/recovery`: includes the latest list review for reload.

Deploy matching API, worker and generated client on schema `0042_recovery_scans`. No runtime dependency or migration is introduced. Keep the verified database/key/configuration/journal bundle from before deployment. The persistent restore pause and disabled development dispatch remain unchanged.

## Qualification boundary

The synthetic tests cover both providers, omissions versus complete removals, exclusions/manual membership, catch-up versus future additions, independent request reasons, retained reservations/outbound evidence, changed authority/evidence, stale synchronization leases, command replay and atomic rollback. Browser evidence covers the explicit operator workflow, durable reload, mobile layout and unchanged synthetic external media/download records. The browser pause fixture predates its checkpoint and keeps its dedicated RSS subscription unscheduled; it is not an actual offline restore. Restricted restored-worker tests remain separate.

Exact results are recorded in [implementation status](IMPLEMENTATION-STATUS.md). Uncertain outbound reconciliation, remaining conflicting/untracked effects, permission/configuration repair, historical-command resolution and controlled resume still require implementation and qualification. Actual-service/platform, full populated restore/resume, reference-load and RPO/RTO gates remain open; S09 and the full PRD are not complete.
