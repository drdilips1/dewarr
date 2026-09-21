# Goodreads discovery, Choice Awards, and personal lists

September 20, 2026. Refines [the discovery proposal](discovery-curation-proposal.md) following the user's preference for a rich default public Goodreads catalog, full Choice Awards support, connected personal lists, and manual list tracking. Research and design only; no application implementation or live backend adapter validation has been performed.

## Product scope

The default app should offer useful public discovery before connecting a reading account. Connections add a personal layer. Discovery is composed of five views: For you, Browse, Collections, Awards, and Your lists. Add list is available from both the home and Your lists.

The home mixes popular public collections, award highlights, selected personal lists, Hardcover discovery when connected, and relevant local-library rows. Limit the number of visible rows, while retaining a broad collection catalog across fiction, fantasy, science fiction, romance, mystery/thriller, horror, historical fiction, nonfiction, history, biography/memoir, young adult, children/middle grade, classics, and other community-supported interests. Do not claim exhaustive genre coverage until actual definitions are verified.

## Research findings

The supplied link concatenated two URLs. Both intended pages were opened separately:

- [2025 Choice Awards overview](https://www.goodreads.com/choiceawards/best-books-2025).
- [2025 Fiction results](https://www.goodreads.com/choiceawards/readers-favorite-fiction-books-2025).

The overview exposes 15 categories and archive links for 2011–2024. Its 2025 rules describe 20 opening-round nominees and 10 final-round books per category. Fiction results expose a winner, an all-nominees section, and vote counts. However, the browser text extraction omitted most nominee titles; reading the page is not proof that the implementation can extract a complete identity-linked dataset. Validate the actual HTML adapter against title links and counts before shipping. [Overview and rules](https://www.goodreads.com/choiceawards/best-books-2025), [category results](https://www.goodreads.com/choiceawards/readers-favorite-fiction-books-2025).

The [2011 archive](https://www.goodreads.com/choiceawards/best-books-2011) has historical categories and three voting rounds with write-in nominations. Categories, round counts, and nomination rules must therefore be stored per year. Guessed `best-books-2009` and `best-books-2010` URLs returned 404 during research; locate authoritative alternate sources for those years instead of claiming their data has been imported. Only 2011, 2024, and 2025 overviews were sampled, not every linked archive.

The [Listopia fantasy index](https://www.goodreads.com/list/tag/fantasy) exposes public lists with book/voter counts and links to other genre tags. The [epic fantasy list](https://www.goodreads.com/list/show/50.The_Best_Epic_Fantasy_fiction_) exposes ranked entries with separate list scores, vote counts, and book ratings. It includes boxed sets and omnibus records alongside individual novels. Preserve entity type and canonical identity rather than silently substituting a series' first book.

The main Listopia landing page returned a JavaScript/browser challenge while those deeper pages were readable through the research browser. This is evidence of inconsistent access, not a supported Goodreads API. Before building a scheduled HTML integration, verify ordinary backend access, applicable source terms, and a maintainable extraction path. Do not bypass challenges. An unsuccessful fetch must preserve the last permitted, valid snapshot and report refresh failure, never create an empty replacement dataset.

## Choice Awards as a first-class destination

Landing page: choose year, browse category cards, or open all winners for that year. Category page: winner spotlight followed by nominee covers, with source credit and library availability. Offer Winners / All nominees, plus Finalists only where finalist membership is explicitly verified. Historical final vote totals alone must not be treated as evidence of an earlier round's membership.

Useful browsing routes include:

- A single year's winners across categories.
- All nominees in a year/category.
- Winners of one category across years.
- An awards book grid filtered by year, category, known ownership, and known reading status.
- A pinned row for a fixed award year/category.
- A rolling “Latest completed Fantasy awards” row, or a collection following future completed editions of that category.

Default to the latest **verified completed** edition, not the current calendar year. If an award is still running, label nominees and the current stage explicitly; do not show a provisional leader as a winner. Defer live voting-stage updates until finalized historical results work reliably.

“Full support” means an enumerated archive of all verifiable years/categories and their winners/nominees, with visible gaps. Loading just the recent winners is not completion. Establish a coverage inventory with expected categories, expected entries when published, observed entries, matched/unresolved identities, source URL, review time, and status. Do not invent missing historical records to satisfy completeness.

Suggested entities:

- `AwardProgram`: provider and program ID.
- `AwardEdition`: year, source, lifecycle stage, completeness, verified timestamp.
- `AwardCategoryEdition`: edition, original category label, source URL, normalized browsing tags, category-family mapping where appropriate.
- `AwardNomination`: category edition, original provider book ID, optional resolved work/recording, winner flag, verified round membership, optional source rank/votes, provenance.

Allow one book in multiple categories and years. The award label and normalized genre are distinct: “Debut Novel” describes eligibility, while “Audiobook” describes medium. Deduplicate works in aggregate grids but retain every nomination badge. Do not combine vote totals across years into an unsupported popularity score.

## Public Listopia collections

Use a community-reviewed index of source URLs and tags to seed reliable discovery. Collection cards show a cover mosaic, original short description, Goodreads attribution, observed book/voter counts, snapshot freshness, and Add to Discover. Source list order is the default; rating and list score remain separate data.

Start with a few useful lists per broad interest over successive catalog releases. Popularity can help identify candidates, but editorial review should check duplication, fit, oversized lists, and stale or misleading titles. A tag alone is not a guarantee that every book belongs to that genre.

Large lists need paginated collection views and bounded refresh jobs. Home previews can show 12–20 items. The persisted snapshot must separately state whether it covers the full list or a top-N window; displaying the top 100 is acceptable only when labeled that way. Do not create thousands of saved user works just to preview a public collection.

List changes can alter membership and order. A rank change or return to a top-N window is not automatically a newly published book or permission to download it. Track source entry identity separately from rank. Only a completed authoritative observation can establish removal; partial/error observations cannot.

## Personal lists and the manual Add list flow

Connecting Goodreads or Hardcover reveals the reader's discoverable lists under Your lists, with existing partial-discovery indicators retained. Preselect Want to Read where available, and let the reader pin additional shelves. Account discovery, tracking, and home placement remain distinct choices. This continues to respect private/account-scoped visibility.

Manual addition accepts supported URLs and local list creation:

| Input | Detected type | Result |
| --- | --- | --- |
| Goodreads `/list/show/{id}...` | Listopia list | Preview ranked public collection; offer pin and supported refresh |
| Goodreads shelf/My Books URL or RSS URL | Personal shelf | Existing account/shelf resolution and RSS tracking |
| Goodreads Choice category URL | Fixed award category/year | Preview nominees and winner; pin that collection |
| Goodreads Choice year overview | Award edition | Offer all winners or category selection, not an ambiguous list import |
| Supported Hardcover list URL | Hardcover list | Resolve through configured account and existing list integration |
| Local list | User-created collection | Select books or import supported CSV; no remote refresh toggle |

Paste URL → detect and validate → show title, source, covers, and coverage → choose Show on Discover and Keep updated → add. Default both on for a supported remote list when the user is explicitly adding it to display and track. Explain partial/snapshot-only support in the preview; never imply refresh exists when it does not. Download automation remains off and separate.

Canonicalize source identity so alternate slugs or repeated additions reuse the same collection. Reject malformed concatenated URLs with a useful correction prompt rather than guessing which of two collections to import. A fixed 2025 awards shelf remains fixed; following future awards is a separate explicit selection.

## Source adapters and distribution

Keep separate adapter contracts for `goodreads_shelf`, `goodreads_listopia`, and `goodreads_choice_awards`, plus existing Hardcover sources. They share normalized book projection, but differ in pagination, rank, completeness, removals, and refresh policy. Extend strict URL validation and existing bounded network behavior rather than turning RSS into an arbitrary page fetcher.

Suggested implementation files are `services/app/adapters/goodreads_listopia.py`, `services/app/adapters/goodreads_awards.py`, a shared collection resolver, and discovery collection/layout endpoints. These are proposed new files, not existing capabilities.

The GitHub index contains reviewed collection definitions, tags, and provenance. Award snapshots may be maintained as factual, source-linked records with original descriptions after confirming reuse requirements. Do not copy editorial blurbs or treat image URLs as a license to bundle images. Full Listopia dataset redistribution is a separate question from publishing a source-reference index.

Where permitted, ship verified archive snapshots so the home can work without a reading account or a live Goodreads request. Refresh historical finalized awards infrequently or through reviewed corrections. Refresh selected public lists periodically with bounded work, caching, and backoff. Unselected catalog entries should not cause every installation to crawl all of Goodreads. Snapshot distribution must not be presented as a live feed.

## Delivery and verification

1. Verify one complete recent award category, an older category with different structure, and a multi-page Listopia list using the actual backend adapter. Check pagination, stable IDs, rank/votes, blocked responses, and incomplete extraction. Confirm source access/reuse before selecting the distribution mechanism.
2. Add collection source types, snapshot coverage, pin/track preferences, and manual URL preview. Preserve existing personal shelf behavior.
3. Build the Awards destination and an explicit archive inventory. Backfill all verifiable historical year/category datasets; surface remaining gaps. Add source-linked category taxonomy mapping and work/recording resolution.
4. Ship a genre-spanning public-list index and the default Discover layout. Make personal rows appear from selected connected lists. Include no-account and provider-outage states.
5. Add rolling award-category subscriptions, archive corrections, catalog releases, and contribution workflows. Finalized archive completeness remains a tracked requirement until fulfilled.

Acceptance examples: pin 2025 Fiction nominees; view its winner; browse fiction winners across verified years; paste a Listopia URL twice without duplicate subscriptions; keep private shelves isolated; preserve boxed-set identity; survive a challenge page without losing saved contents; never label a top-N list complete; preserve fixed-year pins after a new award edition; follow future awards without enabling downloads; report all historical coverage gaps honestly.
