# Reviewed retirement of historical request commands

This implements the request-batch and acquisition-controller part of S09-02 / FR-36 / AT-25. It uses the [shared recovery review engine](RECOVERY-RECONCILIATION.md) while the persistent restore checkpoint remains active. It complements [external list baselines](RECOVERY-LISTS.md) and [outbound evidence recovery](RECOVERY-OUTBOUND.md).

Subsequent [queue protection](RECOVERY-QUEUE.md) and [saved-approval protection](RECOVERY-APPROVALS.md) prevent historical execution and approval reuse on schema 0044. The schema-0042 deployment and remaining-work notes below describe this earlier increment; current-authority activation and controlled resume remain open.

The same review engine now supports [selective automation pause](RECOVERY-AUTOMATION.md) for automatic imports, inbound subscriptions and Hardcover write-back. These actions preserve external-effect evidence and do not resume automation.

## Operator workflow

1. Run read-only checks and filter to Recovery status. Eligible historical batches, activation previews, acquisition checks and active list policies appear as separate findings.
2. Choose **Review historical command**. The preview identifies the selected saved state and whether the action retires a command, disables a series controller or pauses a list policy.
3. Choose **Retire selected commands**. The worker rechecks the exact review and current local context, then records all selected retirements atomically.
4. Existing wanted books, independent reasons, reservations, download/import state and completed batch receipts stay intact. Unselected commands remain unresolved. No automation resumes.
5. After supported recovery completion, owners must create fresh previews for unsaved requests or acquisition reactivation. An old idempotency key returns its retired receipt; it does not authorize execution again.

This action removes execution authority. It makes no external request and does not establish that any transfer, file or membership effect happened. It can retire local commands when external providers are unavailable; those blocked external findings remain unresolved.

## Exact scope and behavior

| Selected target | Effect |
| --- | --- |
| Uncompleted `lists.requests` or `series.requests` batch | Set cancelled with a recovery-retirement receipt. Reject reuse of its prior approval and stop its worker before reading command contents. Do not invoke normal request cancellation, which can withdraw existing reasons. |
| Uncompleted `lists.policy-preview` | Retire the activation approval. The owner must create a new preview; even a still-unexpired old preview cannot reactivate acquisition. |
| Uncompleted `lists.acquire` check | Retire this historical worker command. Its marker prevents execution even if the list is deliberately reactivated later. |
| Enabled or queued/running `series.acquire` controller | Disable it, advance its authorization revision, clear controller/book due times and mark held. Preserve per-book progress, accepted parent receipt and request reasons. Save prior scheduling timestamps in the recovery audit/receipt. Its retry route requires a new owner preview. |
| Active list acquisition policy | Disable it and advance its revision. Clear monitored-book due times without changing their progress, states or request IDs. Preserve the required historical policy due timestamp; the ordinary scheduler requires an active policy. A fresh owner activation replaces its schedule. |
| Completed or already-cancelled request batch / completed activation preview | No retirement finding. Preserve its durable receipt and existing wanted records. |

Policy pause and historical tick retirement are explicit separate selections. Retiring a tick alone does not disable its policy, and pausing a policy does not claim to have retired every queued job. The final controlled-resume process must account for all historical work before clearing its fence.

## State and replay guarantees

The shared engine binds the designated operator, active checkpoint, newest completed observation, current command/policy context, exact finding signatures and a 15-minute review deadline. Preparations and acceptances have separate idempotency keys; each batch contains 1–100 distinct eligible entities. Selected updates, receipts and audits commit together or roll back together.

Recovery context now projects `series.requests` and `series.acquire` in addition to existing list-command history, with command kind, payload, owner, status and job association. Ordinary batch start/activation paths explicitly reject a recovery-retired receipt. Ordinary list/series workers stop before executing a retired command. A list tick rechecks the receipt under its operation lock after waiting for list/policy authority, including missing-policy or revoked-access exits, so a pre-retirement read cannot overwrite the decision. The existing policy/controller revision checks invalidate prior descendant automatic-acquisition authority.

Completed request receipts are distinct from authority to start acquisition. This action never calls acquisition evaluation or reason withdrawal: manual, list and series reasons and planned/selected/committed reservations remain unchanged. It does not resubmit or cancel a remote download, release a reservation based on absence, change library availability, alter files, write a list or enqueue ordinary work. Original queue rows remain evidence behind the persistent restore fence.

## API and deployment

- `POST /api/recovery/command-reconciliations`: prepare from `scan_id` and `finding_ids`, with an idempotency header.
- `GET /api/recovery/command-reconciliations/{identifier}`: read the operator's review and outcomes.
- `POST /api/recovery/command-reconciliations/{identifier}/accept`: accept its exact revision with a separate idempotency header.
- `GET /api/recovery`: includes the latest command review for reload.

The restricted worker adds `recovery.commands` to the six existing recovery tasks; no ordinary tasks or periodic cleanup are registered. Accepted actions exclude one another. Older reports require fresh observations after the expanded command-context projection. Deploy matching API, worker and generated client on unchanged schema `0042_recovery_scans`; no new dependency or migration is required.

## Remaining recovery work

This is not a global queue retirement or resume control. Other historical approvals/jobs—including source/download selections, import work, CSV/import previews, list comparisons and series-scope approvals—still require the final supported fence and fresh-authority rules. Requests already recorded remain wanted; their reservations and potential external effects need the appropriate observed-state decisions before they can run.

Unresolved effects, permission/configuration repair, complete populated restore/resume, supported-platform and actual-service qualification, reference-load and RPO/RTO gates remain open. See [implementation status](IMPLEMENTATION-STATUS.md) for exact test, browser and deployment evidence. All unmet S00–S10 requirements remain in scope; neither S09 nor the full PRD is complete.
