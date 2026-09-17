# End-to-end development plan

Planning baseline v1.1 · September 17, 2026 · Implementation has started; see [current status and evidence](docs/IMPLEMENTATION-STATUS.md). No full stage gate is yet complete.

This plan implements [the PRD](PRD.md) using [the researched decisions](IMPLEMENTATION-DECISIONS.md). [Acceptance Plan](ACCEPTANCE-PLAN.md) specifies the evidence required at each gate. A stage is complete only when its exit gate passes; this document does not report completed engineering or tested compatibility.

The [Product and Development Roadmap](DEVELOPMENT-ROADMAP.md) provides a concise handoff across these documents, including the product boundary, P0/P1 decisions and milestone demonstrations.

## 1. Delivery strategy

Deliver a working vertical slice early, then expand source coverage and automation. Build durable domain state, identity and inventory before dispatch; certify importing before connecting automatic acquisition. Hardening, accessibility, authorization and migration testing start with their first affected feature rather than waiting for the final stage.

| Stage | Outcome | Depends on | Release milestone |
|---|---|---|---|
| S00 | Repository, contracts, CI and reproducible local stack | Planning baseline | Engineering scaffold |
| S01 | Durable domain, authentication, permissions and jobs | S00 | Internal foundation |
| S02 | Catalog, metadata, familiar browsing and local lists | S01 | Catalog preview |
| S03 | ABS inventory, ownership and reconciliation | S01; integrates with S02 | Connected library preview |
| S04 | Safe, collection-aware importer and ABS confirmation | S01, S03; catalog contracts from S02 | Import certification |
| S05 | Native MAM → qBittorrent → imported book | S02, S03, S04 | Private alpha |
| S06 | ABB/Prowlarr aggregation, ranking and series policies | S05 | Acquisition feature alpha |
| S07 | Hardcover/Goodreads subscriptions and automation | S06; connectors can start after S02 | Automation beta |
| S08 | Discovery, shared curation and optional list write-back | S02, S03, S07 | Feature-complete beta |
| S09 | Recovery, compatibility, accessibility and release operations | S00–S08 gates | Production v1.0 |
| S10 | Independently scoped expansion releases | Stable v1 and relevant module gates | Post-v1 |

S02 and S03 can run as parallel workstreams once S01 contracts stabilize. Source parsing fixtures, discovery layouts and list adapters can be developed early against contracts, but cannot bypass import or automation gates. The dependency table describes integration gates, not a requirement to keep all contributors sequential.

Do not commit to calendar dates before S01 exposes actual integration effort and team throughput. After S01, estimate remaining work packages using observed velocity; track provider/parser uncertainty separately from normal UI work. A date forecast never replaces a gate.

There are **61 work packages**: 55 through v1.0 (S00–S09) and six independently scoped expansion packages (S10). These are planning units, not equal-sized tickets or estimates. The first valuable release is the S05 manual acquisition path; the defining list-to-library product journey is complete at S07; the full v1 experience includes S08 and S09.

```mermaid
flowchart LR
    S00["S00 Scaffold"] --> S01["S01 Identity and durability"]
    S01 --> S02["S02 Catalog and UI"]
    S01 --> S03["S03 ABS inventory"]
    S02 --> S04["S04 Import certification"]
    S03 --> S04
    S04 --> S05["S05 MAM and qBit · Alpha"]
    S05 --> S06["S06 Sources and series"]
    S06 --> S07["S07 List automation · Beta"]
    S07 --> S08["S08 Discovery and curation"]
    S08 --> S09["S09 Production v1"]
    S09 --> S10["S10 Expansion releases"]
```

## 2. Engineering boundaries

### Selected stack and intended repository structure

- Frontend: React, TypeScript, Vite, Tailwind and TanStack Query; adapt selected Seerr visual components to book-specific view models.
- API: Python, FastAPI and Pydantic; generated TypeScript client from a versioned OpenAPI contract.
- Persistence: PostgreSQL, SQLAlchemy 2, psycopg 3 and Alembic.
- Workers: Procrastinate, initially the researched 3.9.0 baseline, with atomic enqueue and explicit stalled-job recovery.
- Distribution: Docker Compose with API/static UI, worker and PostgreSQL. No Redis requirement. External services stay separately administered.

Proposed paths below are development targets, not files already created:

```text
apps/web/                     UI routes, components, generated API client
services/app/api/             HTTP, sessions, authorization, serializers
services/app/domain/          catalog, inventory, lists, policies, acquisition
services/app/adapters/        metadata, sources, downloader, library backend
services/app/jobs/            persistent workflows and reconciliation
services/app/importing/       inspection, manifests, naming, safe publication
services/app/db/              models, migrations, transactions
tests/unit/                   pure identity, policy and path rules
tests/contracts/              provider schemas, parsers, compatibility
tests/integration/            real PostgreSQL, qBittorrent and ABS fixtures
tests/e2e/                    user journeys and authorization
tests/fixtures/               synthetic/redacted media and provider records
deploy/                       Compose, image build, example configuration
docs/                         API, operator guides, compatibility, reuse ledger
```

