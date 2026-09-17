# Identity correction checkpoint

September 17, 2026. Implements reversible asset matches, catalog-source removal, changed-edition review and canonical work grouping/undo. Selective splitting of an originally conflated record and cross-provider edition equivalence remain required work.

## User behavior

Administrators can match or unmatch an ABS library item and undo the decision from its correction history. Matching replaces the item's verified work coverage using its current observed media evidence. Unmatching holds it for review. An indivisible collection must not be silently reduced to a single work; the UI identifies that coverage change before confirmation.

A catalog source can be unmatched from a book. Its catalog-only editions stop appearing unless another accepted source or an accessible library asset still references them. Protected app fields and library copies remain. An otherwise unsupported title/author label is retained for display as untrusted evidence, and automatic matching excludes that rejected identity until corrected.

When a provider changes edition/recording evidence, the user can keep and protect the current version or accept the changed evidence as a separate version. Existing library assets remain bound to their original version. The app does not rewrite audio metadata, rename files or infer that a replacement has been downloaded. Both decisions can be undone while their recorded state remains current.

## Transaction and history contract

`identity_changes` records a monotonic sequence, actor, affected entity/work, before/after snapshots and undo information. The associated audit event commits in the same database transaction. Read APIs expose safe summaries rather than raw snapshot data. Both commands and history require administrator access.

The UI supplies a revision hash of the evidence it reviewed. A stale edit returns a conflict. Undo checks the latest applicable decision and exact current state again under the domain lock; it cannot overwrite a subsequent decision, changed recording evidence, or later metadata edits. Repeated concurrent undo is idempotent. Inventory sync timestamps and harmless file moves alone do not invalidate a bibliographic correction.

Library correction locks follow the inventory integration → asset order. Catalog-source and version corrections lock their work. Provider attachment rechecks identity after obtaining that lock, including a catalog import that waited while the user changed a work's title. Reapplying an asset decision reuses the earlier recording only when the same asset, work and accepted recording evidence still agree.

Version records remain available for history. Current catalog views include only accepted catalog references or accessible library assets; retired orphan versions do not inflate the active catalog display. A manual recording lock remains effective during provider refresh.

## Migration and verification

Migration `0005_corrections` adds the journal and explicit edition-to-metadata-source association. It backfills legacy edition associations only where one same-provider source exists for that work. Ambiguous legacy associations remain unresolved until an explicit refresh/match establishes their source.

Downgrade refuses to discard an existing correction journal. Restore a pre-upgrade backup when the older schema cannot preserve the data. Empty-schema upgrade/downgrade and schema drift were verified; a dedicated migration test checks source backfill and the history-preservation refusal.

The integration corpus covers match/unmatch/undo, changed evidence, stale requests, concurrent undo, private history access, protected fields, source removal, changed-recording keep/separate/undo and an actual PostgreSQL lock-wait race. The browser journey exercises these controls at desktop and mobile sizes.

This does not complete FR-06 or AT-02. Selective splitting, reversible original source attachment, equivalence of pre-existing cross-provider versions, and future dispatched-download/import identity handling still need their own implementation and evidence.

## Canonical book grouping and undo

An administrator opens **Merge duplicate book**, chooses the main record, reviews the affected versions/copies and their own list memberships/requests, and confirms that both records describe the same book. The chosen main record keeps its metadata. Existing book URLs resolve to it. A stale preview or an attempt to merge a record into its own group returns a conflict. When a public and private record are combined, the public catalog record must be the main record; private source metadata is not silently promoted into its fields.

`Work.redirect_to` defines an acyclic canonical relationship. Origin records are retained: versions, provider namespaces, source attachments, library item/file IDs, asset coverage, list entries and historical request IDs are not rewritten or deleted. Canonical projections aggregate those bindings for catalog search, availability, versions, list display and requests. Two origin assertions about one canonical work count as one work when evaluating standalone/omnibus coverage. Different recordings remain distinct; grouping works does not establish version equivalence.

List display and counts collapse duplicate canonical memberships. Removing a displayed membership removes its origin memberships and withdraws only the corresponding list reasons. New local list entries and new requests bind to the selected canonical record. Historical equivalent intents can remain separate, sharing compatible planned reservations; this preserves their original meanings during undo.

Private library grants continue to filter ownership and assets. Metadata sources and catalog versions retain origin-level visibility checks. A public main record does not expose a private origin's sources or recordings to an ungranted user. A shared private canonical book can be discovered through an accessible origin, while its library-copy details remain individually scoped.

Merge and undo serialize under an exclusive graph advisory lock. Request/reservation mutations take the matching shared graph lock before the canonical work lock. List mutations retain list-row-first ordering; the merge never acquires a list row or edits its membership history. It rebuilds the affected **planned** reservations atomically, rechecking each owner's grants and requested version. This is not a contract for already dispatched transfers: S05 must extend the lifecycle before those can exist.

Undo restores the recorded canonical relationships and recomputes fulfillment, preserving later metadata and additions at their origin. Dependent later merges must be undone first. The journal records group topology rather than copying every related row, so routine inventory updates do not invalidate undo. A request created for the main record after the merge remains with that record after undo; a refreshed provider edition retains its provider-origin binding.

Migration `0007_work_merges` adds the journal kind, redirect index and self-redirect constraint. Downgrade refuses existing merge history or redirects because the older application cannot interpret their inventory/request semantics. Tests cover merge/undo, chained and concurrent opposite merges, concurrent request/worker execution, private grants, inherited source refresh, list cancellation, exact recordings, canonical omnibus counting and post-merge request provenance. The browser verifies preview/focus, merge, old-URL navigation, undo and mobile layout.

Future modules must resolve canonical identity for comparisons and fulfillment while retaining origin IDs for provenance. Direct equality of two stored `work_id` values is not proof that they describe different books. Full reference-dataset performance and real ABS integration remain separate gates.
