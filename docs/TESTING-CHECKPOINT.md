# Internal-alpha testing checkpoint

September 19, 2026 · Local Git tag: `internal-alpha-2026-09-19`.

Development is stopping at this checkpoint for user testing. The full PRD remains incomplete; this is not production acceptance or a reduction of the remaining scope. Resume feature work after reviewing testing feedback.

## Running product

Open **http://localhost:8000** on this Mac. This is a local native installation, not a remotely hosted team deployment. The API and worker use schema `0044_recovery_approvals`; download dispatch is disabled. The last verified development state has no active user or configured real-service workflow. Browser test accounts and holdings belong to a separate disposable database.

Complete first-run administrator setup, then use Getting started to connect Audiobookshelf and optional Hardcover metadata. Keep the locally configured bootstrap token private. Test catalog search, actual holdings, lists, source comparison and Activity before enabling controlled downloads into a test destination. Follow the ordered [internal-alpha walkthrough](INTERNAL-ALPHA.md).

This checkpoint includes catalog and metadata browsing, scoped ABS inventory, ebook/audio ownership, MAM/ABB/Prowlarr adapters, qBittorrent acquisition and file organization, list subscriptions/policies, discovery shelves, followed-list browsing, saved requests in Activity and searchable operation history. Existing automated tests use synthetic external services. They do not certify your accounts, files, server versions or filesystem topology.

## Major unfinished P0/P1 implementation

Priorities below concern production or unattended use. They do not require finishing every feature before controlled internal testing. “Incomplete” means existing supported cases work but the full intended behavior is not yet implemented/accepted.

| Priority | Feature gap | What to expect during testing |
|---|---|---|
| **P0 — production blocker** | **Complete restore and safe resume.** Backup and paused restore exist, but metadata-account/configuration reconciliation, uncertain external effects/reservations, fresh wanted-work activation and controlled resume remain unfinished. | Use the current fresh installation. A restored instance cannot yet be treated as a fully resumable production installation. |
| **P1** | **Broader edition/narrator and collection handling.** General edition equivalence, exact-version packs, mixed/constrained packs, additional child-recovery cases and transfer reuse across different owners/routes remain incomplete. | Start with individual ebooks/audiobooks, then deliberately review two narrations and partly owned packs. Do not treat all collection/version combinations as covered. |
| **P1** | **Reviewed changes to an existing unsatisfied request.** Requests retain frozen requirements/preferences; an end-to-end revision flow for those saved requests is not implemented. | Changing defaults or a profile must not be assumed to rewrite an existing request. Record cases where the current flow prevents the desired change. |
| **P1** | **Whole-library series enrichment and discovery depth.** Series continuation uses already loaded catalogs; automatic discovery/enrichment of every series in the library is still missing. Richer recommendation coverage remains unfinished. | Load a known series through its book/series page. Assess current recommendations as basic, attributed discovery rather than full Goodreads/Amazon parity. |
| **P1** | **Complete issue-to-repair coverage.** Requests, download reviews and history have actions, but not every operation/failure type has complete correlated context and a guided repair path. | Use the existing book/list/download/organization workflow when a history row has no direct action. Record the operation ID and the point where guidance is missing. |

## Important qualification gaps, not wholly missing features

| Gate | Remaining evidence |
|---|---|
| **Before trusting unattended acquisitions** | Validate actual MAM/proxy/qBittorrent/ABS connections; current ABB/Prowlarr behavior; save-path mappings, permissions, hardlinks, supported ABS version-folder layouts, original seed-file preservation and final inventory confirmation. Complete the remaining list lifecycle/policy-change/backfill/overlapping-reason cases using real external lists. The underlying integrations and automation exist. |
| **Before production/shared deployment** | Qualify the supported Compose/platform/service matrix, upgrades and populated restore, reference-load performance, complete accessibility/security review and operator documentation. Native local readiness is not evidence for all deployment platforms. |

BookOrbit/other player backends, additional download clients/Usenet, advanced recommendation providers, automatic upgrades/existing-library reorganization and SSO remain later-stage work. They are not prerequisites for testing the ABS + qBittorrent alpha, but remain in the full PRD scope.

## First test pass

1. Connect ABS and verify a known ebook, audiobook and multiple-version work.
2. Browse/search and follow a small Hardcover or Goodreads list in Browse mode. Check ownership, followed-list status and Activity navigation.
3. Compare MAM and optional other-source results for known titles.
4. Qualify a separate test destination, then intentionally enable controlled acquisition for one ebook and one audiobook. Confirm source preservation, organization, ABS detection and deduplication.
5. Test one small automatic list and one partly owned series pack; record exceptions before broad backfill or unattended operation.

Record the build/tag, steps, expected/actual result, relevant operation ID and whether the issue blocks the task. Keep screenshots/logs redacted. Link findings to ALPHA-01–09 in the [remaining-work register](INTERNAL-ALPHA.md#outstanding-implementation-and-review-register).

Exact test and local-deployment evidence for this checkpoint is recorded in [implementation status](IMPLEMENTATION-STATUS.md), under Searchable background activity. Passing targeted checks does not close all PRD stages.
