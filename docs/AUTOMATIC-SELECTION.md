# Automatic release preparation

September 18, 2026. Partial S06 delivery; complete list-driven acquisition remains pending.

## Experience

A saved wanted-media target links to the book's Sources tab. The Automatic release preparation panel uses the fetched page and its saved profile, a verified downloader and an authorized matching destination. A single ready route is selected by default; multiple choices remain explicit. Prepare best eligible release creates a durable operation, inspects a bounded number of torrent manifests and saves a selection through the existing acquisition service. The receipt and candidate reasons survive page reloads.

Preparing does not submit a download. Open prepared release shows the saved selection and the existing explicit Start download action when dispatch is enabled. That action uses the ordinary durable attempt ledger, association checks, monitoring and import path. Neither a successful preparation nor qBittorrent completion establishes library ownership.

## Eligibility and scope

Current automatic preparation requires a provider-anchored work or a corroborated private Hardcover/Goodreads catalog binding, matching title and author, the requested medium and language, required abridgment evidence, at least one reported seeder, acceptable formats and finite transfer size. Partial-content and collection evidence remains held for the later coverage implementation. Exact audio recordings require review because narrator names alone do not establish recording identity; exact ebook editions require corroborating ISBN evidence.

The actual torrent must have a supported import root, allowed files and one supported ebook or one recording's audio sequence. Alternative ebook files, mixed audio encodings, multiple book folders and ambiguous audio filenames require review. Audiobook PDF companions are allowed without becoming ebook ownership. Current supported primary extensions are EPUB/PDF/CBZ and M4B/MP3/FLAC/AAC/OGG/OPUS. Selecting an extension does not certify every codec or downstream layout; completed-file inspection still decides whether it can import.

Default size limits are 1 GiB for ebooks and 10 GiB for audiobooks unless the selected profile specifies another finite limit. The effective limit is frozen into the shared selection and import restrictions. Installation-wide capacity reservations and standing list policies are separate remaining work; this feature does not claim those limits are implemented.

The worker resolves at most five candidate artifacts from the fetched page. After inspecting a candidate, it ranks the actual primary-media formats against the remaining observations; already inspected eligible candidates can be reused without another fetch. At the inspection limit it chooses the best verified candidate, or holds if none qualify. The saved receipt identifies the selected candidate separately from other eligible inspected alternatives. Rejected manifests and permanent artifact/parser failures retain their reasons and allow another candidate. Temporary access/rate failures use bounded queue retries and respect cooldowns. Unknown/unsupported results do not become eligible merely because no better candidate exists.

## Persistence and authority

- POST `/api/acquisition/automatic-selections` accepts the intent, target slot, search, downloader generation and destination revision plus an idempotency key.
- GET `/api/acquisition/automatic-selections/latest/{intent_id}/{slot}` and GET `/{operation_id}` load private receipts. POST `/{operation_id}/cancel` stops uncompleted preparation.
- The operation and `acquisition.auto-select` queue job commit atomically. External artifact resolution runs outside the database transaction under a finite lease; redelivery waits for a current lease or reclaims an expired one.
- Cancellation, current account/permissions, request withdrawal, catalog/search identity, source generation, expiry, profile revision and route evidence are checked before creating the shared selection.
- The internal selection command has a stable key and uses the existing work reservation. Selection creation runs in a savepoint, so a failed route check cannot leave a partially prepared reservation.
- An already-satisfied target ends without a new selection. Exhausted queue work becomes a failed receipt with a fresh-selection action; a terminal operation never repeats its preparation.

The public release-selection schema cannot submit automatic evidence. The worker alone supplies its source/search/result lineage, inspected count, observed availability and effective limit to the shared selector. Receipts remain owner-scoped and revalidate request access.

## Qualification

Synthetic PostgreSQL/API and offline torrent tests cover eligibility, ranking, replay, bounded inspections, fallback, stale authority/configuration, cancellation, temporary cooldown and route rollback. Browser qualification uses the real app API/worker and synthetic external services, including a Hardcover-list title, preparation/reload, saved release, explicit dispatch and mobile layout. Actual tracker credentials and live transfer compatibility require their independent gates.

Still required for full S06/S07: ABB, magnet metadata resolution, complete collection/recording identity, broader multi-track layouts, Either-medium fallback, installation capacity scheduling and automatic list-to-dispatch orchestration. Current preparation is not a substitute for the PRD's complete unattended journey.
