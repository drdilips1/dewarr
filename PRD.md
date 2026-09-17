# Product requirements: book discovery and acquisition

Version 1.0 planning baseline · September 17, 2026 · Working product name: Book discovery app.

Status: ready for staged development. No application code or production deployment is implied by this document. User requirements from the conversation take precedence. This PRD defines product behavior; [Implementation Decisions](IMPLEMENTATION-DECISIONS.md) defines the researched engineering baseline; [Development Plan](IMPLEMENTATION-PLAN.md) defines delivery; [Acceptance Plan](ACCEPTANCE-PLAN.md) defines verification. Earlier research remains rationale, not an alternative product direction.

## 1. Product purpose

Build a self-hosted discovery, curation and acquisition application for ebooks and audiobooks. It sits above Audiobookshelf, knows what the connected library contains, presents books through familiar Seerr-style browsing, searches multiple download sources, and completes acquisition through qBittorrent and an organized library import.

The defining journey is: follow a Hardcover or Goodreads list → observe a new book → determine which requested media are missing → find a suitable individual or series release → download → identify and organize each book → confirm it in Audiobookshelf. The user should not configure dozens of metadata rules or repeatedly acquire books already owned.

The app owns discovery, catalog reconciliation, lists, policies, source aggregation, dispatch and organization of its new acquisitions. Audiobookshelf remains the reader/player and backend inventory. Seerr supplies presentation patterns and selected reusable visual components. MouseSearch supplies source-search and downloader references. This is a new app; it does not depend on another acquisition manager.

## 2. Users and jobs

| User | Job | Successful outcome |
|---|---|---|
| Household administrator | Connect existing services and establish destinations/defaults | Healthy integration diagnostics and an import preview without advanced metadata tuning |
| Reader/listener | Browse, discover and request a book | One book page shows owned formats, catalog versions and available releases clearly |
| Curator | Maintain local lists and follow external/community lists | New memberships appear automatically; each list can browse, request manually or acquire automatically |
| Collector | Prefer formats, sources, narrators or complete series | Explainable selection respects requirements and avoids duplicate library items |
| Operator | Recover from failures and upgrades | Repair/retry the failed stage without redownloading successful work or modifying seeded files |

One household installation can have multiple users. Lists and external account tokens are private until shared. Libraries and acquisition infrastructure are administered centrally. User-visible ownership is constrained by library access grants; a privileged backend credential must not leak inaccessible library data.

## 3. Goals and success measures

Product goals:

1. One coherent bookstore-like catalog across sources and owned media.
2. Faithful MAM detail alongside aggregated release comparisons.
3. Reliable per-list automation with understandable defaults.
4. Collection-aware organization that produces correct ABS items.
5. Recoverable operation through outages, retries, corrections and upgrades.

Release measures are targets to verify, not existing performance claims:

| Measure | v1 acceptance target |
|---|---|
| Duplicate acquisition | Zero unintended duplicate transfers/imports in the concurrency, restart and repeated-sync acceptance corpus |
| Source integrity | No changed source-file bytes, source renames or unrelated destination overwrites in import tests |
| Ownership semantics | All cases preserve overall ownership when either full medium is confirmed; missing requested media stay independent |
| Collection correctness | Every resolvable child in the certified corpus maps to the intended work/version and backend item; ambiguous children are held |
| Automation | A newly observed list member reaches owned, pending, searching or actionable attention state without silently disappearing |
| Setup simplicity | No per-field metadata rules or scoring weights required to finish setup and acquire a book |
| Diagnosis | Every held/failed acquisition exposes its stage, reason and valid next action |
| Recovery | A restored installation reconciles external work before dispatch resumes |