Use a modular monolith and a separate worker process from the same backend codebase. Adapters return typed results and errors; they do not directly modify arbitrary domain tables. Domain services own state transitions. Workflow jobs orchestrate short transactions around external operations; they never hold a database transaction open for a network request or file copy.

### Minimum adapter contracts

| Contract | Operations | Required result properties |
|---|---|---|
| Metadata provider | Search, work/version/series fetch, supported discovery | Namespaced IDs, provenance, language, unknown values, capability flags |
| List provider | Fetch pages/snapshot; optional mutate | Account/scope, cursor, completeness, observation time, supported mutations |
| Release source | Search, detail, resolve acquisition | Original source/indexer IDs, raw fields, coverage evidence, transport, auth/route errors |
| Download client | Capabilities, submit, find/reconcile, status, files | Stable association, uncertain outcome, source paths, completion and seeding state |
| Library backend | Libraries, inventory, item, events, optional scan, deep link | Accessible scope, complete-generation marker, backend item IDs, file evidence |
| Import publisher | Validate, inspect, plan, stage, publish, reconcile | Confined paths, manifest, no-replace behavior, filesystem evidence |

Each adapter has timeout, rate-budget, retry classification, cancellation and redaction behavior. Capabilities control UI actions; missing fields remain unknown. MAM-specific data survives normalization. Gluetun HTTP routing is configured per applicable integration; qBittorrent torrent egress is not changed by this setting.

### Persistence and concurrency responsibilities

| Domain | Records and constraints to establish |
|---|---|
| Identity | Work/version/representation UUIDs; provider namespace/kind/ID references; attributed identifier assertions; reversible link/merge history |
| Inventory | Backend/library/item/file IDs; scan generation and completeness; verified work coverage; per-user library grants; stale/missing state |
| Lists | Local list/membership; external subscription and observation; source membership distinct from local curation; policy version; baseline/backfill marker |
| Acquisition | Intent, target constraints, request reasons, active reservation, source release/coverage, shared download job, cancellation/suppression history |
| Import | Immutable planned mapping plus revision history, per-child entries, publish journal, source fingerprints, destination ownership and ABS bindings |
| Operations | Encrypted connection secrets, redacted audit events, durable outbox, locks/leases, migration version and backup metadata |

Do not create a blanket unique constraint on work+medium: a user may deliberately request another narrator or edition. Define normalized target constraints and reservation keys; serialize competing fulfillment checks for a work/medium, then evaluate whether an existing asset or in-flight transfer actually satisfies each target. One shared transfer can satisfy several compatible intents. Database constraints protect the resulting associations, while domain rules protect semantic compatibility.

Inventory visibility and transfer deduplication have different scopes. Check user-visible ownership only against granted libraries. Privileged orchestration may avoid duplicate transfers across the installation, but must not expose another user's private library, list title, reason or credentials. Define a generic pending outcome when shared infrastructure is reused without granting visibility. An asset in an inaccessible library cannot satisfy that user's request merely because it exists elsewhere; any shared transfer must still deliver to an authorized destination and gain accessible backend confirmation.

### API and UI boundaries

Publish contracts for catalog/search, works/versions, availability, lists/subscriptions, profiles, source searches, requests, activity, integrations, import previews and corrections. Mutating calls accept idempotency keys where replay can cause work. Long-running commands return operation IDs, not a connection held open until a download finishes. Incremental search/activity updates may use server-sent events with resumable polling fallback; reconnecting must not resubmit a request.

Paginate potentially large collections. Use typed errors with safe user messages and correlation IDs. Reject unauthorized operations server-side. Use secure server-managed sessions, CSRF protection for cookie-authenticated mutations, bounded request bodies and validated outbound destinations. Administrator-configured local service URLs are supported deliberately; provider-supplied redirects and feed entries do not gain unrestricted access to the local network.

## 3. Stage work packages and gates

Ticket IDs below are stable planning references. Each ticket should acquire a concrete owner and implementation estimate when its stage starts. Responsibility names describe roles, not a staffing requirement; one developer can own several roles.

### S00 — Repository, contracts and scaffold

**Entry:** PRD and implementation decisions accepted as the working baseline. **Responsible:** technical lead/platform, with frontend and backend input. **Requirements:** FR-01, FR-36 foundations; NFR-09, NFR-12.

