# End-to-end development plan

Planning baseline v1.7 · September 18, 2026 · Implementation has started; see [current status and evidence](docs/IMPLEMENTATION-STATUS.md). No full stage gate is yet complete.

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

The structure below defines module responsibilities. Several paths already exist; consult the implementation status for actual coverage rather than inferring completion from a directory:

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

Acceptance scenarios often span several stages. The [stage evidence scopes](ACCEPTANCE-PLAN.md#7-stage-evidence-scopes) define which assertions apply at each gate. Referencing an AT ID at an early gate never makes its later-source, list or recovery assertions prerequisites for that earlier stage; those remain explicitly pending until their delivery stage and the S09 full regression.

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
| S02-03 | Implement Seerr-style navigation, cover cards, shelves, detail layout, dialogs and settings visuals against book-native contracts. Adapt eligible presentation components where useful; avoid carrying framework/server dependencies solely to reuse markup. Record copied components and notices. Implement responsive keyboard-accessible states. |
| S02-04 | Local/catalog search, work/edition/recording/series views, provisional works and correction flow. Add paginated endpoints and local search indexes. |
| S02-05 | Local list CRUD, ordering and bulk selection; own/private access; placeholder ownership fields use explicit unknown state until inventory exists. |

**Demo:** find a book, inspect its editions/recordings and provenance, protect a title edit and add it to a local list without advanced setup.

**Exit:** AT-02 catalog identity/correction subset, AT-03 app metadata subset, AT-04 catalog search/detail subset and AT-05 local-list subset pass. Backend/file preservation and source-native results remain assigned to S03–S06. Provider outage leaves cached catalog usable. No catalog edition is created merely because two tracker releases exist. Initial accessibility checks cover navigation, search and book detail.

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

**Exit:** AT-06 inventory assertions, AT-07 missing/move detection and non-destructive repair subset, and AT-27 library-scope subset pass. Explicit replacement execution integrates in S05 and complete recovery in S09. Inventory-only credentials work. No scan-start or download status is used as proof of ownership.

### S04 — Safe importing, naming and collection manifests

**Entry:** S01 durability and S03 inventory verification. **Responsible:** importer/filesystem backend, compatibility QA, frontend preview. **Requirements:** FR-04, FR-08 preservation, FR-25–FR-30; NFR-01, NFR-02, NFR-06.

| Ticket | Deliverable |
|---|---|
| S04-01 | Completed-file inspection, directory grouping, embedded metadata reading and conservative work/version matching. Create per-book manifests and hold ambiguous children. Distinguish book containers from generic archives; unsupported/encrypted/incomplete archives stay held. Optional extraction must satisfy the PRD storage and confinement contract. |
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
| S06-04 | Complete profiles, inheritance and effective-policy explanations using the PRD precedence and in-flight change table. Default source/format preferences, minimum requirements, unknown-value handling and deterministic ranking; manual sorting separate from stored policy. Preserve each reason's constraints when sharing fulfillment. |
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
| S07-05 | Scheduled due-sync jobs using PRD section 19 defaults (30 minutes with bounded jitter), shared budgets, adaptive backoff, bounded backfill batches and request reasons. Recheck inventory, reservations and suppressions at dispatch time, not just list ingest. Polling cadence is adjustable and subordinate to provider limits. |
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

For a new checkout without implemented foundations, start with S00-01 through S00-05, then S01-01 and S01-03 as the first substantive engineering proof: schema plus atomic domain/job commit. For this existing workspace, follow section 8 and close verified gaps instead of rebuilding those foundations. Freeze adapter DTOs and the work/version/asset vocabulary before implementing dependent feature screens. The first release-worthy acquisition demonstration is S05; the first end-to-end automated-list demonstration is S07; public v1 requires S09.

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

## 9. Integrated development rehearsal

Use the [PRD walkthrough](PRD.md#15-end-to-end-product-acceptance-walkthrough) as one continuous example across the backlog. Maintain a single synthetic identity graph and media corpus so that each module consumes the same works, recordings and collection evidence.

| Stage | Increment of the rehearsal |
|---|---|
| S01–S02 | Create the trilogy, provider references, two recordings and local list; prove stable IDs and reversible corrections |
| S03 | Observe ebook-only/audio-only ownership and granted-library visibility |
| S04 | Import a synthetic completed pack into an isolated ABS instance; certify paths, item boundaries and restart behavior |
| S05 | Replace the completed-download fixture with the native MAM/qBittorrent lifecycle; retain identical importer assertions |
| S06 | Add independent sources, source failure, duplicate release origins and explained pack selection |
| S07 | Trigger acquisition through Hardcover and Goodreads observations using the same intent/dispatch/import path |
| S08 | Finish discovery, community-list entry, sharing and supported optional write-back around that journey |
| S09 | Execute from clean install and restored app state; attach full compatibility and release evidence |

Preserve a fixture-only run in CI and a separately recorded run against the supported external service versions. A parser fixture cannot certify live account authentication; a live search cannot certify a filesystem import. No evaluation or replacement of the user's existing stack is a prerequisite for planning or building these fixtures.

## 10. Capability activation and integration readiness

Stage completion and installation configuration are separate checks. A certified release still verifies the particular user's credentials, destination permissions and filesystem. Persist capability state on the server and enforce it in command handlers; hiding a button is insufficient. Feature activation does not silently create requests from existing lists.

| Capability | Earliest delivery | Required before enabling it | Useful behavior while unavailable |
|---|---|---|---|
| Catalog browsing and local curation | S02 | Account permissions and catalog/list contracts | Catalog remains useful without a downloader or paid metadata account |
| In-library indicators | S03 | Successful scoped inventory and verified media classification | Explicit unknown/stale state; no claim of confirmed absence from a failed sync |
| Sample naming preview and saved preferences | S04 foundation | Validated template language and explicit synthetic/example inputs | No filesystem access required; destinations/item counts are predicted and no import is enabled |
| Inspected download plan and fixture import | S04 | Verified files, confined paths, actual link/copy probe and manifest validation for import | Hold uncertain children; distinguish a planned mapping from publication readiness |
| Publication to the serving library | S04 | Certified layout, no-replace primitive and confirmation path | Completed files remain pending; unsupported nesting offers the certified conventional preset |
| Manual MAM acquisition | S05 | Authenticated source route, supported client, destination and durable dispatch/import path | Catalog and source search remain independently usable where their own connections work |
| Multi-source automatic selection | S06 | Each participating adapter certified, complete eligibility rules and bounded pack expansion | Healthy sources can return results; failed or unsupported sources show their reason |
| Automatic external-list acquisition | S07 | Successful baseline/backfill decision, authorized policy, durable reasons and S05–S06 lifecycle | Continue list observation and browsing while acquisition is paused |
| Outbound Hardcover list changes | S08 | Supported account mutation scope, explicit opt-in and reconciliation ledger | Inbound sync continues; pending outbound changes retain an actionable state |
| Production release | S09 | Complete v1 evidence, install/upgrade/restore and operator documentation | Earlier milestones retain their actual alpha/beta labels |

An unavailable connection is not necessarily a global outage. Pause only dependent operations. In contrast, recovery mode after restoring app state pauses new external dispatch across the installation until reconciliation completes. Keep the reason and next action visible in Activity.

### Integration questions resolved through evidence

The product direction is settled. These remaining implementation questions have named resolution work; they do not require another open-ended product discovery phase.

| Question | Resolution package | Evidence and fallback |
|---|---|---|
| Which Seerr presentation components are economical to reuse? | S00-01, S02-03 | Record exact files, notices and dependency cost; independently implement presentation where reuse adds framework coupling |
| Which provider fields identify a recording reliably? | S02-01, S02-02 | Provider fixtures plus account capability checks; preserve unknown narrator/version rather than inventing equivalence |
| Does the desired book/version nesting create distinct ABS items? | S04-06 | Actual scanner fixtures with multiple recordings/editions; ship conventional distinct leaves if nesting fails |
| Can the deployment create hardlinks and publish without replacing content? | S04-03 | Probe the actual configured paths and competing publishers; require corrected mounts or an explicit supported copy policy |
| Which source and format rules win when preferences conflict? | S05 baseline, S06 ranking packages | Implement the documented ordered presets and selection explanations; no hidden numerical-weight setup |
| What limits keep automatic pack and backlog expansion bounded? | S06 series policies, S07-05 | Measure representative packs/backlogs; ship visible finite limits before activation; unknown coverage stays reviewable |
| What can a connected Hardcover account read or write? | S07-01, S08-03 | Verify scopes, pagination and mutation responses; inbound-only when writes are unsupported |
| What happens when Goodreads RSS is partial? | S07 Goodreads adapter | Observation-ledger tests; preserve prior membership and never infer removal from omission |

### Reviewable ticket template

Split stage packages into implementation tickets using this record. A ticket is ready when its inputs and expected behavior are concrete; its owner can be one developer filling several roles.

```text
Ticket: <stage package and subtask>
User outcome: <one observable result>
Requirements: <FR/NFR IDs>; acceptance assertions: <AT IDs and subset>
Dependencies: <required contract/revision; actual external capability if needed>
Scope: <owned modules, API/UI behavior, migration and operational changes>
Inputs/outputs: <typed records and durable transition>
Success fixture: <observable database, UI and external result>
Failure fixtures: <relevant retry, ambiguity, permission and interruption cases>
Activation: <server-enforced conditions and unavailable behavior>
Completion evidence: <revision, commands/results, demo and remaining limits>
```

Assign estimates after this split. Separate implementation effort from provider access or compatibility waits, and revise forecasts after each accepted stage. The critical path is identity/inventory → certified import → manual acquisition → aggregated selection → list automation → release qualification. Discovery presentation can advance against the agreed contracts while those integrations are built; its final acceptance still requires working data and user flows.

## 11. Release blockers and stage review

Priority describes the consequence of a defect, not the order in which every feature must be coded. Planned functionality is tracked as remaining scope; it becomes a release blocker when its milestone requires it. Do not label every incomplete future ticket as an incident.

| Severity | Definition for this product | Examples | Required response |
|---|---|---|---|
| P0 | Integrity, authorization or uncontrolled external-action failure | Changes seeded bytes; overwrites unrelated media; leaks another user's tokens/private library; repeatedly dispatches downloads after restart | Stop the affected action, preserve evidence and existing data, repair and run the relevant regression before reactivation |
| P1 | A required milestone journey is unavailable or materially incorrect | Wrong edition/narrator acquired; false ownership; duplicates across lists; series children merged incorrectly; restore cannot reconcile; required connector unusable | Block that milestone; repair and prove the complete failing path, including its recovery behavior |
| P2 | A bounded defect with a clear workaround that preserves product invariants | Secondary visual polish, optional sorting inconvenience, nonessential diagnostics detail | Record owner, workaround and target release; cannot be used to relabel a P0/P1 problem |

Provider outages are operational states when handled correctly. An outage becomes an application defect if it causes false absence, unsafe fallback, duplicate work or lost requests. Unsupported account capabilities are restrictions only when the product already permits that restriction and explains it; unavailable credentials cannot count as passed connector certification.

### First required proof by risk

| Proof | Earliest blocking gate | Required evidence |
|---|---|---|
| Stable work/version identities and reversible correction | S01–S03 | Same title/different author, alternate narrator, provider duplicate and mistaken-match repair without lost holdings/history |
| Correct overall ownership and missing-medium requirements | S03; integrated S05 | Ebook-only ownership plus an unsatisfied audio request; exact recording stays distinct; private holdings remain scoped |
| Source-preserving collection publication | S04 | Per-child manifests, real link/copy behavior, actual ABS item boundaries, collision and crash recovery |
| One compatible transfer despite uncertain submission | S05 | Concurrent requests and response-lost add; reconciliation before another submission; unrelated torrents unchanged |
| Correct selection across independent sources | S06 | Eligibility before seed/format ranking; unknown fields remain unknown; source failure isolated; verified pack scope |
| Safe repeated external-list observations | S07 | Baseline/backfill, overlapping lists, pause/resume, exclusions and RSS truncation; no duplicate acquisition |
| Bookstore browsing without configuration overload | S08 | Task-based onboarding, discovery, list following and requests using shipped defaults; optional customization remains discoverable |
| Recoverable supported installation | S09 | Shipped-image startup, upgrade/backup/restore, external-state reconciliation, permissions and compatibility matrix |

### Stage review record

Maintain one review per stage in the implementation evidence. Use the following fields rather than a percentage-complete estimate:

```text
Stage and candidate revision:
Required FR/NFR and AT assertions:
Implemented packages and remaining scope:
Fixture evidence:
Actual service/filesystem evidence:
Browser demonstration and accessibility evidence:
Open P0/P1 findings:
Supported versions and explicit capability restrictions:
Migration/backup/recovery impact:
Decision: incomplete | accepted for the stated milestone
Capabilities enabled by this decision:
Next dependent packages:
```

An accepted review is specific to its tested revision and capabilities. Changes to identity, source selection, dispatch, publication or inventory confirmation require rerunning the affected contracts before release. Presentation-only changes use appropriate UI checks; they do not require repeating unrelated provider certification. Product direction changes update the PRD and dependent acceptance criteria before they silently alter implementation behavior.

The planning deliverable is complete when requirements, defaults, dependencies and evidence obligations are reviewable. The application is complete only when its applicable stage gates pass. These are separate outcomes.

## 12. Development backlog and execution batches

[Development Backlog](DEVELOPMENT-BACKLOG.csv) is a portable export of all 61 work packages in section 3. Each row carries its stable ticket ID, deliverable, stage requirement scope, responsible role, stage dependencies, release milestone and gate. It can seed an issue tracker without requiring one particular project-management service. The Markdown plan remains authoritative; regenerate the export when package scope changes.

The export deliberately has no inferred completion percentages, assignees or dates. Requirement and exit fields describe the **stage scope**, not proof that an individual ticket satisfies the entire stage. Split packages into reviewable implementation tickets using section 10, assign the applicable assertions, and attach actual evidence before marking them complete. Existing progress is recorded in [Implementation Status](docs/IMPLEMENTATION-STATUS.md); an exported row is neither a claim that the work is finished nor a request to rebuild existing code.

Use the following execution batches to reach the requested product from the current partial implementation. These organize the existing packages; they add no new release scope and do not bypass earlier gates.

| Batch | Work to finish | Product demonstration | Required decision before proceeding |
|---|---|---|---|
| A — Close foundation contracts | Remaining S00–S03 contracts, identity correction, catalog/version resolution, library reconciliation and permissions; review existing evidence before writing replacement code | One title presents correct ebook/audio holdings, distinct recordings and protected metadata; failed inventory cannot erase ownership | Record which foundation assertions pass and which still block import/acquisition; source authentication is not required for catalog-only work |
| B — Finish import certification | Remaining S04 metadata/source resolution beyond local identifier matching, collection coverage, omnibus handling, file-alias reconciliation and recovery/layout cases | A completed synthetic pack is mapped, previewed, hardlinked and confirmed as the correct ABS items; uncertain children remain reviewable | No source-byte changes, wrong-book publication or unsupported item boundaries; only certified formats/layouts can publish |
| C — Deliver manual acquisition | S05 native MAM, mam_id/proxy lifecycle, qBittorrent association, dispatch reconciliation and connected Activity UI | A manual request travels from rich MAM search to an ABS-confirmed book, including a lost submission response | Complete the private-alpha gate; fixture success and live account compatibility stay separately recorded |
| D — Expand selection | S06 AudiobookBay/Prowlarr, origin-aware aggregation, profiles, release explanations and bounded series selection | One title shows alternatives across sources; the selected release obeys format/version rules and a partially owned pack imports only qualifying missing children | Wrong identity cannot win on seeds; failed sources cannot block healthy results; pack limits are enforced |
| E — Enable the defining automation | S07 Hardcover and Goodreads observations, baselines/backfill, exclusions, per-list policy and durable acquisition reasons | An external list addition acquires missing requested media once; overlapping lists, pauses and restarts remain predictable | The manual acquisition engine is reused; no second downloader path; no automatic backfill without the configured activation choice |
| F — Complete discovery and release | S08 shelves, recommendations, community/local list curation and optional supported write-back; S09 recovery, deployment and qualification | A bookstore-like browse → follow → acquire → open-in-ABS journey works from both a clean installation and restored state | All v1 requirements have passing evidence, operator documentation and supported compatibility; no unresolved applicable P0/P1 defect |
| G — Deliver extensions individually | S10 packages selected as separate releases after v1 | Additional backends, clients or policies demonstrate their own complete workflows | Each extension passes its additional gate and affected v1 regressions |

### Development cadence

At the start of each batch, identify the next demonstrable user outcome, review current code and evidence, and split only the packages needed for that outcome. Keep the ticket's API/UI changes, domain transitions and failure recovery together where practical. Pure adapter or UI work may proceed against fixtures once its contracts are stable, but activation waits for the dependent gates.

At each review, demonstrate the outcome through the UI and persisted state, record its revision and relevant test evidence, and update the implementation status. Review uncertainty separately: unavailable account access is a certification dependency; a parser failure is an implementation defect; a supported capability absent from the product is remaining scope. None is a passing result.

Forecast dates after estimating the split tickets and observing delivery throughput. Track engineering effort, integration-access waits and release-certification effort separately. Reforecast after the manual alpha and automation beta, when source and list behavior have been measured. This avoids assigning a misleading equal duration to a visual component and a crash-recoverable importer.

### Planning completion checklist

- Product boundary, ownership semantics and work/version/release identity are defined in the PRD.
- Normal UX, meaningful advanced settings and the end-to-end list/pack walkthrough have observable outcomes.
- Every v1 requirement has a delivery stage and acceptance obligations; later extensions are explicitly separated.
- Each integration has an adapter boundary, capability check and failure behavior.
- All stages have dependencies, responsible roles, deliverables and release gates; all packages are available in the backlog export.
- Existing implementation status is distinct from planned scope and release acceptance.

The next development action is to review and close the earliest incomplete dependency for batches A/B using the current implementation, then proceed through the manual acquisition slice. Do not restart the project scaffold or enable list-driven downloading merely because its settings screen exists.

## 13. Next development slices from the current checkpoint

This section preserves the earlier checkpoint's dependency sequence. Several narrow slices now have implementation evidence. Use section 15 for the refreshed starting point; do not recreate completed fulfillment, review, list-observation or manual-request components.

This is the execution order within the existing 61 packages, not a second backlog or an assertion that earlier stages have passed. The September 18 checkpoint includes reviewed single-file and directory imports, synthetic durable downloader attempts and partial native ABS certification. It does not yet provide a fully qualified manual acquisition release. Review [actual evidence](docs/IMPLEMENTATION-STATUS.md) before each slice; preserve working components and close their missing contracts.

| Order | Existing packages | Concrete implementation outcome | Exit evidence |
|---|---|---|---|
| 1. Close fulfillment correctly | S01-04, S03-04, S05-05–S05-06 | Link attempts, inspections, import children and confirmed assets; reconcile each target; retire satisfied reservations separately from transfer identity claims; show partial/available/held outcomes in Activity | Confirmed ebook, wrong narrator, inaccessible asset, already-owned skip, partial pack, repeated reconciliation and crash-after-confirmation cases pass; no false ownership or second add |
| 2. Repair existing attempts | S01-04, S05-03, S05-05–S05-06 | Reviewed credential/configuration repair with immutable selection history; persistent unknown-outcome handling; authorized administrator import handoff for member requests | Credential rotation resumes observation of the same transfer; changed endpoint or destination requires reconciliation; revoked users cannot resume; uncertain submissions are never automatically resubmitted |
| 3. Complete the manual path | S02-01–S02-04, S04-01, S04-05–S04-06, S05-04–S05-06 | Finish source-to-catalog/version resolution, straightforward profiles, provisional titles, per-child import and automatic continuation of unambiguous supported files | One UI journey from MAM selection through qBittorrent to ABS, without manual database changes; ambiguous files alone need review; single-file, multi-track and series fixtures retain source integrity |
| 4. Qualify manual alpha | Remaining S00–S05 gates | Close outstanding foundation permissions/corrections, real client/source/proxy and deployment certification; record supported versions/layouts and recovery instructions | Required stage assertions and manual alpha demo pass; unavailable live access remains explicitly unverified and prevents a compatibility claim |
| 5. Aggregate and choose | S06-01–S06-06 | ABB/Prowlarr adapters; incremental release aggregation; ordered source/format/availability profiles; bounded pack expansion; reuse verified pack files for additional authorized targets | Correct identity outranks seeds; native/Prowlarr duplicates preserve origin; one failed source does not block others; overlapping pack requests avoid a duplicate transfer |
| 6. Observe lists, then automate | S07-01–S07-06 | First deliver inbound observations and policy preview; then authorize missing-media acquisition through the same request engine | Read-only list sync passes before activation; baseline, backfill, truncation, pause/resume, exclusions and overlapping reasons pass before automated-list beta |
| 7. Finish the browsing product | S08-01–S08-05 | Attributed shelves, useful related titles, series navigation, community/local list curation, sharing and capability-gated write-back | Core tasks work with defaults on desktop/mobile/keyboard; unsupported upstream capabilities have useful truthful fallbacks |
| 8. Release and extend | S09; then S10 | Packaging, migrations, restore reconciliation, complete security/performance/accessibility evidence and operator guides; extensions released independently | Full v1 requirement coverage and release rehearsal pass before v1; each extension gets its own affected regressions |

### Slice 1 engineering handoff

Keep logical request fulfillment, observed transfer state and serving-library availability separate. Persist enough lineage to answer which request was satisfied by which asset and which import produced it. An existing qualifying asset can satisfy a request without being attributed to the current import. Do not force these distinct facts into one `complete` flag.

Reconciliation should run after relevant inventory/import changes and periodically repair missed events. Use short, idempotent transactions with the existing canonical-work lock order; do not acquire domain locks in reverse order from an importer transaction. Recheck actual asset presence, medium/version constraints and requester library grants before closing a target. Record the asset/evidence association durably so repeated events and restarts produce the same outcome.

Retire only the satisfied fulfillment reservation. Retain the transfer ledger while external state may exist, including uncertain and still-seeding transfers. Future pack reuse requires fresh file/identity/permission validation and a new import plan where needed; an active identity claim must neither cause an unreviewed second add nor permanently prevent legitimate reuse. Shared request reasons retain independent satisfaction and privacy.

Expose a derived public status and valid next action through the API; the frontend must not infer availability from downloader progress. Include the ordinary already-owned case, partial packs and administrator review handoff. Migrate existing committed records conservatively: backfill lineage from durable evidence where possible, otherwise leave them pending reconciliation, never assume they are fulfilled.

### Definition of done for each slice

1. Required schema, domain/API contracts, worker recovery and user-facing actions are delivered together for the stated outcome.
2. Relevant acceptance assertions include authorization, concurrency and interrupted side effects, not only a successful screen.
3. Migration and restore implications are documented; secrets and private source details remain excluded from diagnostics.
4. Capability activation is limited to demonstrated combinations. Fixture, actual-service and release evidence are recorded separately.
5. Update the implementation status and existing package records; do not mark an entire stage complete because one slice passed.

Estimate each slice after splitting it into reviewable changes with a named owner. Calendar forecasts must include external certification access and the remaining foundation gates. UI or adapter work can proceed against stable contracts while certification is pending, but its dependent acquisition capability stays gated.

## 14. Executing the complete automation path

These subdivisions implement the [unattended-operation contract](PRD.md#18-unattended-operation-and-exception-review) inside existing work packages. They do not add a new stage, change the 61-package count or mark current work complete. They are ordered to make the manual path and the eventual automatic path share the same authority, matching, publication and recovery services.

| Order / parent packages | Development unit and owner | Required demonstration |
|---|---|---|
| 1 · S01-02, S05-05–S05-06 | Backend + frontend: persist original requester separately from reviewer; restricted review queue, claim/reassignment receipts and safe member status | Member-owned completed files reach an administrator; another administrator cannot act on a stale assignment; private list/account data remain private |
| 2 · S04-02–S04-03, S05-05 | Importer/backend: carry original request and assignment lineage through inspection, frozen plans, reservations and the final publication guard | Grant revocation, withdrawal, wrong destination or exact-version mismatch blocks unpublished work even after review; ordinary administrator imports still work |
| 3 · S02-01–S02-02, S04-01, S05-04 | Catalog/importer: qualify deterministic source-to-catalog and actual-file matching; preserve conflicting and unknown evidence | A clean single book and clean pack child resolve without manual mapping; wrong-author, alternate-narrator and incomplete-file cases enter review |
| 4 · S04-02–S04-06, S05-05 | Importer/worker: persist administrator-approved automatic routes and reuse the same planner/publisher for qualifying jobs | A supported manual acquisition continues from completion to ABS confirmation without per-file approvals; ambiguous siblings remain independently held |
| 5 · S06-01–S06-06 | Sources/domain + frontend: complete independent adapters, eligibility, ordered ranking, bounded packs and shared-file reuse | Candidate explanation matches the persisted choice; an eligible complete pack wins according to policy; wrong identity never wins on seed count |
| 6 · S07-01–S07-06 | Lists/domain + frontend: ship observation first, then activation preview, reasons, capacity controls and scheduled acquisition | Future-only baseline performs no historical downloads; a later entry automatically reaches the already qualified acquisition/import path once |
| 7 · S08–S09 | Frontend + QA/platform: complete curation, exception UX and deployment/recovery qualification | Browse → follow → automatic acquisition → Open in ABS works with defaults; failures show specific recovery actions; restore does not replay downloads |

### Implementation contracts

- **One planner and publisher:** review and automation call the same typed planning and publication services. Their difference is the recorded authorization and matching evidence, not duplicate filesystem code.
- **Frozen decisions, current authority:** persist the selected release, request constraints and import destinations, but recheck permission before side effects. A settings revision cannot retroactively grant access or silently redirect an existing job.
- **Durable exception state:** a held child stores its reason, evidence revision and allowable resolution. Resolving it creates an idempotent continuation of the original workflow. Refreshing the page or reobserving a list cannot dismiss the hold.
- **Server-enforced activation:** automatic dispatch/import requires certified adapter capabilities, valid route probes, finite backlog/pack/transfer limits and capacity checks. Previewing policy is read-only. Applying it is an explicit versioned command.
- **Bounded work:** limit active transfers per downloader, source-search concurrency, backfill batch size, pack expansion and disk requirements. Publish finite tested defaults before S07 activation; provider Retry-After/quota behavior takes precedence over polling preferences. Unknown size or coverage follows the profile's review rule rather than being interpreted as zero.
- **Reconciliation owns recovery:** observation workers repair missed events; the queue is not the only record of work. Replaying a job never bypasses reservations, submission ambiguity, source preservation or backend confirmation.

### Staffing, estimation and release accounting

Responsibility labels are roles, not required headcount. A single developer can deliver each unit sequentially. With additional developers, catalog/UI, source adapters and list observation can advance independently after their contracts stabilize; integration acceptance still follows the stage dependency graph. Keep domain migrations and acquisition invariants under one designated technical owner during each development batch.

For each unit record separate estimates for implementation, browser/domain verification, external-service certification and contingency for unresolved integration facts. Establish a date forecast only after estimating the actual remaining code and identifying who supplies certification access. Do not derive a delivery date by multiplying 61 packages by an arbitrary sprint length. Reforecast at manual alpha, automated-list beta and the production release candidate.

Release review must answer four questions: can the user complete the promised journey; do its relevant failure cases recover correctly; was it demonstrated on the claimed deployment/integrations; and are any P0/P1 findings still open? A happy-path demonstration, a large test count or a complete settings page alone cannot accept a stage.


## 15. Refreshed implementation starting point and delivery order

This is the current execution handoff for the v1.7 planning baseline. It supplements the stable S00–S10 packages rather than adding new scope or restarting the scaffold. The committed status records inbound Goodreads/CSV/Hardcover observations, reviewed list batches, MAM/Prowlarr aggregation, durable attempts, scoped fulfillment and selected automatic-import cases. These are partial proofs, not accepted whole stages. Automatic-selection files currently in the working tree are work in progress; their presence is not release evidence.

| Sequence | Deliverable within existing packages | Acceptance before activation |
|---|---|---|
| A. Establish the evidence baseline | Compare current code, migrations, generated API and test evidence with each outstanding S00–S05 assertion; preserve existing uncommitted work | Record implemented, fixture-verified, service-verified and stage-accepted separately; identify the precise remaining gaps rather than rebuilding working modules |
| B. Finish release preparation | S06-03–S06-04: eligibility, deterministic ranking, bounded artifact inspection, current source/actor/profile checks, saved explanations and a simple title-page action | Wrong work/language/version cannot win; stale evidence holds; failures remain actionable; preparation alone does not dispatch or mark ownership |
| C. Add scheduling and capacity authority | S01-04, S05-05, S07-04–S07-05: durable installation limits, fair scheduling, byte/slot reservations and shared request-to-dispatch continuation | Implement PRD section 19; concurrent jobs cannot overspend capacity; a crash or unknown submission cannot create another transfer |
| D. Finish list policy activation | S07-01–S07-06: Browse/Manual/Automatic, baseline, reviewed backlog, future additions, pause/resume, exclusions and frozen policy reasons | A new list addition reaches the existing qualified import path without per-title approval; overlapping lists and repeated observations produce one compatible acquisition |
| E. Complete sources, packs and identity coverage | Remaining S02/S04/S06: ABB, missing direct-source/provisional paths, exact edition/recording evidence, series selection, per-child coverage, omnibus and shared-pack reuse | Each actual child maps to its correct catalog identity and ABS item; ambiguous siblings alone wait; no release row becomes a fabricated edition |
| F. Complete the bookstore experience | S08 and remaining S02 UI: Discover shelves, related titles, series views, community-list following, local sharing and supported optional write-back | Defaults support browse → curate → request/open; provider outage has an attributed cached/local fallback; keyboard/mobile flows are complete |
| G. Qualify and ship | Remaining S00–S09: deployment, live compatibility, filesystem layouts, permissions, correction/repair, migrations, restore, performance and accessibility | Full AT-01–AT-30 evidence and zero applicable P0/P1 blockers; publish supported combinations, operator guide and release notes |
| H. Expand separately | S10: other backends/clients, deliberate upgrades/reorganization, additional recommendation providers and SSO | Independent acceptance for each extension plus affected v1 regression |

C and D may be developed against qualified single-book fixtures while E progresses, but **automated-list beta is not accepted until its required S06 dependencies pass**. Shipping an internal single-book slice does not waive native ABB, packs or version handling from the promised beta/v1 scope. Actual account/service and Compose certification remain separate from synthetic HTTP or native-process evidence.

### Reviewable development units

Each change should close one observable path across domain, API, worker and UI where applicable. Example for B: select a wanted audiobook, fetch sources, prepare the best eligible candidate, reload its persisted explanation, invalidate its source configuration and show a safe repair action. Include only the migration and tests needed for that unit; do not turn the 61 planning packages into 61 oversized pull requests.

For each unit attach: parent package IDs; FR/AT assertions; preconditions; typed input/output; durable transitions; idempotency and cancellation rules; a browser demonstration; relevant failure/restart evidence; migration/rollback effect; and any capability restriction. Update current status after verification. Never treat a prepared selection as a completed automatic acquisition.

### Planning deliverables and handoff checks

- PRD: 36 v1 functional requirements, six expansion requirements and 12 nonfunctional requirements, with observable behavior and normal/advanced UX.
- Engineering backlog: 55 v1 work packages and six expansion packages, each with role ownership, dependencies, deliverables and gates.
- Acceptance: 30 v1 scenarios and five expansion scenarios, with early-stage assertion scopes and full release expectations.
- Traceability: [requirements export](REQUIREMENTS-TRACEABILITY.csv) maps all 54 requirements to acceptance IDs; [backlog export](DEVELOPMENT-BACKLOG.csv) maps packages to their stage scope.
- Decision references: provider APIs/capabilities, identity, naming/ABS boundaries, hardlinks, source routing, durability and reuse licensing remain in Implementation Decisions and supporting research.

No calendar commitment is implied. At each stage start, assign named owners and estimate remaining implementation, verification, integration access and contingency separately; reforecast at manual alpha and automation beta. A complete planning package makes development reviewable; it does not certify the application as complete.
