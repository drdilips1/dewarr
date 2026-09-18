# Acceptance, compatibility and release verification

Planning baseline v1.8 · September 18, 2026.

**Status: acceptance definitions; implementation evidence is tracked in [Implementation Status](docs/IMPLEMENTATION-STATUS.md).** Some foundation subsets have now been tested; no full scenario is yet certified complete. This document maps [PRD requirements](PRD.md) to the gates in [Development Plan](IMPLEMENTATION-PLAN.md). Research/source inspection is evidence for a design choice, not a passing runtime test.

## 1. Evidence format and test environments

Record each execution with scenario ID, application revision/image digest, dependency/service versions, fixture revision, environment/filesystem, timestamp, result and evidence location. Record skipped cases and the missing dependency explicitly. Live-provider credentials absent from CI do not mean a connector passed its live contract.

Use four environments:

1. Unit/contract: synthetic or sanitized records, no real accounts, deterministic clocks and bounded parser fixtures.
2. Integration: actual PostgreSQL and disposable ABS/qBittorrent services; generated/public-domain media; isolated mounted directories.
3. Browser: test users with different grants, seeded catalog/list/activity states and actual API integration.
4. Connector certification: authorized test account and actual configured route; read-only checks where possible and controlled acquisition of authorized test content where needed. Never run a production-library migration as a test.

Initial certification targets come from the researched decisions: ABS 2.36.1, qBittorrent 5.2.3, PostgreSQL 18.x and Procrastinate 3.9.0. Pin exact artifacts at scaffold time and record any baseline changes. These are targets, not verified claims or an instruction to upgrade the user's installed services.

## 2. Acceptance matrix

All AT-01–AT-30 are v1 release scenarios. Individual stage gates may exercise a subset first, with the full scenario completed by S09. AT-31–AT-35 apply only to their post-v1 feature releases.

