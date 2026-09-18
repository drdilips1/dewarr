# Development and operation of the current build

This is an early development build. The full [PRD](../PRD.md) remains the target; [Implementation Status](IMPLEMENTATION-STATUS.md) records actual coverage. Do not connect production acquisition automation until the relevant import and recovery gates pass.

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

The browser journey covers bootstrap, catalog/list/library/metadata/request workflows, real worker execution, reviewed imports and cancellation, same-edition formats, PDF companions, local catalog matching, native MAM setup/search/detail, saved torrent manifests and reviewed wanted-book release selection/cancellation, qBittorrent settings/test/path preview/disable, reload persistence and mobile layout/sign-out. MAM, qBittorrent and ABS HTTP responses in this journey are synthetic fixtures; actual ABS compatibility has a separate harness. Screenshots are saved under `apps/web/test-results/`.

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

Organization settings provide a naming preview and saved defaults. The completed-download screen runs read-only inspection, supports collection-group correction, freezes selected group/version mappings and initial metadata/covers, and offers per-book import through verified routes. Unpublished entries can be stopped and unresolved collection children replanned while preserving completed siblings. Availability changes only after ABS confirmation. See [Organization planning](ORGANIZATION-PLANNING.md) for root mapping, supported formats, retry behavior and remaining importer gates, and [Ebook imports](EBOOK-IMPORTS.md) for PDF/CBZ inspection, equivalent formats and companion roles. Native audio inspection additionally requires ffmpeg/ffprobe; tests generate tiny original fixtures. [Native ABS certification](ABS-NATIVE-CERTIFICATION.md) documents the real pinned-server item tests and six application workflows with their boundaries.
