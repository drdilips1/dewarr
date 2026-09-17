# Identity correction checkpoint

September 17, 2026. Implements reversible asset matches, catalog-source removal and changed-edition review. Canonical work merge/split and cross-provider edition reconciliation remain required work.

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

This does not complete FR-06 or AT-02. Work merge/split, reversible original source attachment, equivalence of pre-existing cross-provider versions, and future acquisition/job rebinding need their own implementation and evidence.
