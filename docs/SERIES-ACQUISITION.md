# Automatic acquisition of a reviewed series

The series page can acquire the missing media for an explicitly reviewed, finite set of books. This continues S06-05c–f using the existing source search, selection, shared-transfer and import services. The [list-derived series increment](LIST-SERIES.md) adds inherited Complete reviewed series for automatic list entries; manual single-book previews link to this series page.

## User flow

Select books in a verified Hardcover series catalog. Choose Selected books or Complete reviewed main-book set, requested media and download preferences. Enable **Automatically acquire missing books after review**, choose a tested downloader and an approved destination for each requested medium, then preview. A single eligible downloader or destination is selected automatically. Both and Either require routes for both media so an accepted fallback never invents a destination.

The preview shows the exact books, omitted titles, requested media, available holdings and effective preferences. **Start automatic series acquisition** accepts that snapshot. Saving ordinary series requests with the checkbox off retains the existing manual behavior.

Each accepted book displays its own acquisition message and next check. Already available media are skipped; compatible pending requests retain their transfer. Eligible releases use the ordinary ranking, capacity, downloader and importer. Compatible books can share a pack or reuse a qualifying saved transfer. Availability requires confirmed accessible Audiobookshelf items, not download completion.

History and progress survive reload. A held book can be retried while siblings continue; retry retains the accepted scope and existing progress. Changed route approval, settings or identity require a fresh review. Cancelling withdraws this series operation's reasons and prevents further effects under its authority; unrelated reasons, existing media and seeded downloads remain intact. A changed catalog never appends new books to the accepted set.

## Durable orchestration

`series.requests` saves its ordinary per-book request receipts and enqueues one `series.acquire` controller in the same database transaction. The controller's immutable scope fingerprint covers the accepted records, media specification, profile and route approvals. Its mutable progress records each book's source search, selection, retry timing and state. No new database table or second downloader is introduced.

The controller uses the same target advancement service as list automation. A per-book savepoint isolates expected authority/configuration failures and rolls back any queued work for that failed book. Other books keep progressing. Controllers take the identity graph lock and visit work IDs in deterministic order. The minute scheduler resumes due controllers; stopped jobs become held and expose a retry action. Recovery mode pauses scheduling and execution. Once all reviewed targets are confirmed available, the finite controller completes; it does not become a replacement or future-sequel monitor.

Every automatic selection carries a series proof naming both the accepted parent and controller. Selection, physical dispatch and import authority verify the original owner, current automation permission, active series reason, accepted work identity and unchanged profile/routes. Surviving manual or list reasons do not substitute for revoked series authorization. Shared transfers retain each child's separate proof.

The common route resolver validates downloader generation, path mapping, accessible target library, administrator import approval and actual route probe. List policy behavior uses this same resolver. [Route defaults](ROUTE-DEFAULTS.md) now add inherited downloader and per-medium destination references; accepted routes and approvals remain frozen.

## API and deployment

`POST /api/catalog/series/hardcover/{external_id}/requests/preview` accepts optional `automatic` settings: `downloader_id`, `downloader_generation`, and a per-medium `routes` map containing destination ID and revision. Omitting them preserves existing commands and replay behavior.

Series request responses add `automatic`, controller status/message, `can_retry_acquisition`, and per-book acquisition status/message/next check. `POST /{operation_id}/retry-acquisition` requeues the saved controller after current configuration checks; it never broadens the accepted book set. Submit, cancel and owner-scoped history retain their existing endpoints.

No migration beyond `0037_download_joins` is needed. Deploy API and worker from the same code revision because the worker must recognize `series.acquire`. Back up database and encryption keys before deployment. Older binaries do not understand these controller payloads; a downgrade requires a deliberate job/state recovery plan. This feature does not enable installation download dispatch by itself.

## Verification and remaining scope

The PostgreSQL integration tests cover preview without dispatch, idempotent controller creation, concurrent ticks, cancellation before dispatch and during artifact lookup, changed approval, revoked permission/reason/identity, independent child failure/retry, stopped-worker recovery and no expansion after catalog refresh. Real-file worker workflows acquire two ebooks from one pack, preserve original bytes/hardlinks and confirm both targets with immediate or delayed ABS responses. External source/downloader/ABS responses in those workflows are synthetic.

Exact integrated test and browser results are recorded in [Implementation status](IMPLEMENTATION-STATUS.md). These tests do not certify a live MAM account, every recording/edition combination, mixed-route transfers or a complete production release.

Inherited series scope and list-derived finite expansion are documented separately in [List series](LIST-SERIES.md). Remaining series work includes Prefer-pack incidental expansion, complete manual-surface integration, reviewed policy changes, broader recording/edition and omnibus fulfillment, and actual-service qualification. Native ABB, discovery and production stages remain part of the full PRD.