| ID | Requirements | Scenarios and required result | Gate |
|---|---|---|---|
| AT-01 | FR-01, FR-02, FR-03, FR-04 | Clean install, bootstrap race, restart, account roles, invalid integrations and path access. One bootstrap admin; reusable bootstrap closes; unauthorized API calls fail; nondestructive diagnostics distinguish auth/route/capability/path problems. | S00–S05 |
| AT-02 | FR-05, FR-06 | Duplicate provider IDs, reused ISBN, translated edition, narrator variation, title collision, provider merge, manual unmatch and mistaken-merge repair. Stable internal identity; contradictory records held; asset/job history survives correction. | S01–S03 |
| AT-03 | FR-07, FR-08 | Provider disagreement/outage, missing fields, manual field/cover locks and later refresh. Automatic defaults work; provenance remains; unknowns stay unknown; protected app/ABS values are preserved. | S02–S04 |
| AT-04 | FR-09, FR-10 | Search by title/author/series/identifier, direct-source provisional work, multiple releases of one recording, ebook-only ownership and ABS deep link. One coherent work page with truthful version/release boundaries. | S02–S06 |
| AT-05 | FR-11, FR-12 | Create/order/bulk-edit local lists, follow supported public list, grant/revoke sharing, provider outage and recommendation labels. Only authorized content visible; attributed shelves and local fallback remain useful. | S02, S08 |
| AT-06 | FR-13, FR-14 | Full/paginated/event ABS sync, failed page, reconnect, removed grant, ebook-only/audio-only/both, companion PDF and partial audio. Completeness tracked; overall check requires a full confirmed medium; no false removal or hidden-library disclosure. | S03 |
| AT-07 | FR-15 | Missing mount, transient ABS failure, external move/deletion, changed backend item ID and explicit ignore/replace. Reconcile before confirmed missing; suppressions persist; no automatic replacement; unaffected medium stays owned. | S03, S09 |
| AT-08 | FR-16, NFR-10 | Rich MAM details, mam_id rotation, concurrent workers, required proxy failure, auth expiry, parser failure, empty results and rate limits. Safe serialized credential updates; no direct-route fallback; no error disguised as no results. | S05 |
| AT-09 | FR-17 | ABB search/detail fixture variants, supported host changes, missing file lists, invalid magnets and markup break. Typed errors, bounded parsing/fetching, no fabricated coverage and unaffected other-source results. | S06 |
| AT-10 | FR-18 | Prowlarr multiple indexers/categories, native MAM overlap, torrent/Usenet results and origin-specific credentials. Preserve origin, suppress duplicate querying, expose unsupported protocol without a working-looking download action. | S06 |
| AT-11 | FR-19 | Partial/slow/failed sources, duplicate release references, unknown seeds/narrator, differing raw titles. Incremental useful results; raw detail retained; catalog versions not inflated by releases. | S06 |
| AT-12 | FR-20, FR-21 | Wrong language, blocked format, preferred/required/unknown narrators, exact recording, EPUB preference, M4B/MP3 preference, conflicting source/seeder preference, either/both and owned-media requests. Required names are all-of constraints; preferred names only rank eligible audio. Same narrator alone does not identify a recording; file/backend evidence must confirm requirements. Inherited audio preferences do not constrain ebook targets or remove overall ownership. Eligibility first; deterministic explanation; correct missing targets; manual sorting never rewrites stored profile. | S05–S06 |
| AT-13 | FR-22, FR-23 | Concurrent requests/lists, repeated idempotency key, compatible/incompatible version constraints, qBit add timeout, preexisting unrelated torrent and shared cancellation. One authorized compatible transfer; uncertain add reconciled; unrelated jobs remain untouched; cancellation of one reason does not cancel others. | S01, S05, S07 |
| AT-14 | FR-24, FR-25 | Just-book/prefer-pack/complete-series, aliases, main/related/unreleased works, partial/wrong pack claims, mixed-media packs and already-owned children. Explicit expansion; actual per-child coverage; independent completion/recovery; no duplicate import. | S04, S06 |
| AT-15 | FR-26 | Indivisible omnibus with verified/unknown contents, shared asset availability and deletion. One actual asset can satisfy verified works; no fictional split files; losing that asset updates all affected coverage. | S04, S06 |
| AT-16 | FR-27 | Missing author/series/year, decimal/non-numeric order, Unicode, reserved characters, long paths, duplicate names, different narrators, changed templates and same-edition ebook formats. Stable valid preview and collision handling; no implicit existing-file moves. | S04 |
| AT-17 | FR-28, NFR-01 | Same-filesystem hardlink, incompatible mounts, explicit copy fallback, disk-full, destination collision, symlinks/path traversal and interrupted publication. Confined no-replace import; verified source integrity; unrelated files untouched; no destructive fallback. | S04 |
| AT-18 | FR-29 | Initial generated sidecars/covers, existing absMetadata/OPF conflict, refreshed catalog, protected ABS edits and post-import template change. Correct initial metadata; later refresh changes app data only; no source inode/tag writes. | S04 |
| AT-19 | FR-30 | Conventional/nested version layouts, multiple narrators, multi-file recordings, ebook formats, scan-capable/inventory-only credentials and delayed/failed scan. Correct ABS item count/identity/files; watcher mode works; only observed items become available. | S04–S05 |
| AT-20 | FR-31 | Hardcover pagination, private/public authorized lists, quota/auth failure, interrupted snapshot, repeated pages and provider membership updates. Per-account boundaries; committed complete observations; no lost entries or invented removals. | S07 |
| AT-21 | FR-32 | Goodreads RSS repeated/truncated/empty/304 responses, changed feed entry IDs, malformed XML, CSV duplicates and encoding. Safe parsing and identity dedupe; RSS omission never removes membership; CSV preview explains snapshot behavior. | S07 |
| AT-22 | FR-33 | Browse/manual/auto, future-only baseline failure, backlog preview, overlapping lists, media both/either, exclusions, pause/resume and removing a request reason. Paused acquisition continues membership observation; resumption previews accumulated additions; policy changes preview existing unsatisfied targets. No work before valid authorization/baseline; bounded resumable backfill; repeated sync has no duplicate side effect. | S07 |
| AT-23 | FR-34 | Hardcover write-back disabled/enabled, unsupported mutation, success response lost, remote conflict, echoed membership, account revoked and read-status fields. Reconcile intended list state; no blind duplicate write; no download-to-read mutation; no Goodreads write-back. | S08 |
| AT-24 | FR-35, NFR-08 | Search rejection, auth failure, uncertain dispatch, partial pack, held match, scan delay and retry. Correlated redacted history; visible policy/reason; correct next action resumes only necessary stage. | S01–S09 |
| AT-25 | FR-36, NFR-11 | Upgrade backup, restored keys/manifests, running external download, partially published import and deleted media after backup. Restore dispatch-paused; reconcile before resume; no historical replay; measured app-state RPO/RTO meets reference targets. | S09 |
| AT-26 | NFR-03, NFR-04, NFR-10 | Reference dataset/load, slow upstreams, large list backfill, large pack, repeated failures and worker concurrency. Meet PRD latency/capacity targets, bound queues/memory/connections, honor budgets and show partial results. | S09 |
| AT-27 | NFR-05, FR-02 | Cross-account object IDs, list/library grants, shared-transfer privacy, CSRF/session misuse, secret exports, provider redirects to local services, malicious metadata/feed/path inputs. Authorization enforced; secrets redacted; untrusted routing/files confined; intended admin local-service configuration supported. | S01, S03, S08–S09 |
| AT-28 | NFR-07 | Keyboard-only onboarding/search/request/list/repair, focus restoration, labels/errors, screen-reader status, contrast and zoom/mobile. Core flows meet WCAG 2.2 AA target with documented automated and manual evidence. | S02 onward; S09 release |
| AT-29 | NFR-06, NFR-09, NFR-12 | Fresh Compose install, supported version matrix, migration from prior release fixture, missing optional provider, image/non-root permissions, license notices and generated API drift. Reproducible deployment; truthful capability limits; degraded browse; documented upgrade/recovery. | S00 onward; S09 release |
| AT-30 | NFR-01, NFR-02, FR-22, FR-23, FR-28 | Kill/restart at every side-effect boundary in section 4. State converges without duplicate dispatch, source mutation, destination overwrite or premature ownership. | S01, S04–S07, S09 |
| AT-31 | FR-37, FR-38 | Optional upgrade/reorganization with failure before/after publication, old-copy retention, seeding, collision and ABS progress mapping. Preserve existing availability until replacement confirmed; resumable previewed changes; block unknown progress-preservation cases. | S10 |
| AT-32 | FR-39 | Additional backend inventory, permissions, capabilities, media/version grouping, item moves and availability. Pass independent adapter/compatibility contract; no assumed ABS behavior. | S10 |
| AT-33 | FR-40 | Additional recommendation/provider identity, attribution, opt-ins and usefulness evaluation. No private-data leakage or false edition merge; document benefit and fallback. | S10 |
| AT-34 | FR-41 | Actual additional client's submit ambiguity, monitoring, completion, files, cleanup and restart. Same durable acquisition/import guarantees with client-specific evidence. | S10 |
| AT-35 | FR-42 | OIDC linking, issuer/subject collision, revoked access, grant enforcement and admin recovery. No account takeover or lost list ownership; recovery remains possible. | S10 |

