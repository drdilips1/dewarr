# Manual selection of additional pack books

This increment connects explicit pack review to the existing shared-download and per-book importer. It complements [automatic Prefer-pack expansion](PACK-EXPANSION.md); it is not standing permission to acquire future books.

## User flow

1. Save a manual release selection for a wanted book. A multi-file selection exposes **Review additional pack books**.
2. The app intersects the user's current main-series review with catalog and torrent-manifest evidence. Only additional covered reviewed works appear. Without sufficient evidence, the panel explains what needs review and links to the known series where available.
3. Choose additional books in the selected medium and destination. Already-owned qualifying media are shown as satisfied; compatible pending requests are distinguished from missing books.
4. **Prepare selected pack books** atomically creates independent request reasons and manual selections. Compatible existing manual selections can be reused. A committed or incompatible pending selection is reported separately; an automatic selection is not adopted into the manual group.
5. Review the resulting shared-download scope, then start it explicitly. Preparation alone makes no downloader call. The existing shared transfer pipeline inspects actual files, imports qualifying children independently and waits for accessible Audiobookshelf inventory before showing ownership.

The selected root's ebook/audio medium is used for every additional child. Root-specific ebook/recording IDs are not copied onto unrelated books. Other request restrictions and the effective release profile remain binding. Each child receives its own source-candidate confirmation and actual-file verification; a tracker description does not establish a catalog recording.

## API and persisted contract

- `GET /api/acquisition/selections/{id}/pack-preview` returns state, explanation, medium, optional series link, additional works and a revision when ready. It does not create requests or selections. Private coverage evidence is not serialized.
- `POST /api/acquisition/selections/{id}/pack-selections` accepts the revision, 1–20 distinct covered work IDs and an idempotency key. It returns prepared selection IDs, per-work outcomes and a manual series-request receipt.
- The receipt uses `acquisition.pack-prepare`; the independent child reasons use an accepted manual `series.requests` parent. No automatic acquisition controller is started.
- Identical commands replay the saved receipt, including retries with a new outer key. Internal command identities include the complete batch fingerprint so different subsets of unchanged pending work do not collide.

Prepared children represent explicit manual consent. Cancelling the original root request later does not withdraw those independent reasons; the user can cancel the reviewed child batch through its series-request view. A surviving independent reason remains effective. Request cancellation does not remove torrent data or published files.

## Consistency and recovery

Preparation verifies current ownership, permissions, route configuration, profile, work identity, saved artifact bytes and frozen release/descriptor evidence. Material changes invalidate a preview. Already satisfied children are skipped without another request or selection. The root must still be wanted, active and manually prepared.

The transaction serializes commands and batches for the root, acquires child command locks before sorted canonical-work locks, then rechecks the preview. Series scope/catalog locks use the existing nonblocking planner. All child requests, selections and receipts commit together; a child failure rolls the batch back. No network submission occurs inside this transaction.

The browser preserves the idempotency key across an unchanged failed submission, changes it when the selection changes, disables an empty submission and offers explicit refresh. Successful preparation populates the existing shared-download control. Starting that download clears the preparation-only receipt.

The schema remains `0037_download_joins`; no migration or new job kind is introduced. Back up and restart API and worker together when deploying updated code. Installation dispatch remains separately controlled.

## Verification boundaries

Domain/API tests cover explicit member permission without automation permission, read-only review, atomic rollback, concurrent retries, same-command aliases, distinct pending subsets, stale scope/profile/ownership/artifact evidence, satisfied children and refusal to adopt automatic selections. Generated EPUB workflows exercise one shared transfer, separate hardlinked imports, unrequested extra files and immediate/delayed synthetic Audiobookshelf confirmation.

The browser contract uses deterministic pack-review responses over actual saved selections, then the real shared-download action. It exercises selection controls, failed submission retry, mobile layout and handoff. It does not independently certify tracker manifest matching; the domain and real-file tests cover that boundary. Exact commands/results are recorded in [Implementation Status](IMPLEMENTATION-STATUS.md).

This finite reviewed workflow does not complete generic author collections, large or unidentifiable manifests, per-child exact recording evidence, mixed destinations/media, omnibus containment, all manual source entry points or actual-service qualification. Those remain requirements in the existing PRD stages, not claims inferred from this increment.
