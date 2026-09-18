# Prowlarr source integration

September 18, 2026 checkpoint. This implements a Prowlarr search and torrent-file path into the existing acquisition engine. It does not complete S06: native AudiobookBay, combined native/Prowlarr book-level aggregation, full ranking profiles and series acquisition remain pending.

## Connection and search

Administrators save the Prowlarr server URL, write-only API key, enabled state and optional excluded indexer IDs. Secrets use the existing authenticated encryption boundary. Changing the endpoint requires a replacement key; optimistic generation checks reject stale edits. Read-only testing calls the server status endpoint. Tracker proxy configuration remains in Prowlarr, while native MAM retains its own Gluetun/proxy settings.

`GET /api/sources/prowlarr/indexers` returns a sanitized capability view: indexer identity, definition, protocol, enabled/search/pagination flags and category IDs. It never forwards Prowlarr's provider configuration fields or tracker credentials. A definition identified as MyAnonamouse is excluded while the native MAM connection is enabled. Explicit exclusions and capability checks are enforced again on search and resolution, not only in the UI.

`POST /api/sources/prowlarr/search` queries one explicitly selected indexer, using ebook category 7020 and audiobook category 3030, with bounded offset/limit. The UI searches selected indexers sequentially under the shared connection budget, shows each source as it completes and retains successful results beside failed sources. Paging is offered only when the indexer supports it. The response does not claim a complete catalog or a reliable global result count.

Prowlarr's search controller can turn some upstream failures into an empty array. The page therefore exposes a warning and does not treat zero results as evidence that a book is unavailable. Cross-source identity/ranking and automated search retries are later work.

## Results, identity and private references

Each release retains its indexer, raw title, known medium from categories, size and seed count. Zero seeds differs from unknown seeds. Missing language, narrator and format remain unknown; an indexer language setting is not evidence of the language of each book. Existing request constraints still apply: a language/exact-narrator requirement cannot be satisfied by invented source facts.

The public source ID combines indexer ID with a digest of the opaque upstream GUID, because GUIDs themselves may contain private URLs. Identical titles on different indexers remain different release options. Tracker releases do not create catalog editions. Raw upstream GUIDs, download URLs, info URLs, API keys and proxy tokens are not returned to the browser.

The `source_results` table stores owner-scoped result snapshots and encrypted download references with a 25-minute expiry. Expired rows are deleted during subsequent searches; per-user retention is bounded. Expiry and owner checks prevent replay through another account or after the connection generation changes. These temporary rows are separate from durable inspected artifacts. Migration `0023_source_results` adds the table; its downgrade discards temporary observations, retaining the existing artifact and acquisition tables.

## Resolution and acquisition

`POST /api/sources/prowlarr/results/{id}/artifact` accepts a saved result UUID, never a browser-provided download URL. Only a reference from the configured Prowlarr origin and exact configured base path plus `/{indexerId}/download` is eligible. The client reconstructs that route, authenticates with the API-key header, and fetches a bounded torrent file. It does not follow redirects to magnets, trackers or other local services. Logs suppress private proxy requests. The API never calls Prowlarr's grab endpoint or asks Prowlarr to dispatch to a separate downloader.

The existing offline native torrent inspector validates content, file layout and v1/v2/hybrid identity. Original torrent bytes remain encrypted; the UI receives the safe descriptor. Repeated resolution deduplicates by owner, source identity, generation and artifact hash. The shared selection, request, reservation, qBittorrent attempt, connection-repair and importer services consume these artifacts. Their source locks now use the artifact's actual source key. No second dispatch/import pipeline was added.

NZB, direct links and magnet-only acquisition remain unsupported and labelled. A proxy URL may still redirect at resolution time; this becomes an actionable error without following it. Usenet support still requires a download-client adapter. This checkpoint does not change the default dispatch gate.

## Failure and concurrency behavior

- Short database transactions claim and finish a credential-wide lease; no network call holds the transaction open.
- HTTP, response-body and overall operation durations are bounded. There is no automatic torrent-file download retry.
- API-key read leases can recover after expiry; they do not inherit MAM's rotating-cookie recovery requirement.
- Persisted cooldowns survive configuration edits and process restarts. A late response cannot clear a newer lease or establish results under a new configuration.
- Current user access and source generation are rechecked before returning/saving results and artifacts. Viewer accounts can browse but cannot resolve acquisition artifacts.
- Successful source fetches do not establish work identity, file completeness or library ownership. ABS confirmation remains required.

## Verification and remaining evidence

Unit tests cover query/category contracts, indexer identity, known versus unknown fields, secret redaction, untrusted URLs, redirects, unsupported protocols, malformed responses and response-size limits. PostgreSQL/API tests cover private result storage, expiry, source generation changes, access revocation, native-MAM exclusion, pagination capabilities, cooldown persistence, active/expired leases, unsupported data and immutable artifacts. A synthetic Prowlarr result proceeds through the real acquisition services to a fixture qBittorrent client; worker replay submits once. Browser tests use real app API/database state with synthetic upstream HTTP services for configuration, partial results, unsupported NZB, mobile layout, inspection and reload.

The full backend regression passes 770 tests; the browser suite passes three journeys. The frontend build, formatting/lint, wheel module/migration inclusion, migration roundtrip and schema-drift checks pass. The development API reports ready on schema `0023_source_results`, with dispatch disabled.

These are contract and integration fixtures, not live Prowlarr/indexer/account certification. Existing ABS compatibility evidence remains separately scoped in [Implementation Status](IMPLEMENTATION-STATUS.md). Cross-source automatic ranking, additional source metadata, magnet acquisition and end-to-end live source-to-library certification remain pending.

## Primary interface references

The adapter is an original client of these interfaces; no Prowlarr implementation source is bundled or translated.

- [Search request fields](https://github.com/Prowlarr/Prowlarr/blob/develop/src/Prowlarr.Api.V1/Search/SearchResource.cs) and [search controller](https://github.com/Prowlarr/Prowlarr/blob/develop/src/Prowlarr.Api.V1/Search/SearchController.cs): explicit indexers/categories, pagination, proxied result references and empty-result limitations.
- [Release resource](https://github.com/Prowlarr/Prowlarr/blob/develop/src/Prowlarr.Api.V1/Search/ReleaseResource.cs) and [indexer resource](https://github.com/Prowlarr/Prowlarr/blob/develop/src/Prowlarr.Api.V1/Indexers/IndexerResource.cs): wire metadata and capability fields.
- [Download proxy reference](https://github.com/Prowlarr/Prowlarr/blob/develop/src/NzbDrone.Core/Download/DownloadMappingService.cs) and [download HTTP endpoint](https://github.com/Prowlarr/Prowlarr/blob/develop/src/Prowlarr.Api.V1/Indexers/NewznabController.cs): authenticated proxy shape, binary content and redirect behavior.

References were inspected on the checkpoint date; `develop` is mutable. Live version certification must record the installed version and exercised indexer capabilities.
