# Implementation status and evidence

Updated September 17, 2026. Objective remains **implement the full PRD end to end**, including the planned later capabilities. This is an implementation checkpoint, not a completion declaration.

## Current code

- FastAPI API, React/TypeScript/Vite/Tailwind UI, generated OpenAPI client and locked Python/npm dependencies.
- Explicit Alembic migrations for identities, versions/representations/provider references, accounts/sessions, library bindings/grants, lists, operations and audit records.
- Procrastinate 3.9.0 schema in a separate namespace; enqueue on the same underlying psycopg transaction as domain changes.
- One-time token-protected bootstrap; Argon2 passwords; revocable opaque sessions; origin/CSRF checks; administrator/member/viewer enforcement; persistent sign-in budgets; authenticated secret encryption.
- Searchable/paginated local catalog, provisional title creation, availability projection, book detail, private/shared local lists, membership deduplication/order, account creation and durable activity checks.
- Responsive Seerr-style presentation independently implemented for the initial screens; no upstream frontend source has yet been copied.
- Docker/Compose scaffold, CI checks, isolated native database/browser harness, notices/reuse ledger and developer guide.

## Stage coverage

| Stage | Status | Remaining gate work |
|---|---|---|
| S00 | In progress | Run container/PG18 certification; complete full adapter contracts and media/provider fixtures; operator backup scaffold; execute CI |
| S01 | In progress | Acquisition intents/reasons/reservations, version compatibility, mutation outbox, reversible identity merge/unmatch, complete grants/account management and recovery workflows |
| S02 | In progress | Hardcover/Open Library adapters, metadata resolution/provenance/locks, version/series pages, expanded search and complete list UI |
| S03 | Initial domain logic only | Actual ABS adapter/inventory generations/events, binding corrections, missing/move reconciliation, grants UI and backend deep links |
| S04–S09 | Pending | Importer, native sources, qBittorrent, aggregation/ranking, external lists/automation, discovery/write-back, complete hardening and release |
| S10 | Pending | All six expansion work packages remain in scope and unimplemented |

No full stage gate is marked complete. Working isolated foundations are not substitutes for the complete required workflow.

## Verified evidence

Environment: macOS arm64, Python 3.13.14, local PostgreSQL 16.14, Procrastinate 3.9.0, Node 26.7.0. These are actual local test versions, distinct from the planned production certification matrix.

| Evidence | Scope |
|---|---|
| 15 backend tests passing | Bootstrap concurrency/authorization, CSRF/revocation/roles, persistent login budget, safe validation errors, encrypted secrets, transactional rollback, concurrent command dedupe, real worker/redelivery, local catalog/list privacy and availability semantics |
| Migration upgrade → downgrade to base → upgrade and Alembic drift check passing on isolated test database | Current two migrations and queue namespace; not an upgrade from a released production application |
| Frontend TypeScript and production build passing | Current implemented routes and generated API types |
| Browser journey passing | Setup, catalog/list persistence, ownership remains unconfirmed without an asset, actual worker completion, desktop/mobile rendering, reload and mobile sign-out; 1 Playwright journey passed |
| Wheel build and frozen migration inclusion | Current Python packaging |
| Registry-resolved image digests | Image identities exist; does not prove image build or Compose runtime |

Backend evidence is saved locally at `.local/evidence/backend.xml`; browser screenshots/results are under `apps/web/test-results/`. Generated artifacts and live database files are not committed. CI definitions are present but have not been run remotely.

## Acceptance mapping: partial evidence only

- AT-01: bootstrap/roles/origin subset; integrations and filesystem setup pending.
- AT-02: entity schema exists; merge/unmatch behavior pending.
- AT-04/AT-05: local catalog, book page and basic private/shared lists only.
- AT-06: availability predicate tested with explicit database assets/grants; ABS acquisition of that evidence pending.
- AT-13/AT-30: generic diagnostic command concurrency, atomic enqueue and redelivery tested; actual acquisition and external-side-effect crash matrix pending.
- AT-24: basic operation activity implemented; acquisition repair actions pending.
- AT-27: account/list isolation, sessions and validation-redaction subset; outbound URL/file/source defenses pending.
- AT-28/AT-29: responsive browser/build/migration subsets; full accessibility, packaging and compatibility certification pending.

All other scenarios remain not run. None of the full AT scenarios is claimed complete by these narrower tests.

## Next work

Complete S01 acquisition/identity contracts, implement S02 metadata adapters and provenance, and build the S03 ABS connection/inventory path. Use actual inventory to drive ownership before enabling any download. Then implement S04 import certification before the S05 MAM/qBittorrent vertical slice. Keep S07 list automation gated on those results.

Known gaps to address as those modules land: complete list pagination instead of current bounded result windows; list rename/delete UI and bulk actions; full metadata editing and corrections; integration secrets/key rotation; role/grant administration and revocation; durable acquisition state transitions and operation payload conflict detection; explicit external-state backup/restore.