| Ticket | Deliverable |
|---|---|
| S00-01 | Initialize frontend/backend structure, formatting/type checks, dependency lockfiles, MIT project license and file/dependency reuse ledger. Record upstream revision and retained notices before adapting code/assets. |
| S00-02 | Add Compose development/test configuration, non-root identities, secret-file support, health/readiness and migration entrypoint. Pin researched integration test images; do not assume the user's versions. |
| S00-03 | Define adapter interfaces, error taxonomy, operation envelope, OpenAPI generation and architecture boundaries. Record identity/authority decisions as ADRs linked to D01–D13. |
| S00-04 | Create synthetic catalog/media/provider fixture sets and isolated ABS/qBittorrent/PostgreSQL harness. Document how fixtures are generated without distributing private tracker data. |
| S00-05 | Configure CI for contracts, backend/frontend checks, migration smoke tests, image build and secret/license/dependency checks. Establish local backup/restore skeleton. |

**Demo:** clean checkout starts the stack and displays a health-aware shell; API client generation is reproducible.

**Exit:** AT-01 installation subset and AT-29 scaffold subset pass. No required runtime service is omitted from Compose. No copied component lacks a recorded provenance/license decision. Establish baseline test reports without claiming integrations are certified.

### S01 — Durable domain, permissions and jobs

**Entry:** S00 contracts and test harness. **Responsible:** backend/platform; frontend for session/activity shell. **Requirements:** FR-01, FR-02, FR-05, FR-06, FR-22, FR-35 foundations; NFR-02, NFR-05, NFR-08, NFR-09.

| Ticket | Deliverable |
|---|---|
| S01-01 | Alembic schema for catalog, provenance, inventory bindings, lists, intents/reasons, jobs, manifests and audit. Define constraints, indexes and transactional service boundaries. |
| S01-02 | Bootstrap admin; administrator/member/viewer permissions; encrypted per-user credentials; library grants; secure sessions and recovery procedure. |
| S01-03 | Wire Procrastinate enqueue through the same underlying psycopg transaction as domain changes. Prove rollback/no-enqueue and commit/one-job behavior through SQLAlchemy integration; document the supported adapter path. |
| S01-04 | Implement idempotent command handling, leases, serialized reservation checks, worker restart/stalled-job handling, and a durable external-operation ledger/outbox. |
| S01-05 | Implement identity assertions, protected manual matches, reversible association corrections and merge redirects. Add audit and activity APIs with redacted structured events. |

**Demo:** concurrent duplicate fixture requests create one compatible acquisition, survive worker termination and remain correctly scoped to each account.

**Exit:** AT-01 authorization baseline, AT-02 foundation, AT-13 reservation subset, AT-24 event subset and AT-30 transaction/redelivery subset pass using real PostgreSQL. Failure to achieve atomic enqueue blocks this stage; choose and document a supported transactional outbox adaptation before progressing, rather than silently accepting dual writes.

### S02 — Catalog, metadata and familiar browsing

**Entry:** S01 identity and authorization contracts. **Responsible:** catalog/backend and frontend. **Requirements:** FR-05–FR-10, FR-12 initial local lists; NFR-03, NFR-07, NFR-10.

| Ticket | Deliverable |
|---|---|
| S02-01 | Hardcover catalog adapter and independent provider contract; Open Library for targeted conservative work/ebook fallback, caching, budgets and version/series normalization. Explicitly document which fields each adapter supplies; do not treat Open Library as a complete recording catalog or bulk-harvest it. |
| S02-02 | Metadata resolver with Automatic defaults, provenance, protected edits, cover selection and advanced group/field preferences. Keep contradictory editions separate. |
| S02-03 | Adapt Seerr navigation, cover cards, shelves, detail layout, dialogs and settings visuals. Remove film/TV service bindings and vocabulary; implement responsive keyboard-accessible states. |
| S02-04 | Local/catalog search, work/edition/recording/series views, provisional works and correction flow. Add paginated endpoints and local search indexes. |
| S02-05 | Local list CRUD, ordering and bulk selection; own/private access; placeholder ownership fields use explicit unknown state until inventory exists. |

**Demo:** find a book, inspect its editions/recordings and provenance, protect a title edit and add it to a local list without advanced setup.

**Exit:** AT-02–AT-04 and AT-05 local-list subset pass. Provider outage leaves cached catalog usable. No catalog edition is created merely because two tracker releases exist. Initial accessibility checks cover navigation, search and book detail.

### S03 — Audiobookshelf inventory and reconciliation

**Entry:** S01; S02 schemas/views available for final integration. **Responsible:** library adapter/backend, frontend availability. **Requirements:** FR-02 library grants, FR-03 ABS, FR-10, FR-13–FR-15; NFR-01, NFR-05, NFR-08.

| Ticket | Deliverable |
|---|---|
| S03-01 | ABS connection/capability test, inventory pagination, item details, deep links and change-event support where the backend permits it. Polling repairs gaps and supports connections without event capability. Separate scan authority from inventory access. |
| S03-02 | Reconciliation generations with complete/partial markers; periodic full repair after event gaps; stale, suspected missing and confirmed missing transitions. |
| S03-03 | Asset-to-work/version matching, technical media classification, companion-document exclusions and omnibus containment model. Keep match corrections durable. |
| S03-04 | Overall and medium-specific availability projections, granted-library filtering, pending states and version counts in cards/detail/library. |
| S03-05 | Relink external moves, handle permission changes and unavailable mounts conservatively; expose repair/ignore/replacement intent without enabling automatic replacement. |