## 3. Required fixture corpus

Build fixture directories during S00; filenames below describe cases rather than existing artifacts.

| Corpus | Minimum representative cases |
|---|---|
| Catalog | Same title/different authors; translations; reused/missing identifier; abbreviated author; pen name; multiple narrators; abridged/unabridged; revised ebook; provider duplicate/merge; ambiguous series order |
| Audio | Single M4B; ordered multi-MP3 book; nested CD folders; two narrator versions; missing/contradictory tags; incomplete tracks; companion PDF; same recording in two encodings |
| Ebook | EPUB; PDF full book versus companion; EPUB+AZW3 of same edition; distinct revised editions; missing title/author; Unicode/long names |
| Collections | Clean book-per-folder series; flat filenames; mixed ebook/audio; missing advertised child; unrelated extras; partially owned pack; mislabeled child; inseparable omnibus; ambiguous grouping |
| Filesystem | Same filesystem; incompatible mounts; writable/unwritable roots; collision with unrelated file; symlink escape; directory replacement race; full disk; worker restart mid-copy/publish |
| Lists | Complete paginated list; interrupted page; duplicate membership; RSS window truncation; existing-entry edit; empty/304/error feed; CSV import; future-only baseline; multi-user overlapping lists |
| Services | ABS scan permission denied/event gap; qBit response lost/torrent already exists; MAM rotated session/login page; ABB parser drift; Prowlarr unsupported protocol; Hardcover quota/permission error |

Assertions should inspect database state and external files/items, not only UI messages. Source hashes, destination file identities, manifest entries, qBittorrent associations and ABS item boundaries provide the integrity evidence. Generated test media must contain enough real structure for the scanner/inspector to classify it; zero-byte filename placeholders are insufficient for media compatibility tests.