Reference performance environment: Linux, 4 vCPU, 8 GiB RAM, SSD, API/worker/PostgreSQL; fixture backends isolated from performance measurements. Reference dataset: 20,000 works, 50,000 assets, 10 users, 50 subscriptions. Target cached/local list and detail endpoints at p95 ≤500 ms, local search at p95 ≤1 s, and job submission at p95 ≤500 ms excluding external calls. First useful UI content should appear within 2 s on the reference LAN/warm-cache scenario. Remote-provider latency is measured separately; one slow source cannot block completed sources. These budgets may be revised only with recorded benchmark evidence.

## 4. Release scope

| Release boundary | Included |
|---|---|
| Internal foundation | Schema, identities, authentication, durable jobs, fixture integrations and compatibility harness |
| Private alpha | Catalog/search, ABS inventory, native MAM, qBittorrent, collection-aware import, default naming and ownership badges |
| Feature beta | AudiobookBay/Prowlarr aggregation, editable ranking profiles, series acquisition, Hardcover/Goodreads inbound automation |
| v1.0 | Complete core below: curation shelves, accessible community-list following, local list sharing, optional Hardcover list write-back, recovery, documentation and supported deployment |
| Post-v1 stages | Automated upgrades, explicit existing-library reorganization/metadata push, additional backends, richer recommendations, additional download clients and SSO |

The nested book/version layout is a v1 compatibility target. It may be enabled only where certified; a disabled preset must state why. v1 still supplies the conventional layout and all book/version organization capabilities. Do not advertise unsupported scanner layouts.

Out of scope for v1: playback/reader implementation, hosted multi-tenancy, automatic audiobook splitting/transcoding, embedded retagging of seeded media, arbitrary existing-library migration, a new public social network, an LLM recommendation dependency, bidirectional Goodreads RSS, and Usenet downloading without a real client adapter. Filesystem names, colors and advanced matching thresholds are implementation details unless they affect the requirements below.

## 5. Product invariants

- **Owned means either medium.** A complete ebook OR audiobook confirmed in an accessible backend gives “In library.” A companion PDF alone does not.
- **Versions are catalog entities.** Alternate tracker releases and file encodings do not create editions or recordings.
- **Requests are requirements.** “Both” may want an audiobook even when an ebook makes the work owned.
- **Packs are many-to-many.** One transfer may contain several works; one recording may use many files; one omnibus may contain multiple works.
- **No fabricated certainty.** Unknown narrator, seed count, coverage or match remains unknown.
- **No implicit upgrade.** Better-seeded releases, different covers or new provider metadata do not replace owned media.
- **No implicit destructive sync.** List removals and temporary inventory failures do not delete files or cause reacquisition.
- **No in-place seeded-media mutation.** Naming operates on destinations; generated sidecars are independent files.
- **Inventory is observed state.** qBittorrent completion and a successful scan request alone do not establish availability.
- **Correction is durable.** Manual matches, exclusions and edits survive repeated refreshes.

## 6. Information architecture and UX

Primary navigation: Discover, Search, My Library, Lists, Activity. Settings and integration diagnostics are administrator-visible. “My Library” is a view of granted backend inventory, not an independent player or unrestricted file manager.

| Surface | Required content/actions | Essential states |
|---|---|---|
| Setup | Admin bootstrap; ABS; paths/import preset; downloader; sources/proxy; optional catalog/list accounts | Not configured, connected, limited capability, repair needed |
| Discover | Attributed trending where supported, followed lists, series continuation, related titles, available-now shelves | Loading, empty, cached/stale, provider unavailable |
| Search | Catalog/local search plus explicit direct-source mode; title/author/series/identifier inputs | Partial source completion, no matches, source failure, provisional title |
| Book detail | Overview, editions/recordings, sources, lists, activity; separate ebook/audio actions and overall ownership | Owned, missing medium, pending, other versions, uncertain match |
| Sources | Source, raw title, medium, narrator/edition, format, size, seeds if known, coverage, match and selection explanation | Selected, rejected with reason, unknown fields, unavailable |
| Series | Ordered works, owned count, medium-specific completion and Get series | Main/related works separated; missing/unreleased/unknown order |
| Lists | Local/external origin, owner, membership, sync time, policy summary and bulk selection | Future-only, backlog preview, active, paused, partial/error sync |
| Activity | Requests, transfer/import children, stages, exceptions, Retry/Resolve/Ignore/Open in ABS | Partial pack success, dispatch uncertain, awaiting scan, suppressed |
| Settings | Connections, download profiles, metadata defaults, organization and recovery | Inherited values, overrides, preview, reset to defaults |

