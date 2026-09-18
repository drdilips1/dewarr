# Inherited series scope and automatic lists

Automatic lists can acquire a finite reviewed series when one of its books is added. This extends the existing [series controller](SERIES-ACQUISITION.md), [main-book review](SERIES-SCOPE-REVIEW.md) and [list policy](LIST-POLICIES.md) contracts. It uses the shared request, source selection, transfer and importer pipeline.

## User behavior

**Series scope** offers Just this book, Prefer series packs and Complete reviewed series. It inherits through installation, personal, profile, list and request settings. Prefer packs remains the built-in default. Just this book rejects broader packs in automatic selection. Complete reviewed series allows a standing automatic list to request the eligible books in one saved main-book set.

Save the main-book review on the series page, then choose Complete reviewed series in an automatic list's preferences. A selected backlog entry previews the exact reviewed books. Activation freezes that selected scope; later review withdrawal does not cancel an already accepted backlog request. A future list addition resolves its scope when the worker first processes that membership episode. Missing, stale or ambiguous evidence holds that entry with a review link and scheduled recheck; unrelated entries continue. Saving usable evidence allows the held entry to proceed without another per-title approval.

The current resolver supports one unambiguous owner-reviewed Hardcover series containing the root book, with at most 21 books. Catalog positions and tracker titles do not establish main membership. If no catalog series membership is known, the preview explicitly reports a single-book scope, which remains fixed for that episode. It does not silently expand after later metadata arrives. Multiple matching reviewed series require an explicit series selection.

An ebook-owned root still shows the overall library check. Complete series evaluates each child's requested medium independently, so a Both policy can still want audio. Already satisfied targets and compatible pending requests use existing acquisition rules. The list monitor links to the frozen series request, whose page identifies the originating list and shows per-child progress. A later missing library item becomes an actionable hold; completing the finite series does not create an automatic replacement policy.

Manual Complete-series requests use the existing reviewed series page. The single-book request preview provides that link and prevents saving only the root under a misleading Complete-series label. Prefer packs currently imports independently requested children; automatic expansion to additional unrequested pack children is a separate, unfinished PRD requirement.

## Authority and recovery

A list-derived parent stores the originating policy/list/book IDs, policy generation, membership activation episode, root request ID and configuration fingerprint. The scope fingerprint includes this origin, and every automatic child selection carries it. Current list authority is checked before child creation, selection and dispatch through the series-authority contract. Before each new file publication, the importer also checks the saved list episode and the specific series reason; a generic surviving manual reason cannot substitute for the revoked origin.

A pause prevents new dispatch under that reason without changing seeded files or completed imports. An already-submitted transfer can finish importing while paused; permanent membership withdrawal or cancellation blocks new publication under that old origin. Compatible explicit list resume can restart a parent/controller held by the upstream pause while keeping the same accepted scope. Arbitrary identity, route or child failures retain their own review path. Removal, exclusion, changed generation or a new membership episode invalidates the old derived authority. An independent manual reason cannot authorize an automatic action whose list reason was withdrawn. Acquisition reconciliation retires the permanently withdrawn derived reasons while preserving other reasons.

Re-adding the root creates a new membership episode and finite parent. Existing qualifying inventory and compatible work can be reused, but the old parent cannot become authorized again merely because the same title returned. Review changes never append books to a previously accepted set. List policy revisions and account/route changes remain subject to the ordinary policy checks.

Lock order acquires upstream list authority before series parents/controllers and principal/work locks. Grouped transfer dispatch collects all direct and derived list authorities in stable order before locking series operations. The publication guard retains shared locks on the originating root and child reasons through publication, so concurrent cancellation cannot slip between the final authority check and file publication. Planning that already holds list/identity locks uses nonblocking series-scope/catalog advisory locks: a concurrent catalog publication yields a scheduled retry instead of an inverse lock wait.

## Compatibility and API

The optional `series_scope` preference is stored in existing JSON snapshots. Old snapshots omit it and retain the meaning of `prefer_series_packs`. A higher-layer legacy boolean overrides a lower-layer enum; an explicit null enum clears it and uses the resolved legacy value. Empty overrides inherit as before. Existing saved fingerprints are not rewritten.

List activation records expose `series_scope` with its status, message and reviewed books. Monitored-book responses add `series_request_id`, `series_external_id` and `series_scope_issue`. Series request responses add `originating_list_id`; private authority proof remains internal. Existing authorization and owner-scoped endpoints still apply.

No migration beyond `0037_download_joins` is required. Deploy API and worker together; older workers do not enforce the new origin payload. Back up state and keys before updating. This feature does not turn on installation download dispatch.

## Evidence and remaining work

Targeted PostgreSQL cases cover finite creation/replay, accepted backlog scope, invalidated unaccepted preview, pause before and after child creation, removal/re-addition, independently surviving manual reasons, unavailable review/recovery, busy catalog publication and the manual single-root guard. Real generated EPUB workflows add a root to an automatic list, acquire one two-book torrent, preserve source bytes, hardlink both children and confirm them through immediate or delayed synthetic ABS inventory. Repeated monitoring remains available without another submission. Real-file mutation cases remove or pause the root after download and before publication: removal holds both children even with surviving manual reasons, while pause preserves the submitted lifecycle. A separate PostgreSQL lock-timeout case verifies both root and child cancellation are fenced during the guard.

Exact full-suite and browser checkpoint results belong in [Implementation status](IMPLEMENTATION-STATUS.md). Synthetic external-service responses do not certify live MAM/Hardcover/Goodreads behavior. Remaining work includes Prefer-pack incidental expansion, complete manual-surface integration, broader exact-recording/edition/omnibus handling, reviewed policy revisions, cross-owner/mixed-route reuse, full concurrency/actual-service qualification, discovery and production gates. This increment does not complete S06 or S07.