## 4. Crash and ambiguous-outcome matrix

| Interruption point | Required recovery |
|---|---|
| Domain transaction before commit | No committed intent/job side effect |
| Domain commit before worker execution | Durable job remains executable; no lost acquisition |
| Worker redelivery/concurrent reservation | Compatible targets attach to one active fulfillment path |
| qBit add submitted, response absent | Mark dispatch-uncertain; lookup and reconcile before resubmitting |
| qBit completion before status persisted | Discover existing associated torrent/files; continue inspection |
| Manifest planned before staging | Resume that versioned plan; do not silently use changed templates |
| Partial hardlink/copy staging | Reconcile owned staging entries; retry safely; original files unchanged |
| Publication succeeds before DB acknowledgment | Recognize owned published destination from journal/evidence; do not overwrite or duplicate |
| Some pack children published, another fails | Preserve successful children; retry/hold only incomplete entries |
| ABS scan requested, response lost | Observe inventory or retry safe scan under policy; never redownload |
| ABS confirmation before availability commit | Reconcile backend binding and commit availability once |
| List observation persisted around dispatch | Reasons/intents remain idempotent; no repeated backlog |
| Hardcover mutation succeeds, response lost | Reconcile remote desired state before repeating operation |
| Database restored behind external state | Start dispatch-paused, reconcile downloads/files/backend, then resume deliberately |

A no-replace publication test must exercise competing publishers and preexisting unrelated destinations. A pass based only on checking `exists()` before writing is insufficient because it does not protect against races. Verify the selected filesystem primitive's actual behavior.

## 5. Compatibility certification template

Publish a matrix for each release with these fields:

| Dimension | Evidence required |
|---|---|
| Backend/client | Exact version/image, auth mode, required permissions, tested operations and limitations |
| ABS media/layout | Conventional/nested; audiobook/ebook; multiple recordings; multi-file audio; omnibus; resulting item boundaries |
| Metadata | Folder/tag/sidecar precedence, imported fields, manual-edit preservation and refresh behavior |
| Filesystem | Host/filesystem/mount arrangement, UID/GID, hardlink test, publication primitive, copy support |
| Source | Adapter revision, sanitized fixture revision, live connection check date, supported fields/transport/route |
| List provider | Read/write capabilities, tested pagination/observation semantics, scope and quota behavior |

Default to disabled or explicitly unverified for untested optional capabilities. Display degraded mode when a previously healthy integration changes behavior. Never generalize one Linux filesystem result to all network or container mounts.

## 6. Release gates and evidence package

Gate severity:

- **P0:** source data corruption, unrelated overwrite, credential/private-data exposure, broken authorization or unrecoverable persisted state. Blocks all affected releases immediately.
- **P1:** unintended duplicate acquisition, false ownership, mandatory workflow failure, wrong-book automatic acquisition, unbounded automation or failed recovery. Blocks v1; an alpha may only exclude the affected feature explicitly when doing so remains safe.
- **P2:** degraded optional behavior with a truthful documented workaround; prioritize by user impact.
- **P3:** cosmetic polish without functional/accessibility impact.

Release package: requirement coverage report; AT results with revisions; parser/live-connector distinction; compatibility matrix; crash/concurrency evidence; before/after source-integrity checks; backup/restore timings; performance percentiles; accessibility review; security/reuse review; screenshots of principal states; known limitations and operator guide.

All FR-01–FR-36 and NFR-01–NFR-12 must map to passing evidence before v1. AT-31–AT-35 are not v1 blockers because their features are explicitly post-v1. When a scenario fails, record its actual effect and owner; do not convert “not run” into “passed with limitations.”

## 7. Stage evidence scopes

An AT scenario is a release-level collection of assertions. Early stages prove their assigned subset; they cannot claim the whole scenario passed or require a later integration merely to close an earlier package. Record the specific assertion/fixture alongside the AT ID. The S09 gate runs the complete v1 scenarios across the integrated application.

