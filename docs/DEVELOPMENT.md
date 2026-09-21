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

The URL above is an example; create the database and use your own local credentials. Tests clear their dedicated databases. Never use an installation database.

Browser tests require a second database ending in `_browser_test`:

```sh
cd apps/web
npx playwright install chromium
BOOK_E2E_DATABASE_URL=postgresql+psycopg://book:example-password@localhost:5432/dewarr_browser_test npm run test:e2e
```

The browser runner starts its own API, worker, and mock integration server. Fixtures use synthetic credentials. Do not add live tokens, personal reading lists, or private server addresses to fixtures.

## API changes

```sh
uv run python scripts/export_openapi.py
npm --prefix apps/web run generate:api
```

Commit the OpenAPI document and generated TypeScript types together. For database changes, include an Alembic migration and matching tests. Keep API and worker versions aligned.

## Repository hygiene

Commit source, reproducible tests, build tools, and public documentation. Keep installation `.env` files, secrets, database dumps, logs, personal research, generated test output, and internal plans out of Git. Third-party license notices must remain in distributions.
