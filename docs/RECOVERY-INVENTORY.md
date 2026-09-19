# Reviewed library inventory after restore

This implements the Audiobookshelf inventory portion of S09-02 / FR-36 / AT-25. It follows [read-only observations](RECOVERY-OBSERVATIONS.md) and complements [matching-transfer recovery](RECOVERY-RECONCILIATION.md). Restored ownership is historical until freshly checked; this action records current library evidence while the restore checkpoint remains active. It does not resume any automation.

## Operator workflow

1. Start the restored API and restricted recovery worker as described in the [restore runbook](RECOVERY.md). Run fresh read-only checks.
2. Filter observations to **Media libraries**. Inspect the per-item findings, then choose **Review inventory for …** on a complete backend observation. A failed or partial observation cannot prepare this action.
3. Review current item counts, audio/ebook counts, absent saved media, newly visible libraries and inaccessible saved libraries. One backend is reconciled as a whole so an omitted item is interpreted against a complete observation. The API also supports an explicitly selected batch of up to 100 distinct backend findings.
4. Choose **Record current inventory**. The worker re-reads complete current membership, expanded items and permissions, then updates the selected backends atomically. Changed remote evidence or local context holds the action without publishing a partial inventory.
5. Read the saved outcome. Run fresh observations before preparing another recovery action, since the restored context has changed. Results survive reload and backup.

The shared review engine enforces current designated-operator access, CSRF, exact idempotent commands, a revision-bound preview, 15-minute observation freshness, expiring worker leases and a final token/context check. Transfer and inventory recovery actions exclude one another while queued/running; a new observation cannot race an accepted action. Completed retries do not repeat network reads or writes. Expected upstream failures are summarized; unexpected logs contain only operation ID and error class.

## Inventory rules

| Evidence | Local result |
|---|---|
| Complete unchanged media | Reuse ordinary ABS work/version resolution and preserve manual matching. Establish availability only for complete, verified coverage in an accessible library. |
| New item | Resolve through the same catalog identity service; ambiguous work/version evidence stays unresolved. A tracker release never becomes a catalog edition. |
| Changed narration, edition or reviewed collection content | Apply existing version/containment checks. Changed recording identity or collection file evidence requires review and cannot silently retain verified ownership. |
| Previously reviewed equivalent ebook formats | Retain only the existing importer-verified formats whose file evidence still agrees, using normal inventory rules. |
| Saved item absent from a visible library | Mark missing-suspected under unchanged scope, retain prior missing-confirmed status where applicable, or mark scope-unavailable when the account scope changed. No file deletion or replacement is authorized. |
| Item observed in another accessible library | Mark the prior asset moved and establish the new library's asset. Existing member grants do not follow it automatically. |
| Saved library no longer accessible | Set the library inaccessible and its nonsuppressed assets scope-unavailable. Lost access does not establish that files were deleted. |
| Newly visible library | Create its library/inventory records without new member grants. Administrators retain their ordinary administrative view. |
| Explicitly suppressed asset | Preserve intentionally-removed state even if the backend still returns it. |

The action preserves local user grants. It does not certify that historical grants are still the household's intended policy; configuration/permission repair and the final resume decision remain separate. It makes no ABS scan request, metadata update, file operation, qBittorrent mutation, list mutation or acquisition/import/fulfillment enqueue. Old ordinary jobs remain paused. Missing and unavailable observations feed the existing acquisition hold/replacement rules; this action never turns them into a request to download.

A completed `InventoryRun` and audit record identify the recovery review and observed scope. Historical collecting runs are marked interrupted and their prior connection lease is cleared, so a late inventory publisher cannot reuse its old lease. Staged observations remain evidence. Historical queued inventory commands still require the later controlled-resume fence; updating an inventory is not authority to replay an old job.

## Boundaries and deployment

The restricted worker registers exactly `recovery.scan`, `recovery.reconcile` and `recovery.inventory`. It has no ordinary or periodic task and no built-in history cleanup. Use `python -m app.jobs.worker --recovery` only with a restored checkpoint. Normal installations use the ordinary worker.

New APIs:

- `POST /api/recovery/inventory-reconciliations`: prepare selected complete backend findings with `scan_id`, `finding_ids` and an idempotency header.
- `GET /api/recovery/inventory-reconciliations/{identifier}`: read the current operator/checkpoint's review and result.
- `POST /api/recovery/inventory-reconciliations/{identifier}/accept`: accept its exact revision using a separate idempotency header.
- `GET /api/recovery` includes the latest inventory reconciliation alongside transfer recovery.

The current schema remains `0042_recovery_scans`; no dependency or migration is added. Back up and deploy matching API, worker and generated frontend. Fresh observations are required after this upgrade: the context now also covers grants, work/version identities, provider matches and asset coverage. Earlier reports remain readable but cannot authorize the new inventory action.

Remote collection retains the observation limits: at most 100 libraries per backend, 10,000 items per library and the bounded local context/report limits. A backend re-read has a 10-minute timeout within the shared 15-minute batch deadline. External pagination is not an atomic server snapshot; repeated membership/update-marker and permission checks detect observed changes, and the second complete read must match the reviewed metadata/file evidence. Qualification at 50,000 assets, supported real services, containers, RPO/RTO and full restore/resume remains outstanding.

See [implementation status](IMPLEMENTATION-STATUS.md) for actual verification. Remaining recovery work includes publication children, untracked/conflicting transfers, configuration repair, list/outbound rebaseline, historical-command handling and controlled resume. The full S09 and PRD gates remain open.
