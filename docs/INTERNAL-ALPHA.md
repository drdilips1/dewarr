# Internal alpha: use the product and track the remaining work

September 19, 2026. This is a runnable internal alpha, not a feature-complete release. The full PRD and S00–S10 objective remain active. Start user testing now; production recovery, expansion features and every release qualification do not need to be finished before people can evaluate the core experience.

## Where to start

The native development instance is at **http://localhost:8000** on this Mac. It binds locally; this is not a remotely hosted or certified Docker deployment. The instance inspection found an empty application database: no active user, catalog works, lists, inventory assets or configured integrations. Existing browser demonstrations use a separate disposable database and synthetic services; those records are not your library.

Complete first-run administrator setup in the UI. The deployment bootstrap token is stored in the local environment configuration; keep it private and choose your own account password. Then configure catalog/library connections through the app. Download dispatch remains disabled in this installation. Browsing and setup can be tested first; actual downloading requires the controlled acquisition qualification below and an intentional deployment setting change.

After signing in, open **Getting started** in the navigation, or **Set up your collection** in an empty catalog. It links the setup steps in order and reports saved library inventories, your own Hardcover connection, sources, downloader mappings, destination checks and the deployment's download switch. Refreshing this page only reads saved evidence. It does not test external connections, approve an import or enable downloads. An unavailable status request replaces the checks with a retry message rather than presenting cached evidence as current.

Runtime and build evidence is recorded in [implementation status](IMPLEMENTATION-STATUS.md). Tests establish the scenarios they exercise, not blanket completion of a stage or compatibility with an untested live account.

## What is available for testing

| Product area | Implemented experience | What still needs user or integration evidence |
|---|---|---|
| Setup and connections | Administrator setup, roles/grants, encrypted service settings and connection diagnostics | First-run clarity and the user's actual URLs, permissions and path topology |
| Catalog and curation | Hardcover/Open Library lookup, book/version pages, protected metadata, local lists, sharing and browsing | Metadata quality on the user's books, defaults and ease of curation |
| Library view | ABS inventory, scoped ownership, ebook/audio distinctions, matching corrections and deep links | Live inventory reconciliation and ambiguous real-world records |
| Source search | Native MAM, AudiobookBay and Prowlarr adapters, rich result details, comparison and preference handling | Current live accounts/hosts, proxy route and source equivalence |
| Acquisition and organization | qBittorrent lifecycle, inspected artifacts, reservations, reviewed/automatic imports, naming and hardlink/copy publication | Controlled live ebook/audio acquisitions, actual mount permissions and supported ABS layout boundaries |
| Lists and automation | Hardcover and Goodreads inbound observations, local policies, activation/backlog reviews and shared acquisition reasons | Real list pagination/change semantics, overlapping lists and unattended lifecycle behavior |
| Discovery | Attributed shelves, related titles, community lists and loaded-series continuation | Usefulness, broader series coverage, provider capabilities and bookstore-like usability |
| Recovery | Backup/paused restore plus successive review/repair workflows, including source sessions | Complete configuration/effect reconciliation, fresh activation and controlled resume are still unfinished |

Basic discovery, curation and acquisition exist. Full catalog/edition/collection coverage, recommendation depth, release hardening and later integrations are not all complete. Screens existing in the app should not be mistaken for every PRD acceptance case passing.

## First internal testing session

Use the app normally and record friction; avoid turning this into only another automated-test exercise.

1. **First run:** create the account, open Getting started and configure ABS plus an optional Hardcover account. Open Library search is available without a token. Return to Getting started after connection testing and inventory sync; record any setting that requires external explanation. Confirm connection failures tell you what to fix.
2. **Recognize your library:** inspect a known ebook, an audiobook and a work with multiple recordings. Check the overall ownership badge, medium/version details and the selected ABS link. Resolve an intentionally ambiguous match.
3. **Browse and curate:** use the header search to find local and provider titles together. Local results also support known series, valid ISBNs/ASINs and qualified provider IDs such as `hardcover:42`. Accepted provider matches show current scoped library status and open the existing book; an unmatched result does not prove the book is absent from your library. Try a provider outage and confirm local matches remain usable. Inspect Recent library additions and its ebook/audio filters; observation dates should reflect when the app first saw a copy, while catalog-only books stay out of that shelf. Inspect recommendations and series, create a local list, reorder/remove titles, and follow one external list in Browse mode. Check empty/error/stale states as well as successful results.
4. **Compare sources:** connect MAM and its required route, then optional Prowlarr/ABB. Inspect raw titles, narrators, formats, sizes, seeds and pack coverage for known books. Try Sort this view and the loaded-result filters; the original profile rank stays visible, unknown numbers sort last, and these controls do not change download policy. To prioritize a specific Prowlarr indexer, expand Individual Prowlarr priorities in the download preference editor, load the indexers and save the chosen ordering. Verify the preferred result is the right book/version before testing acquisition.
5. **Controlled acquisition:** qualify qBittorrent mappings and a separate test destination/ABS library. In Library destinations, select the tested downloader and run Test destination route; this works with an empty, existing writable save folder and needs no import plan. Confirm the naming preview and actual hardlink capability. Intentionally enable dispatch for this test, then acquire one ebook and one audiobook. Verify original download bytes/paths, organized files, ABS detection and final ownership. Repeating the request must not start another transfer.
6. **Small automatic list:** after the manual path works, activate future additions for a small dedicated list. Add one title upstream, observe it arrive once, then test a second overlapping list and an already-owned book. Keep broad historical backfill off during the first exercise.
7. **Versions and packs:** try a known two-narrator work and a partly owned series pack. Review ambiguous children instead of guessing. Verify that resolved children can complete without duplicating owned books or changing the seeded pack.

