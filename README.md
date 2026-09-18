# Book discovery app — planning workspace

A self-hosted ebook/audiobook discovery, curation and acquisition application above Audiobookshelf, with native MAM/AudiobookBay, optional Prowlarr, direct qBittorrent, and Hardcover/Goodreads list automation.

**Status:** implementation is in progress. Accounts, catalog/lists and durable workers are implemented; Audiobookshelf inventory/grants and metadata provider search, editions, protected edits, reversible corrections, canonical book grouping/undo and automatic secondary enrichment have fixture-tested API/UI flows. Wanted requests support media/version requirements, independent reasons, compatible reservations and inventory reconciliation; saving a request does not download it. Organization supports naming presets, inspection, collection-group correction, catalog-version mapping, frozen plans, verified destinations and reviewed per-book publication with initial OPF/cover export and ABS confirmation. Pending imports can be stopped through journaled cleanup; unresolved collection children can be replanned beside unchanged completed siblings. PDF/CBZ inspection, reviewed equivalent ebook formats and PDF companions are implemented. Eight real ABS scanner/API cases and eight application import workflows pass with synthetic media, including inventory refresh without phantom editions or lost reviewed formats. Native MAM acquisition now has an opt-in durable qBittorrent submission/monitoring path with inspection handoff. Complete source-to-library compatibility and external list automation remain pending. See [Implementation Status](docs/IMPLEMENTATION-STATUS.md) for precise coverage and evidence, and [Development Guide](docs/DEVELOPMENT.md) to run the current build. The full PRD remains the goal.

## Development handoff

Latest list checkpoint: [Goodreads shelf subscriptions](docs/GOODREADS-SUBSCRIPTIONS.md) bring RSS additions into private local lists through scheduled workers, retain omitted books, remember exclusions and reuse corroborated catalog identities with existing library availability. [Reviewed CSV snapshots](docs/CSV-LIST-IMPORT.md) now add column mapping, shelf/subset selection, private identity dedupe and durable import receipts. Hardcover lists, backfill/catch-up policy and automatic list acquisition remain pending.

Latest import checkpoint: [single-file imports](docs/SINGLE-FILE-IMPORTS.md) handle standalone downloads without scanning neighboring files, preserve existing directory receipts, and pass real ABS ebook/audio workflows. [Catalog matching](docs/IMPORT-MATCHING.md) resolves embedded edition identifiers against the local catalog, exposes conflicts for review and saves revalidated evidence without asserting file completeness or ownership.

Latest lifecycle checkpoint: [download fulfillment](docs/DOWNLOAD-FULFILLMENT.md) links satisfied targets to confirmed assets and import entries, retires completed request reservations, retains transfer identity claims and shows current library availability separately from historical fulfillment. [Reviewed connection repair](docs/DOWNLOAD-REPAIRS.md) validates updated credentials against the existing transfer while preserving the original selection and file routes. [Administrator import reviews](docs/DOWNLOAD-REVIEWS.md) let members' completed downloads reach the reviewed importer while preserving requester permissions through publication. [Automatic import](docs/AUTOMATIC-IMPORTS.md) now continues qualifying EPUB/M4B/MP3 downloads through that shared importer under an administrator-approved route. [Provider edition resolution](docs/IMPORT-CATALOG-RESOLUTION.md) now fills missing local editions through the requester's catalog connection and resumes qualifying imports. Resolution without embedded identifiers, broader collection coverage, changed-endpoint/path reconciliation, shared-pack reuse and external-list automation remain pending.

Latest aggregation checkpoint: [Book Sources](docs/BOOK-SOURCES.md) combines durable MAM/Prowlarr searches on a title page, keeps source failures independent, saves private format/source/seed preferences and carries the chosen release into the shared acquisition path. Complete automatic eligibility, series coverage, native ABB and external-list policies remain pending.

Latest additional source checkpoint: [Prowlarr](docs/PROWLARR-INTEGRATION.md) adds per-indexer browsing and private torrent-file resolution into the shared acquisition engine, with incremental results and native-MAM overlap prevention. Complete ranking/series automation and live certification remain pending.

