# Development and operation of the current build

This is an early development build. The full [PRD](../PRD.md) remains the target; [Implementation Status](IMPLEMENTATION-STATUS.md) records actual coverage. Do not connect production acquisition automation until the relevant import and recovery gates pass.

Current schema: `0043_recovery_queue_fences`. Stop API/worker processes, back up with the tool version matching the pre-upgrade schema, apply migrations and restart matching builds. [Restored queue protection](RECOVERY-QUEUE.md) seals historical jobs and referenced records without enabling resume. The request contract introduced at `0037_download_joins` remains in effect. [Saved-transfer reuse](DOWNLOAD-REUSE.md) adds independent join receipts and later import continuations. [Request restrictions](ACQUISITION-FOUNDATION.md#request-download-restrictions) preserve independent format and whole-transfer size limits across shared acquisitions. Populated history blocks lossy downgrade. Default dispatch remains disabled; this migration does not activate list automation.

[Automatic reviewed-series acquisition](SERIES-ACQUISITION.md) adds a durable `series.acquire` task without a new migration. Update API and worker together before accepting automatic series requests. Finite accepted sets retain their own scope and authority; this does not enable future-sequel monitoring or installation dispatch.

[Reusable main-book reviews](SERIES-SCOPE-REVIEW.md) add finite owner-reviewed membership evidence and optional proof reuse in series requests. Deploy API and worker together before saving proof-backed requests; older binaries cannot interpret the new command field. No migration beyond `0037_download_joins` is needed, and saving a review creates no acquisition or job.

[Route defaults](ROUTE-DEFAULTS.md) add inherited downloader and per-medium destination references to the existing JSON preferences. Deploy API and worker together before saving these fields; no new migration is required. Automatic acquisition still needs current route approval, and deployment does not enable dispatch.

## Native development

Requires Python 3.13, uv, Node 24+ and PostgreSQL. The current workspace uses a dedicated PostgreSQL 16.14 cluster on loopback port 55438; PostgreSQL 18 container certification is pending.

```sh
uv sync --frozen
npm --prefix apps/web ci
```

For a new local installation with PostgreSQL binaries available:

```sh
mkdir -p .local
initdb -D .local/postgres -U book -A trust --no-locale -E UTF8
pg_ctl -D .local/postgres -l .local/postgres.log -o '-h 127.0.0.1 -p 55438 -k /tmp' start
createdb -h 127.0.0.1 -p 55438 -U book book_search_dev
createdb -h 127.0.0.1 -p 55438 -U book book_search_test
createdb -h 127.0.0.1 -p 55438 -U book book_search_browser_test
uv run python scripts/init_env.py --mode native
uv run alembic upgrade head
npm --prefix apps/web run build
```

The trust-authenticated database is a loopback-only development fixture, not a production deployment pattern. Do not rerun initialization over an existing cluster. `init_env.py` refuses to replace an existing `.env`. It writes secrets with restrictive permissions and never prints them.

Run the API/static UI and worker in separate terminals:

```sh
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
uv run python -m app.jobs.worker
```

Open `http://localhost:8000`. Initial setup requires the token in `.local/secrets/bootstrap_token`; choose your own administrator username and password. No default account is installed. The development database and real installation secrets are distinct from disposable tests.

For Vite hot reload, run `npm --prefix apps/web run dev` and change `BOOK_PUBLIC_URL` to the exact browser origin, normally `http://localhost:5173`, before restarting the API. Its `/api` proxy targets port 8000. Production serves static assets and API from one origin.

## Checks

```sh
uv run ruff check services tests scripts
uv run ruff format --check services tests scripts
BOOK_TEST_DATABASE_URL=postgresql+psycopg://book@127.0.0.1:55438/book_search_test uv run pytest -q
uv run alembic check
uv run python scripts/export_openapi.py
npm --prefix apps/web run generate:api
npm --prefix apps/web run format:check
npm --prefix apps/web run build
npm --prefix apps/web exec playwright install chromium
npm --prefix apps/web run test:e2e
```

Backend tests require a database name ending `_test`; browser tests require `_browser_test`. They truncate those disposable databases. With no `BOOK_TEST_DATABASE_URL`, integration tests skip explicitly, so a unit-only run is not integration evidence. Browser tests launch their own API and worker, use generated encryption keys and a fixture-only bootstrap token, and stop those processes afterward. Override `BOOK_E2E_DATABASE_URL` when needed.

The browser journey covers bootstrap, catalog/list/library/metadata/request workflows, real worker execution, reviewed imports and cancellation, same-edition formats, PDF companions, local catalog matching, file-scoped inspection/planning, automatic-import policy enable/reload/disable, native MAM setup/search/detail, saved torrent manifests and reviewed wanted-book release selection/cancellation, qBittorrent settings/test/path preview/disable, opt-in synthetic submission and persistent transfer Activity, reload persistence and mobile layout/sign-out. MAM, qBittorrent and ABS HTTP responses in this journey are synthetic fixtures; actual ABS compatibility has a separate harness. Screenshots are saved under `apps/web/test-results/`.

Torrent inspection uses the pinned libtorrent 2.1.1 Python wheel in an offline child process. Native parser tests cover v1/v2/hybrid layouts and cancellation on the local macOS runtime. Linux/Compose certification remains pending; retain the explicit libtorrent/Boost/OpenSSL notices when packaging. See [Source artifacts](SOURCE-ARTIFACTS.md) for limits and the dispatch boundary.

## Container deployment scaffold

On a fresh installation with Docker/Compose:

```sh
uv run python scripts/init_env.py --mode compose
docker compose up --build -d
```

The initializer sets UID/GID to the invoking user so mounted secret files remain readable by the application account. The image itself defaults to UID/GID 1000. Do not generate native `.env` then assume its localhost database URL works inside Compose; create the appropriate configuration for the deployment environment deliberately.

Compose runs PostgreSQL, a one-shot migration process, API and worker. The API is bound to loopback by default. Configure the reverse proxy and exact `BOOK_PUBLIC_URL` for remote access; enable `BOOK_COOKIE_SECURE=true` under HTTPS. Forwarded headers are not trusted by default. No Docker socket or media directory is mounted into the API. Optional read-only inspection mounts and BOOK_IMPORT_SOURCES are documented in [Organization planning](ORGANIZATION-PLANNING.md); publication needs destination/staging write access and source mounts that permit the selected hardlink operation. Verify the actual route before importing.

Base image digests are pinned and were resolved from the Docker Hub registry. Local container build/run has not been verified because Docker is unavailable on this host. CI includes an image-build job; an unexecuted workflow is not passing evidence.

## State and recovery boundaries

- Preserve PostgreSQL application/queue state and `.local/secrets/app_key` together. Without the key, encrypted provider credentials cannot be recovered from a database backup.
- The [versioned state bundle and restore review](RECOVERY.md) now provide an offline command, new-database restore, session invalidation and a persistent operator-only fence. External reconciliation and supported resume remain pending; this is a rehearsal foundation, not AT-25 acceptance.
- Schema migrations are explicit (`alembic upgrade head`), not performed implicitly by every API process. The frozen queue SQL is versioned independently of future Procrastinate upgrades.
- `BOOK_RECOVERY_MODE=true` blocks diagnostic dispatch and worker startup. Full external-state restore reconciliation is still pending S09; this flag alone does not certify restore safety.
- Stalled-job recovery includes diagnostics, fenced ABS inventory, fenced secondary metadata enrichment, idempotent acquisition evaluation/reconciliation, completed-download inspection, destination probes and journaled item publication. Wanted requests are reevaluated every five minutes without submitting downloads. Published items awaiting ABS detection and pending cancellation reconciliation are checked every minute. Other future external workflows require their own reconciliation before joining recovery.
- A reviewed import can publish new complete-item folders; it never overwrites existing media. The final rename is guarded by current permissions, configuration and attempt state. Preserve the private staging/journal root along with the application database. Publication recovery tests do not establish full restore safety across independently restored external systems.
- Migrations 0011–0014 add import history/reservations, immutable grouping revisions, initial-cover export evidence and recoverable cancellation states. Their populated-state downgrade guards require restoring a pre-upgrade backup rather than discarding history. Catalog entries and completed filesystem writes do not imply ownership; ABS must confirm the intended item.

Keep local database/log/test artifacts out of commits. Use the application health endpoints for readiness and the Activity screen's background-worker check for a durable queue round trip.

## Organization foundation

Organization settings provide a naming preview and saved defaults. The completed-download screen runs read-only inspection, supports collection-group correction, freezes selected group/version mappings and initial metadata/covers, and offers per-book import through verified routes. Unpublished entries can be stopped and unresolved collection children replanned while preserving completed siblings. Availability changes only after ABS confirmation. See [Organization planning](ORGANIZATION-PLANNING.md) for root mapping, supported formats, retry behavior and remaining importer gates, and [Ebook imports](EBOOK-IMPORTS.md) for PDF/CBZ inspection, equivalent formats and companion roles. Native audio inspection additionally requires ffmpeg/ffprobe; tests generate tiny original fixtures. [Native ABS certification](ABS-NATIVE-CERTIFICATION.md) documents the real pinned-server item tests and eight application workflows with their boundaries.

## Development download dispatch

`BOOK_DOWNLOAD_DISPATCH_ENABLED=false` is the default. The new [download-attempt lifecycle](DOWNLOAD-ATTEMPTS.md) is available for isolated integration testing when explicitly enabled on both API and worker. Normal activation remains pending full import/recovery certification. Synthetic browser tests enable it; the local development installation keeps it disabled. Existing uncertain attempts retain their identities and are never automatically resubmitted.

Migration `0018_attempts` adds the attempt/identity-claim ledger and committed reservation state. A populated ledger cannot be downgraded without losing external-side-effect history; rollback requires a pre-upgrade backup and recovery-mode reconciliation.

Migration `0019_fulfillment` records confirmed request satisfaction and permits completed fulfillment reservations to retire while preserving torrent claims. Import confirmation enqueues a separate reconciler; periodic request evaluation repairs missed events. Completed Activity entries can check current library availability without new download dispatch. Populated fulfillment history also requires backup-based rollback. See [Download fulfillment](DOWNLOAD-FULFILLMENT.md) for evidence, privacy and remaining repair/sharing boundaries.

Single-file download and import behavior, receipt compatibility and verification are described in [Single-file imports](SINGLE-FILE-IMPORTS.md). The native ABS workflow harness now includes standalone ebook and audio file selections.

Migration `0020_repairs` adds reviewed connection repair history. The existing download worker observes the original transfer using a reviewed configuration and only accepts it after full association checks. Same-route connection repair works with new dispatch disabled; it does not authorize another add or rewrite frozen import plans. See [Download repairs](DOWNLOAD-REPAIRS.md) for the settings/review workflow and remaining endpoint, path and member-handoff gates.

## Automatic import checkpoint

See [Automatic imports](AUTOMATIC-IMPORTS.md) for opt-in destination policies and the currently qualifying EPUB/M4B/MP3 path. This uses the shared planner/publisher and requester-authorized administrator handoff; it does not turn on external-list acquisition. Migration `0022_auto_import` preserves policy and continuation history and blocks lossy populated downgrade. Back up before upgrading. Route changes, expired authority and ambiguous evidence hold work for review; exhausted automatic/inspection jobs do not gain fresh retry budgets through the periodic scheduler.

Automatic imports can now enqueue `metadata.resolve-import` for a missing catalog edition. This requester-owned job uses the configured catalog adapters, releases transactions during network I/O, respects provider retries and fences changed permissions/accounts/evidence before source attachment. The edition-lookup setting defaults on independently of work-field enrichment. See [Import catalog resolution](IMPORT-CATALOG-RESOLUTION.md) for limits and current evidence. No schema migration beyond `0022_auto_import` is required for this checkpoint.

## Combined source search checkpoint

[Book Sources](BOOK-SOURCES.md) uses two durable source jobs, private saved preferences and the existing inspected-artifact/selection path. Apply migration `0024_book_sources` before starting the new API and worker; populated profile/search history requires a pre-upgrade backup for rollback. Source jobs participate in stalled-job recovery. API and worker must run the same revision. Default download dispatch remains disabled.

## Goodreads observation checkpoint

Apply `0025_list_subscriptions` before restarting the API and worker. The `lists.schedule` job runs every minute to queue due subscriptions; the default observation interval is 30 minutes plus jitter. Both `lists.schedule` and `lists.sync` participate in stalled-job recovery. [Goodreads subscriptions](GOODREADS-SUBSCRIPTIONS.md) documents privacy, provenance, exclusions and remaining automation requirements. The browser harness uses a fixture-only Goodreads transport and rejects non-browser databases; the production worker retains HTTPS/public-DNS checks.

[CSV snapshots](CSV-LIST-IMPORT.md) use migration `0026_list_csv` and the durable `lists.csv` worker. Apply the migration before starting API and worker at the same revision. Uploads use bounded raw CSV request bodies; only normalized mapped assertions are persisted. No extra parser service or multipart dependency is required.

[Hardcover subscriptions](HARDCOVER-LISTS.md) use migration `0027_hardcover_lists` and the existing `lists.sync` queue. They reuse each owner's Metadata account. Apply migrations before restarting the API and worker together. No extra environment secret or service is needed. Membership reads deliberately bypass cached metadata; disabled accounts fail only their own due observations. Populated Hardcover history requires backup-based rollback.

[Reviewed list requests](LIST-REQUESTS.md) add the `lists.requests` task to the existing queue and operation ledger without a schema change. API and worker must run the same revision. Stalled jobs are recoverable; accepted request batches retain receipts, and only unsubmitted previews are bounded by retention. This worker saves wanted media through the ordinary request engine and does not dispatch downloads.


[Automatic release preparation](AUTOMATIC-SELECTION.md) adds `acquisition.auto-select` in the sources queue with bounded retries and stalled-job recovery. It reuses schema `0027_hardcover_lists`; restart API and worker together so both know the new task and routes. The worker saves a selection through the existing acquisition service. Download dispatch remains disabled by default and is not enabled by this feature.

[Transfer and storage limits](CAPACITY.md) require `0028_capacity`. Stop old API/worker processes, back up the database and publication journals, apply the migration, and restart both at the same revision. Existing external transfers and unpublished reserved imports need storage reconciliation before new work can bypass their unknown costs. The existing download and import schedulers resume capacity waits; no new queue or service is required. Populated capacity history requires backup-based rollback. Keep dispatch disabled until the installation's acquisition gates pass.

Explicit automatic selection-to-download handoff also uses `0028_capacity`; there is no additional migration or queue task. Restart API and worker together. The new Sources action records `download_when_ready` consent, requires a current automatic-import approval, and queues the ordinary attempt atomically with selection. Default dispatch remains disabled. Standing list policies and scheduled list-to-source searches now have their own checkpoint below; see [Automatic selection and download](AUTOMATIC-SELECTION.md).

## Standing list policies

Migration `0030_list_policies` adds durable activation and per-book monitoring. The list scheduler shares existing source, selection, download and import workers. Follow [List acquisition policies](LIST-POLICIES.md) for prerequisites, future-only/backlog behavior, permissions and remaining qualification. The browser suite uses a later Hardcover fixture addition to trigger acquisition without a per-title request. Development dispatch remains disabled unless deliberately enabled for a qualified isolated integration.

Membership re-addition and canonical merge/undo monitoring reuse `0030_list_policies`; there is no new migration. Restart API and worker together after backing up. Monitoring progress now records membership and identity evidence, with defaults for existing rows. The generated monitored-book API includes its canonical title. Original monitoring and request rows are retained for history and merge undo.


## Acquisition defaults

Apply `0031_acquisition_defaults` after backing up, then restart API and worker together. It adds sparse personal and installation preferences without rewriting existing complete profiles. The Sources profile editor links to `/download-preferences`; members can edit personal defaults and administrators can also edit installation defaults. Stale effective revisions require a refreshed preview/search. Populated defaults block downgrade. See [Download preferences](DOWNLOAD-PREFERENCES.md) for the boundary between ordinary preferences, request restrictions and remaining inheritance work.

## Request and list preference snapshots

Migration `0032_request_release_policy` records effective release preferences on acquisition intents and individual reasons. Back up before upgrade and restart API and worker at the same revision. Existing requests retain null historical snapshots; no guessed backfill is performed. Once a snapshot is stored, downgrade is refused to prevent loss of acquisition evidence.

List policies and manual request forms expose sparse release overrides. Request-bound source searches retain those layers through selection; polling is scoped to the request. See [Download preferences](DOWNLOAD-PREFERENCES.md) for precedence, stale-preview behavior and the remaining media/language/scope inheritance work. This migration does not enable dispatch or change existing files.

[Reviewed series requests](SERIES-REQUESTS.md) add the `series.requests` task and independent series reasons. Apply `0034_series_requests` before restarting API and worker together. Populated series history requires backup-based rollback. Saving a series request creates ordinary wanted requests; it does not dispatch a pack or expand future membership.

[Series source search](SERIES-SOURCE-SEARCH.md) requires `0035_source_queries`. API and worker must be restarted together after backing up and migrating. Existing searches retain their original query plans; new searches can include bounded known series names under the inherited search preference. Automatic pack selection is not enabled by this change.

[Reviewed shared downloads](SHARED-DOWNLOADS.md) require `0036_download_memberships`. Stop the old API/worker before migration, back up, upgrade and restart both together. Existing attempts receive one membership; new reviewed batches can serve multiple selections through one transfer. Populated multi-member history prevents destructive downgrade. New automatic series selection and later/cross-owner reuse remain pending; dispatch stays disabled by default.

[Verified collection contents](COLLECTION-CONTENTS.md) require migration `0038_asset_containment`. Back up the database/key, stop the old API and worker, migrate and restart both together. Populated containment or its correction history requires backup-based rollback. Ordinary assets keep their existing version bindings; reviewed omnibus items remain one backend item with no invented child editions.

[Reviewed omnibus import](COLLECTION-IMPORT.md) uses the same schema with additive frozen-plan and containment-proof fields. Restart API and worker together before saving these plans. The independently confirmed physical collection version is retained; its contents gain ownership only after ABS detection. No new migration, service or dispatch activation is introduced.

[Discovery](DISCOVERY.md) adds `/discover` and scoped `/api/discovery` reads with the existing Hardcover gateway. No migration beyond `0038_asset_containment` is required. Deploy matching API/frontend and restart both backend processes. Provider account generation, accepted catalog identifiers and current library grants govern the results; local shelves do not require a provider connection. Dispatch stays unchanged.

[Community lists](COMMUNITY-LISTS.md) adds `/discover/lists` and public Hardcover list browse/preview/follow APIs using existing schema `0038_asset_containment`. Rebuild the generated client/frontend and restart matching API/worker builds after backup. There is no new service, secret or migration. The first sync uses the existing `lists.sync` task; following leaves download automation off.

[Series discovery](SERIES-DISCOVERY.md) adds a read-only local shelf to Discover using current scoped holdings and observed series catalogs. Rebuild the generated API client/frontend and deploy matching API/worker code. Schema remains `0038_asset_containment`; there is no new task, integration credential or migration.

[Local list curation](LIST-CURATION.md) adds synchronous `lists.curate` receipts and revision-aware list editing. No migration or new queue is required. Deploy the generated frontend/client with matching API/worker code on `0038_asset_containment`; legacy single-entry and full-order routes remain supported.

List detail now defaults to 50 books and exposes count/matched/offset/limit; app consumers use bounded paging/search instead of assuming a complete response. Deploy the matching generated frontend/API together. See [list pagination](LIST-PAGINATION.md) for relative moves, optimistic selection revisions, compatibility and remaining qualification. No migration beyond `0038_asset_containment` is needed.


[Optional Hardcover write-back](LIST-WRITEBACK.md) requires migration `0039_list_writeback` and the registered `lists.writeback` worker. Back up database/key/configuration, stop old API/worker builds, migrate and restart matching backend/frontend versions. Policies begin disabled; enablement checks ownership and applies to future local membership changes only. Populated outbound history requires backup-based rollback. Recovery mode holds outbound work; full restored-state reconciliation remains an S09 qualification gate. Download dispatch stays independent.


[Existing-list comparisons](LIST-COMPARISONS.md) require `0040_list_comparisons` and the new `lists.writeback.compare` task. Back up database/key/configuration, stop old API/worker builds, migrate and restart matching backend/frontend versions. Initial enablement now waits for the comparison returned by the ownership preview; older previews need refreshing. Populated comparison history requires backup-based rollback. This does not enable dispatch or change existing write-back policies.


[Read-only recovery observations](RECOVERY-OBSERVATIONS.md) require `0042_recovery_scans`. Populated scan history blocks downgrade; preserve a pre-upgrade database/key/configuration backup with the prior compatible tooling. The state-bundle format remains version 1, but its schema compatibility check now requires 0042. A restored database runs the API and explicit `python -m app.jobs.worker --recovery` only; ordinary workers stay blocked. Normal installations use the ordinary worker, and this migration does not activate download dispatch. Deploy the generated client/frontend together with matching backend code.


[Reviewed transfer recovery](RECOVERY-RECONCILIATION.md) adds `recovery.reconcile` to the restricted recovery worker on existing schema `0042_recovery_scans`. Back up and restart matching API/worker/frontend builds. No migration or dispatch activation is needed. Re-run observations after this upgrade because their context now also includes transfer capacity, memberships and identity claims. The action records verified existing transfers only; the restored installation still has no supported resume command.


[Reviewed inventory recovery](RECOVERY-INVENTORY.md) adds `recovery.inventory` to the isolated worker without a schema/dependency change. Fresh observation context includes catalog identities, grants and verified asset coverage. The worker re-reads the full reviewed ABS inventory before one atomic publication, leaves existing grants unchanged and fences prior inventory leases. Deploy matching API/worker/frontend after backup; recovery still has no supported resume command.


### Reviewed publications during restore

[Publication recovery](RECOVERY-PUBLICATION.md) adds `recovery.publication` to the isolated recovery registry and three operator review routes. It records already published children and exact-version ABS confirmation without file or remote mutations. Deploy matching API, worker and generated client on schema 0042; no migration or runtime dependency is added. Run fresh observations after deployment because frozen import and capacity context is now included. Controlled resume and remaining S09 qualification stay open; development dispatch stays disabled.


### Reviewed external-list baselines during restore

[List recovery](RECOVERY-LISTS.md) adds `recovery.lists` to the restricted worker and three explicit operator-review endpoints on schema 0042. Deploy matching API/worker/client and run fresh observations because the bound list/acquisition context expanded. Recovered members are baseline entries; acquisition and write-back remain paused for explicit owner review. No migration or dependency is added, and development dispatch remains disabled.


## Outbound recovery review

[Reviewed outbound evidence](RECOVERY-OUTBOUND.md) adds original-target Hardcover membership checks and an operator preview/acceptance flow. It records current outcomes without resending list changes, fences old remote leases and requires fresh owner review before write-back can return. Deploy matching API/worker/client on unchanged schema 0042. Unknown effects remain held; historical commands and controlled resume are still open.


## Historical request-command review

[Recovery command retirement](RECOVERY-COMMANDS.md) adds an operator review for stale request approvals and acquisition controllers. It preserves already-recorded wanted books, reasons and reservations, retires selected workers/previews and requires fresh owner activation. Deploy matching API/worker/client on schema 0042. This action leaves other historical work and the persistent restore fence unresolved; it does not authorize resume.