| Gate | Evidence required at this stage | Evidence deliberately completed later |
|---|---|---|
| S00 | Clean install/scaffold, schema lifecycle, generated contracts and reproducible fixture harness | Real integration behavior, production deployment certification |
| S01 | Roles, durable identity/corrections, atomic enqueue, target reservations and redelivery using domain fixtures | Actual downloader side effects, provider conflicts involving live adapters, file publication |
| S02 | Catalog identity/metadata, protected edits, local list CRUD and catalog search/detail; AT-02–AT-05 applicable subsets | ABS preservation/ownership in S03–S04; source-native provisional discovery in S05; aggregation in S06; discovery/sharing in S08 |
| S03 | Complete/partial inventory, grants, media ownership, move/missing detection, relink/ignore and replacement-intent creation | Execution of replacement acquisition in S05; full restore/recovery rehearsal in S09 |
| S04 | AT-14 import subset and AT-15–AT-19 using completed-file fixtures and actual supported ABS; publication crash points | Live qBittorrent lifecycle in S05; source-ranked pack selection in S06 |
| S05 | MAM/proxy/session, qBittorrent and the complete manual request-to-library flow; actual submission-uncertainty recovery | Other sources/ranking in S06; external-list triggers in S07 |
| S06 | Multi-source aggregation, eligibility/ranking, series policy, actual-versus-claimed coverage and partial pack fulfillment | Scheduled external-list observations in S07; curation surfaces in S08 |
| S07 | Inbound lists, baselines/backfill, overlapping reasons, pause/resume/exclusions and list-to-library automation | Optional outbound list writes and shared/community curation in S08 |
| S08 | Discovery, complete local list sharing, supported write-back, core-flow usability/accessibility | Final cross-version, performance, restore and packaging certification in S09 |
| S09 | Full AT-01–AT-30 and all v1 FR/NFR evidence, including earlier-stage regressions | Only explicitly post-v1 FR-37–FR-42/AT-31–AT-35 |
| S10 | The complete relevant expansion scenario plus v1 regression for affected modules | Other independently scoped expansion releases |

