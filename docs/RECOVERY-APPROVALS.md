# Saved approvals after a restore

This implements the saved-preview portion of S09-02 / FR-36 / AT-25. [Queue protection](RECOVERY-QUEUE.md) prevents job replay; this additional boundary prevents an old approval from creating a new command through an ordinary API. It does not provide controlled resume or activate historical wanted books.

## Durable evidence

Schema `0044_recovery_approvals` extends the existing sealed boundary with exact IDs for acquisition selections, frozen import plans and CSV previews. Saved ordinary operations already cover list requests, acquisition-policy previews, series requests/controllers, series-scope reviews, write-back activation/review and list comparisons. Sealing records approval coverage version 1 in the same offline restore transaction. These memberships do not depend on timestamps, and deleting a source record cannot erase its fence.

The migration backfills existing **active** paused checkpoints while all ordinary processes are stopped. It preserves their queue ceiling and job count. It does not invent the original membership of inactive legacy checkpoints. Missing headers or unsupported/incomplete approval coverage prevent ordinary jobs and approval use. Such legacy histories require a future supported repair path, not manual flag changes.

## User-visible behavior

| Saved item | Behavior after the pause is eventually lifted |
| --- | --- |
| Prepared release selection | A new single/shared download or derived manual-pack review cannot use it. The selection remains visible with an explanation; download and pack actions are unavailable. |
| Frozen import plan | A new import command cannot publish from it. Reinspect files and save a fresh reviewed plan. Reusing the old file inspection to recreate the same plan is also rejected. |
| Existing import run | Its original command key returns the receipt without starting work. Pending children cannot use ordinary Retry/Cancel as a recovery bypass; their view explains the hold. Confirmed children retain their completed evidence. |
| Uncommitted CSV preview | Held with a re-upload explanation; it cannot create or retry an import. A fresh upload is independently reviewable. |
| Completed CSV import | Its original selected rows still return the completed receipt. No membership is added again. |
| List/series request preview or policy activation | Uncompleted historical commands require fresh approval. Completed request/activation receipts remain readable and idempotent; returning one cannot reactivate a policy. Explicit command-retirement markers still take precedence. |
| Reusable series-scope review | Displayed as changed with its original books intact. A fresh review advances its revision and can support a new request preview. |
| Hardcover activation, membership review or existing-list comparison | An old preview cannot enable write-back or apply a difference. Completed mutation receipts still replay without another mutation. A fresh comparison never coalesces onto a protected historical queued observation. |

Ordinary authorization and object ownership checks run before these guards, so a guessed private ID does not expose recovery evidence. Rejections are HTTP 409 and occur before the new effect, reservation or intent is created. Read-only evidence and completed receipts are distinct from permission to execute. No automatic expiration rewrite, payload retagging, media mutation or deletion is needed to revoke a saved approval.

The recovery screen reports whether saved approvals are protected. Its queue and subject counts remain historical evidence, not completed downloads or a recovery score. No resume action is exposed.

## Deployment and verification

Stop the API and all workers. Create and verify a private pre-upgrade bundle using the build matching schema 0043, migrate, then deploy matching schema-0044 API/worker/UI builds. Backups still require an exact matching application schema. Populated approval boundaries refuse downgrade; retain a verified pre-upgrade bundle for rollback.

Verification covers immutable membership, deletion survival, old timestamps on fresh records, missing/legacy boundaries, active-checkpoint backfill, actual offline restore and rollback protection. API cases exercise stale selection dispatch, original receipts, CSV replacement, fresh series review, existing-list and membership reviews, blocked publication and source-byte/inode preservation. The browser recovery fixture and actual restore test remain separate evidence. See [implementation status](IMPLEMENTATION-STATUS.md) for measured runs and deployment checks.

## Remaining recovery work

Future activation must reconcile external effects and reservations, verify current permissions/configuration and give narrowly scoped new authority to wanted books. Historical work IDs remain protected by the queue boundary. Persistent automation settings, unknown/untracked effects, conflict repair and controlled resume need their remaining implementation and qualification; a new preview alone does not release an old download or import job.

Full populated restore/resume, actual-service and container/filesystem qualification, reference-load limits and RPO/RTO remain open. This increment does not close S09 or the full PRD.