The first four steps can start before enabling downloads. Steps five through seven deliberately introduce side effects into a test destination. Do not use the unfinished restored-instance resume flow as the basis for the alpha installation.

## Outstanding implementation and review register

This register is the concise product-facing list. Detailed obligations remain in the [61-package backlog](../DEVELOPMENT-BACKLOG.csv), [requirement traceability](../REQUIREMENTS-TRACEABILITY.csv) and [acceptance plan](../ACCEPTANCE-PLAN.md). Items below distinguish unfinished implementation from qualification and user feedback. Priorities state what they block.

| ID | Type / priority | Remaining work | Completion evidence | Packages |
|---|---|---|---|---|
| ALPHA-01 | Setup qualification / first testing session | Configure this currently empty instance with the user's catalog and library; verify account scopes and inventory access | A real user finishes setup and sees correct known holdings | S02–S03, S08-04 |
| ALPHA-02 | Integration qualification / before live automatic acquisition | Qualify actual MAM/proxy/qBit/ABS, download mappings, destination permissions and source-preserving publication | One ebook and audiobook complete; repeated requests dedupe; correct ABS items and unchanged seed data | S04–S05, AT-08, AT-13, AT-17–AT-19 |
| ALPHA-03 | Implementation + qualification / before broad collection automation | Broader edition/recording equivalence, mixed/constrained packs, omnibus and child recovery; certify intended nested version layouts | Partly owned series, two narrations and an ambiguous child produce truthful independent ownership | S03–S06, AT-02, AT-12, AT-14–AT-19 |
| ALPHA-04 | Implementation + qualification / before unattended operation | Complete policy-change, overlapping-reason, catch-up/backfill and bounded scheduling coverage with real external lists | New membership reaches ABS once; pause/remove/re-add/profile changes preserve independently authorized work | S06–S07, AT-20–AT-22, AT-30 |
| ALPHA-05 | Provider qualification / before claiming supported integrations | Current ABB host parsing, Prowlarr/native overlap, Hardcover operation/account permissions and optional write-back | Tested current versions/accounts and explicit capability/failure diagnostics | S02, S05–S08, AT-03, AT-08–AT-11, AT-20–AT-23 |
| ALPHA-06 | UX review + implementation / internal alpha feedback | Setup simplicity, metadata/ranking defaults, bookstore browsing, discovery quality, collection review and actionable Activity screens | Users complete the first-session tasks; resolve recorded confusing steps; desktop/mobile/keyboard review | S02, S08, AT-04–AT-05, AT-24, AT-28 |
| ALPHA-07 | Unfinished implementation / production release blocker | Metadata-account recovery, real destination/route qualification, uncertain external effects/reservations, fresh wanted-work activation and controlled resume | Populated offline restore reconciles external state and resumes without historic replay or duplicate effects | S09-02, AT-25, AT-30 |
| ALPHA-08 | Release qualification / production release blocker | Supported Compose/platform/service matrix, reference-load benchmarks, complete accessibility/security review, upgrade/restore timings and operator documentation | Mandatory v1 acceptance gates pass on the supported deployment, with measured evidence | S00–S09 gaps, AT-26–AT-30 |
| ALPHA-09 | Planned expansion / later stages | Additional player backends including BookOrbit, other clients/Usenet, richer recommendation providers, optional upgrades/reorganization and SSO | Each extension passes its independent identity, permissions and recovery contract | S10-01–S10-06, FR-37–FR-42 |

No full stage acceptance is claimed yet. This reflects both remaining functionality and uncompleted live-service/release evidence; it does not mean the implemented product is unusable. Internal-alpha feedback should now drive the product work alongside integrity fixes. Source connection recovery and the first-use setup overview are implemented; prioritize the first connected-library and controlled-acquisition sessions over expanding recovery features ahead of user feedback.

## Recording feedback

For each issue, record the journey and build, expected versus actual behavior, exact reproduction steps, a redacted screenshot or operation ID when useful, and whether it blocks the task. Classify it as a defect, confusing UX, missing capability or environment/integration problem. Link it to an ALPHA ID and stable FR/AT/package when applicable. Preserve secrets and distinguish a fixture result from a live-service observation.

An alpha pass means the selected user journeys worked on the tested installation. Production readiness still requires the full v1 gates, and completion of the active end-to-end goal also includes the separately scoped S10 work.
