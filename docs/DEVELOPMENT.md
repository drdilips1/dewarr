# Contributing to Dewarr

## Project layout

- `apps/web`: React and TypeScript UI.
- `services/app`: FastAPI backend, integrations, worker, and database migrations.
- `tests`: backend unit, integration, and adapter contract tests.
- `apps/web/tests`: Playwright browser tests.
- `scripts`: installation, API generation, dependency notices, public catalog updates, and isolated test fixtures.
- `deploy`: optional Docker Compose configurations.

## Run locally

Requires Python 3.13, uv, Node.js 24, PostgreSQL 18, and FFmpeg (including ffprobe).

```sh
uv sync --frozen
npm --prefix apps/web ci
python3 scripts/init_env.py --mode native
```

Create a development database and edit `BOOK_DATABASE_URL` in `.env` to match it. Set `BOOK_PUBLIC_URL` to the browser origin you will use. The generated native database URL is a local example, not a provisioned database.

```sh
uv run alembic upgrade head
npm --prefix apps/web run build
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Run the worker in another terminal:

```sh
uv run python -m app.jobs.worker
```

Open http://localhost:8000 and create the first account. For UI hot reload, use `npm --prefix apps/web run dev` and set `BOOK_PUBLIC_URL=http://localhost:5173` before restarting the API. Vite proxies API requests to port 8000.

For a container development build:

```sh
docker compose -f compose.yaml -f deploy/compose.build.yaml up -d --build
```

This uses the same two-service layout with a locally built app image. The container entrypoint initializes `/config`, waits for PostgreSQL, runs migrations, and supervises the API and worker. Unit tests in `tests/unit/test_container.py` cover startup and process lifecycle behavior.

## Checks

```sh
uv run ruff check services tests scripts
uv run ruff format --check services tests scripts
uv run pytest tests/unit -q
npm --prefix apps/web run format:check
npm --prefix apps/web run build
```

Integration tests require a separate PostgreSQL database whose name ends in `_test`:

```sh
BOOK_TEST_DATABASE_URL=postgresql+psycopg://book:example-password@localhost:5432/dewarr_test uv run pytest -q
```

Install `ffmpeg` and PostgreSQL client tools matching your test server’s major version (`pg_dump` and `pg_restore` are used by restore tests).

The URL above is an example; create the database and use your own local credentials. Tests clear their dedicated databases. Never use an installation database.

### Release checks and test timing

`Publish container` calls the reusable `Application checks` workflow and publishes only
after every check succeeds. Main and release-tag pushes enter through the publish
workflow, so they do not also launch a duplicate standalone check run. Pull requests,
other branches, and manual check runs still run checks directly. A newer commit cancels
obsolete checks on the same branch; different release tags remain independent.

Backend lint, schema, unit, and contract checks run separately from four integration
shards. Each shard uses two pytest workers with independent databases. Shards partition
the collected test IDs deterministically, including parameterized cases, so every case
runs exactly once across the four shards. To reproduce a shard, set
`BOOK_TEST_DATABASE_URL` as above and run:

```sh
uv run pytest tests/integration -q -n 2 --dist=worksteal \
  -p scripts.pytest_shard --ci-shard=1/4 \
  --timeout=120 --timeout-method=thread --max-worker-restart=0 --durations=25
```

CI limits each test (including fixtures) to two minutes. The timeout terminates the
stuck worker and identifies its test; worker replacement is disabled so the shard
fails instead of repeatedly restarting. Integration steps have a ten-minute limit and
their jobs have a twelve-minute limit, leaving time to upload evidence after a step
timeout. Shards finish independently even if another fails, preserving failure evidence.
The `backend` aggregate check requires both the quick checks and every integration shard
to pass. Each shard uploads its own JUnit report and prints its slowest tests in the log.
Local pytest runs have no time limit unless the timeout options are supplied.

Schema drift is checked by explicitly migrating a fresh database before `alembic check`;
it does not rely on databases created by pytest workers. Dependency caches are keyed by
their lockfiles. Workflow improvements do not suppress failing application tests: a
failed test, timeout, or skipped backend dependency prevents publishing.

Browser tests require a second database ending in `_browser_test`:

```sh
cd apps/web
npx playwright install chromium
BOOK_E2E_DATABASE_URL=postgresql+psycopg://book:example-password@localhost:5432/dewarr_browser_test npm run test:e2e
```

The browser runner starts its own API, worker, and mock integration server. Its foundation project creates the first account and synthetic connections before the browser journeys run. Goodreads collection pages use bundled snapshots; remote cover images use local responses, so tests do not depend on public services. Fixtures use synthetic credentials. Do not add live tokens, personal reading lists, or private server addresses to fixtures.

## API changes

```sh
uv run python scripts/export_openapi.py
npm --prefix apps/web run generate:api
```

Commit the OpenAPI document and generated TypeScript types together. For database changes, include an Alembic migration and matching tests. Keep API and worker versions aligned.

## Repository hygiene

Commit source, reproducible tests, build tools, and public documentation. Keep installation `.env` files, secrets, database dumps, logs, personal research, generated test output, and internal plans out of Git. Third-party license notices must remain in distributions.
