# Discovery shelves and related books

**Discover** adds cover shelves above the existing catalog, list and request workflows. Monthly trending and recent publications come from Hardcover. Recently added catalog books remain available independently of that provider. Opening an unknown title shows the existing catalog preview; adding it opens the book page, where the reader can curate lists, inspect editions and request media. Browsing alone does not create catalog books, request reasons or downloads.

## Signals and ownership

- **Trending on Hardcover** preserves the order returned by `books_trending(duration: month)`. It displays no invented popularity or seed counts. Twenty identifiers are hydrated in one bounded book query; catalog editions are loaded only when the user opens a preview.
- **New releases** selects work publication dates from the preceding 90 days through today, ordered by release date and then stable book ID. These are catalog work dates, not claims about a particular ebook or recording release.
- **Related books** uses the matched Hardcover work's cached related identifiers. The reason is “Suggested by Hardcover”; the app does not pretend to know the provider's recommendation algorithm. When suggestions are unavailable or empty, visible local books sharing an exact author name provide an explicitly labeled fallback.
- **Recently added to your catalog** contains the most recent twenty accessible canonical catalog records. It is a local curation shelf, not a popularity ranking.

Provider shelves attach a local work only through accepted, visible Hardcover source identifiers. Title similarity does not establish a match. Ambiguous mappings stay unbound; merged mappings produce one local card. Protected local metadata is retained on matched cards. Every request projects current library availability through ordinary grants, even when the provider response comes from cache. Unknown matches are labeled **Library match not established** instead of being declared absent. Existing collection, ebook/audio and stale-inventory badges retain their normal meanings.

## Provider behavior and privacy

The adapter uses the existing per-account/generation catalog gateway and credential-wide rate budget. Provider responses are cached under that scope, ordinarily for one hour. Transient failures can reuse cached responses up to seven days old with a visible stale label. Authentication and permission failures do not activate that fallback. Malformed or provider-declared errors are not successful empty shelves. Connection changes during lookup reject the old response before projection.

Shelves load independently so a provider failure does not hide local books or another successful shelf. Browsing is bounded to twenty titles per page and twenty-five pages. Related suggestions and the local shelf are bounded to twenty titles. The local related fallback considers up to ten credited authors. Missing hydrated provider records produce an explicit warning. Private catalog sources, list titles and inaccessible library holdings cannot supply another reader's matches or recommendation candidates.

The published contract was inspected at Hardcover documentation revision `e8d38c8b7bd53cada7e97121ab0cacfa0804013c`: [`books_trending`, `TrendingDuration`, book release dates and cached similar IDs](https://github.com/hardcoverapp/hardcover-docs/blob/e8d38c8b7bd53cada7e97121ab0cacfa0804013c/schema.graphql). Synthetic contract tests validate parsing and query behavior; actual account/permission compatibility remains a separate gate.

## Deployment and remaining scope

No migration, new secret or additional service is required. Deploy the API with the matching frontend and restart the worker from the same build. The feature uses schema `0038_asset_containment`, existing metadata accounts, inventory grants and catalog APIs. It does not enable download dispatch or alter reading progress.

This advances S08-01 and FR-11 through provider discovery, explained related titles and usable local fallback, with a path into existing list curation. [Community-list discovery and following](COMMUNITY-LISTS.md) now connects Discover to private subscriptions and their existing automation controls. Series-continuation shelves, full sharing, optional supported write-back, broader recommendation providers, task-based usability and actual-service/performance qualification remain open. The existing series pages and list subscription tools remain available. These increments do not close S08 or the full PRD.
