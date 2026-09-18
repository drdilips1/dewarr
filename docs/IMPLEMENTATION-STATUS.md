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
- Reversible administrator asset matches, source unmatch and changed-edition keep/separate review, with journaled history, optimistic revisions, concurrent undo and immutable library-version bindings.
- Automatic targeted Open Library enrichment for missing Hardcover work fields, with atomic job creation, protected/primary-value preservation, run-token fencing, permission/identity rechecks, provider-directed retry delays, orphaned-job recovery and book-detail status.
- Wanted media requests with normalized ebook/audio/both/either requirements, exact recording/edition constraints, independent manual/local-list reasons, compatible destination reservations, cancellation and periodic inventory/permission reconciliation. Book-page preview and persisted request history explicitly distinguish saving wanted media from downloading it.
- Reversible canonical book grouping with merge preview, inherited source/version views, canonical search/list/availability projections, original binding preservation and atomic planned-request reconciliation. Private origin metadata/grants remain scoped; existing URLs resolve to the selected main record.
- Administrator naming presets/token preview and saved settings; read-only completed-download inspection with actual EPUB/PDF/CBZ/audio evidence, source hashes, bounded traversal/probes, proposed recording groups, version mapping and immutable review plans. Owner-scoped API/UI, transactional queueing, generation fencing and stale-settings checks; see [Organization planning](ORGANIZATION-PLANNING.md).
- Configured destination bindings and generation-fenced real filesystem probes; journaled no-replace hardlink/copy publication with interruption recovery. Reviewed import API/UI, per-child states and shared-library version reservations, final permission/configuration/identity fencing, source-preserving retries and ABS-confirmed availability are now implemented. Resolved collection children proceed while uncertain children stay held.
- Eight actual ABS 2.36.1 native scanner/API cases and six application workflows passed with synthetic media; see [native certification](ABS-NATIVE-CERTIFICATION.md). EPUB, PDF, CBZ, equivalent ebook formats, two-track audio and PDF companion cases include API dispatch, durable worker, exact-version confirmation, inventory refresh and duplicate skip.
- Immutable collection-group review with merge/split, disc/track assignment, explicit exclusions, proposal restore, stale-plan rejection and protection of reserved groups during sibling correction. Multi-file audio confirmation requires the reviewed playback order.
- Recoverable per-entry import cancellation, journaled staging cleanup, reservation release only after reconciliation, and selective replanning beside unchanged published siblings. Ambiguous publication stays held or continues ABS confirmation; see [Import cancellation](IMPORT-CANCELLATION.md).
- Initial cover export now freezes selected URLs and normalized JPEG bytes, validates public image routing and observed Open Library Archive redirects, and preserves later library artwork edits. Optional artwork failures leave books importable; see [Cover export](COVER-EXPORT.md).
- PDF/CBZ byte inspection runs in bounded child processes. Group review supports explicit same-edition ebook formats and PDF audiobook companions; companions do not establish ebook ownership or create catalog editions. Verified imported formats survive ABS inventory refresh only while file evidence agrees. See [Ebook formats and companions](EBOOK-IMPORTS.md).
- Production initial OPF generation is frozen in schema-2 import plans and exercised by the actual ABS scanner. Destination probes now verify ABS root mapping through an empty-folder challenge, library media/metadata settings and detection capabilities; credential changes invalidate evidence.
- Docker/Compose scaffold, CI checks, isolated native database/browser harness, notices/reuse ledger and developer guide.

## Stage coverage

| Stage | Status | Remaining gate work |
|---|---|---|
| S00 | In progress | Run container/PG18 certification; complete full adapter contracts and media/provider fixtures; operator backup scaffold; execute CI |
| S01 | In progress | Intents/reasons/planned reservations and request reconciliation implemented; frozen dispatch/outbox, complete version compatibility, selective work splitting and original source-attachment undo, complete grants/account management and recovery workflows remain |
| S02 | Metadata/catalog path implemented and fixture verified; remaining stage work | Live Hardcover certification; cross-provider version reconciliation and selective work splitting; series pages, richer identifier search and complete list UI |
| S03 | Inventory path implemented and fixture verified | Complete ABS certification beyond the eight native scanner/API cases; change-event adapter; broader identifier/file-based move resolution; explicit repair/ignore/replacement intents |
| S04 | Reviewed manual import, per-child publication/reservations/fencing, PDF/CBZ, same-edition formats, PDF companions and ABS confirmation implemented | Broader metadata resolution; automatic matching and broader collection coverage; additional formats and omnibus handling; file-alias reconciliation; full recovery and compatibility matrix |
| S05–S09 | Pending | Native sources, qBittorrent, aggregation/ranking, external lists/automation, discovery/write-back, complete hardening and release |
| S10 | Pending | All six expansion work packages remain in scope and unimplemented |

No full stage gate is marked complete. Working isolated foundations are not substitutes for the complete required workflow.

## Verified evidence

Environment: macOS arm64, Python 3.13.14, local PostgreSQL 16.14, Procrastinate 3.9.0, Node 26.7.0 and ffprobe 8.1.2. These are actual local test versions, distinct from the planned production certification matrix.

