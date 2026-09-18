# Automatic release selection and download

September 18, 2026. Partial S06 delivery; complete list-driven acquisition remains pending.

## Experience

A saved wanted-media target links to the book's Sources tab. The Automatic release preparation panel uses the fetched page and its saved profile, a verified downloader and an authorized matching destination. A single ready route is selected by default; multiple choices remain explicit. Prepare best eligible release creates a durable operation, inspects a bounded number of torrent manifests and saves a selection through the existing acquisition service. The receipt and candidate reasons survive page reloads.

Prepare best eligible release does not submit a download. Open prepared release shows the saved selection and the existing explicit Start download action when dispatch is enabled. Select and download automatically instead records explicit consent to select one eligible release and queue its download through the ordinary attempt ledger. It requires enabled dispatch and a currently approved automatic-import destination. Its receipt links to Activity and survives reload. Neither a successful selection nor qBittorrent completion establishes library ownership.

## Eligibility and scope

Current automatic preparation requires a provider-anchored work or a corroborated private Hardcover/Goodreads catalog binding, matching title and author, the requested medium and language, required abridgment evidence, at least one reported seeder, acceptable formats and finite transfer size. Partial-content and collection evidence remains held for the later coverage implementation. Exact audio recordings require review because narrator names alone do not establish recording identity; exact ebook editions require corroborating ISBN evidence.

The actual torrent must have a supported import root, allowed files and one supported ebook or one recording's audio sequence. Alternative ebook files, mixed audio encodings, multiple book folders and ambiguous audio filenames require review. Audiobook PDF companions are allowed without becoming ebook ownership. Current supported primary extensions are EPUB/PDF/CBZ and M4B/MP3/FLAC/AAC/OGG/OPUS. Selecting an extension does not certify every codec or downstream layout; completed-file inspection still decides whether it can import.

Automatic size ceilings are 1 GiB for ebooks and 10 GiB for audiobooks; a selected profile or participating request can lower these limits. [Request restrictions](ACQUISITION-FOUNDATION.md#request-download-restrictions) also preserve blocked formats from compatible shared requests. The whole torrent, including padding, must fit the effective limit, which is frozen into the shared selection and import restrictions. Automatic download currently requires EPUB, M4B or MP3 primary files, matching the qualified automatic-import formats. Other supported formats remain available for preparation and reviewed importing. [Shared transfer/storage limits](CAPACITY.md) apply to automatic attempts, including the rolling automatic-transfer budget. Standing list policies remain separate work.

The worker resolves at most five candidate artifacts from the fetched page. After inspecting a candidate, it ranks the actual primary-media formats against the remaining observations; already inspected eligible candidates can be reused without another fetch. At the inspection limit it chooses the best verified candidate, or holds if none qualify. The saved receipt identifies the selected candidate separately from other eligible inspected alternatives. Rejected manifests and permanent artifact/parser failures retain their reasons and allow another candidate. Temporary access/rate failures use bounded queue retries and respect cooldowns. Unknown/unsupported results do not become eligible merely because no better candidate exists.

## Persistence and authority

- POST `/api/acquisition/automatic-selections` accepts the intent, target slot, search, downloader generation and destination revision plus an idempotency key. Optional `download_when_ready` defaults to false; changing it on an existing command key is rejected. Earlier preparation-only receipts remain compatible.
- GET `/api/acquisition/automatic-selections/latest/{intent_id}/{slot}` and GET `/{operation_id}` load private receipts. POST `/{operation_id}/cancel` stops uncompleted preparation.
- The operation and `acquisition.auto-select` queue job commit atomically. External artifact resolution runs outside the database transaction under a finite lease; redelivery waits for a current lease or reclaims an expired one.
- Cancellation, current account/permissions, request withdrawal, catalog/search identity, source generation, expiry, profile revision and route evidence are checked before creating the shared selection.
- Internal selection and dispatch commands have stable keys and use the existing work reservation. Selection, automatic attempt, identity/capacity claims and download-job creation share a savepoint and commit together. Failed dispatch cannot leave an orphan selected release; queue outages roll back the final transaction and allow lease-based recovery.
- An already-satisfied target ends without a new selection. Exhausted queue work becomes a failed receipt with a fresh-selection action; a terminal operation never repeats its preparation.

The public release-selection schema cannot submit automatic evidence. The worker alone supplies its source/search/result lineage, inspected count, observed availability and effective limit to the shared selector. Receipts remain owner-scoped and revalidate request access.

Automatic consent freezes the administrator's import-policy identity/generation, approver and destination revision. Selection and every pre-submission authority check revalidate that approval, requester access, original catalog identity and saved profile. Approver/requester locks precede acquisition locks. Disabling or replacing an approval before dispatch holds the attempt without submitting. Once a transfer may exist, observation continues through the ordinary reconciliation path. A changed approval cannot silently authorize import under a replacement policy: completed files reach scoped reviewed importing. Revocation of requester access still blocks publication.

Cancel release preparation applies before the atomic handoff. After a download is queued, Activity owns cancellation before submission and transfer inspection. Already-submitted torrents continue to follow the existing non-destructive cancellation rules.

## Qualification

Synthetic PostgreSQL/API and offline torrent tests cover eligibility, ranking, replay, bounded inspections, fallback, stale authority/configuration, cancellation, temporary cooldown, approval changes and atomic dispatch rollback. Real EPUB/audio fixtures exercise source search, native torrent inspection, automatic member-owned submission, hardlink publication, delayed ABS confirmation and replay through actual workers with synthetic external services. Browser qualification includes preparation-only and automatic-dispatch actions, approved routes, persistent receipts and mobile layout. Actual tracker credentials and live transfer compatibility require their independent gates.

Still required for full S06/S07: ABB, magnet metadata resolution, complete collection/recording identity, broader multi-track layouts, Either-medium fallback, fair standing-policy scheduling and automatic list-to-dispatch orchestration. The current explicit per-title action starts from a saved wanted target and fetched search page; it does not yet schedule search or activate a followed list. It is a shared handoff for that forthcoming orchestration, not completion of the PRD's unattended list journey.