**Demo:** an ebook alone checks the work as owned; an audio request is still missing. Losing an ABS page does not erase the library. Two narrators show two available recordings.

**Exit:** AT-06, AT-07, AT-27 library-scope subset pass. Inventory-only credentials work. No scan-start or download status is used as proof of ownership.

### S04 — Safe importing, naming and collection manifests

**Entry:** S01 durability and S03 inventory verification. **Responsible:** importer/filesystem backend, compatibility QA, frontend preview. **Requirements:** FR-04, FR-08 preservation, FR-25–FR-30; NFR-01, NFR-02, NFR-06.

| Ticket | Deliverable |
|---|---|
| S04-01 | Completed-file inspection, directory grouping, embedded metadata reading and conservative work/version matching. Create per-book manifests and hold ambiguous children. |
| S04-02 | Naming preset/token model, conditional punctuation, source-to-destination preview, medium roots, version separation and stable collision suffixes. Freeze each accepted import plan. |
| S04-03 | Validate mount/path mappings and actual hardlink capability; implement confined paths, source validation, external staging, no-replace publish and journaled crash reconciliation. Copy fallback requires an explicit policy. |
| S04-04 | Generate independent OPF/cover sidecars with initial-export authority; reject unsafe inode-changing operations; track generated-file ownership separately from preexisting destination content. |
| S04-05 | Handle split series packs, mixed media, existing-owned children, extras and inseparable omnibus assets. Do not publish unresolved children as verified works. |
| S04-06 | Certify conventional and nested-version layouts against actual ABS item boundaries and metadata precedence. Implement scan-capable and watcher-only confirmation, timeout/attention and repair. |

**Demo:** a synthetic completed series folder becomes separate correctly named ABS items, preserving all source bytes; one ambiguous child remains held while others complete. Two recordings stay separate in ABS.

**Exit:** AT-14 import subset and AT-15–AT-19 pass; AT-30 publication crash subset passes. Compare source hashes before/after and hardlink inode behavior where supported. A missing ABS confirmation leaves awaiting-library, never available. Enable nested presets only for tested capability combinations. This gate uses disposable test services, not the user's media collection.

### S05 — Native MAM and qBittorrent vertical slice

**Entry:** S02–S04 gates. **Responsible:** source/downloader backend and acquisition frontend. **Requirements:** FR-03–FR-04, FR-09–FR-10, FR-16, FR-20–FR-23, FR-30; NFR-01, NFR-02, NFR-10.

| Ticket | Deliverable |
|---|---|
| S05-01 | Native MAM search/detail adapter adapted from bounded MouseSearch references; retain authors, narrators, descriptions, genres, raw titles, formats and release evidence. |
| S05-02 | mam_id storage/rotation, credential-scoped distributed serialization, explicit proxy route, shared rate limits and distinct auth/parser/no-result outcomes. No secret-bearing diagnostics. |
| S05-03 | qBittorrent adapter for capability negotiation, add, association, status and file enumeration; route/download path settings; preserve external ownership and seeding. |
| S05-04 | Basic profiles and ebook/audio/both/either requests. Implement eligibility before ranking, acquisition reservations and media/version-aware satisfaction. |
| S05-05 | Orchestrate search → reserve → submission ledger → reconcile/monitor → inspection/import → ABS confirmation. Recover an add timeout by lookup before any resubmission. |
| S05-06 | Sources/detail panel, direct-source search/provisional catalog flow, download action and activity actions. Expose pack scope and per-child progress. |

**Demo:** select a title, compare rich MAM results, download to qBittorrent and receive an ABS-confirmed check. Restart at uncertain submission without creating another transfer. A second request attaches its reason or reports satisfaction.

**Exit/private alpha:** AT-08, AT-12 baseline, AT-13 and end-to-end AT-19 pass; critical AT-30 crash points pass. Live account-specific auth/route checks are recorded separately from offline fixtures. Private alpha is for bounded use with explicit supported versions and recovery instructions; list automation is not enabled yet.

### S06 — Multi-source search, complete ranking and series policies

**Entry:** S05 working vertical slice. **Responsible:** source/catalog/acquisition backend and source/series UI. **Requirements:** FR-17–FR-20, FR-24–FR-26; NFR-03, NFR-10.

