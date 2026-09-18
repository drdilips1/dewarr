# Series catalog and curation

The Hardcover series browser is the catalog foundation for S06-05. It lets a connected member follow a series link from a book's metadata, load its catalog, inspect individual books and add selected books to an existing editable list. The companion [Reviewed series requests](SERIES-REQUESTS.md) flow saves finite, reviewed book requests. Automatic pack selection and complete-series fulfillment remain pending.

## Observations and identities

`POST /api/catalog/series/hardcover/{external_id}/refresh` accepts an idempotency key and returns a durable operation. The worker reads at most 100 entries per keyset page and at most 1,000 memberships per observation, then verifies membership with a second uncached pass. Matching passes detect common pagination drift; they are not a transactional snapshot guarantee from Hardcover. Observations expire after 30 minutes. Transient provider errors have bounded retries; permanent errors preserve the previous catalog.

The account token stays encrypted in the catalog account. The operation records owner, account generation and endpoint, never the token. Each network request occurs outside database transactions. Lease and operation checks fence duplicate workers, replacement refreshes, account changes and permission revocation. The final catalog, membership mappings and operation completion commit together. An interruption never publishes a partial replacement.

Series identity is provider plus external ID within the observing account. Relationship IDs remain stable across refreshes. Removed relationships remain historical records; disappearance does not remove local lists, library files or requests. Existing accepted Hardcover bindings reuse canonical works; otherwise the observation creates a private provisional work. Manual identity corrections continue to resolve through the shared canonical graph.

Provider series data can contain duplicate positions, compilations, partial books and merged records. These remain visible. Decimal positions sort numerically; unknown positions sort after known positions. Publication state uses an explicit date; an unknown date stays unknown. No main-series classification is inferred from popularity, an integer position or Hardcover's featured-series flag.

## Browser behavior

The page shows the last verified timestamp, refresh status, raw entry count and distinct book count. Book totals exclude compilation, partial and merged-provider entries; they are not a claim of main-series completion. Ownership counts use distinct canonical works and the current user's accessible ABS inventory. An ebook establishes overall ownership independently of an audiobook requirement.

Individual rows retain warnings and separate ebook/audio availability. The Select published books action excludes ambiguous positions, compilations, partial/merged entries and unknown/future publication dates. Individual selection remains available for deliberate curation. Pages show up to 50 entries. Selection survives navigation and is bounded to 100 books across pages.

Before adding, the page shows whether the chosen list has active automatic acquisition. Additions use the existing idempotent list commands, in batches of at most five concurrent calls. Successful additions remain committed if another fails; failed selections remain for retry. The destination cannot be changed while that command is pending. A list's existing authorized acquisition policy applies to new memberships; no separate series downloader is created.

## Migration and recovery

Migration `0033_catalog_series` adds account-scoped `catalog_series` and `series_memberships`. Back up application state before upgrading and deploy the matching API and worker together. Downgrade refuses to discard populated series history; rollback requires a pre-upgrade backup. A refresh whose queue job has stopped is reported as interrupted; a new refresh supersedes it while retaining the previous complete catalog.

This feature does not alter download dispatch activation, rename existing files, reorganize imports, or claim ownership from a source result. Finite reviewed target sets now have bounded implementation evidence. Shared policy inheritance for Just book / Prefer packs / Complete series, shared-transfer selection and verified per-child fulfillment remain pending. Those gates remain in the implementation plan.
