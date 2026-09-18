# Transfer and storage capacity

This checkpoint implements the shared capacity part of PRD section 19. It applies to the existing download-attempt and import services. Standing list-to-download policies remain separate unfinished work; saving these limits does not enable downloads or list automation.

## Operator behavior

Open **Connections → Downloaders → Transfer and storage limits** as an administrator. Four inherited installation defaults are available:

| Control | Default | Scope |
|---|---|---|
| Active downloads | 3 | Per configured downloader endpoint, across users and workers |
| Automatic transfers | 10 | Per installation, rolling 24 hours |
| Minimum free bytes | 5 GiB | Per measured filesystem |
| Minimum free percentage | 5% | Per measured filesystem; use the larger of the two reserves |

Manual downloads require a slot and storage capacity. The automatic budget is enforced for attempts created by the trusted internal automatic-dispatch path; it is not a public client-supplied flag. There is currently no standing list policy that calls that path. The original attempt retains its automatic/manual classification when another command returns the same attempt.

Lowering limits does not stop an already-submitted transfer. Completed seed-only transfers stop using active download slots. A lost submission response keeps the slot and daily debit until the existing transfer is reconciled, even when the uncertainty lasts longer than 24 hours. Cancellation before submission releases capacity; an uncertain external attempt cannot be cancelled as though nothing happened.

Low or unknown capacity leaves the existing attempt queued with its reason. Downloads and waiting imports are reconsidered through their existing durable schedulers at approximately one-minute intervals. No extra torrent, import command or renewed retry budget is created. Permission, catalog and route conflicts still use the ordinary held/review workflow.

Settings updates use an optimistic revision and current administrator authority. The panel shows aggregate reserved bytes and occupied slots without exposing book titles, private requests or raw filesystem paths.

## Accounting contract

Capacity lives in PostgreSQL, not worker memory. Domain and authorization locks precede the installation capacity lock. The reservation, automatic submission debit and sticky external-submission marker commit before the downloader receives an add request. Earlier due attempts on the same endpoint receive an admission opportunity before later ones; an earlier capacity wait advances its next-check time so it does not permanently block every smaller request.

Filesystem measurements use open directory handles, refuse symlink traversal, and identify actual filesystems rather than assuming different mount paths mean different disks. A not-yet-created save directory uses its nearest existing ancestor. Hardlinks require download and library storage on the same filesystem; staging and library publication must also share a filesystem. Existing route probes remain required: capacity measurement does not establish hardlink or scanner compatibility.

For an inspected torrent, reserve its entire payload, including padding/extras. Future imports reserve an initial metadata allowance of 8 MiB per torrent file, capped at 100 files. Copy destinations additionally reserve the whole payload's future copy. This conservative estimate is refined by actual per-book plans; it is not a promise that every pack child is identified or authorized.

Actual import claims use the selected file sizes, frozen generated sidecars/artwork and a 1 MiB publication allowance. A child takes its budget from its completed download's import pool before requesting additional space, so the same promised copy is not reserved twice. Successful or cancelled children release their own future costs. The unused parent pool is released only once no unpublished, unresolved import entry remains for that attempt's known inspections. A later separately authorized import must reserve capacity afresh.

Physical consumption and future reservations are distinct. A fully staged item is verified against its durable journal, object identity and file hashes. Its reservation then shrinks to the publication allowance, because its media already occupies disk space. This reduction commits even if another job temporarily prevents publication. Resume uses the same staged inode. Incomplete staging conservatively retains a full-copy estimate; it may wait for more space or require cancellation and replanning.

Consumption advances a transactional storage generation. Measurements taken before another job consumes and releases reserved space cannot admit new work using stale free bytes; the worker must observe storage again. Measurements also expire after ten seconds. Admission is checked before contacting/submitting to qBittorrent and before import staging; current limits and remaining reservations are checked again under the final publication guard.

These are admission controls, not filesystem quotas. An unrelated application can consume space after a measurement. The publisher retains its disk-error handling and journal recovery. Active downloads are conservatively reserved at full size until completion, so partially downloaded bytes can temporarily reduce admission more than strictly necessary. Progress-based optimization is not implemented.

## Migration and recovery

Apply `0028_capacity` with old API/worker processes stopped, then start both at the same revision. Back up the database, keys and existing publication journals before upgrading.

The migration creates singleton settings, download claims and per-import claims. Existing external, incomplete attempts occupy slots and keep their original submission timestamp. Their storage is unknown until the ordinary observer reconstructs the claim; new work cannot spend that unknown capacity. Existing reserved unpublished imports also receive unknown claims and must resume or be resolved before new work bypasses them. Historical attempts are classified manual because no prior automatic-list dispatcher existed.

Capacity rows survive worker restarts. Final publication and cancellation release claims only with the corresponding durable database acknowledgement. A crash after filesystem changes therefore retains conservative claims until journal reconciliation. A lost ABS scan does not reacquire or re-copy the book: ownership still requires backend confirmation through the existing importer.

Populated capacity history refuses lossy downgrade. Rollback requires a pre-upgrade backup and the existing external-state reconciliation procedure. Do not delete claims to free capacity while an external transfer or unresolved staging item may exist.

## Scope and evidence

Coverage includes simultaneous admission, rollback, space changes between preflight and submission, unknown outcomes, completed slots, parent-to-child handoff, hardlink/copy recovery, final publication checks, periodic wait recovery, cancellation acknowledgement and legacy-data migrations. The browser exercises settings persistence and mobile layout against the real API. See [Implementation Status](IMPLEMENTATION-STATUS.md) for current verified counts and limitations.

This is partial S01/S04/S05/S07 evidence. Full list-policy activation, per-profile transfer/series/backfill limits, fair scheduling across future automatic reasons, shared-pack reuse, archive/extraction support and real-service/Compose/NAS certification remain open. A filesystem call that stalls inside the operating system can outlive the asynchronous observation timeout; network-filesystem deployment needs separate certification. Download dispatch remains disabled by default.
