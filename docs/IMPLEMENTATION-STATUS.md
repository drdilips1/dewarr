# Implementation status and evidence

Updated September 17, 2026. Objective remains **implement the full PRD end to end**, including the planned later capabilities. This is an implementation checkpoint, not a completion declaration.

## Current code

- FastAPI API, React/TypeScript/Vite/Tailwind UI, generated OpenAPI client and locked Python/npm dependencies.
- Explicit Alembic migrations for identities, versions/representations/provider references, accounts/sessions, library bindings/grants, lists, operations and audit records.
- Procrastinate 3.9.0 schema in a separate namespace; enqueue on the same underlying psycopg transaction as domain changes.
- One-time token-protected bootstrap; Argon2 passwords; revocable opaque sessions; origin/CSRF checks; administrator/member/viewer enforcement; persistent sign-in budgets; authenticated secret encryption.
- Searchable/paginated local catalog, provisional title creation, availability projection, book detail, private/shared local lists, membership deduplication/order, account creation and durable activity checks.
- Responsive Seerr-style presentation independently implemented for the initial screens; no upstream frontend source has yet been copied.
- Audiobookshelf connection create/edit/disable/test with encrypted write-only tokens, URL prefixes, separate browser URL and scan capability diagnostics.
- Durable manual and scheduled ABS inventory with staged complete snapshots, pagination verification, permission/generation fencing, expired-run recovery, conservative missing detection and confirmed cross-library moves.
- My Library and book-copy views, medium-specific availability, private library grants, ABS deep links and durable manual work matching/unmatching. Recording evidence changes are held for review; matching narrator names alone never merge recordings.
- Hardcover/Open Library catalog adapters; paged search/edition loading; encrypted per-user Hardcover accounts; shared credential rate budgets, persistent cache and explicit provider errors/fallback.
- Provider search/preview/import UI, edition/recording cards, provenance, protected metadata edits, catalog-source matching/refresh, cover selection and simple/advanced metadata preferences. Catalog import never implies ownership or starts a download.
- Docker/Compose scaffold, CI checks, isolated native database/browser harness, notices/reuse ledger and developer guide.

## Stage coverage

| Stage | Status | Remaining gate work |
|---|---|---|
| S00 | In progress | Run container/PG18 certification; complete full adapter contracts and media/provider fixtures; operator backup scaffold; execute CI |
| S01 | In progress | Acquisition intents/reasons/reservations, version compatibility, mutation outbox, reversible identity merge/unmatch, complete grants/account management and recovery workflows |
| S02 | Metadata/catalog path implemented and fixture verified; remaining stage work | Live Hardcover certification; automatic targeted secondary enrichment; cross-provider version reconciliation and reversible match/merge; series pages, richer identifier search and complete list UI |
| S03 | Inventory path implemented and fixture verified | Actual ABS 2.36.1 certification; change-event adapter; broader identifier/file-based move resolution; reversible correction history UI; explicit repair/ignore/replacement intents |
| S04–S09 | Pending | Importer, native sources, qBittorrent, aggregation/ranking, external lists/automation, discovery/write-back, complete hardening and release |
| S10 | Pending | All six expansion work packages remain in scope and unimplemented |

No full stage gate is marked complete. Working isolated foundations are not substitutes for the complete required workflow.

## Verified evidence

Environment: macOS arm64, Python 3.13.14, local PostgreSQL 16.14, Procrastinate 3.9.0, Node 26.7.0. These are actual local test versions, distinct from the planned production certification matrix.

| Evidence | Scope |
|---|---|
| 47 backend tests passing | Prior foundation/ABS cases plus metadata provider parsing, author/narrator separation, malformed GraphQL, cache/rate budgets, private tokens, concurrent catalog import, edition pagination, protected edits, changed-version review, private inventory-version visibility and credential-generation fencing |
| Migration upgrade → downgrade to base → upgrade and Alembic drift check passing on isolated test database | Current four migrations and queue namespace; not an upgrade from a released production application |
| Frontend TypeScript and production build passing | Current implemented routes and generated API types |
| Browser journey passing | Prior setup/list/ABS/grant/member flows plus Hardcover account test, provider search and focused preview, catalog import, edition cards, protected edits and refresh; desktop/mobile metadata screenshots and no horizontal overflow; 1 expanded Playwright journey passed |
| Read-only live Open Library lookup passing | Search for Frankenstein/Mary Shelley, resolve the returned work/authors and load 50 editions with truthful continuation; no broader provider/format certification implied |
| Wheel build and frozen migration inclusion | Current Python packaging |
| Registry-resolved image digests | Image identities exist; does not prove image build or Compose runtime |

Backend evidence is saved locally at `.local/evidence/backend.xml`; browser screenshots/results are under `apps/web/test-results/`. Generated artifacts and live database files are not committed. CI definitions are present but have not been run remotely.

## Acceptance mapping: partial evidence only

- AT-01: bootstrap/roles/origin subset; integrations and filesystem setup pending.
- AT-02: entity schema exists; merge/unmatch behavior pending.
- AT-03: metadata provenance, manual locks/clear/unlock, fresh refresh and changed-narrator review verified through fixtures; full cross-provider and initial sidecar/ABS-edit preservation remains pending.
- AT-04/AT-05: local/provider catalog search, book page/editions and basic private/shared lists; source-native books, series navigation and discovery/sharing completion remain pending.
- AT-06/AT-07: synthetic HTTP inventory, private grants, media classification, partial-sync freshness, conservative missing confirmation and cross-library moves tested. Actual ABS version/scanner and broader move/replacement scenarios remain pending.
- AT-13/AT-30: generic diagnostic command concurrency, atomic enqueue and redelivery tested; actual acquisition and external-side-effect crash matrix pending.
- AT-24: basic operation activity implemented; acquisition repair actions pending.
- AT-27: account/list/library isolation, permission revocation, sessions, write-only connection secrets and restricted endpoint redirects verified in the current subset; complete source/file defenses pending.
- AT-28/AT-29: responsive browser/build/migration subsets; full accessibility, packaging and compatibility certification pending.

All other scenarios remain not run. None of the full AT scenarios is claimed complete by these narrower tests.

## Next work

Complete S01 acquisition/identity contracts, the remaining S02 metadata/series/list behavior, and S03 event/correction/live-compatibility gates. See [Metadata integration](METADATA-INTEGRATION.md) for the implemented provider contracts and remaining limitations. Actual ABS certification remains required before claiming live support. Then implement S04 import certification before the S05 MAM/qBittorrent vertical slice. Keep S07 list automation gated on those results.

Known gaps to address as those modules land: complete list pagination instead of current bounded result windows; list rename/delete UI and bulk actions; reversible metadata matching and cross-provider identity corrections; integration secrets/key rotation; role/grant administration and revocation; durable acquisition state transitions and operation payload conflict detection; explicit external-state backup/restore.

## Inventory checkpoint limitations

See [Audiobookshelf integration contract](AUDIOBOOKSHELF-INTEGRATION.md). The current fixture proves our HTTP/workflow behavior, not actual scanner/file-layout compatibility. No user's ABS account, qBittorrent or media files were used. Source acquisition, importing, external list automation and the rest of the PRD remain incomplete. Mixed-media/private inventory blocks downgrade to the older schema because that schema cannot preserve its identity/privacy semantics; use a pre-upgrade backup for that rollback.
