# Stop pending imports and replan unresolved books

September 17, 2026. Implemented for reviewed manual imports. Acquisition-source and shared-download cancellation remain part of the later acquisition workflow.

## User workflow

An unpublished entry offers **Stop pending import**. Downloaded originals and already published library books are preserved. A queued, publishing or held entry moves to **Stopping import** while the worker checks its publication journal; merely clicking Stop does not release its reservation.

If publication never completed, the worker removes only its own identified private staging files, records a durable cancellation receipt and releases the entry's version reservation. The entry then shows **Stopped** and a link to review files and create a new plan. Repeating the stop command or redelivering the worker job does not repeat publication. The stopped entry itself cannot be retried as an import; a newly submitted reviewed import gets a new entry and journal.

If publication completed before its database acknowledgement, stopping discovers and preserves that item. The entry moves to library detection, then requires the same media/identity/ABS checks as an ordinary import. A known published or confirmed entry does not offer the stop action. Stopping a pending import is not deletion, an undo of publication or cancellation of qBittorrent seeding.

An unresolved group with no publication specification can stop immediately because it has no filesystem work or reservation. Other cases require the worker. **Cancellation needs attention** retains the reservation and offers **Retry stopping import** after the problem is repaired.

## Collection replanning

Group review can change unresolved files beside reserved or published siblings. Each protected sibling must retain its exact group identity, membership and disc/track mapping. Attempts to exclude, split, merge or reorder its files are rejected. Stop its unpublished import and wait for **Stopped** before regrouping those files.

After the correction, select the intended catalog versions and save a new frozen plan. The normal revision checks reject obsolete group plans; actual source identities/hashes are checked again during publication. New requests cannot reserve the same inspected group under a different version while the original import still reserves those files. Already confirmed sibling items retain their files, bindings and availability.

This does not edit a published item's identity or reorganize existing media. The source-group guard is scoped to an inspection; broader physical-file alias reconciliation across separate inspections and integrations remains gate work.

## Durability and authority

- The stop command, attempt invalidation, audit event and queue dispatch commit together. The owner must remain an active administrator, and recovery mode pauses changes.
- Filesystem cancellation takes the same destination publication lock as importing. A short database guard rechecks the actor, frozen destination/staging paths, entry state and attempt before cleanup. Disabled source credentials or changed catalog metadata do not prevent stopping an unpublished import.
- A final publication guard rejects revoked attempts. A delayed older worker also refuses a cancelling/cancelled filesystem receipt, so it cannot recreate staging or publish after cancellation.
- Before removing any staged file, validate every present file against recorded ownership. Only identified media hardlinks or journaled generated/copied file inodes are removed. Original downloads are never opened for writing or removed. Unknown files, replacements, symlinks and unconfirmed staging folders stay untouched and hold cancellation.
- Persist cleanup intent before the first unlink. A restart can finish partial cleanup or acknowledge a previously removed stage. An absent stage without that evidence remains ambiguous: publication may have happened and the item may have moved.
- An existing destination without a journal, a changed destination identity, or a missing previously published item requires review. These cases do not release reservations as though nothing happened.
- Periodic recovery revisits cancelling entries when no queue attempt is active. An actual live job is not restarted merely because a status observation is delayed. Persistent path/journal/permission failures become explicit attention rather than being treated as success.

API: `POST /api/organization/imports/{run_id}/entries/{entry_id}/cancel`, owner-scoped administrator access. Existing run responses expose `can_cancel`. The API returns a durable entry state; the UI polls until the worker resolves it.

Migration `0014_import_cancel` extends entry states with `cancelling`, `cancel-held` and `cancelled`. Populated cancellation history blocks a lossy downgrade. Preserve the database and private filesystem journal together; full independently restored external-state reconciliation remains S09 work.

## Verification and remaining scope

Seventeen filesystem cases cover stopping before/after staging, hardlinks/copies, interrupted cleanup, delayed publishers, unknown/replaced files, publication-before-acknowledgement, moved items and missing journals. Nine database/API integration cases cover repeated commands, reservation retention/release, final-rename fencing, publication recovery, stale roots/permissions, owner isolation, duplicate file-group reservations, sibling-preserving replanning and downgrade protection.

The browser stops a held import, reloads its result, repairs the synthetic backend capability and imports successfully. Both real ABS ebook and merged-audio application workflows stop a queued entry, verify unchanged source files and no published item, then import successfully with a fresh command. Those native cases do not certify every cancellation race; the fault-injection suite supplies the additional assertions.

Remaining: filesystem-alias reconciliation, bulk stop UX, broader formats/collections, direct correction of published items, generic orphan recovery and the complete filesystem/ABS compatibility matrix. Existing library deletion and automatic reacquisition remain outside this action.
