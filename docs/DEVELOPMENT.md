# Development and operation of the current build

This is an early development build. The full [PRD](../PRD.md) remains the target; [Implementation Status](IMPLEMENTATION-STATUS.md) records actual coverage. Do not connect production acquisition automation until the relevant import and recovery gates pass.

Current request contract: back up the database and apply `0029_request_constraints` before restarting API and worker together. [Request restrictions](ACQUISITION-FOUNDATION.md#request-download-restrictions) preserve independent format and whole-transfer size limits across shared acquisitions. Populated new restrictions block lossy downgrade. Default dispatch remains disabled; this migration does not activate list automation.

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