| Ticket | Deliverable |
|---|---|
| S06-01 | Native AudiobookBay adapter, supported-host configuration, markup fixtures, detail/coverage/magnet handling and parser-health errors. |
| S06-02 | Prowlarr per-indexer capabilities/categories/search/resolution; origin attribution; native-MAM overlap suppression; unsupported transport handling. |
| S06-03 | Incremental federated search, per-source budgets, normalized+raw fields, release equivalence and per-origin availability. Preserve distinct credentials/download routes even when results describe the same transfer. |
| S06-04 | Complete profiles, inheritance and effective-policy explanations. Default source/format preferences, minimum requirements, unknown-value handling and deterministic ranking; manual sorting separate from stored policy. |
| S06-05 | Just book / Prefer packs / Complete series selection, aliases, published/main-series set, verified coverage and bounded size/expansion controls. Replan uncovered wanted children after inspection without refetching satisfied children. |
| S06-06 | Source comparison, rejection explanations, edition/recording distinction, series coverage and omnibus UI with a truthful shared-asset link. |

**Demo:** one book displays releases from independent sources, one failed adapter does not hide successful results, and an eligible series pack wins under the selected profile. Incorrect advertised coverage never gives false ownership.

**Exit:** AT-09–AT-12 and full AT-14–AT-15 pass. A higher seeder count cannot override wrong language/recording or a blocked format. Missing seed data is not silently treated as an authoritative zero. Search alone causes no downloads.

### S07 — External lists and acquisition automation

**Entry:** S06 selection and recovery gates. **Responsible:** list/workflow backend, list/settings frontend. **Requirements:** FR-12 sync, FR-22 automated concurrency, FR-31–FR-33; NFR-02, NFR-05, NFR-10.

| Ticket | Deliverable |
|---|---|
| S07-01 | Hardcover authorized lists/pages/memberships, per-account scopes, cursors, quotas and complete snapshot tracking. Preserve list/source provenance and unresolved entries. |
| S07-02 | Goodreads RSS conditional fetch and dedupe; CSV snapshot import with field mapping/preview. Distinguish observed additions from authoritative removals; record feed truncation/partial status. |
| S07-03 | Local membership/subscription reconciliation, explicit detach/remove semantics, source-owned memberships and durable exclusions. List deletion never deletes library files. |
| S07-04 | Browse/manual/automatic modes; ebook/audio/both/either and profile inheritance; backlog preview versus future-only first-successful-sync baseline. Start paused if no valid baseline can be established. |
| S07-05 | Scheduled due-sync jobs, initially around 30 minutes with jitter, shared budgets, adaptive backoff, bounded backfill batches and request reasons. Recheck inventory, reservations and suppressions at dispatch time, not just list ingest. Polling cadence is adjustable and subordinate to provider limits. |
| S07-06 | List status/policy summary, per-item pending/owned/attention, manual selection, pause/resume, backlog cancellation and clear next actions. Pausing acquisition continues list observation; resuming previews accumulated additions. Policy changes preview their effect on existing unsatisfied entries. |

**Demo:** add a new title to a connected list → the app acquires the missing requested medium → imports and confirms it. Repeating sync, following an overlapping list and restarting workers add no duplicate transfer. Already-owned books remain checked and skipped according to media requirements.

**Exit/automation beta:** AT-20–AT-22 pass with outage, overlapping-list and shared-torrent scenarios; relevant AT-13 and AT-30 regressions pass. Feed omission, list removal and account outage produce neither media deletion nor a surprise full backfill.

### S08 — Discovery, curation, sharing and deliberate write-back

**Entry:** S07 reliable inbound sync; catalog/inventory available. **Responsible:** discovery/frontend and list/backend. **Requirements:** FR-02 sharing, FR-11–FR-12, FR-34; NFR-03, NFR-05, NFR-07.

| Ticket | Deliverable |
|---|---|
| S08-01 | Attributed provider-supported trending, new releases, related titles and series-continuation shelves. Provide transparent signal labels and useful cached/local fallback; do not invent popularity metrics. |
| S08-02 | Accessible external/community list browsing/following, local curation/order/sharing and permission checks. Sharing a local list never shares a provider token. |
| S08-03 | Optional Hardcover list write-back for verified mutation capabilities. Add outbox, external correlation/reconciliation, echo prevention, conflict handling and scoped user controls. |
| S08-04 | Refine onboarding and default profiles using task-based usability sessions: connect, find, request, follow, resolve. Progressive disclosure for metadata, ranking and naming. |
| S08-05 | Complete responsive/accessibility states, empty/error/stale views and book/version/source vocabulary. Download state remains distinct from reading progress. |

**Demo:** browse a recommendation with its reason, follow a community list under an explicit policy, share a private local list deliberately and reconcile an optional outbound list change after an outage.

**Exit/feature-complete beta:** AT-05 discovery/sharing, AT-23, AT-27 account/privacy and AT-28 core-flow checks pass. Every visible capability has a working implementation or clear unsupported state. Goodreads never displays a write-back control.

### S09 — Production readiness and v1.0 release

