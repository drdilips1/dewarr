# Book discovery app — planning workspace

A self-hosted ebook/audiobook discovery, curation and acquisition application above Audiobookshelf, with native MAM/AudiobookBay, optional Prowlarr, direct qBittorrent, and Hardcover/Goodreads list automation.

**Status:** implementation is in progress. Accounts, catalog/lists and durable workers are implemented; Audiobookshelf inventory/grants and metadata provider search, editions, protected edits, reversible corrections, canonical book grouping/undo and automatic secondary enrichment have fixture-tested API/UI flows. Wanted requests support media/version requirements, independent reasons, compatible reservations and inventory reconciliation; saving a request does not download it. Organization supports naming presets, inspection, collection-group correction, catalog-version mapping, frozen plans, verified destinations and reviewed per-book publication with initial OPF/cover export and ABS confirmation. Pending imports can be stopped through journaled cleanup; unresolved collection children can be replanned beside unchanged completed siblings. Eight real ABS scanner/API cases and ebook/merged-audio application import workflows pass with synthetic media. Source acquisition, downloading, complete import compatibility and external list automation remain pending. See [Implementation Status](docs/IMPLEMENTATION-STATUS.md) for precise coverage and evidence, and [Development Guide](docs/DEVELOPMENT.md) to run the current build. The full PRD remains the goal.

## Development handoff

Start with the [Product and Development Roadmap](DEVELOPMENT-ROADMAP.md) for the product boundary, end-to-end journey, P0/P1 decisions, stage summary and release milestones.

1. [Product Requirements](PRD.md): v1.4 purpose, scope, user journeys, UX, 36 v1 functional requirements, six post-v1 requirements and 12 nonfunctional requirements. Includes ownership decision tables, list lifecycle, ranking/series rules, settings precedence, in-flight changes, resolved P0/P1 decisions and an integrated list-to-library walkthrough.
2. [End-to-End Development Plan](IMPLEMENTATION-PLAN.md): S00–S10 stages, 61 work packages, dependencies, engineering boundaries, ownership and exit gates. Includes module handoffs, API delivery map and milestone demonstrations.
3. [Acceptance Plan](ACCEPTANCE-PLAN.md): requirement coverage, scenario matrix, fixtures, crash recovery, compatibility, stage-specific evidence scopes and full release evidence.
4. [Implementation Decisions](IMPLEMENTATION-DECISIONS.md): researched technical choices D01–D13 and primary-source evidence.
5. [Product Architecture](PRODUCT-ARCHITECTURE.md): system overview, integration responsibilities and code-reuse direction.

The PRD controls product behavior; the implementation decisions control the researched technical baseline; the development plan controls sequencing; the acceptance plan controls verification. User instructions take precedence over all documents. Update dependent documents together when a decision changes.

## Supporting research

- [Metadata and collections](research/metadata-and-collections.md)
- [Audiobookshelf import layouts](research/audiobookshelf-import-layout.md)
- [Initial discovery research](research/book-discovery-architecture.md) — historical; its earlier acquisition-manager recommendation is superseded.
- [Source snapshot](research/source-snapshot.json)

For a new checkout, begin with S00. For this existing implementation, use the plan's [execution and handoff contracts](IMPLEMENTATION-PLAN.md#8-execution-and-handoff-contracts) and verified status to continue incomplete work. The first full manual acquisition milestone is S05, list-driven automation is S07, and production v1 requires S09. S10 capabilities are separate later releases.
