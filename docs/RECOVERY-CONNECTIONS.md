# Review library and downloader connections after restore

This increment implements repair of existing Audiobookshelf and qBittorrent connections within S09-02 / FR-03–FR-04 / FR-36 / AT-25 and AT-27. The designated recovery operator can review endpoints, replace credentials, enable or disable connections, and repair downloader path mappings while restored work remains paused.

## Operator workflow

1. Run fresh read-only checks and select **Review status**. Connection settings remain reviewable when an old endpoint is unavailable.
2. Open **Review settings** for the connection. Saved values are prefilled; saved credentials are never returned. Leave credential fields empty to retain them. Changing the server endpoint requires fresh credentials, including when saving a disabled connection.
3. Preview the exact public settings and whether credentials will be replaced. This step makes no request to the proposed server.
4. Confirm the review. Enabled connections must pass fresh read-only authentication/capability checks before any settings in the batch are saved. Disabled connections are recorded without contacting the server. A failed test or changed review context leaves the entire batch unchanged.
5. Run new observations. Changed ABS connections require current inventory reconciliation. Downloader mappings require file-route verification. A successful connection test does not establish current library ownership, hardlink compatibility or permission to resume downloads.

The UI reviews one connection at a time; the API accepts up to ten distinct connections atomically. An unchanged confirmation preserves the configuration generation. Real configuration or credential changes advance it. Other stored configuration fields are preserved. Changed ABS connections mark their saved libraries inaccessible until reconciled; library assets and grants are retained.

## Credentials and path authority

Replacement credentials are encrypted before a prepared review is stored. Public previews and audit details show only whether credentials are kept or replaced. A keyed digest distinguishes idempotent commands with different credentials without storing plaintext or an unkeyed password digest. Exact replay returns the same receipt rather than retesting or applying twice.

qBittorrent mappings select from the worker's deployment-configured source roots. Roots must not overlap, and a changed save path must lie within a mapped download root. A disabled connection can retain its unchanged routing when an old mount is unavailable, allowing the operator to disable it while repairing deployment configuration. This exception does not authorize new invalid paths or enable an unavailable route.

Connection tests use ABS authorization/library listing or qBittorrent login/version capabilities. They do not submit transfers, request library scans, publish files, rewrite torrent paths, change remote membership or activate saved commands. Previously frozen downloader selections and import plans retain their historical meaning and protection.

## Durable contract

The API provides POST `/api/recovery/connection-reconciliations`, GET `/api/recovery/connection-reconciliations/{id}` and POST `.../{id}/accept`. Preparation binds current findings, checkpoint, operator, connection configuration and deployment roots. Acceptance requires the exact revision, current observation, valid CSRF/origin and unexpired review. Current context is checked again after remote verification and before the atomic settings/audit transaction.

New requests cannot reuse a command key with changed credentials or settings. Another configured qBittorrent connection cannot occupy the same endpoint. A failed item rolls back all local changes. Queued secrets are encrypted; no credential-bearing draft is included in the API response. Sessions, request reasons, transfers, reservations and publication records are not reassigned or replayed.

This increment added `recovery.connections`; the current exact registry, including source verification, is documented in [source recovery](RECOVERY-SOURCES.md). It has no ordinary or periodic registrations. API and worker must be deployed together. Schema remains `0044_recovery_approvals`; no migration or runtime dependency is added.

## Qualification and remaining scope

See [implementation status](IMPLEMENTATION-STATUS.md) for measured verification and environment limits. The browser harness uses a synthetic paused state; actual offline restore, live services and release-platform compatibility require their own evidence.

[Source recovery](RECOVERY-SOURCES.md) now supplies MAM/session/proxy, Prowlarr and AudiobookBay settings review. Metadata-account settings, import-destination qualification, uncertain effects/reservations, fresh wanted-book activation and controlled resume remain required. This increment does not complete configuration recovery, S09 or the full PRD.