Cover cards use Seerr's familiar visual hierarchy with ebook/audio indicators. Detail pages separate clean catalog information from original release descriptions. Keep rich source data accessible in a drawer/tab without turning the book page into a torrent table. Do not remove useful MAM-specific detail to fit a lowest-common-denominator schema.

Normal metadata settings: Automatic mode, primary catalog, language; Advanced contains provider groups and field exceptions. Normal list configuration: mode, desired media, profile, current entries versus future additions. Profiles display a plain-language summary. Advanced overrides always expose the inherited value and a reset action. Temporary result sorting does not silently change automation policy.

Naming uses presets and a token picker with live original-path → destination-path preview and expected ABS item count. Missing metadata removes empty punctuation; years specify work/edition/recording/source meaning. Show library folder, book/version boundary and hardlink/copy result in the preview without requiring template syntax knowledge.

## 7. Functional requirements

All FR-01 through FR-36 are v1 requirements. “Core” means required in its delivery stage; it does not imply exposing every option during onboarding. FR-37 through FR-42 are planned post-v1 requirements, not promised launch functionality. Stage IDs refer to the development plan.

### Access and setup

| ID | Requirement and acceptance behavior | Delivery |
|---|---|---|
| FR-01 | Bootstrap one administrator and start a reproducible self-hosted installation; bootstrap cannot remain publicly reusable after setup | S00–S01 |
| FR-02 | Administrator/member/viewer roles, private account connections, list ownership/sharing and library grants are enforced in the API, not just UI | S01; sharing completed S08 |
| FR-03 | Configure, edit, test and disable integrations; show version/capability/auth/route diagnostics independently, without destructive test actions | S03–S06 |
| FR-04 | Configure qBittorrent-to-worker path mappings, ebook/audio roots, UID/GID access and hardlink/copy mode; validate actual access/link behavior before automatic imports | S04–S05 |

### Catalog, metadata and browsing

| ID | Requirement and acceptance behavior | Delivery |
|---|---|---|
| FR-05 | App-owned work/version/representation IDs with namespaced provider references; changing providers or duplicate upstream records does not duplicate owned works | S01–S02 |
| FR-06 | Review matches, create provisional works, merge or correct mappings with history; undo a mistaken association without losing asset/job relationships | S01–S03 |
| FR-07 | Hardcover-first automatic metadata when connected, targeted Open Library work/ebook fallback and per-group/advanced field preferences; conflicting versions are not silently merged and recording details are not invented from work-level data | S02 |
| FR-08 | Show provenance; allow cover selection and protected app metadata edits; refresh does not overwrite manual locks or ABS edits | S02–S04 |
| FR-09 | Search catalog/local records by title, author, series and supported identifiers; unresolved source-native books remain usable | S02; source entry S05 |
| FR-10 | One book page aggregates ebook editions and audio recordings, separate media actions, ownership and download releases; open available assets in ABS | S02–S03; source UI S05–S06 |
| FR-11 | Browse attributed discovery shelves, series continuation and related titles with explained signals; browse/follow accessible provider/community lists where supported | S08 |
| FR-12 | Create, edit, order and share local lists; add/remove/select books individually or in batches; list ownership is distinct from acquisition reasons | S02; sync S07; sharing S08 |

### Backend inventory

