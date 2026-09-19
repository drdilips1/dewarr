# Review source connections after restore

This increment implements existing-source configuration recovery within S09-02 / FR-03 / FR-16–FR-18 / FR-36 / AT-08, AT-25 and AT-27. The designated recovery operator can repair MAM, Prowlarr and AudiobookBay settings while ordinary work remains paused. It extends [library/downloader repair](RECOVERY-CONNECTIONS.md); metadata accounts and actual import-route qualification remain separate work.

## Operator workflow

1. Run fresh read-only checks and choose **Review status**. The observation reads saved source configuration without contacting trackers or consuming a MAM session.
2. Open the source settings. Review its endpoint and enabled state, the applicable proxy, Prowlarr indexer exclusions or AudiobookBay metadata downloader. Saved secrets are never returned.
3. Supply a current `mam_id` for an enabled restored MAM connection. An interrupted session, changed endpoint, changed proxy URL or changed proxy credentials also requires a current cookie. A session explicitly supplied during this recovery can be retained while its generation is current and no request was interrupted.
4. Preview public before/after settings and credential replacement/clearing. The preview sends no request to the proposed endpoint. Confirm this exact review to save it.
5. Enabled sources receive a separate durable connection test. The screen distinguishes **settings saved**, **verification queued/running**, **verified**, and **verification held**. Disabled sources are saved without a network call. Automation remains paused in every case.
6. If verification fails, the settings remain saved. Observe again, correct the source or wait for its cooldown, then confirm a new review. Successful verification does not certify release resolution, a metadata downloader, file paths, hardlinks or authority to resume acquisition.

Prowlarr endpoint changes require a fresh API key, including when disabled. Indexer proxy routing remains configured in Prowlarr. MAM/ABB proxy URL changes clear old proxy credentials unless a replacement pair is supplied. Clearing proxy credentials is explicit. Clearing them while disabling MAM needs no remote authentication, but invalidates retained-session authority for a later enable. Existing source cooldowns survive edits. Active request leases cannot be cleared by entering replacement credentials; wait for the current lease to expire.

## Why settings and verification are separate

MAM can rotate its cookie during a connection test, including a response that otherwise reports failure. Testing a proposed cookie and then rolling back local settings can lose the only current session. Instead, confirmation commits the reviewed settings and queues verification in one database transaction. Verification uses the native serialized source transport, which persists a returned cookie and cooldown before reporting failure or a revoked actor.

Verification has its own durable operation and lease. A live duplicate invocation cannot send a second request. A test interrupted after being claimed is held after lease expiry rather than replayed automatically. For MAM, an interrupted native request retains its session lease until explicit current-cookie repair. A remote response may be lost, so even an apparently harmless test needs this recovery boundary.

The native transport rechecks the current checkpoint, operator, source signature, reviewed parent and broader recovery context before network I/O. Completion checks them again, allowing the expected MAM cookie rotation while rejecting changed routing, credentials or authority. Returned cookies are preserved even when the final verification proof must be held. A verified finding requires the completed proof to match current source settings; a saved or connected status alone is insufficient.

## API, privacy and queue contract

The API adds POST `/api/recovery/source-reconciliations`, GET `/api/recovery/source-reconciliations/{id}` and POST `.../{id}/accept`. One source is reviewed at a time. The recovery summary exposes the latest source review and its separately typed verification result. These routes retain recovery-operator authorization, CSRF/origin validation, exact revision, expiry, current-observation checks and idempotency. Ordinary source/settings/search routes remain blocked during restore.

Prepared credential replacements are encrypted. Keyed digests distinguish different credential commands without persisting plaintext or unkeyed password hashes. Public views and audits contain only projected settings, replacement/clear indicators, source generation and verification state. Existing extra secret fields are preserved inside the encrypted configuration.

The recovery context now includes source configuration, so editing a source invalidates an older prepared recovery review. Settings confirmation advances the source generation. Another review or observation cannot run while the durable verification job remains queued or running. This does not refresh historical acquisition approvals or transfer associations.

The restricted worker registers `recovery.sources` and `recovery.source-test`, bringing its exact allowlist to eleven tasks without ordinary or periodic registrations. Deploy matching API and worker builds. Schema remains `0044_recovery_approvals`; no migration or runtime dependency is added.

## Qualification and remaining work

[Implementation status](IMPLEMENTATION-STATUS.md) records measured test evidence. Source HTTP fixtures test the native adapters with synthetic responses and credentials; the browser fixture is a disposable paused installation. Neither establishes current live tracker credentials, Gluetun deployment compatibility or a complete offline restore/resume rehearsal.

Metadata-account repair, current import destinations and actual file-route probes, unresolved external effects/reservations, fresh wanted-book activation and controlled resume remain required. Broader source/version/collection, list lifecycle, discovery, platform, accessibility and performance gates remain part of the full PRD. This increment does not close S09 or any other incomplete stage.
