# Series continuation from library holdings

Discover includes **Continue your series**, a read-only shelf of published catalog gaps. It uses already loaded Hardcover series catalogs and the current user's accessible library holdings. It works without a live metadata connection and links into the existing book, series, list and request pages.

## Reader experience

The default **Books in either format** filter considers a work owned when a complete ebook or audiobook is confirmed. **Ebooks** and **Audiobooks** find gaps in that particular medium. An ebook-owned book can therefore appear as an audiobook gap while retaining its green In library indicator and Ebook badge. These are library holdings, never inferred reading/listening progress.

Four series appear per page, with up to three missing titles per series and a link to see the full series. The newest successfully observed catalogs appear first. Within each series, missing published books sort by numeric catalog position, then title and stable work ID; unknown positions come last. Fractional positions are retained. Duplicate/conflicting positions show **Order needs review**. A position does not assert main-series membership or authorize a series download.

Counts group canonical works. Compilations, partial books, upstream merged records and removed memberships are excluded. Known future publications and unknown publication dates are counted separately and excluded from published gaps. When multiple accepted origins map to one work, an observed past release establishes that the work has been published; the shelf does not claim that every edition is released. Separate version requirements remain in the request flow.

The shelf labels catalogs older than the existing 24-hour acquisition freshness window and stale library holdings. Stale holdings retain last-known ownership rather than inviting duplicate downloads. Refreshing the series or reconciling inventory repairs these observations through existing tools. A provider outage does not empty this local shelf.

When no eligible gaps exist, the empty state explains the scope and links to the catalog: open an owned book, follow its series link and load/refresh that series. This increment does **not** automatically discover every series in the library or fetch missing catalogs in the background.

## API and data boundaries

`GET /api/discovery/series` accepts `medium=any|ebook|audio`, `page=1..100` and `limit=1..12` (default 4). Authentication and ordinary no-store response headers apply. It creates no operations, acquisition intents, catalog entries or external requests.

Candidates must belong to an observed catalog owned by the current user and include at least one confirmed accessible normal work. The shared availability relation requires verified asset containment, complete content, present/stale assets, accessible libraries, enabled integrations and applicable library grants. Reviewed omnibus children use that same relation. Companion documents, unverified associations and missing files cannot seed ownership. Private metadata remains subject to the ordinary canonical-work visibility rules; even an administrator sees only their own series catalog observations here.

Selection filters eligible series before pagination, so fully owned series, unowned series and series with only unknown/future gaps cannot hide later useful results. Members and availability are hydrated in batches, not per card. Canonical aliases are grouped before counting or choosing the first three titles. The response's full-series counts and three-title preview are intentionally different.

The React query is independent of live provider shelves. It refreshes at one-minute intervals and on remount/focus, with zero stale time and no retained inactive shelf cache; changing the media filter resets pagination. An error hides old shelf cards and offers a retry. It does not represent failed data retrieval as a completed series.

## Verification and remaining scope

Integration coverage uses real PostgreSQL for medium filtering, canonical aliases, verified collection children, private catalogs, member/viewer grants and revocation, disabled/inaccessible sources, stale observations, ordering/publication uncertainty, pagination and read-only behavior. A 1,255-membership fixture checks that increasing the page from one to four series does not increase the number of database reads and returns at most three titles per series. This is a batching check, not certification of the full PRD performance dataset.

The browser journey connects empty shelf → owned book → real catalog-refresh worker → shelf → medium-specific owned badges → existing series curation → local list. It also checks the acquisition section, keyboard navigation, mobile overflow and error/retry behavior. Provider responses are synthetic; these tests do not establish actual Hardcover account compatibility.

No migration, dependency, service or secret is added. Rebuild the API contract/frontend and deploy matching API/worker code with the existing schema `0038_asset_containment`. Exact test results and deployment evidence belong in [Implementation Status](IMPLEMENTATION-STATUS.md).

This advances S08-01/FR-11 and its discovery acceptance scope. Whole-library series enrichment, complete curation/sharing, supported optional list write-back, usability and actual-service/performance qualification remain open. Earlier acquisition and production gates and S10 remain in scope; this increment does not complete S08 or the full PRD.