The [integrated PRD walkthrough](PRD.md#15-end-to-end-product-acceptance-walkthrough) provides one shared demonstration across stages. It supplements the negative-case matrix; a successful happy path does not waive a failed duplicate, privacy, source-integrity or recovery assertion.

## 8. Policy and preview contract assertions

These refine existing scenarios, without introducing additional release stages or changing the AT identifiers.

| Existing scenario | Additional required assertion | Delivery |
|---|---|---|
| AT-12 | Resolve request/list/profile/user/installation preferences in documented order; enforce administrator restrictions independently; show inherited origins; reject an empty eligible-format set | S05 baseline, S06 complete |
| AT-13 | Two lists with conflicting exact-version constraints retain independent requirements; compatible reasons may share a transfer without losing either policy snapshot | S06–S07 |
| AT-12–AT-13, AT-22, AT-30 | Concurrent lists preserve blocked-format and transfer-size restrictions; a planned shared reservation uses their intersection, incompatible restrictions stay separate, and withdrawal recomputes only unselected requirements. A selected release is shared only with inspected evidence that it satisfies the new reason. Acquisition restrictions do not make a confirmed owned book missing | S06–S07; S09 concurrency/restart regression |
| AT-15–AT-19 | Sample naming preview needs no library mount and makes no verified-link claim; inspected and publication-ready plans have distinct prerequisites | S04 |
| AT-15–AT-19, AT-27 | EPUB/CBZ are preserved as book containers; unsupported archives are held. Any enabled extractor proves traversal/link confinement, bounded resource use, unchanged archive bytes and honest additional-storage accounting | S04; extraction assertions only when capability enabled |
| AT-21–AT-23 | Editing a list profile previews unsatisfied targets; it never silently replaces a running transfer or acquires an already satisfied title | S07–S08 |
| AT-30 | A naming change during an interrupted import does not change frozen destinations; permission revocation before publication pauses it despite a valid historical plan | S04 publication subset; S09 full regression |

Preserve the distinction between proposed behavior and implementation evidence when evaluating these assertions. A saved profile and a successful sample preview cannot close the importer stage.

## 9. Stage review and defect severity

Apply the [release-blocker policy and stage review record](IMPLEMENTATION-PLAN.md#11-release-blockers-and-stage-review) when evaluating these scenarios. Every failure records the affected requirement, actual result, severity, reproduction evidence and owner. Mark missing credentials or unavailable test infrastructure as not run; do not convert them into passing evidence.

Acceptance requires both the positive journey and its relevant failure assertions. For example, a successful list download does not close AT-22 if a truncated feed launches the backlog, and a correct folder tree does not close AT-19 if ABS combines different recordings into one item. A release restriction must be explicitly allowed by the PRD and enforced in the application; documenting a broken mandatory journey is not acceptance.

## 10. Acquisition closure and repair assertions

These refine existing scenarios for [PRD acquisition closure](PRD.md#17-closing-the-acquisition-loop). They add no new AT identifiers and are not claims of passing tests.

| Scenario | Required assertion | Gate |
|---|---|---|
| AT-06, AT-12, AT-19 | A completed download or successful scan does not close a request. A confirmed accessible ebook establishes work ownership but leaves a Both request's audio target missing; the wrong narrator cannot satisfy an exact-recording target | S05 |
| AT-13, AT-19, AT-30 | Confirmation followed by a crash before request reconciliation converges on one satisfied target and a retired fulfillment reservation; transfer identity/history persists and repeating the event never submits again | S05 |
| AT-13, AT-19, AT-27 | A qualifying existing accessible asset can satisfy the request and skip duplicate import. An inaccessible asset cannot; neither outcome leaks another user's library or private request reason | S05 |
| AT-14, AT-19, AT-24 | In a three-child pack, confirmed children remain available while one ambiguous child stays held. Resolving that child resumes its import without redownloading or republishing completed siblings | S04–S06 |
| AT-13, AT-14, AT-27 | Two works requested from the same known pack share an authorized transfer or reuse verified files through separate import plans; identity conflicts neither launch duplicate transfers nor expose private holdings | S06 |
| AT-08, AT-13, AT-24, AT-30 | Credential rotation has a reviewed repair path that observes the same associated transfer. Missing transfer, changed client identity, altered destination and uncertain prior add remain explicit; no blind add retry | S05 |
| AT-02, AT-13 | Fulfilled historical acquisitions do not permanently block canonical correction; active or uncertain transfers retain their protected associations, immutable origin and audit history through any permitted correction | S01 foundation; S05 full lifecycle |
| AT-13, AT-22, AT-24 | A member's import can reach authorized administrator review. Withdrawing one reason preserves others; post-submission withdrawal does not delete source files, abandon uncertain identity evidence or imply permission to resubmit | S05; list reasons S07 |

Inspect durable lineage and external call counts as well as UI states. Closing a request and retiring a torrent identity are different assertions; a test that only checks `progress = 100%` cannot satisfy either.

## 11. Unattended acquisition and review assertions

These assertions complete the [automation contract](PRD.md#18-unattended-operation-and-exception-review) under existing AT IDs. They are required behavior, not passing evidence.

| Scenario | Required assertion | Gate |
|---|---|---|
| AT-13, AT-19, AT-27 | Administrator review preserves the original requester and authorized destination; a member sees only their own progress; claiming a review exposes no private list/token or unrelated artifact | S05 |
| AT-24, AT-27, AT-30 | Concurrent review claims produce one active assignment; repeated command keys create no second inspection; reassignment invalidates prior unstarted authority and cannot race a reserved/published child | S05 |
| AT-13, AT-17, AT-27, AT-30 | Revocation or withdrawal after planning but before publication holds unpublished work; a reviewer cannot substitute their own broader permissions; existing files and transfer evidence are preserved | S04 baseline, S05 handoff |
| AT-14, AT-19, AT-24 | A clean supported acquisition uses the automatic route without per-title approval; an ambiguous sibling alone waits; resolving it continues the same transfer/import lineage | S05 baseline, S06 packs |
| AT-20–AT-22, AT-30 | After a valid future-only baseline, one Hardcover or Goodreads addition reaches ABS confirmation with zero per-title approvals; repeated observations and restarts add no extra transfer/import | S07 |
| AT-12, AT-22, AT-26 | Backlog, pack, concurrency and storage limits are finite and server-enforced; unknown size/coverage is not zero; quota failures back off without creating an endless stream of review tasks | S06–S07; S09 capacity qualification |
| AT-25, AT-29–AT-30 | The same unattended journey works on the shipped deployment and resumes correctly after restore reconciliation; historical list entries do not launch an unintended backlog | S09 |

Measure approval steps and inspect the resulting ABS items, persisted reasons, source hashes and external submission counts. A list entry merely appearing in Wanted or a completed torrent waiting indefinitely for routine manual import does not pass the S07 defining journey.


## 12. Automation limits and planning traceability

Apply these assertions to AT-12–AT-14, AT-20–AT-22, AT-26 and AT-30 under the existing S06/S07/S09 gates; they add no acceptance-scenario IDs. The [requirement traceability export](REQUIREMENTS-TRACEABILITY.csv) includes all 42 functional and 12 nonfunctional requirements. It records obligations, not pass/fail results.

- Two workers competing for the final transfer slot or free-space reservation admit at most one qualifying transfer. Restart retains unresolved reservations; seed-only completed transfers do not consume active-download slots.
- Actual torrent bytes include extras and already-owned pack children. Unknown bytes or unresolved magnet metadata cannot be dispatched automatically. Shared-filesystem hardlinks, separate-filesystem copies and extraction use the correct storage accounting without counting linked media twice.
- Pack size/expansion, five-manifest inspection, rolling automatic-transfer budget and reviewed backfill limits are enforced by the server. UI changes, retries and alternative list reasons cannot reset them. Manual requests cannot bypass physical-capacity or permission checks.
- Future-only activation dispatches no baseline members. One later entry reaches ABS without per-title approval. Pausing acquisition still refreshes membership; resuming offers a catch-up preview; pausing one reason does not cancel another reason's shared transfer.
- Missing releases progress from the initial search to bounded daily/weekly monitoring without duplicate scheduled work. Provider cooldown supersedes local cadence. A stale lease, permanent authentication failure or unavailable source has an actionable state rather than an unbounded retry loop.
- A stale activation preview, changed profile, revoked grant or newly owned title is re-evaluated before dispatch. The recorded explanation matches the effective rules and actual selected candidate.

Qualification records the tested values from PRD section 19. Changing a default updates product documentation and its boundary fixtures; limits may be tuned with evidence without inventing a new feature or silently broadening an active list's authority.


## 13. Product journey review

The PRD's [J-01–J-08 launch journeys](PRD.md#20-launch-journey-checklist) group existing AT assertions into product demonstrations. They add no new scenario IDs and do not replace the detailed failure matrix. The implementation plan's [M0–M7 release contract](IMPLEMENTATION-PLAN.md#16-release-delivery-contract) assigns those demonstrations to milestones.

Record the journey, tested revision, prerequisite configuration, user-visible result, durable/external evidence and remaining unsupported combinations. For the automation journeys, count routine approval steps and actual transfer submissions; inspect final files and ABS inventory. Repeat with overlapping lists, a worker restart and a delayed scan. For J-06, include an ambiguous child and a separately owned child, and verify their independent outcomes. For J-08, reconcile an external transfer that is ahead of the restored database before resuming dispatch.

Document-only planning updates require requirement/backlog cross-reference and link checks. They do not constitute a new application test run or alter previous implementation evidence. New functionality and changed defaults require their relevant implementation checks before acceptance.

## 14. Series catalog and acquisition boundary

These assertions refine AT-02, AT-04–AT-06 and AT-14–AT-15, with automated fulfillment still covered by AT-20–AT-22 and AT-30. They introduce no new scenario IDs. Apply them to the S06-05 child tasks in the implementation plan.

- Two provider series with the same name remain separate. Repeated positions, decimal positions, unknown positions, compilations, partial books and merged records retain their source evidence. Popularity never silently decides acquisition identity or main-series membership.
- An interrupted, changing or permission-limited series refresh preserves the previous usable snapshot and reports its freshness. A same-size membership replacement is not mistaken for an unchanged catalog merely because counts match. Account revocation or superseding refresh fences stale workers from publishing.
- A series page counts distinct canonical works from accessible inventory; a compilation row does not count as another owned main-series work. An ebook-only work stays owned while an audio target remains wanted. Identity corrections update the projection without losing request history.
- Adding selected books to a list is authorized, idempotent and reports partial failures. The UI identifies when the chosen list already has automatic acquisition enabled. Read-only catalog refresh never submits downloads.
- Complete series records a finite target set and its catalog/policy revision. An unknown publication date or ambiguous main membership does not become eligible by guesswork. Provider refresh, a new sequel and a popularity change cannot expand an accepted request; explicit future monitoring uses standing policy.
- A partly owned pack keeps separate claimed and verified coverage. One verified child may finish while another is held. Retries preserve successful publication, seeding paths and surviving request reasons. An inseparable omnibus remains one asset; losing it updates all verified containment relationships.