| ID | Requirement and acceptance behavior | Delivery |
|---|---|---|
| FR-13 | Initial and periodic complete ABS reconciliation plus change events; page failures, filtering or permission changes cannot masquerade as whole-library deletion | S03 |
| FR-14 | “In library” when either confirmed full medium is available; separate edition/media availability and pending requirements; tracker count does not affect edition count | S03 |
| FR-15 | Detect stale/suspected/confirmed missing assets and external moves; offer repair/replace/ignore; do not automatically replace intentional or unexplained deletions by default | S03; recovery completed S09 |

### Sources and acquisition

| ID | Requirement and acceptance behavior | Delivery |
|---|---|---|
| FR-16 | Native MAM search/detail using mam_id, rich fields and explicit proxy routing; preserve session rotation safely across workers and distinguish login/error/empty responses | S05 |
| FR-17 | Native AudiobookBay search/detail/file-list/magnet adapter with configurable supported host, bounded fetching and parser diagnostics | S06 |
| FR-18 | Optional Prowlarr indexers, per-indexer origin/capabilities/categories; avoid duplicate native-MAM query paths; label unsupported acquisition protocols | S06 |
| FR-19 | Aggregate releases by work/version while retaining raw titles, descriptions, technical fields and pack coverage; partial results appear independently of failed sources | S06 |
| FR-20 | Reusable profile with inherited language/media/format/source/coverage preferences and deterministic eligibility/ranking explanation; reorder formats/sources and block formats | S05 baseline; complete S06 |
| FR-21 | Request ebook, audiobook, both or either; select an exact recording or any acceptable version; manual download applies the effective scope/profile | S05 |
| FR-22 | Durable intents, reasons, reservations and jobs prevent repeat/concurrent acquisitions, reconcile uncertain submissions and resume after crashes | S01 foundation; end-to-end S05–S07 |
| FR-23 | Direct qBittorrent submission, association and monitoring; inspect completed files; preserve seeding paths and do not claim unrelated existing torrents | S05 |

### Series, editions and importing

| ID | Requirement and acceptance behavior | Delivery |
|---|---|---|
| FR-24 | Just this book / Prefer series packs / Complete series; search known series aliases; distinguish published-main-series coverage from future/related titles | S06 |
| FR-25 | Track claimed/corroborated/verified pack contents; map each actual book/version to its own manifest entry; skip satisfied imports and resume unresolved children independently | S04 foundation; selection completed S06 |
| FR-26 | Represent an inseparable omnibus as one asset containing verified works; do not invent separately playable files or count unverified contents as owned | S04; UI completed S06 |
| FR-27 | Default and customizable author/series/book/version folder and file templates, per-medium roots, preview, conditional metadata tokens and collision handling | S04 |
| FR-28 | Hardlink-first import into external staging with safe no-replace publication, optional explicit copy policy, confined paths and unchanged seeded bytes | S04 |
| FR-29 | Generate per-version supported sidecars and covers; distinguish initial export from later app/ABS edits; provider/template changes never implicitly rename published items | S04 |
| FR-30 | Scan or await watcher detection and verify expected ABS item boundaries, files and identity; multiple narrators/editions remain separate; delayed confirmation does not redownload | S04; real-client flow S05 |

### Lists, automation and operations

| ID | Requirement and acceptance behavior | Delivery |
|---|---|---|
| FR-31 | Subscribe to authorized Hardcover lists, paginate/diff safely and record freshness; account-specific quotas/scopes do not leak between users | S07 |
| FR-32 | Subscribe to supported Goodreads RSS feeds and import CSV snapshots; conditional fetch and entry dedupe; omission/partial feeds never imply removals | S07 |
| FR-33 | Browse/manual/automatic list modes, inherited desired media, backlog preview, future-only baseline, exclusions and shared acquisition reasons; repeat sync has no duplicate effect | S07 |
| FR-34 | Optional scoped Hardcover list write-back with durable desired-state operations, reconciliation and conflict handling; never mark read because a file downloaded | S08 |
| FR-35 | Activity/issue views expose effective policy, selected/rejected reasons, per-book progress and valid repair actions; retries restart only appropriate stages | S01 shell; complete S09 |
| FR-36 | Versioned migrations, backup/restore including keys/manifests, restore reconciliation mode and operator documentation; upgrade never silently replays historical downloads | S00 foundation; complete S09 |

