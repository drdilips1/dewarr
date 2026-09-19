# Search and filter library copies

My Library presents observed backend copies, including separate ebook and audio representations and recordings. Its count is a count of copies, not canonical books. Book detail and Discover retain work-level ownership and version grouping.

## Finding a copy

Submit **Search your library** to search observed titles, author credits, narrator credits, and the titles/authors of matched canonical catalog books. The search is a case-insensitive literal substring: `%`, `_` and backslashes are literal text. Arbitrary descriptions and other provider payload fields are not searched. A corrected catalog title can find a copy whose original Audiobookshelf title differs; the copy still displays its observed title and author credits.

Combine the search with **Media**, **Library**, **Inventory state** and **Needs matching**. Filters apply in PostgreSQL before counting and pagination, across the entire accessible inventory. Search does not fetch catalog-provider data or modify matching. A library filter never grants access; inaccessible libraries and disabled integrations remain excluded, including from counts.

**Sort copies** defaults to title with a stable asset-ID tie-break. **Recently observed** sorts by the copy's initial observation time, then title and ID. Initial sync may bring old books into this ordering; repeated inventory checks do not make them new again. Null observed titles sort last within each date group or the title ordering.

Inventory-state filters describe the observed asset state. They do not establish full-book ownership: a present companion document or unresolved item can still appear here without satisfying a book request. Normal book badges and automation continue to use verified complete ownership. The existing Needs matching filter selects the backend's `needs-review` state.

## View state and failure handling

The selected query, filters, sort and offset live in the URL. Reload and browser Back/Forward restore the selected view; changing a filter or submitting a search returns to the first page. Reset library view clears all of them. Search input is submitted explicitly, so typing does not issue a request on every key.

An empty filtered result explains how to broaden the search, while an empty unfiltered inventory explains syncing. A now-empty later page retains Previous and Reset instead of stranding the user. The results count always describes the filtered accessible copies. Library errors hide old rows and correction controls and offer Retry; previously cached rows are not presented as a successful fresh inventory. The query refreshes every fifteen seconds and retains no inactive cache.

The book-page Library copies component keeps its work filter and ordinary paging. The shared rendering adds observed authors without changing match, collection, open-in-ABS or correction behavior.

## API and verification

`GET /api/library/assets` adds `q` (up to 300 characters), `medium=any|ebook|audio`, `state=any|present|stale|missing-suspected|missing-confirmed|scope-unavailable|moved`, and `sort=title|recent`. Existing work/library/review/offset/limit parameters retain their meaning. `AssetView` adds an `authors` array from observed inventory metadata. There is no database migration or new dependency.

PostgreSQL tests cover literal search, observed and corrected metadata, canonical links without duplicate copies, media/state/library/review combinations, counts and sorting before pagination, initial-observation ordering, member/viewer grants, inaccessible and disabled connections, revocation and invalid inputs. Existing Audiobookshelf, identity correction, collection and merge workflows are included in the affected regression. Browser tests cover actual fixture-backed results, URL reload/history, filters, empty pages, failure/retry, mobile layout and read-only browsing. Exact results are recorded in [Implementation status](IMPLEMENTATION-STATUS.md).

This advances the PRD My Library experience, S03-04/S08-04 usability and the internal alpha. Real-library setup, reference-load performance, broader version/collection qualification and complete stage acceptance remain open.
