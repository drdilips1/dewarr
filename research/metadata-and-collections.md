# Metadata, availability, and collection acquisition

Planning refinement, September 17, 2026. This document incorporates the user's requirements for straightforward defaults, optional customization, ownership across either medium, catalog-defined editions, and series-pack acquisition. It supplements the active [product architecture](../PRODUCT-ARCHITECTURE.md). These are design decisions and source-code observations, not results of running these applications.

## What the comparison supports

| Application | Observed approach | Design lesson |
|---|---|---|
| [BookOrbit preference resolver](https://github.com/bookorbit/bookorbit/blob/main/server/src/modules/metadata-preferences/metadata-preference-resolver.ts) | Field-level provider order and merge strategies, with library overrides | Keep this flexibility internally; ordinary setup should not require a matrix |
| [Audiobookshelf metadata documentation](https://github.com/audiobookshelf/audiobookshelf-docs/blob/master/docs/documentation/libraries/book-library/2.book-metadata.md) | Library default provider, alternative provider during matching, selectable fields for manual matching | Make the default useful and place correction at the affected book |
| [Shelfmark metadata provider interface](https://github.com/calibrain/shelfmark/blob/main/shelfmark/metadata_providers/__init__.py) and [configuration](https://github.com/calibrain/shelfmark/blob/main/docs/environment-variables.md) | Provider capability interface, selected metadata provider per search medium with fallback to the main configured provider | Separate capabilities from UI configuration; provider selection is not itself field aggregation |
| [Calibre identification pipeline](https://github.com/kovidgoyal/calibre/blob/master/src/calibre/ebooks/metadata/sources/identify.py) | Groups provider results and merges fields using rules including string length and rating averaging | Useful precedent for consolidation, but avoid those heuristics for recording identity or cross-provider ratings |

These patterns support a hybrid design; they do not establish a universally best aggregation algorithm. Calibre's ebook-oriented merge behavior is not a reliable recording model. Shelfmark's provider selection must not be misrepresented as a cross-provider consensus engine. Source licenses need separate consideration if code is incorporated; this comparison recommends behavior and boundaries, not unqualified copying.

## Defaults with optional depth

Normal setup asks for service connections and a small number of meaningful preferences. Provider tokens and destination paths are necessary setup; field-by-field metadata tuning is not.

Metadata settings initially show:

- **Metadata mode: Automatic (recommended).** Identity-aware enrichment using built-in rules.
- **Primary catalog: Hardcover.** An explicit connection is required. Without it, use the best supported configured fallback and clearly label the active catalog; do not imply Hardcover lists are connected.
- **Fill missing information: On.** Consult available fallback providers when the primary record lacks useful data or cannot resolve the identity. Match identity before merging.
- **Preferred language.** Choose once and inherit elsewhere.
- **Advanced provider preferences.** Optional ordering by data group (book details, covers, recording details), with field exceptions accessible only if needed and a reset-to-defaults action.

Ship coherent built-in metadata rules: primary provider owns normal work details; fallback fills gaps; matched recording owns narrator/duration/abridgment; release descriptions remain source-owned; manual edits are locked. Cross-provider identifiers and provenance are stored even though ordinary users do not configure them. Never merge conflicting editions solely because title and author match. Newly discovered providers must not silently replace manually selected authority.

Catalog search returns quickly from the primary source. Additional matches and detail enrichment can arrive asynchronously, with caching and provider rate-limit handling. Provider failure leaves known catalog data visible. Avoid querying every provider for every card. Prevent cover/text churn by using deterministic authority, not fastest response or longest description.

Normal book actions are “Fix match,” “Choose cover,” and “Edit details.” A collapsed “Metadata sources” panel explains provenance. A conflict queue is for materially uncertain identity, not for every differing genre or punctuation mark.

Normal list setup shows four choices: sync mode (browse/manual/automatic), media (ebook/audio/both/either), acquisition profile, and current entries versus future additions. It inherits everything else. Each override shows its effective value and origin, plus “Use default.” Advanced settings are optional and never a prerequisite for usable automation.

## Ownership, format requirements, and editions

Keep three independent questions:

1. **Do I have this book?** Yes when at least one confirmed library asset contains the work, in either medium.
2. **Which versions do I have?** Ebook edition(s) and audiobook recording(s), mapped through catalog identity and local evidence.
3. **What else did I ask the app to acquire?** A missing medium, a specific recording, or explicitly enabled upgrades.

An ebook asset must contain the actual work: a companion PDF or other supplementary material alone does not satisfy ebook ownership. The [ABS import contract](audiobookshelf-import-layout.md) defines per-version item folders, optional nested layouts, primary versus supplementary files and metadata export.

| Library state | Main card | Secondary information | Automation for “both” |
|---|---|---|---|
| Ebook only | In library ✓ | Ebook available; audio absent | May acquire audio |
| Audiobook only | In library ✓ | Audio available; ebook absent | May acquire ebook |
| Both | In library ✓ | Both media available | Satisfied |
| Recording A, catalog also knows B | In library ✓ | Other recording available | No automatic B unless requested |
| Same recording on four trackers | Same ownership state | Four download releases under Sources | No new edition and no duplicate request |
| Transfer complete, no confirmed library asset yet | Importing / awaiting scan | Pending import | Do not redispatch |

An “either format” policy is satisfied by either medium and selects one acquisition when both are missing. An “ebook,” “audio,” or “both” policy can deliberately acquire a missing medium while preserving the work's ownership check. Default upgrades off: a newly found EPUB or better-seeded release does not automatically replace an already-owned acceptable copy. A specifically requested recording remains a separate intent.

Edition/recording listings derive from Hardcover or other catalog providers and reconciled metadata, not torrent count or file extension. Source-only claims remain provisional until matched; they can still be displayed as release details and manually acquired. A format change does not by itself establish a new edition. Series membership also requires catalog evidence or a deliberate correction.

## Acquisition profile: simple choices, deterministic selection

Proposed initial profile for this user, editable rather than a universal quality claim:

| Setting | Starting value |
|---|---|
| Metadata | Automatic, Hardcover primary when connected |
| Ebook preference | EPUB, then other enabled formats; PDF lower for ordinary text books |
| Audiobook preference | M4B, then MP3; other supported formats available as fallbacks |
| Sources | MAM first, AudiobookBay next, configured Prowlarr indexers afterward |
| Series behavior | Prefer series packs |
| Selection | Balanced; optional “Most seeded,” “Preferred source,” or “Custom” |
| Existing copies | Keep; automatic upgrades off |

Formats use a draggable preference list, with “Allowed” versus “Blocked.” Sources use a simple preference list. Presets expose descriptions, not numeric weights. M4B is a container preference, not proof of superior audio quality; codec, bitrate/duration sanity, completeness and abridgment remain relevant. PDF may be the correct preferred format for illustrated/reference material through a profile override.

All presets first enforce identity, requested medium/language/recording constraints, allowed formats, completeness, exclusions and basic availability policy. Unknown evidence is distinct from failure; default automatic acquisition holds candidates with uncertain identity or unverified required coverage. A highly seeded wrong book can never win.

Balanced uses an explainable ordered comparison: requested series coverage when enabled → format preference → source preference → recent swarm health → source-local popularity as a tie-break. “Most seeded” promotes seeder count among otherwise eligible candidates; “Preferred source” promotes the configured source order. Each preset displays the actual order. Minimum availability requirements prevent a known unusable preferred source from indefinitely blocking usable fallbacks; absent seed data is unknown, not zero.

Seed counts are time-stamped and not guaranteed to exist for every adapter. Historical downloads/snatches or “popular” flags are different metrics from current seeders, and generally comparable only within their source. Book popularity from Hardcover is a discovery signal, not release quality. Missing data cannot be invented, and signals should be labelled with their origin. Ranking reasons should read “Selected: contains books 1–5, EPUB, preferred source, 42 reported seeders.”

Display sorting and auto-selection share these rules by default. Manual column sorting can temporarily inspect results without silently changing automation preferences.

## Series and collections are first-class acquisition units

Add explicit Series, SeriesMembership, ReleaseCoverage, and AssetContains relationships. Preserve series positions as provider-backed values, including decimals/novellas and alternative orders; do not assume every sequence is an integer. ReleaseCoverage records claimed, corroborated, and verified contents separately. One download job has many per-book import entries and can satisfy several existing intents.

Offer a single normal setting with three understandable modes:

| Mode | Behavior after requesting one book |
|---|---|
| Just this book | Seek this work; packs may be inspected manually |
| Prefer series packs | Search the book and its known series; prefer a qualifying pack containing it, import qualifying included series books; fall back to the single book |
| Complete the series | Expand to missing published main-series books and choose packs and/or individual releases to cover them |

For this user's starting profile, select **Prefer series packs**. This authorizes acquiring extra books from the same identified series when a qualifying pack is found. It does not authorize unrelated author libraries, spin-offs, every language, or every narrator. A search query alone never initiates downloading; a Download action or enabled automation invokes the profile. Manual requests display the expanded scope, and automated activity reports it without prompting on every job.

“Prefer series packs” changes candidate selection when there is an unmet acquisition target. If the requested book is already owned in the desired medium, ordinary list reconciliation does nothing. “Complete the series” is the explicit mode that expands even an owned book into missing-series targets. A deliberate “Get series” action provides the same choice from a book page.

Resolve main-series membership first. Search using series names/aliases and target title, then compare pack contents against known works and requested media. Rank a corroborated full pack above a partial pack containing the target, and partial above single when coverage is the selected priority and all requirements are met. “Complete” is relative to the catalog snapshot of released main-series works; a tracker label is not sufficient. Future installments require a separate “Monitor future books” option and are not implied by downloading today's complete pack.

A series preference is independent of media preference: an audiobook pack does not satisfy missing ebook targets. Edition/narrator constraints apply per covered work. A pack with mixed narrators may qualify for “any recording”; it cannot satisfy an exact narrator constraint for the wrong recording. Apply explicit size/book-count limits where configured and show a clear reason if a promising pack exceeds them. Do not require users to configure limits to use the default profile.

## Importing a collection and accounting for each book

Example: a five-book audio series pack contains books 1–5; book 2 already exists. Requesting book 3 under the series-pack profile creates one torrent job. The importer maps book folders/files to works and recordings, imports books 1, 3, 4 and 5 separately, retains the existing book 2, and confirms each new library asset through ABS. Downloading book 2 again as part of the indivisible transfer is possible, but need not create a duplicate library entry.

The importer performs:

1. Record expected coverage from source file lists/descriptions and catalog matches before dispatch when available. If metadata cannot support safe automation, keep the candidate available for review rather than asserting full coverage.
2. On completion, enumerate actual files; group by folder and embedded metadata, then corroborate title/author/series/recording identity. Cover images and companion PDFs are not automatically additional books.
3. Build a per-book manifest with source files, mapped work/edition, medium, destination and status. Skip already-satisfied imports; link each new book's files into its own ebook/audio destination when separable.
4. Recheck pending jobs/reservations atomically. A chosen pack reserves its identified covered targets so simultaneous list jobs do not download the same books separately. Release reservations for books that prove absent and resume their searches.
5. Trigger library scans and reconcile confirmations per book. One unresolved book does not invalidate successful imports of the others. Resume only incomplete manifest entries after failure.

Do not assume a collection is physically separable. An omnibus EPUB or continuous audio file may contain several works inside one asset. Represent verified constituent works as “In library — included in omnibus/collection,” with links to the actual ABS item, rather than inventing standalone files or ABS items. If contents are not confidently known, show the collection and unresolved membership; do not mark every claimed work owned. A profile explicitly requiring standalone copies can remain unsatisfied while ownership via the omnibus remains true.

Automatic splitting/conversion is a separate future capability requiring reliable boundaries. Hardlinks alone cannot split an EPUB or audio file. Archive extraction also creates new output: preserve the seeded archive, safely extract to managed staging, and hardlink extracted files where filesystem placement permits. Never mutate original or hardlinked seeded bytes.

## UX consequences

A normal card has an overall “In library” check and compact ebook/audio icons. Its detail page may say “1 ebook edition · 2 audiobook recordings”; Sources separately says “8 download releases.” These are different counts.

Series pages show availability per work, overall owned count and optional medium-specific completion. “3 of 5 books in library” counts works with either medium; “2 of 5 audiobooks” answers the separate format question. Novellas and side series remain visible without silently changing the main-series completion denominator.

A pack result says “Books 1–5 · 4 new · 1 already in library,” and expands into the mapped contents. Before download, unverified contents are labelled as source claims. After import, activity reports per-book outcomes. Preset selection explains why this pack beat a single-book release; routine operations require no metadata matrix, custom scoring formula, or per-book manual configuration.

## Acceptance scenarios for the eventual implementation

- An ebook-only work retains its ownership check while audio is wanted.
- A new catalog recording does not make an owned work missing.
- Multiple tracker releases of one recording do not increase the edition count.
- A preferred-format candidate beats a more-seeded candidate under the applicable profile, and reversing the preset predictably reverses that priority.
- A known unavailable preferred source falls through; unknown seed counts remain distinguishable.
- A five-book pack creates five coverage mappings, imports four missing books and preserves one existing asset.
- A falsely labelled complete pack confirms only books actually present; missing targets return to search.
- Concurrent single-book and collection requests share reservations and do not create redundant jobs.
- A continuous omnibus is tracked as one asset containing verified works, without fabricated separate imports.
- Fresh list polls do not repeat downloads, and changing metadata providers does not erase owned status or create new works for the same identified book.
- Switching format preference does not trigger upgrades unless explicitly enabled.