**Entry:** S00–S08 complete; any core feature gaps identified explicitly. **Responsible:** release/platform, QA, all module owners. **Requirements:** FR-15 recovery, FR-35–FR-36; all v1 requirements and NFRs.

| Ticket | Deliverable |
|---|---|
| S09-01 | Full fault-injection/concurrency suite: worker/API/db restarts, unknown submission, expired leases, disk-full, permission denial, corrupt inputs and backend outages. Close all invariant failures. |
| S09-02 | Versioned backup/restore and upgrade rehearsal covering database, encryption keys, configuration and manifests; restore starts dispatch-paused and reconciles before resuming. Document separate media backup responsibility. |
| S09-03 | Benchmark reference dataset; tune indexes, batch sizes, connection pools and bounded concurrency. Publish measured results against PRD budgets and explain provider latency separately. |
| S09-04 | Security/privacy review, dependency/license inventory, accessible UI verification and log/export redaction. Validate server-side permissions on every affected API. |
| S09-05 | Certify supported ABS/qBittorrent/PostgreSQL versions and filesystem/layout matrix; publish capabilities and limitations. Unknown versions get diagnostics, not an unearned compatibility claim. |
| S09-06 | Production images, deployment/upgrade/recovery guides, troubleshooting, release notes, changelog and release evidence package. Document settings migration and safe rollback/restore boundaries. |

**Demo:** restore a backup with an already-running external torrent, reconcile it and finish its import without a second download; recover a partial pack; walk through installation and all principal journeys from the operator guide.

**Exit/v1.0:** all FR-01–FR-36 and NFR-01–NFR-12 have passing mapped evidence; AT-01–AT-30 release scope is complete. No unresolved P0/P1 integrity, authorization, duplicate-download or mandatory workflow failure. Optional capability restrictions are documented consistently with the PRD, not used to hide an unfinished required integration.

### S10 — Expansion releases

**Entry:** stable v1 with operational evidence. Each work package is a separately planned release, not one required mega-release. **Responsible:** relevant module owner. **Requirements:** FR-37–FR-42.

| Ticket | Capability | Additional gate |
|---|---|---|
| S10-01 | Opt-in quality upgrades and replacement policies | AT-31: retain old availability until replacement confirmation; preserve seed paths; explicit retention and rollback |
| S10-02 | Existing-import reorganization and selected metadata push | AT-31: preview/diff, collision handling, resumable movement, ABS identity/progress preservation; uncertain preservation blocks execution |
| S10-03 | BookOrbit/other library adapters | AT-32: independent inventory/version/layout contract; no assumption of ABS behavior |
| S10-04 | Additional recommendation/catalog/community providers | AT-33: capability, attribution, identity, privacy and usefulness evidence |
| S10-05 | Additional download clients and Usenet | AT-34: submission reconciliation, completed-file ownership, cleanup and import lifecycle for the actual client |
| S10-06 | OIDC/SSO | AT-35: secure account linking, ownership preservation, grant enforcement and local recovery |

Do not expose inactive settings for these features during v1. Reprioritize S10 using observed user needs rather than committing to all six immediately.

## 4. Defaults to implement and test

| Setting | Initial behavior |
|---|---|
| Metadata | Automatic, Hardcover primary when connected; advanced field control hidden until opened |
| Book ownership | Any confirmed complete ebook or audiobook; media/version-specific details alongside |
| Existing library | Observe and reconcile; no automatic rename, retag or replacement |
| New list | Browse-only until acquisition is enabled; explicit current entries/future additions choice |
| Desired media | Explicit setup choice inherited by lists; do not infer “both” from connecting two roots |
| Either medium | Require a first-acquisition medium preference; either already-owned full medium satisfies the target |
| Source and format | MAM first; EPUB preferred; M4B then MP3 for audio, subject to matching/eligibility |
| Series preference | Prefer series packs for acquisitions; main/published scope; future/related expansion requires opt-in |
| File handling | Hardlink-first, validated filesystem support; explicit copy fallback; no destructive source operations |
| Layout | Certified conventional item/version leaves; nested version layout only after certification |
| Upgrades/deletions | Off; removing a list or request does not delete media or seed data |
| Goodreads | Inbound RSS/CSV; no inferred removals from RSS omission |
| Hardcover write-back | Off until explicitly enabled for a supported operation and account scope |
| Missing media | Reconcile and show attention; no automatic replacement by default |

Profile eligibility precedes all ranking. The initial Balanced preset uses qualifying coverage → format preference → source preference → fresh availability → source-local popularity, following D09. A Most seeded preset changes the preference order without weakening identity or media requirements. Presets must show their effective order. When preferences conflict, the explanation should make the winner clear; no hidden cross-source popularity equivalence is assumed.

## 5. Continuous validation and release process

Every stage delivers migrations, API contracts, working UI states, meaningful tests, operational errors and documentation together. Definition of done:

