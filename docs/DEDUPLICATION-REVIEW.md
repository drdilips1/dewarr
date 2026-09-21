# Deduplication and matching review

Reviewed 2026-09-20. Scope: source inspection, targeted automated tests, mocked browser flows, and a read-only query against the current local catalog. No catalog identities or files were merged during this review.

## Implementation follow-up

The main recommendations below are now implemented:

- **Consistent reader details:** `scope=display` returns the whole visible group's editions and sources, including origin work IDs. The default metadata/editor scope remains the permanent identity. Requests for a particular edition use its origin ID.
- **Explainable, durable decisions:** Library copies → “How these editions are grouped” explains the match. Administrators can keep a record separate, allow automatic grouping again, or confirm the same book through the existing revision-checked merge preview. Decisions are audited. Separation is deliberately per record, not a pairwise exception; undoing a merge also prevents immediate automatic regrouping.
- **Conflicting identities:** Different accepted Hardcover work IDs block automatic title grouping. An explicit reviewed merge can still establish equivalence.
- **Stable existing links:** Display-only grouping no longer redirects detail URLs. Confirmed permanent merges still redirect and preserve tab/filter/fragment state. The grid's representative may still change with holdings; existing origin bookmarks remain valid while visible.
- **Request clarity:** Preview identifies accessible sibling copies, links to their files, and says whether they meet edition requirements. These hints do not automatically fulfill requests. Owned editions offer “View library copies.”
- **Primary editions and freshness:** Administrators can choose/reset primary ebooks and recordings in Editions. The same selection drives narrator details and format-specific artwork. Present copies take precedence over stale inventory, inaccessible choices fall back, and each format has its own freshness status. Cover URLs change with the primary version so a selection refreshes an already-rendered image.
- **Normalization parity:** Python and PostgreSQL share Unicode compatibility normalization, curly-apostrophe handling, whitespace and author-set rules. Explicit script variants such as Simplified/Traditional Chinese remain distinct. Permanent import keys remain unchanged.
- **Scaling:** Provider evidence is aggregated once per root; listing filters reuse their display relation; reader visibility uses set membership instead of repeated correlated inventory checks. No cross-user ownership cache was introduced.

Validation: 244 backend regression tests passed before the two final primary-cover validation cases were added; the dedicated grouped-reader suite also checks those cases. Three browser flows exercise the combined UI, including the request hint, and the production build passes. All five original examples still return one group against the actual local catalog.

`scripts/benchmark_catalog_grouping.py` seeds only a database whose name ends in `_test` and rolls fixtures back. With fresh planner statistics and a non-admin reader granted two private libraries, three full-group count samples were **0.303–0.361 seconds at 10,000 records** and **3.236–3.580 seconds at 100,000 records**. This is query timing, not page latency or p95. The earlier un-analyzed bulk fixture timed out at 100,000; it is not a valid apples-to-apples speedup comparison.

Remaining deliberate limits: title-based grouping is still provisional; automatic reconciliation of duplicate Version IDs across sources still requires trustworthy edition evidence. Pairwise separation exceptions, persistent grid group IDs, and caching/index changes beyond the measured query improvements are future extensions. The original audit below is retained as rationale, not an assertion that every listed gap is still open.

## Current model

| Layer | Responsibility | Evidence / implementation |
| --- | --- | --- |
| Permanent work identity | Source bindings, reversible redirects, merge history | `domain/work_graph.py`, `domain/work_merges.py` |
| Display grouping | One visible book across owned formats and recordings, before pagination | `domain/catalog_display.py` |
| Edition / recording | Language, narrator, abridgment, publication year, ISBN/ASIN | `Version`, `domain/identity.py::resolve_abs_version` |
| Library copy | Actual accessible asset, files, state and library grant | `LibraryAsset`, `AssetContains` |
| Ownership projection | Combines formats and distinct version IDs within the reader's display group | `domain/availability.py` |
| Provider ownership hint | Accepted link first; otherwise unique normalized title/author and compatible language, without writing a binding | `domain/catalog_bindings.py` |
| Import matching | Exact edition evidence, conflicts and review; not display equivalence | `importing/matching.py` |
| Hardcover matching | Identifier or unique title/author evidence, fetched canonical details, language checks | `domain/hardcover_matching.py` |

Display grouping requires author evidence and at least one accessible owned format. It honors rejected work identities, ignores known trailing edition labels, compares author names independent of order, and keeps explicitly different languages apart. An unknown language cannot bridge two known languages. Short/full title matching requires a real short title and at most one distinct longer title, with exclusions for different content.

Mixed views request ebook artwork first, then fall back. Cover geometry is separately configurable. A version count is not a file count: multiple chapter files and duplicate copies with the same Version ID count once. Unknown-version assets count separately rather than asserting equivalence.

## Confirmed issues addressed in this pass

- **Order-dependent label removal:** stacked narrator, abridgment and marketing labels left residual text and split one book into multiple groups. Python and PostgreSQL now remove one shared repeated terminal pattern. Narrator extraction reads that terminal chain regardless of label order.
- **Overbroad short-title matching:** `Title: A Study Guide`, `Title: Dramatized Adaptation`, and `Title: The Graphic Novel` could collapse into the original. Shared subtitle guards prevent those title-only associations. Provider matching checks the candidate side as well as the local evidence.
- **Inconsistent author evidence:** duplicate and blank credits could produce different display/provider identities. Display SQL treats credits as a distinct nonempty set; provider fallback rejects blank-only credits and uses the same set semantics. Persistent import match keys are unchanged.
- **Lost navigation state:** redirecting an old edition URL to the displayed representative discarded the selected tab, format and fragment. These now survive the redirect.

