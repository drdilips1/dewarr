# Read-only recovery observations

This implements the observation portion of S09-02 / FR-36 / AT-25 on schema `0042_recovery_scans`. A designated restore operator can collect current external evidence while the persistent restore pause remains active. Reports do not reconcile domain records, authorize resubmission or permit resume. A separate [reviewed transfer action](RECOVERY-RECONCILIATION.md) can record selected freshly verified associations while the restore stays paused. A [reviewed inventory action](RECOVERY-INVENTORY.md) can now refresh complete current ABS evidence. A [reviewed publication action](RECOVERY-PUBLICATION.md) records verified published children and eligible ABS confirmation. A [reviewed list baseline](RECOVERY-LISTS.md) can now apply current inbound membership without catch-up acquisition. The next delivery packets are defined in the [implementation plan](../IMPLEMENTATION-PLAN.md#19-recovery-delivery-packets-and-final-release-order).

## Operator journey

Restore a verified application-state bundle using the [recovery runbook](RECOVERY.md). Start the API and a separate recovery worker with that restore's generated configuration:

```sh
BOOK_ENV_FILE=/private/recovery/book-search-rehearsal/restore.env \
uv run python -m app.jobs.worker --recovery
```

Remove stale `BOOK_*` overrides first, especially database/key overrides. The process requires an active restore checkpoint and holds the normal shared maintenance lease. An ordinary worker still refuses a restored database. The recovery worker registers `recovery.scan` and the separately reviewed local `recovery.reconcile`, `recovery.inventory`, `recovery.publication` and `recovery.lists` actions, consumes only its dedicated queue, and does not register periodic automation or Procrastinate's built-in history cleanup. The registry restriction is tested against the pinned queue version and must be requalified when upgrading it.

Sign in as the designated operator and choose **Run read-only checks**. The screen shows progress, observation time, area filters and pages of up to 50 findings. Expand **Observed evidence** to load an individual finding's details; full file inventories are not loaded for every summary card. Sign-out clears the session's query cache. Other users and ordinary product routes remain blocked.

The final message **Observation finished** means the observation attempt finished, including any individual blocked areas. It is not a clean bill of health. Read the findings; disabled connections, provider failures, unavailable roots and partial feeds remain explicit. Start a fresh observation when the external state changes. The report is saved evidence, not a continuously synchronized view.

## Evidence contracts

| Area | Reads and verification | Preserved boundary |
|---|---|---|
| qBittorrent | Paginate the whole client in hash order; verify membership/routing in repeated passes; inspect files and full identities for known hashes, app tags or configured categories. Compare saved hash/tag/path/category associations and flag untracked transfers. | No add, delete, move, rename, tag or pause calls. A missing transfer does not authorize a retry; a matching transfer does not mutate the saved attempt. Login is allowed for authenticated reads. |
| Audiobookshelf | Read current authorization and libraries, complete expanded inventory, verify a second membership pass and recheck access scope. Show new, changed, missing or inaccessible media separately. | No scan request, metadata write or update to owned assets/grants. Inaccessible libraries do not prove deletion. Restored availability stays historical until an explicit inventory reconciliation. |
| Hardcover | Reuse bounded uncached, two-pass membership verification; compare saved observations, current owner/target and outbound intent. | No list mutation, local membership update or automation episode. Unknown outbound results need separate deliberate reconciliation. |
| Goodreads | Fetch fresh bounded RSS and observe visible entries under the existing provider budget. | Feed omissions never prove removal. Private feed URLs are not report evidence. |
| Files | Open configured roots through confined descriptors; inspect frozen manifests, journals, published hashes/inode identity and source fingerprints. Detect untracked current journals/stages. | No publication, rename, lock-file creation, deletion, media tagging or receipt update. Staged evidence needs reconciliation; only verified published files get a published finding, and ABS confirmation remains separate. |

The qBittorrent census uses documented sorting and pagination from the [official Web API](https://github.com/qbittorrent/qBittorrent/wiki/WebUI-API-(qBittorrent-5.0)). Multiple stable passes reduce inconsistent observations; they are not an atomic snapshot of an external service. Any future effect must revalidate current evidence.

## Durability, privacy and limits

Commands require CSRF and an idempotency key. One active observation per checkpoint is permitted. A lease fences duplicate workers; stalled observation jobs may retry without executing ordinary queued work. An expired lease discards the attempt's partial findings before recollecting. Completed or held reports are not silently rerun. A failed queue attempt permits a new explicit observation command.

The scan captures a digest of relevant restored users, connections, catalog accounts, workflows, list observations/policies and filesystem configuration. Raw credential-bearing context is not returned by the API. A changed checkpoint, operator, lease or captured context holds the report. Unexpected errors log only the scan ID and exception type. Findings are restricted to the current checkpoint's designated operator, including separately fetched evidence.

Initial limits are deliberately explicit: 10,000 captured records per entity type; 10,000 transfers per downloader; 100 libraries per backend and 10,000 items per library; 30,000 findings; 2 MiB per finding; 15 minutes per collection attempt and one hour from command creation. File verification has a 60-second hash deadline per import; current staging census is bounded to 30,000 entries, 256 MiB of journal data and a 60-second read deadline. Filesystem calls on an unresponsive mount can still wait in the operating system; these cooperative deadlines are not a hard process kill. Hardcover retains its existing membership/page budget, with bounded rate-limit waits. Exceeding these bounds holds the report or the affected area instead of treating omitted data as absent. This is not qualification at the PRD's 50,000-asset reference load.

Observation records and provider rate accounting are written to the application database. Remote business state and domain acquisition/import/list records remain unchanged. The configured current staging root is observed; historical roots and separately preserved backup journals still require the later comparison/reconciliation workflow. A changed list binding can be flagged but does not authorize querying or writing an old remote target.

## Verification and remaining delivery

Tests cover census pagination and changing routing/membership, transfers ahead of backup, untracked effects, missing/new backend items, complete Hardcover versus partial RSS observations, partial/published file evidence, unchanged bytes/inodes/receipts, command replay, leases, bounded summaries with lazy detail and checkpoint privacy. The actual native PostgreSQL restore test launches the restricted worker as a subprocess and proves that ordinary queued work stays queued. Browser tests exercise a disposable recovery fixture; they are separate from that offline restore test.

See [implementation status](IMPLEMENTATION-STATUS.md) for exact passing runs and environments. Native PostgreSQL evidence does not certify the Compose deployment. Reviewed matching-transfer application is now available separately. Still required: resolution of other findings, current permission/configuration repair, stale approval/command handling, list rebaseline and complete inventory/permission qualification, safe partial-pack continuation, controlled resume, actual-service/platform qualification and measured RPO/RTO. No full stage or PRD completion is implied.