1. Mapped behavior works, including unknown/partial/error states and permission boundaries.
2. Required tests pass at the appropriate level; mocks do not substitute for PostgreSQL transactions, hardlinks or ABS scanner behavior.
3. No unbounded retry or unjournaled side effect is introduced; relevant crash tests accompany stateful changes.
4. Secrets and paths are handled under the established policy; logs are useful and redacted.
5. UI covers keyboard/focus and loading/empty/failure states; copy distinguishes work, version, release and asset.
6. Schema upgrades, backward-compatible API changes and recovery implications are reviewed.
7. Requirement IDs, acceptance evidence and compatibility notes are updated.

Test layers: pure rule tests for matching/ranking/templates; sanitized parser/provider contract fixtures; actual PostgreSQL integration for transactions/locks; disposable qBittorrent and ABS instances for lifecycle/scanner behavior; browser journeys for the end-user flow; narrowly scoped live provider checks for account/routing compatibility. This does not require testing or adopting another acquisition manager.

Before each release candidate, freeze dependency versions and migration set, run the complete critical corpus, restore an earlier backup, build the same images that will be shipped and record compatibility evidence. Keep backups before schema migration. Do not promise binary downgrade across incompatible migrations; use the documented restore procedure when required.

## 6. Risk ownership and resolution points

| Risk | Owner | Resolution point |
|---|---|---|
| Metadata identity conflates versions or changes provider IDs | Catalog owner | S01–S03 identity/correction corpus |
| Nested folders merge ABS versions or sidecars override edits | Import owner | S04 scanner/authority certification; disable unsupported preset |
| Shared job submission creates duplicate torrents | Workflow owner | S01 atomic enqueue and S05 uncertain-outcome tests |
| MAM cookie/session changes race across workers | MAM adapter owner | S05 credential-scoped lock and auth contract |
| ABB markup or provider capabilities change | Adapter owner | S06/S07 contract fixtures, runtime diagnostics, independent degradation |
| Pack claims do not match files | Import/acquisition owners | S04/S06 verified coverage and child recovery |
| RSS truncation triggers removals or historic backfill | List owner | S07 snapshot/observation semantics |
| Hardlink mount mismatch or inode mutation damages seeds | Import/platform owners | S04 real filesystem capability test and immutability checks |
| Private list/library data leaks via search or shared jobs | API/security owner | S01 policy model; S03/S08/S09 adversarial tests |
| UI customization becomes overwhelming | Frontend/product owner | S02/S08 task-based usability; defaults remain complete |
| Copying frontend/reference code brings license obligations | Technical lead | S00 provenance review; ongoing reuse ledger |

## 7. Initial development handoff

Start with S00-01 through S00-05, then S01-01 and S01-03 as the first substantive engineering proof: schema plus atomic domain/job commit. Freeze adapter DTOs and the work/version/asset vocabulary before implementing feature screens. The first release-worthy demonstration is S05; the first end-to-end automated-list demonstration is S07; public v1 requires S09.

Acceptance definitions are maintained in [Acceptance Plan](ACCEPTANCE-PLAN.md); actual implementation and test coverage are tracked separately in [Implementation Status](docs/IMPLEMENTATION-STATUS.md). A passing subset does not complete an entire stage or acceptance scenario.

## 8. Execution and handoff contracts

### Starting from this repository

Use the existing foundation and preserve unrelated work. Inventory the current implementation against the stage gates before assigning tickets; code existence alone is not completion. The status document records verified evidence, while uncommitted integration work still needs review and validation. Do not restart completed foundation work merely because the stage contains other unfinished packages.

The next integration sequence is:

1. Close S01 identity, authorization and durable-operation gaps needed by inventory. Preserve stable UUIDs, manual corrections, private-library visibility and generation fencing.
2. Complete S03 ABS connections and inventory through HTTP contract fixtures and actual-version certification. Show work-level ownership and per-medium/version details in the UI.
3. Complete S02 metadata/provider resolution and local list UX against the same work/version contracts. Catalog ingestion from ABS must remain useful before optional metadata accounts are connected.
4. Implement S04 on synthetic completed downloads, including two narrators and a series pack. Prove file integrity, item boundaries and restart recovery before enabling MAM/qBittorrent dispatch.
5. Deliver S05's manual vertical slice, then S06 aggregation, S07 automation, S08 curation and S09 release qualification.

S00 infrastructure and CI gaps remain release blockers even when feature work advances. This ordering accounts for existing code; it does not change stage dependencies or waive gates.

### Cross-module artifacts required at handoff

