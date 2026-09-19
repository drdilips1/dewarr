# Reviewed publication recovery after restore

This is the per-book publication portion of S09-02 / FR-36 / AT-25. It follows [read-only observations](RECOVERY-OBSERVATIONS.md), complements [transfer recovery](RECOVERY-RECONCILIATION.md) and uses [reviewed ABS inventory](RECOVERY-INVENTORY.md) to establish the current library scope. It records existing effects while the restore checkpoint remains active.

## Operator workflow

1. Start the restored API and restricted recovery worker using the [restore runbook](RECOVERY.md). Review current library inventory first if its permissions or inventory have changed.
2. Run fresh observations and filter to **Files and journals**. Choose **Review publication for …** on a verified published book. A staged, missing, conflicting or untracked folder is not eligible.
3. Read the proposed outcome for each book: confirm available in ABS, record publication while awaiting library confirmation, or record publication and hold a withdrawn import. The preview includes its medium, destination folder and the reason for that outcome.
4. Choose **Record published books**. The worker rechecks the physical publication and any ABS evidence needed for the exact reviewed outcome. The API supports 1–100 distinct children in one explicit batch; the UI reviews a child at a time. A failed verification holds the whole selected batch without partial ledger changes. Unselected children remain independent.
5. Run fresh observations before another correction. Outcomes survive reload; neither a successful record nor an availability confirmation resumes automation.

## Evidence and outcomes

| Evidence | Result |
|---|---|
| Destination belongs to this entry's journal and matches every frozen file/sidecar | Record the original receipt and existing publication in the local ledger. Clear the obsolete import token and confirmation timer. |
| Rename completed but the journal still says prepared | Accept only when the destination inode equals that journal's staged-directory identity and its complete contents match. Leave the external journal unchanged. |
| Original source is gone, but the published files still pass all checks | Allow recording the existing publication. Source availability does not erase the observed published fact. |
| Fresh ABS observation uniquely matches the current frozen version, file set and folder | Confirm the exact imported asset using the ordinary local confirmation service, provided the library scope, route and file identities are also corroborated. |
| ABS has not detected the book, or identity/permissions need review | Record publication as awaiting-library, with no new availability claim, scan request or automatic confirmation schedule. |
| The import was cancelled, cancelling, cancel-held or skipped | Record the physical fact as cancel-held. Do not revive the old request or its reservation. |
| Another child remains staged or unresolved | Leave that child, its files and its storage reservation unchanged. A published sibling can be reviewed separately. |
| A reviewed omnibus matches | Confirm the physical edition and only its explicitly frozen contained works through the existing collection-coverage rules. No narrator or edition is invented for its children. |

Publication verification opens files read-only, rejects symlink/path substitution, verifies journal ownership, exact folder membership and manifest hashes, and reads media/sidecar identities before and after hashing. It rereads the journal and root identities, then walks the current book path again to reject an ancestor replacement that would leave an unchanged open descriptor pointing outside the current path. The original receipt is returned to the local ledger; no lock file, directory, media file or receipt is created or rewritten.

For availability, the app also requires a complete current ABS observation in the selected library, unchanged saved library scope, current enabled destination and connection, unchanged frozen catalog version and collection identities, matching exported metadata and exact media paths/sizes. ABS-reported inode and modification time must corroborate the verified local files; only one millisecond of timestamp rounding is allowed. This is a conservative check: filesystems or backend mounts that expose different inode identities remain awaiting review instead of being assumed equivalent. A manual conflicting match or intentionally suppressed asset cannot be silently overridden.

The worker repeats the complete backend observation, checks the library root and permissions, and rereads the physical publication after the remote reads. A newly detected ABS item cannot silently broaden an accepted awaiting-library outcome into confirmed availability. Preparing a fresh review is required for that change.

## Durable transaction and isolation

The shared recovery review engine binds the current checkpoint/operator, latest completed scan, exact selected findings and any related ABS findings, local-context digest, expiry and preview revision. Its freshness, command idempotency, accepted-job transaction, worker lease and final token/context checks apply unchanged. All selected entry updates, exact-version asset/collection records, released consumed storage reservations, old-operation status and audits commit together or roll back together.

An existing publication timestamp is preserved. If the backup predates publication, the new timestamp records when recovery observed that fact; the audit explicitly identifies the observation time. It does not invent the time of the historical rename. Staged siblings keep their capacity reservations, and ordinary parent storage accounting remains conservative until its publication obligations are satisfied.

The restricted registry contains only `recovery.scan`, `recovery.reconcile`, `recovery.inventory`, `recovery.publication` and `recovery.lists`, with no periodic tasks or built-in history cleanup. Accepted recovery actions exclude one another. This action makes no qBittorrent request, ABS scan/update, mapping-marker write, list mutation, file move, retag, acquisition fulfillment enqueue or import continuation. Original queued jobs remain fenced by the persistent pause. Future controlled resume must still resolve those historical commands and recheck original requester authority.

## API and deployment

- `POST /api/recovery/publication-reconciliations` prepares an exact preview from `scan_id` and `finding_ids`, with an idempotency header.
- `GET /api/recovery/publication-reconciliations/{identifier}` reads the current operator's review and result.
- `POST /api/recovery/publication-reconciliations/{identifier}/accept` accepts that revision with a new idempotency header.
- `GET /api/recovery` includes the latest publication review for durable reload.

Deploy matching API, worker and generated frontend/client. No schema migration, runtime dependency or external service is introduced. Recovery context now includes frozen plans, import runs/destinations, handoffs, automatic-import associations and capacity rows. Reports created before this context expansion remain readable but require a fresh observation before they can authorize changes.

## Qualification boundary

The synthetic integration tests exercise a real temporary filesystem and PostgreSQL, including a rename ahead of the journal/database, independent staged/published siblings, atomic batch rollback, exact recording/edition and omnibus confirmation, changed evidence, source disappearance, revoked or changed permissions and late-worker fencing. Browser coverage demonstrates the explicit review, acceptance, reload and mobile workflow; it is a disposable pause fixture, not a populated external-service restore rehearsal. Exact verification results are maintained in [implementation status](IMPLEMENTATION-STATUS.md).

Staged/untracked/conflicting publication resolution, intended permission repair, external lists/outbound rebaseline, historical-job resolution and controlled resume are still required. Actual-service/platform qualification, reference-load and RPO/RTO measurements remain open. This increment does not accept all of S09 or the full PRD.