Latest native source checkpoint: [native MAM search](docs/MAM-INTEGRATION.md) adds rich release browsing, source details, encrypted session settings and required proxy routing. It is fixture verified; live account compatibility remains pending.

Latest acquisition preparation: [saved torrent manifests](docs/SOURCE-ARTIFACTS.md) resolve MAM artifacts, validate native v1/v2/hybrid identity and safe file layouts, encrypt original bytes and provide owner-only manifest views. Inspecting a manifest does not start a download or establish ownership.

Latest request checkpoint: [reviewed release selection](docs/RELEASE-SELECTION.md) connects a wanted title to its saved torrent and verified library route. Requirements remain fixed, compatible requests share the preparation, and cancellation retains history. The opt-in download lifecycle now consumes this selection.

Latest downloader checkpoint: [qBittorrent integration](docs/QBITTORRENT-INTEGRATION.md) includes encrypted administrator settings, read-only connection tests, path mappings and preview, plus submission acknowledgements, transfer/file observations and strict attempt association. Settings and adapter behavior have fixture/browser coverage. [Durable download attempts](docs/DOWNLOAD-ATTEMPTS.md) now add persisted submission, recovery, identity claims and Activity controls. Dispatch is disabled by default pending the remaining integration gates; repair and full source-to-library certification remain unfinished.

Start with the [Product and Development Roadmap](DEVELOPMENT-ROADMAP.md) for the product boundary, end-to-end journey, P0/P1 decisions, stage summary and release milestones.

The roadmap's [requirements-to-delivery checklist](DEVELOPMENT-ROADMAP.md#7-your-requirements-mapped-to-delivery) maps the requested user experience to PRD requirements, development stages and acceptance scenarios.

1. [Product Requirements](PRD.md): v1.6 purpose, scope, user journeys, UX, 36 v1 functional requirements, six post-v1 requirements and 12 nonfunctional requirements. Includes ownership decision tables, list lifecycle, ranking/series rules, settings precedence, in-flight changes, resolved P0/P1 decisions, an integrated list-to-library walkthrough, acquisition closure/repair and unattended operation with scoped exception review.
2. [End-to-End Development Plan](IMPLEMENTATION-PLAN.md): S00–S10 stages, 61 work packages, dependencies, engineering boundaries, ownership and exit gates. Includes module handoffs, API delivery map, milestone demonstrations and eight concrete next slices from the current checkpoint.
3. [Acceptance Plan](ACCEPTANCE-PLAN.md): requirement coverage, scenario matrix, fixtures, crash recovery, compatibility, stage-specific evidence scopes and full release evidence.
4. [Implementation Decisions](IMPLEMENTATION-DECISIONS.md): researched technical choices D01–D13 and primary-source evidence.
5. [Product Architecture](PRODUCT-ARCHITECTURE.md): system overview, integration responsibilities and code-reuse direction.
6. [Development Backlog](DEVELOPMENT-BACKLOG.csv): 61 portable work-package records with stage dependencies, responsible roles, deliverables and exit criteria. Progress remains in Implementation Status; the export does not imply completion.

The PRD controls product behavior; the implementation decisions control the researched technical baseline; the development plan controls sequencing; the acceptance plan controls verification. User instructions take precedence over all documents. Update dependent documents together when a decision changes.

## Supporting research

- [Metadata and collections](research/metadata-and-collections.md)
- [Audiobookshelf import layouts](research/audiobookshelf-import-layout.md)
- [Initial discovery research](research/book-discovery-architecture.md) — historical; its earlier acquisition-manager recommendation is superseded.
- [Source snapshot](research/source-snapshot.json)

For a new checkout, begin with S00. For this existing implementation, use the plan's [execution and handoff contracts](IMPLEMENTATION-PLAN.md#8-execution-and-handoff-contracts) and verified status to continue incomplete work. The first full manual acquisition milestone is S05, list-driven automation is S07, and production v1 requires S09. S10 capabilities are separate later releases.