| Producer → consumer | Required artifact | Invariant the consumer may rely on |
|---|---|---|
| Catalog → search/automation | Work/version DTO, provider references, accepted mapping evidence and manual locks | Version fields are not copied from unrelated recordings |
| Inventory → policy engine | Visibility-scoped asset coverage, media/version constraints, freshness and pending state | Unknown/stale is distinguishable from confirmed absent |
| Lists → requests | Stable membership reason, user/destination scope, policy revision and baseline/backfill decision | Repeated observations do not create new acquisition reasons |
| Source search → selector | Normalized result plus raw origin fields, freshness, capability and coverage evidence | Missing fields remain unknown; private origin routes remain distinct |
| Selector → downloader | Frozen release choice, eligibility explanation, target reservations and attempt ledger | Compatible concurrent requests have been serialized and reconciled |
| Downloader → inspector | Associated client transfer and validated completed-file inventory | Unrelated torrents are not claimed; source paths remain client-owned |
| Inspector → publisher | Versioned per-child manifest with immutable source mapping and destination plan | Ambiguous children are held; collisions and file boundaries are explicit |
| Publisher → inventory | Publication evidence and expected backend item/file bindings | File publication is not yet ownership confirmation |
| Inventory → completion/write-back | Confirmed accessible coverage and satisfied target set | Download success never implies read status; write-back failure cannot undo ownership |

Each artifact has a typed schema, version/compatibility policy and representative fixture. A module does not invent another module's state to unblock its UI. Cross-process messages reference durable records rather than carrying secrets or treating transient events as authoritative.

### API delivery map

These are resource families, not a claim that endpoints already exist. Exact URLs are frozen in the generated OpenAPI contract with their implementation stage.

| Resource family | Read behavior | Commands | First complete stage |
|---|---|---|---|
| Accounts/connections | Current user, roles, capabilities, sanitized health | Bootstrap/login, connection test/edit, grants | S01/S03 |
| Catalog/versions/series | Paginated search, details, provenance, availability | Refresh, protected edit, resolve/undo mapping | S02/S03 |
| Inventory | Granted libraries/assets, freshness, deep links | Sync, relink, resolve missing state | S03 |
| Organization | Presets, tokens, path diagnostics, manifest preview | Validate, approve import plan, retry held child | S04 |
| Searches/releases | Incremental results, source errors, raw detail, ranking explanation | Start/refresh/cancel search | S05/S06 |
| Profiles/requests | Effective policy, satisfied/pending targets, request reasons | Preview/submit/cancel request, update profile | S05/S06 |
| Lists/subscriptions | Memberships, completeness, policy and backfill preview | Follow/sync, activate/pause/resume, exclude, bulk request | S07 |
| Discovery/sharing | Attributed shelves, accessible community/local lists | Share, follow, explicit supported write-back | S08 |
| Activity/recovery | Operations, child states, redacted evidence, recovery mode | Retry appropriate stage, reconcile restore, export diagnostics | S01 shell/S09 complete |

Commands return durable operation references where work outlives the HTTP request. Idempotency keys bind to actor, operation type and canonical payload: reusing a key with different content is a conflict, not permission to return unrelated work. Frontend refresh/reconnection polls or subscribes to that operation; it never repeats a side-effecting command to recover a screen.

### Per-ticket completion record

Before starting a package, write its scope, upstream dependencies, affected FR/AT IDs, representative success/failure fixtures and expected demo. Split packages if their acceptance cannot be reviewed independently. Record role ownership without requiring a particular team size.

On completion, attach the implementation revision, migration/API changes, automated evidence, relevant real-service evidence, UI states and remaining limitations. Record tests as passed, failed or not run. A stub adapter, disabled button or passing mock cannot close the real integration gate. Keep these statuses separate: implementation complete, fixture verified, live compatibility verified, stage accepted.

Estimate remaining work after the first measured stage using observed completed packages, then revise for integration uncertainty. Track normal engineering effort separately from elapsed waits for provider accounts or runtime certification. Do not convert the 61 package count into a calendar promise.

### Milestone demonstrations and release decisions

| Milestone | Demonstration | Release decision |
|---|---|---|
| Connected catalog | Browse synchronized inventory; show two narrators under one work; hide ungranted assets | Inventory preview only |
| Safe import | Organize a synthetic pack; recover an interrupted child; verify source integrity and actual ABS items | Certify the tested layout/mount/backend combination |
| Manual acquisition alpha | Search MAM, submit, recover ambiguous add, import and receive an ABS-confirmed badge | S05; no list automation yet |
| Multi-source acquisition | Compare MAM/ABB/Prowlarr, explain selection, import a partially owned pack | S06; independent source degradation |
| Automated list beta | Add a title; acquire missing media; repeat sync/restart without duplicate work; resume paused lists predictably | S07; explicit activation and bounded backfill |
| Complete discovery beta | Browse related/community content, curate/share lists, use defaults and supported optional write-back | S08; full requested UX present |
| Production v1 | Install, upgrade, restore behind external state, repair failed import, pass mapped release criteria | S09; zero open P0/P1 release blockers |

The requested product is complete for v1 only at the final row. S10 is a visible continuation roadmap with independent requirements and evidence; it must not absorb unfinished FR-01–FR-36 work.
