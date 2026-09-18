# Native MAM search integration

The Sources page now provides native MAM search and release detail. Catalog book pages link to a title-prefilled source search. Administrators configure the installation's shared MAM connection; authenticated readers can search without access to its credentials. Members can also [inspect and privately save a torrent manifest](SOURCE-ARTIFACTS.md). Download dispatch, acquisition ranking and source-to-catalog mapping remain unfinished.

## Search and source evidence

Search supports ebooks, audiobooks or both; title/author/series fields; optional narrator search; language IDs; source relevance or seeder ordering; and paginated results. The API additionally accepts description, tag and filename search fields. English is the shipped language default; an empty language list means all languages. Queries retain the supplied text rather than silently replacing a precise source query with a catalog match.

Results preserve the original title and a clean display title, credited authors/narrators, source series IDs and positions, category, tags, language, file type, displayed size, normalized size when possible, seeds, leechers, snatches, source date, flags, ISBN, description and media information. Source-series claims do not establish verified pack coverage. Multiple releases do not create catalog versions. Missing fields remain unknown; a rounded tracker size is marked as an estimate in the normalized details.

Source descriptions become plain text. The UI never renders tracker HTML, executes embedded scripts or requests arbitrary tracker images. Credential-bearing `dl` values and complete raw account responses are not returned to the browser. A release detail lookup verifies that the returned release ID is the one requested. An empty result is accepted only from a valid empty page or the explicitly recognized empty-result response; login/error/malformed pages remain failures. Malformed individual results produce a partial-page warning, and an entirely undecodable page is an error.

Request fields and response shapes were checked against [MouseSearch at b42b0b9](https://github.com/sevenlayercookie/MouseSearch/blob/b42b0b98d1b81145f6bc6410407d03ae48fb100e/app.py) and the [MAM MCP API reference at 551d71a](https://github.com/sandymac/myanonamouse-mcp/blob/551d71a8725003aa7ab844d1cfd9ae1566ddd389/src/mam/api.rs). These are source-code references, not a live account compatibility certificate. Bounded request-field adaptations retain their notices in the [reuse ledger](REUSE-LEDGER.md).

## Connection and routing

The administrator supplies the MAM endpoint and `mam_id`, optionally a Gluetun HTTP proxy URL and proxy authentication. Credentials are encrypted with the installation key, accepted as write-only values and omitted from connection responses, audit details and validation errors. Existing saved secrets can be retained without sending them back to the browser. Changing the MAM endpoint requires an explicit cookie; changing the proxy endpoint clears its old authentication unless replacement credentials are provided.

A configured proxy is always required: route failure never falls back to direct access. Without a configured proxy, MAM uses the explicit direct route. Environment proxies are ignored and redirects are not followed. Proxying source HTTP does not alter qBittorrent's torrent network configuration. HTTP(S) proxy origins are supported; SOCKS proxy support is not advertised. [HTTPX proxy configuration](https://www.python-httpx.org/advanced/proxies/).

Requests have a 40-second total timeout and an 8 MiB decoded response budget. One native MAM connection is supported per installation. PostgreSQL serializes its session-sensitive calls across processes using a committed lease, with no transaction retained over HTTP. Concurrent calls receive an explicit short retry response. A two-second minimum request interval is an application default, not an assertion of MAM's allowed quota. Source `Retry-After` and supported rate headers extend a persisted cooldown; settings edits and worker restarts do not erase it.

The rotated named cookie from an applicable response is encrypted before the lease is released. A newer explicit credential cannot be overwritten by an older request. Disabling the connection suppresses in-flight results while preserving a rotation of the same unchanged session and route. Reader revocation suppresses results without discarding the installation's rotated session. A cancelled/crashed request leaves its lease fenced: after expiry, the administrator must supply a current cookie because the missing response may have contained a rotation. There is no blind concurrent takeover with an unverified old session.

## API and persistence

| Endpoint | Access and behavior |
|---|---|
| `GET /api/sources/mam/connection` | Administrator; redacted configuration and health |
| `PUT /api/sources/mam/connection` | Administrator; generation-checked settings and encrypted secrets |
| `POST /api/sources/mam/connection/test` | Administrator; authenticated account check, no account profile exposed |
| `POST /api/sources/mam/search` | Authenticated user; bounded query with CSRF/origin checks |
| `GET /api/sources/mam/releases/{id}` | Authenticated user; exact-ID detail lookup |

Migration `0015_sources` adds `source_connections` independently of ABS integrations. This prevents source credentials from entering library-sync scheduling. Its primary key enforces one connection/session for the native source. Populated credentials/session state block lossy downgrade; retain a pre-upgrade backup and installation key. The empty schema can round-trip normally.

## Evidence and unfinished work

Twenty-nine adapter tests and eleven PostgreSQL/API tests cover request fields, rich/unknown results, invalid/partial pages, cookies, size budgets, session rotation, serialized calls, concurrent configuration changes, cancellation, account revocation, persistent cooldowns, permission boundaries, credential redaction and guarded migration. A real local HTTP proxy responds with 407; the test verifies that the target receives no direct request. This proves the client's required-proxy behavior, not a particular Gluetun deployment.

The browser journey configures a synthetic MAM endpoint, verifies token-free reload, tests the account, searches, reads full details, checks plain-text rendering and exercises a valid empty response. Desktop/mobile screenshots are retained locally. All source fixtures are invented; no personal MAM account, tracker posting or download was used.

Live account/IP/proxy certification, source-native provisional catalog creation, richer filters/autosuggest, cross-source aggregation, release ranking and qBittorrent dispatch remain pending. Artifact resolution/inspection now has its own fixture and native-parser evidence in the linked contract. Current source ordering is a browse control and does not change acquisition policies. This checkpoint does not satisfy the complete S05 manual acquisition gate.