### Planned later capabilities

| ID | Requirement | Delivery |
|---|---|---|
| FR-37 | Opt-in automatic quality upgrades/replacement, retaining existing assets until a replacement is confirmed and defining retention/seeding behavior | S10 |
| FR-38 | Explicit existing-import reorganization and selected metadata push with diff, collision checks and progress-preserving reconciliation | S10 |
| FR-39 | Additional library backends such as BookOrbit through the same inventory adapter contract, with independent capability certification | S10 |
| FR-40 | Richer recommendation signals and additional community/catalog providers with attribution, privacy and measurable usefulness | S10 |
| FR-41 | Additional download clients/protocols, including Usenet only with an implemented client and lifecycle contract | S10 |
| FR-42 | OIDC/SSO account linking without changing list ownership, permissions or existing local-admin recovery | S10 |

## 8. Core user journeys

**A. Discover and request.** Search by title → select work → see owned formats and other versions → choose ebook/audio/both/either → see effective profile and collection expansion → submit. An already satisfied target shows availability; it does not create a transfer. Direct-source discovery may create a provisional work with transparent uncertainty.

**B. Follow a list.** Connect the user's account/feed → choose list → preview membership and owned/missing/unresolved counts → choose browse/manual/automatic, media and profile → choose current entries or future-only → activate. Future-only records a baseline. A subsequent new membership creates only unsatisfied targets. A book requested from multiple lists retains all reasons behind one compatible acquisition.

**C. Acquire a series pack.** Request book three with Prefer series packs → search work and identified series → select a qualifying pack → show books/versions covered and those already owned → one qBittorrent job → inspect files → import missing book groups → confirm each ABS item. Missing claimed contents resume search; uncertain children remain reviewable. No user confirmation is needed for every routine automatic pack already authorized by the profile.

**D. Import another recording.** An owned book remains checked → select another catalog recording → download its release → create a distinct version destination → ABS confirms another item → book page shows both recordings. Changing narrator metadata on an existing asset is not equivalent to importing another recording.

**E. Recover from failure.** A proxy outage pauses that source; another eligible source may provide results. A download completed before restart is reconciled using its association. A file import waiting on ABS remains pending. User selects Retry import or Resolve match; the app does not restart acquisition unnecessarily.

**F. Missing library media.** An item disappears → retain last-known state as stale/suspected while checking backend/storage → reconnect/relink if moved → confirmed loss becomes unavailable/attention. A user can request replacement or suppress reacquisition. Other owned formats continue to provide the overall ownership check.

## 9. State, authority and integration contract

Keep work ownership, acquisition intent, download job and per-book import states separate. Suggested acquisition progression: wanted → searching → reserved → submitting → downloading → inspecting → importing → awaiting library → available. Branches include dispatch-uncertain, needs-review, paused, retryable-failure, failed and cancelled. Cancellation of a request reason is distinct from cancelling a shared transfer; no request cancellation deletes seeded or published files automatically.

Authority: provider/catalog rules own app metadata; actual files own technical facts; ABS owns observed serving availability; user overrides own corrected app values; source postings own release descriptions; downloader owns original torrent paths. Initial sidecar export does not establish perpetual authority over ABS metadata.