| Evidence | Scope |
|---|---|
| 341 backend tests passing | Prior 317 cases plus nineteen ebook-inspection/grouping cases and five format-import/inventory cases. New coverage includes malformed/encrypted PDFs, CBZ pages/entities/budgets, pinned probes, same-edition consent, companions, actual EPUB+PDF publication, primary-file change and loss of stale format evidence. Existing coverage includes cancellation, exact-version satisfaction, publication crash recovery, partial packs, permission fencing, metadata/export, source integrity, inventory, canonical grouping, correction and request reconciliation |
| Migration upgrade → downgrade to base → upgrade and Alembic drift check passing on isolated test database | Current fourteen migrations and queue namespace; populated correction/acquisition/merge/settings/inspection/import/grouping/cover/cancellation-history downgrade guards tested; not an upgrade from a released production application |
| Frontend TypeScript and production build passing | Current implemented routes and generated API types |
| Browser journey passing | Setup/list/ABS/grant/member/metadata/correction, wanted requests, canonical merge, organization/publication/cancellation and reload flows; additionally same-edition consent rejection/persistence/reset and PDF companion selection. Desktop/mobile screenshots and no horizontal overflow; expanded Playwright journey passed in 49.6 seconds |
| Native ABS 2.36.1 certification: eight item cases and six application workflows passing | Actual server/API/manual scanner, publisher hardlinks, conventional/nested version leaves and OPF metadata; native Node 24, synthetic media only. EPUB, merged two-track audio, PDF, CBZ, EPUB+PDF and audio+PDF companion pass application API/worker confirmation, correct catalog-version count, inventory refresh, ownership and duplicate skip. All six include queued cancellation, independent covers and preservation of later artwork edits; watcher and the wider compatibility matrix remain pending |
| Read-only live Open Library lookup passing | Search for Frankenstein/Mary Shelley, resolve the returned work/authors and load 50 editions with truthful continuation; no broader provider/format certification implied |
| Read-only live Open Library cover retrieval passing | One documented cover fetched through the production public-IP/TLS-pinned route, including Archive redirects, then normalized in the decoder process; no external artwork bundled |
| Wheel build and frozen migration inclusion | Current Python packaging |
| Registry-resolved image digests | Image identities exist; does not prove image build or Compose runtime |

Backend evidence is saved locally at `.local/evidence/backend.xml`; browser screenshots/results are under `apps/web/test-results/`. Generated artifacts and live database files are not committed. CI definitions are present but have not been run remotely.

## Acceptance mapping: partial evidence only

- AT-01: bootstrap/roles/origin subset; integrations and filesystem setup pending.
- AT-02: reversible asset matching/unmatching, source unmatch, changed-version review and stale/concurrent undo verified; canonical grouping/undo and historical binding preservation now verified; selective splitting and complete cross-provider version equivalence remain pending.
- AT-03: metadata provenance, manual locks/clear/unlock, fresh refresh, changed-narrator keep/separate review and targeted secondary enrichment verified through fixtures and the browser; full cross-provider and initial sidecar/ABS-edit preservation remains pending.
- AT-04/AT-05: local/provider catalog search, book page/editions and basic private/shared lists; source-native books, series navigation and discovery/sharing completion remain pending.
- AT-06/AT-07: synthetic HTTP inventory, private grants, media classification, partial-sync freshness, conservative missing confirmation and cross-library moves tested. Actual ABS scanner/application cases now also verify multi-format persistence and companion handling without false ebook editions; broader move/replacement and full compatibility scenarios remain pending.
- AT-12/AT-13/AT-30: wanted-media/exact-recording inventory checks, independent reasons, concurrent/replayed commands, compatible planned reservations, atomic enqueue/redelivery and periodic reconciliation verified; source ranking, actual transfers and the external-side-effect crash matrix remain pending.
- AT-15–AT-19/AT-30: naming, inspection, frozen plans, per-child publication, final authority/identity fencing, journal recovery and ABS confirmation subsets verified. Eight native ABS scanner item cases and six application workflows pass; PDF/CBZ, reviewed equivalent formats and companion files now supplement grouping and playback-order evidence. Cover selection/preservation and cancellation/replanning pass their specific unit/integration/browser/native checks. Omnibus, watcher, additional formats and the complete recovery/scanner matrix remain pending.
- AT-24: basic operation activity implemented; acquisition repair actions pending.
- AT-27: account/list/library isolation, permission revocation, sessions, write-only connection secrets and restricted endpoint redirects verified in the current subset; complete source/file defenses pending.
- AT-28/AT-29: responsive browser/build/migration subsets; full accessibility, packaging and compatibility certification pending.

All other scenarios remain not run. None of the full AT scenarios is claimed complete by these narrower tests.

## Next work

Complete S01 identity and external-side-effect contracts, the remaining S02 metadata/series/list behavior, and S03 event/correction/live-compatibility gates. See [Acquisition foundation](ACQUISITION-FOUNDATION.md), [Metadata integration](METADATA-INTEGRATION.md) and [Identity corrections](IDENTITY-CORRECTIONS.md) for implemented contracts and remaining limitations. Complete ABS certification remains required before claiming general live support. Continue S04 from [Organization planning](ORGANIZATION-PLANNING.md) through grouping/format coverage, file-alias reconciliation and complete recovery/ABS certification before the S05 MAM/qBittorrent vertical slice. Keep S07 list automation gated on those results.

Known gaps to address as those modules land: complete list pagination instead of current bounded result windows; list rename/delete UI and bulk actions; selective work splitting and cross-provider version identity corrections; integration secrets/key rotation; role/grant administration and revocation; source selection and frozen dispatch state transitions; explicit external-state backup/restore.

## Inventory checkpoint limitations

See [Audiobookshelf integration contract](AUDIOBOOKSHELF-INTEGRATION.md). HTTP fixtures prove inventory/import workflow behavior; native certification covers eight specific scanner/file-layout cases and ebook/merged-audio application workflows. Neither is the complete compatibility gate. No user's ABS account, qBittorrent or media files were used. Source acquisition, complete importing, external list automation and the rest of the PRD remain incomplete. Populated schemas with identity/privacy/correction/import history block lossy downgrade; use a pre-upgrade backup for rollback.
