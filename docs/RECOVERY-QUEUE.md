# Durable protection against restored job replay

This implements the historical queue boundary in S09-02 / FR-36 / AT-25. It complements [reviewed command retirement](RECOVERY-COMMANDS.md) and the [paused restore workflow](RECOVERY.md). It does not implement controlled resume or grant fresh authority to historical requests.

## What is protected

An offline restore seals two kinds of evidence in the same transaction as the new checkpoint and session invalidation:

- The maximum saved queue job ID and the number of saved queue rows, including completed rows. Every ordinary job at or below this boundary is historical, even if its saved state says it was never sent.
- Exact IDs of saved ordinary operations, download attempts, automatic imports, import continuations and catalog works. Giving a job a new queue ID does not bypass protection when it references one of these records.

The boundary header and subject memberships are immutable through the supported application paths. Sealing again leaves the original evidence unchanged. Subject IDs deliberately have no foreign key to ordinary records: deleting an old operation cannot erase its protection. Checkpoint history must be retained. A later restore adds another boundary; it does not replace earlier boundaries.

This is an offline operation, not a way to interrupt already-running work. Stop every API and ordinary worker before backup, restore or migration. The existing maintenance locks and persistent restore pause remain necessary.

## Worker behavior

Every ordinary worker uses middleware before entering a task body:

| Condition | Outcome |
| --- | --- |
| Restore pause is active | Ordinary task is aborted without executing its body. |
| Any checkpoint lacks a sealed boundary | Ordinary task is held, even if a pause flag was cleared. |
| Job ID is within a historical boundary | The saved job cannot be replayed. |
| New job references a protected operation, attempt, import, continuation or work | The new queue row does not authorize historical work. |
| Record-reference argument is unknown or invalid | Execution fails closed. A contract test requires explicit coverage for every registered ordinary task argument. |
| Queue-history cleanup after a restore | Cleanup is held so historical evidence remains available. |
| No restore history | Existing ordinary queue behavior continues. |

A denied task raises Procrastinate's `JobAborted` and records `recovery.queue.blocked` with its job ID, task name and reason. The audit adds no task arguments or credential values. It neither claims successful domain execution nor automatically retries the denied task. Database failures prevent entry to the task body.

The seven named recovery tasks require an active checkpoint. Their handlers retain the separate operator, checkpoint, observation, revision and authority checks. The dedicated recovery worker still registers only those tasks, without ordinary work or periodic cleanup. The ordinary queue retains the pinned library's two supported cleanup names; fresh task registration avoids mutation of a shared builtin namespace across application instances.

## Deployment and visibility

Migration `0043_recovery_queue_fences` creates the boundary tables and seals existing **active** restore checkpoints while offline. Inactive legacy checkpoints without a boundary are not silently trusted; they keep ordinary work held and require a future supported repair path. There is no supported resume path for those older checkpoints in this build.

Take a verified pre-upgrade backup with the build matching the old schema, stop the installation, migrate and deploy matching API/worker/UI builds. Backups remain exact-schema restores: the new command does not reinterpret a schema-0042 bundle as schema 0043. Downgrade refuses to remove populated boundary history; use a verified matching pre-upgrade backup for rollback.

`GET /api/recovery` adds an optional `queue_fence` summary with historical job and subject counts. The operator screen shows whether the boundary exists. Counts describe saved evidence, not jobs executed or acquisitions completed. There is no new mutation endpoint or resume button.

## Remaining work and qualification

The fence intentionally includes historical work IDs. Future fulfillment for a restored book therefore needs an explicit, durable, narrowly scoped activation mechanism; simply clearing the checkpoint, retrying a job or creating a replacement operation is insufficient. Tests that deactivate a checkpoint only exercise persistence of the boundary, not a supported operator procedure.

Other approval families, current permissions and configuration, reservations, unresolved or untracked external effects, reviewed activation and controlled resume still need their remaining recovery implementation. This worker-entry boundary does not make arbitrary direct calls to domain functions safe or cancel an external operation already in flight.

Verification covers actual offline restore sealing, migration backfill and guarded downgrade, old/new job IDs, every supported subject family, deleted-record protection, repeated/later sealing, transaction rollback, missing boundaries, cleanup preservation and normal work without restored history. Browser coverage uses a separate synthetic paused fixture. Full populated restore/resume, actual providers, supported containers/filesystems, reference load and RPO/RTO remain release gates. See [implementation status](IMPLEMENTATION-STATUS.md) for measured evidence.
