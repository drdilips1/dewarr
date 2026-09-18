# Reviewed series requests

A series catalog can now produce a finite group of ordinary book requests. This implements the reviewed target-set boundary of S06-05c; automatic pack selection and shared-pack fulfillment remain separate work.

## User journey

Select up to 100 books on the Hardcover series page. Selection survives page navigation; the published-books shortcut retains earlier selections and excludes uncertain catalog entries. Choose requested media or inherit defaults, optionally adjust download preferences, then preview.

Selected books requests exactly those titles. Complete reviewed main-book set additionally requires the user to confirm that these are the main books they want to complete; each selected work must have published, non-partial, non-compilation, non-merged source evidence. This confirmation is recorded as user evidence, never as a claim that Hardcover supplied a definitive main-series classification. Duplicate positions stay visible with a warning. Unknown/future publication entries remain available for deliberate Selected books requests, not automatic main-set classification.

The preview lists selected and omitted works, publication/identity warnings, effective preferences, and per-medium available/missing/pending states. It preserves series ordering. The overall book ownership indicator is unchanged: an ebook still makes the work owned while an audiobook request may be missing.

Save series requests accepts this exact set and queues an atomic worker transaction. The worker uses the existing acquisition service, compatible reservations and frozen preferences. It creates independent series reasons, not a hidden local list and not a second downloader. The receipt identifies each resulting book request. Existing book pages provide source selection and the ordinary download/import lifecycle. Saving this batch alone does not start a download or implement Prefer packs.

Accepted sets do not grow when the provider adds a sequel or refreshes membership. Future monitoring requires a separate standing policy. Request history survives reload, and current target availability is projected from accessible inventory. Completed request creation is distinguished from actually acquired media.

## State and concurrency

Preview requires the currently displayed catalog generation. It stores the source timestamp/generation, exact canonical work identities, original membership evidence, chosen scope, user confirmation, resolved requirements and preference fingerprint. An unaccepted preview expires after 24 hours. Catalog, identity or effective-preference changes require a fresh preview.

Acceptance records a durable timestamp and queues work in the same transaction. After acceptance, catalog refresh and personal preference edits cannot reinterpret the saved set. The worker still checks current actor permissions, library access and work identities. Queue retries reuse child command keys. A failure after one child submission rolls back all requests and enqueues from that transaction; a later retry cannot duplicate committed work.

Child command locks precede parent/graph/work locks. All work locks use canonical UUID order. Network activity is absent from this transaction. Operation, receipt and request reasons commit together. A terminal/missing queue job becomes an actionable failed state when the saved request is opened; retry preserves accepted evidence and validates current authority.

## Reasons and cancellation

Each series operation has its own `series` acquisition reasons. Overlapping series requests, manual requests and list policies may share compatible intents/reservations while retaining independent reasons. Cancelling the series removes only its reasons. It does not delete files, erase receipts or cancel another reason's work. A queued cancellation prevents creation of children. Replaying a completed operation cannot reactivate a reason withdrawn from a book page.

The parent projection shows cancelled unsatisfied targets when its own reason is withdrawn, even if another reason remains active. Already-owned media stays available. The existing import-review authority check accepts a surviving series reason and rejects import after the final reason is withdrawn.

## API and migration

Routes are under `/api/catalog/series/hardcover/{external_id}/requests`: `POST /preview`, paginated `GET /`, and `GET /{operation_id}`, `POST /{operation_id}/submit`, `POST /{operation_id}/cancel`. Preview commands use idempotency keys; operation IDs make submit/cancel replay-safe. Server checks restrict catalogs and requests to their owner and enforce member permissions.

Migration `0034_series_requests` extends the acquisition-reason constraint. Back up before deploying the matching API and worker. Downgrade refuses to discard series operation/reason history; restore the pre-upgrade backup when rolling back to an older binary. Series request payloads and reasons require this binary even though no new table is added.

Remaining work: inherited Just book / Prefer packs / Complete series policy across manual and standing-list flows; automatic destination inheritance; bounded pack coverage selection; one transfer serving compatible child requests; actual per-child and omnibus import accounting; broader live-provider and release qualification. This checkpoint does not close S06, S07 or the full PRD.
