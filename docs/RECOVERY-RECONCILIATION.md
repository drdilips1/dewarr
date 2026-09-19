# Reviewed recovery of existing transfers

This continues S09-02 / FR-36 / AT-25 on the existing `0042_recovery_scans` schema. It implements an operator-reviewed correction for transfers that already match saved download attempts. The app can recover an association even when a backup predates the persisted submission marker. It does not infer that an absent transfer may be resubmitted, adopt an unrelated torrent, resume automation or start an import.

## Operator workflow

1. Follow the [restore runbook](RECOVERY.md), start the API and explicit recovery worker, and run [read-only observations](RECOVERY-OBSERVATIONS.md).
2. Select matching download findings. Selection is explicit, persists across report pages and is bounded to 100 distinct transfers. Missing, conflicting and untracked findings are not eligible for this action.
3. Choose **Review selected transfers**. The preview names each transfer, its saved and observed states, and whether the restored record lacks a submission marker. Review the exact selection; preparing it changes no download association.
4. Choose **Record verified transfers**. The worker rechecks the downloader, then records the whole selected batch atomically or holds it without applying any association. A lost browser response can replay the exact command safely.
5. Read the outcome and run a new observation before further reconciliation. Applying corrections changes the local context, so earlier previews become stale. Downloads, imports, lists and ordinary application access remain paused.

The same recovery worker command remains in use:

```sh
BOOK_ENV_FILE=/private/recovery/book-search-rehearsal/restore.env \
uv run python -m app.jobs.worker --recovery
```

Its allowed tasks are now `recovery.scan`, `recovery.reconcile` and the separately reviewed [inventory refresh](RECOVERY-INVENTORY.md), `recovery.inventory`, plus [per-book publication recovery](RECOVERY-PUBLICATION.md), `recovery.publication`, and [external-list baselines](RECOVERY-LISTS.md), `recovery.lists`, plus [outbound evidence recovery](RECOVERY-OUTBOUND.md), `recovery.outbound`, and [historical request-command retirement](RECOVERY-COMMANDS.md), `recovery.commands`. It has no ordinary acquisition/import/list task, periodic registration or built-in history cleanup. The scan remains read-only with respect to domain and remote state. The reconciliation task performs explicitly reviewed **local database corrections**; its only remote requests are authentication and reads. The regular worker still refuses a restored installation.

## Reconciliation contract

| Boundary | Required behavior |
|---|---|
| Permission | Only the current active designated recovery administrator can prepare, accept or read a review. Both mutations require CSRF and idempotency keys. Current-checkpoint checks repeat in the worker. |
| Exact preview | Bind checkpoint, latest completed scan, selected finding IDs, finding signatures, local-context digest, connection and frozen-selection signatures to a revision. A review and its source observation must be fresh within 15 minutes. |
| Eligibility | Each finding is a matching saved attempt with verified hash identities, application tag, configured path and category. A physical attempt appears once even if several saved connections observe it. Untracked releases remain unresolved. |
| Fresh remote evidence | Re-read through the reviewed enabled connection. Full identities, tag set, save path, category, automatic-management setting, total bytes and file names/sizes must match the reviewed evidence. Download progress may advance; changed routing or file membership holds the batch. |
| Atomic application | Revalidate the checkpoint, operator, complete local context and finding/review signatures after I/O. Update all selected attempts, identity claims, conservative capacity accounting and audit records in one transaction. No database transaction stays open across remote requests. |
| Duplicate protection | Set the sticky external-submission marker only after fresh verification. Restore the attempt's identity claim only if no other attempt actively owns it. Do not overwrite a competing association. |
| Transfer state | Use the same transfer classification as ordinary monitoring. A valid complete payload can become Download complete; a size/file mismatch is held. A withdrawn request remains held even when a transfer is found. Completion never establishes ABS ownership. |
| Capacity | Preserve existing storage reservations and require ordinary capacity/import reconciliation later. Incomplete/held transfers retain a slot. A missing submission debit is conservatively dated at recovery observation time; the audit identifies this as recovery accounting, not a proven historical add time. |
| Continuation | Clear the obsolete transfer lease and polling time. Do not enqueue inspection, import, fulfillment, list writes or a second download. Existing queued ordinary jobs stay fenced by the persistent restore pause. |
| Retry and failure | Lease/token checks fence duplicate workers. An expired lease permits a fresh read; completed actions return without repeating remote reads or local effects. A failed/orphaned queue attempt loses its token, so a late worker cannot apply after a new scan starts. Changed or expired evidence needs a new observation/review. |

A completed action records an existing physical transfer; it does not grant the original requester new access or revive withdrawn request reasons. Future continuation must recheck the original requester's authority and all import/fulfillment requirements. Transport identity, media ownership and permission to publish remain separate facts.

The preview and acceptance receipts use the durable `Operation` ledger. The accepted action and queue job are committed together. The exact accepted revision, per-transfer audit, before/after submission state and applied results survive restart and application-state backup. Report/preview API projections exclude encrypted connections and internal signature inputs. Unexpected failures log only the operation ID and error class.

## API and deployment

- `POST /api/recovery/reconciliations`: prepare a preview from `scan_id` and `finding_ids`; requires an idempotency header.
- `GET /api/recovery/reconciliations/{identifier}`: current-checkpoint operator view of the exact review and result.
- `POST /api/recovery/reconciliations/{identifier}/accept`: accept the exact revision under a new idempotency header.
- `GET /api/recovery` adds the latest reconciliation view so the operator can reload and retain its outcome.

Deploy matching API, worker and generated frontend/client. No dependency, migration or external service is added. The recovery context now also fingerprints transfer memberships, identity claims and capacity rows. Older observation reports remain readable, but a fresh scan is required before they can authorize a new preview under this code. Preserve the current database/key/configuration backup before upgrading.

## Evidence and remaining work

Integration tests cover a transfer ahead of its saved submission marker, exact command replay, stale/expired reviews, changed local and remote context, revoked operator access, original queue preservation, lease recovery, atomic rollback, completion during review without import, conflicting identity ownership and late-worker fencing. Browser tests demonstrate explicit selection, preview, acceptance, durable reload, mobile layout and unchanged remote transfer records. Exact results are in [implementation status](IMPLEMENTATION-STATUS.md).

The complete S09-02 journey still needs reviewed resolution of untracked/conflicting effects, configuration/permission repair, staged/untracked/conflicting publication resolution, complete ABS inventory/permission qualification and list rebaseline, remaining unresolved outbound effects, stale queued-command handling and controlled resume. Reference-load, real external-service, supported-platform, populated restore/resume and RPO/RTO qualification remain open. This increment is not full restore acceptance or full PRD completion.
