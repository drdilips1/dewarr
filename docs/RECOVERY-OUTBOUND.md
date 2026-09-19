# Reviewed recovery of outbound Hardcover changes

This implements the outbound-ledger portion of S09-02 / FR-36 / AT-25. It follows [read-only observations](RECOVERY-OBSERVATIONS.md) and uses the [shared recovery review engine](RECOVERY-RECONCILIATION.md). The [inbound baseline action](RECOVERY-LISTS.md) remains separate: reconciling a write does not import remote list members, activate acquisition or resume automation.

## Operator workflow

1. Start the restored API and restricted recovery worker with the persistent checkpoint active. Sign in as its designated operator.
2. Run read-only checks and filter to External lists. Unsettled outbound commands are checked independently of the subscription, including disabled or detached subscriptions.
3. Choose **Review outbound change**. The preview shows the original book/list target, requested membership, saved command state, presence of a sent attempt and the proposed outcome.
4. Choose **Record outbound evidence**. The worker reads the original target again through the owner's current connected account, requires exactly the reviewed membership identities, then records the result atomically.
5. Run fresh observations before another recovery correction. Unresolved effects stay held. Write-back stays disabled pending a new owner review after recovery; no old command is replayed.

## Outcome rules

| Current evidence | Recorded outcome |
| --- | --- |
| Desired membership is visible: present for an add, absent for a removal | `desired-observed`: complete the saved command, clear its pending attempt, retain prior attempt evidence in the receipt and audit. This proves current membership, not that this application caused the change. |
| The exact attempted removal row is absent, but another membership for the book remains | `attempt-observed`: clear that attempt, retain the command as attention. Do not delete another edition or a newly re-added membership. |
| A sent add is still absent or a sent removal row remains present | `uncertain`: retain the exact pending attempt and mark attention. Absence of the desired effect cannot establish failure; a delayed remote effect remains possible. |
| Current membership differs and the restored ledger has no sent marker | `difference-held`: mark attention without submitting anything. A backup may predate the submission marker. Current membership never authorizes replay of that historical command. |
| Invalid target/base/attempt, inaccessible account/list, changed original remote owner or failed provider read | No eligible correction. Preserve the original command and report the issue. |

Original owner, list and book IDs must agree with the saved base observation. A pending removal must identify a row from that exact base; an empty/malformed attempt is not treated as an unsent command. Hardcover's existing strict owned-list/membership reader bounds coverage at 100 membership rows and rejects malformed or incomplete responses. All reads are uncached and bounded by its 45-second request deadline. Goodreads RSS cannot authorize outbound writes and is not used here.

Credential rotation is allowed when the current enabled account independently verifies the same original remote owner/list. The app does not follow a newly configured subscription to a different target. An inactive owner, viewer role or unavailable account blocks the read. Detached history remains recoverable when its original account and target are verifiable.

## Atomicity, authority and replay prevention

Previews and acceptances use the shared designated-operator, CSRF, exact idempotency, 15-minute expiry, newest-completed-scan and full local-context checks. Each review accepts 1–100 distinct eligible findings. The final transaction rechecks the checkpoint, actor, evidence and lease after network I/O. A changed provider membership, command, account, local context or recovery lease holds the action without applying partial corrections.

The outbound context now includes remote write-back leases. Applying a result retains the original payload, sequence, desired state and attempt count, adds an observation/receipt, and preserves the prior status/attempt in an audit. A matching old remote lease is expired and its token rotated. The current associated write-back policy is disabled, its generation advanced and its old confirmation cleared. A lease belonging to another command is not changed.

Saved commands become terminal (`completed` or `attention`) and receive `reconcile_only=true`. Ordinary workers cannot resume their mutations, including a worker that was waiting on a read when recovery invalidated its lease. Explicit future owner reconciliation can observe uncertainty without sending a mutation; applying a new difference requires the existing fresh owner review. A multi-command failure rolls back all command, lease, policy and audit updates. Replaying a completed recovery job performs no additional reads or changes.

No list mutation, inbound membership change, downloader action, file operation, acquisition enqueue or automatic resume occurs. Original ordinary queue rows remain untouched behind the persistent recovery fence. An uncertain result is recorded as unresolved, never counted as complete restore acceptance.

## API and deployment

- `POST /api/recovery/outbound-reconciliations`: prepare a review from `scan_id` and `finding_ids`, with an idempotency header.
- `GET /api/recovery/outbound-reconciliations/{identifier}`: read the current operator's review and outcome.
- `POST /api/recovery/outbound-reconciliations/{identifier}/accept`: accept its exact revision with a new idempotency header.
- `GET /api/recovery`: returns the latest outbound review for reload.

The restricted worker registers seven tasks: `recovery.scan`, `recovery.reconcile`, `recovery.inventory`, `recovery.publication`, `recovery.lists`, `recovery.outbound` and `recovery.commands`. It contains no ordinary mutations, periodic scheduling or history cleanup. Accepted recovery actions exclude one another. Observation reports created before this context expansion need a fresh scan to authorize corrections.

Deploy matching API, worker and generated client on schema `0042_recovery_scans`. No migration or runtime dependency is added. Preserve a verified database/key/configuration/journal backup before updating the running services.

## Qualification boundary

Tests cover lost responses, backups without submission markers, retained uncertainty, exact and partial edition removals, re-added membership, malformed history, credential rotation, detached subscriptions, changed local/remote evidence, late workers, command replay, authorization and atomic multi-command rollback. Browser evidence uses an isolated paused fixture and synthetic Hardcover service; it is separate from actual restored-worker isolation tests and live account qualification.

See [implementation status](IMPLEMENTATION-STATUS.md) for exact results. Historical request/series commands, remaining conflicting or untracked effects, intended permission/configuration repair, controlled resume and a complete populated restore rehearsal remain open. Actual-service/platform qualification, reference-load and RPO/RTO measurements and all earlier unmet S00–S10 obligations remain required. Neither S09 nor the full PRD is complete.
