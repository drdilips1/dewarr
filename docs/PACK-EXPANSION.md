# Additional books from a preferred pack

This increment implements the automatic Prefer packs path within SC-04 / S06-05. It builds on [main-book reviews](SERIES-SCOPE-REVIEW.md), [list-derived series](LIST-SERIES.md), [automatic pack grouping](AUTOMATIC-PACK-GROUPS.md) and [saved-transfer reuse](DOWNLOAD-REUSE.md). Exact verification is recorded in [Implementation Status](IMPLEMENTATION-STATUS.md). It does not close the complete series, version or production gates.

## User behavior

When automatic acquisition chooses a qualifying series torrent for a missing book, Prefer packs can also acquire additional reviewed main books actually covered by that torrent. The accepted scope is the intersection of the saved finite main-book review and corroborated selected-pack contents, excluding the original book. A later sequel or metadata refresh cannot enlarge it.

The extra requests use the selected medium and approved destination. An ebook pack does not trigger audiobook requests for its other books. Hard language, narrator and download restrictions remain in force; an exact version identifier belonging to the original book is not applied to a different book. Each child checks accessible library inventory and compatible pending work independently. Already available children are recorded as satisfied and skipped.

The automatic selection receipt explains whether extra books were accepted, no extra reviewed books were covered, or main-book evidence needs review. Accepted scope links to the existing series request page, where each child's availability, pending work, errors and retry actions remain visible. The page explicitly identifies a request restricted to its original pack. A green ownership indicator still requires backend-confirmed library coverage.

A generic pack-level narrator, edition or abridgment claim does not establish each child’s recording. The current automatic eligibility guard holds requests with those hard constraints for separate per-book evidence. Unconstrained audiobook packs and ebook packs use the automatic path; complete recording/edition qualification remains required by the PRD.

Missing, busy or ambiguous main-book evidence does not block the original single-book acquisition; the receipt explains why additional books were not accepted. Saving or withdrawing a reusable review is separate from accepting or cancelling acquisition. Withdrawing that review after acceptance does not cancel the frozen request. Preparation-only actions do not create extra-book requests. The account must have automation permission for incidental expansion; otherwise the root continues and the receipt explains the limitation.

## Execution and source evidence

`pack_expansion.create` saves one idempotent accepted `series.requests` parent, with the original automatic operation, selection, intent, source identity/generation, artifact ID and checksum. The existing finite-series controller supplies child reasons and progress; it uses the normal selection, reservation, membership and import services.

Child selection uses a request-bound completed source operation containing only the saved artifact's release evidence. It is labelled as saved evidence and retains the original release observation time. This performs no new tracker query or torrent fetch. Ordinary eligibility, source-generation/access checks and per-child catalog/manifest assessment still run. A fresh local command expiry does not claim that tracker availability or seeder counts were refreshed.

Children are pinned to the original source and artifact. A different release cannot win by having more seeds or a preferred format. The child cannot replace a missing pack member with a separate torrent under this authority. Complete series is the separate policy for acquiring individual releases when necessary. Existing shared-transfer grouping or authorized saved-transfer joins yield one physical download, and import continuation leaves earlier receipts and successful siblings intact.

Actual downloaded files remain the final coverage evidence. Each confirmed child receives its own fulfillment record. The root selection becoming `fulfilled` is successful completion, not withdrawn consent for the remaining accepted children.

## Authority, concurrency and recovery

List-triggered roots also carry the original policy generation, membership episode and configuration proof. Removal/re-addition cannot revive an old origin. An unrelated surviving request reason cannot authorize publication for a withdrawn derived selection. Pausing a list stops new dispatch through that policy while preserving the lifecycle of already-submitted work. Root or child cancellation retains original seeded files and already-published items.

Dispatch and transfer joins acquire all participating canonical work locks in sorted order, including the root work of an incidental child even if the root is absent from the join. Do not take a root selection row lock before those work locks: root fulfillment updates the selection while holding its work lock, which would invert the order. Publication holds root/child reason rows through its authority guard, before backend/library locks. Controllers may persist intermediate intent state, but side-effect boundaries revalidate the origin under their appropriate locks.

Retries reuse the durable parent, target memberships and source artifact. Failed or uncertain children remain separately recoverable. No new job kind or schema migration is introduced. Current schema remains `0037_download_joins`.

## Remaining qualification

The explicit manual path now has a separate [pack preparation contract](MANUAL-PACKS.md): review covered children, prepare their independent requests and selections, then use the existing shared-download action. Its evidence does not expand the automatic authority described above.

This automatic-path increment does not establish all manual release-selection surfaces, mixed-route/media or cross-owner transfer reuse, full recording/edition equivalence, inseparable omnibus fulfillment, or actual tracker/account/filesystem compatibility. Those remain in the existing S04–S09 acceptance gates. Production support must use recorded service and filesystem evidence; synthetic integration results alone do not establish it.