| Integration | Required operations | Graceful limitation |
|---|---|---|
| ABS | Inventory, item details, change events, scan capability, deep links | Inventory-only mode can await watcher detection; no false scan-success confirmation |
| qBittorrent | Capabilities, add, find, status, files, category/tag association | Uncertain submissions reconcile; unsupported clients do not get speculative mutations |
| Gluetun | Explicit HTTP proxy routing | Required route failure pauses; torrent routing remains separately configured |
| MAM | Native search/detail/release retrieval and rotating session | Rich details retained; auth/rate/parser errors distinct from no result |
| ABB | Search/detail/coverage/magnet parsing | Markup break degrades adapter; it cannot erase other-source results |
| Prowlarr | Indexer capabilities/search and result resolution | Retain origin; unsupported protocol visible without a nonfunctional Download action |
| Hardcover | Catalog/editions/series/lists and optional authorized mutations | Cache survives outage; unavailable capabilities do not gain invented substitute data |
| Open Library | Targeted work/ebook fallback and identifier lookup | Cache and identify requests; no assumed recording catalog or bulk harvesting |
| Goodreads | RSS observations, CSV import | No RSS write-back or reliable omission-based removal |

## 10. Nonfunctional requirements

| ID | Requirement | Acceptance |
|---|---|---|
| NFR-01 | Integrity | No seeded-byte mutation, unrelated overwrite or false ownership in the critical corpus |
| NFR-02 | Durability | Restart/redelivery preserves intents and repairs ambiguous external outcomes without duplicate side effects |
| NFR-03 | Responsiveness | Meet the reference latency targets; incremental source results and usable cached views |
| NFR-04 | Capacity | Reference dataset and bounded concurrency operate without unbounded memory, job or connection growth |
| NFR-05 | Privacy/security | Server-side authorization, protected secrets/sessions, redacted diagnostics and confined external/file operations |
| NFR-06 | Compatibility | Published matrix of tested backend versions, media/layout capabilities and filesystem constraints |
| NFR-07 | Accessibility | Target WCAG 2.2 AA: keyboard operation, focus, labelled controls, meaningful status text, contrast and non-color-only indicators |
| NFR-08 | Observability | Correlation from request through import; last successful sync, queue age and actionable errors without credentials |
| NFR-09 | Maintainability | Typed contracts, reproducible dependencies, reviewed migrations, adapter isolation and retained reuse notices |
| NFR-10 | Provider/resource discipline | Shared quota budgets, bounded retries/caches, explicit routes and no fabricated source availability |
| NFR-11 | Recoverability | Daily app-state backup target (≤24 h RPO), pre-upgrade backup, and ≤1 h app-state restore target on reference fixture; media backups are separate |
| NFR-12 | Operability | Documented Compose install/upgrade, health/readiness, non-root filesystem identity and degraded browsing during optional upstream outages |

No telemetry or centralized metadata/list collection is required. Benchmarks and diagnostic exports are local unless explicitly exported. Recovery targets cover application state, not restoring an entire media archive.

## 11. Launch criteria and change control

v1 launch requires FR-01–FR-36 and NFR-01–NFR-12 to pass their acceptance evidence or have a specifically documented capability restriction consistent with this PRD, such as uncertified nested layouts. Provider credentials absent from a test environment are a live-connector release gap, not a passed test. Post-v1 features must not have enabled controls that imply functionality exists.

All invariant-breaking defects block release. A failed optional provider must degrade independently; an integrity or authorization failure cannot be waived as a cosmetic issue. Track deferred items explicitly with release ownership rather than leaving silent TODOs in the core workflow.

Scope changes update the requirement, dependent tickets, acceptance scenarios and any affected architecture decision. Keep data identity, import authority and ownership semantics stable through UI iterations. Screenshots, fixture results, migration/restore evidence and a compatibility matrix form the release review package.

## 12. Dependencies and assumptions

Users supply authorized provider connections and access to their existing services. Automatic import requires worker access to completed files and a supported destination; hardlinks require compatible mounts. Account scopes, MAM routing/session behavior and provider quotas are validated at connection time. The current user-server versions are not yet known. No assumption requires changing their production stack during planning.

Research-date certification targets and evidence are in [Implementation Decisions](IMPLEMENTATION-DECISIONS.md). Product naming, logo and exact visual assets remain open and do not block implementation. Calendar estimates follow initial engineering velocity; milestone completion is defined by evidence, not an unsupported date commitment.