Nine new regression cases were observed failing before the first fixes. Additional coverage exercises empty/repeated authors and alias navigation.

## Remaining priorities

### 1. Make the displayed book consistent across read surfaces

**High priority.** Library copies, cover ownership and format counts use `display_family` / `display_map`. Metadata sources and editions in `api/metadata.py::work_metadata` use permanent `family_ids`. The detail page redirects to the chosen display representative before reading that metadata. A provider source or edition attached only to a sibling can therefore disappear from the detail's editions or source selection while its library copy remains visible.

Introduce a dedicated reader projection that returns the displayed work plus all visible edition origins. Keep administrative metadata editing tied to an explicit origin so editing one record cannot accidentally modify another. Test a metadata-enriched audiobook grouped with a plain ebook, both URL directions, pagination and restricted library access.

### 2. Explain grouping and support persistent separation

**High priority.** Display grouping returns IDs, not evidence or confidence. It does not compare accepted provider work IDs when grouping roots with matching text. Two books with equal title/author/language can therefore be displayed together despite different accepted provider identities. Some distinct provider IDs are themselves duplicate records, so neither blindly merging nor blindly splitting is reliable.

Return a grouping reason (accepted identity, exact normalized title/authors, short/full subtitle) and conflicts. Add a durable “keep these separate” relationship and a reviewed “same book” relationship. Surface uncertain candidates for review. An undo of a permanent merge currently restores redirects, but text-based display grouping can still join the pair; an explicit separation must override both layers.

### 3. Separate stable navigation identity from cover preference

**High priority.** The display representative is chosen dynamically: owned ebook, then plain title, then creation time and ID. Adding/removing access to an ebook or changing inventory can change the representative. Existing IDs resolve while the group remains intact, but bookmarks can move and user-specific groups need not share one representative. Adding a third distinct subtitle can also dissolve a formerly unique short/full grouping.

Prefer a stable reviewed work identity for routes; select artwork and primary edition independently. For provisional display groups, preserve origin navigation and expose why membership changed. Test adding/removing holdings, grants, competing subtitles and restoring prior merges.

### 4. Reconcile requests with grouped ownership explicitly

**High priority, separate implementation.** `domain/acquisition.py::inventory_candidates` uses permanent `family_ids`. A green grouped audio badge does not prove the request evaluator sees that sibling recording. This can lead to a redundant request or confusing status when the requested format already exists under a display sibling.

Do not substitute fuzzy display grouping directly into automatic fulfillment. Show a possible existing-copy warning, allow selecting the actual version, and promote only reviewed identity evidence to permanent work equivalence. Preserve narrator, language, abridgment and format constraints when testing fulfillment.

### 5. Normalize names and languages consistently without losing distinctions

**Medium priority.** Display SQL lowercases and normalizes whitespace. Persistent identity uses Unicode NFKC/casefold; Hardcover author matching removes accents and punctuation. Curly apostrophes, initials and Unicode variants can consequently match in one subsystem and split in another. Provider ownership fallback uses exact normalized full title, while library grouping additionally accepts some short/full titles.

Create explicitly named work-level and edition-level normalization contracts, with Python/SQL parity fixtures. Keep original strings. Avoid broad punctuation deletion and fuzzy author overlap as automatic evidence. Current language grouping reduces regional tags to a primary language; assess script distinctions such as `zh-Hans` versus `zh-Hant` before generalizing this behavior.

### 6. Make version selection and availability more precise

**Medium priority.** The primary narrator comes from the first known-narrated version ordered by asset creation; the cover uses format preference and newest asset. They need not describe the same recording. A single group-level stale flag makes both formats appear last-known when only one copy is stale. Separate Version IDs may still represent duplicate editions from separate sources; the current count correctly avoids guessing, but can overstate distinct versions.

Add an explicit primary edition per format, prefer present copies, display version-specific narrator/language/year/abridgment, and expose freshness per format. Reconcile duplicate version IDs only with identifier and recording evidence. Test present/stale mixtures and the same ISBN/ASIN imported from two integrations.

### 7. Measure scaling before adding caching

**Medium priority.** Several endpoints independently rebuild the recursive canonical map, normalization and window partitions for listing, totals, availability and covers. Cover fallback also retries sources sequentially and sends `private, no-store`.

The current local read-only mapping took approximately **15 ms for 207 origin records / 182 display groups** in one run. This is a small-catalog observation, not an endpoint latency benchmark. Measure query plans and p95 latency at 10k/100k works, with a non-admin reader and multiple grants. Reuse relations within a query where possible. Any cache must include visibility scope and invalidation for inventory, grants, metadata and corrections; never share ownership projections across users.

## Validation

- All five reported examples still produce one display group in the actual local catalog: Salem's Lot, America Before, The Coddling of the American Mind, Christine, and Countdown to Zero Day.
- Targeted backend suite: 94 passing tests covering grouping, ownership, search, discovery, covers, Hardcover matching and import matching.
- Production frontend build passed.
- Browser checks cover alias redirects with tab/filter state, narrator display, extra-version links, edition-specific file dialogs, grouping and cover preferences. Browser data is mocked; the actual catalog check above is a separate read-only database check.

## Suggested implementation order

1. Reader-wide group projection and consistent editions/sources.
2. Explainable evidence plus persistent same-book / keep-separate decisions.
3. Stable routes and explicit primary edition selection.
4. Request-side existing-copy review using those durable decisions.
5. Normalization parity, per-format freshness, then measured performance work.
