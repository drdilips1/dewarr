# Native AudiobookBay integration

This increment connects native AudiobookBay search and posting detail to the existing source artifact, selection, download and import pipeline. It does not complete the entire S06 stage. Evidence from synthetic HTTP services and real local files is separate from live-source/client certification.

## User flow

Open Sources → Search AudiobookBay. An administrator saves the supported site's current origin, optional required HTTP proxy and a qBittorrent connection for manual metadata inspection. There is no embedded default hostname or login cookie. The connection test checks recognized site markup, not torrent availability.

Search by title, author or series. Results preserve the raw posting title, source description, explicit author/narrator, language, format, size and abridgment evidence. Missing seed counts stay unknown. Posting file rows are labelled claims. The detail action performs no torrent submission. Book-level federated searches include ABB alongside MAM and Prowlarr; ebook-only searches report that ABB supplies audio without querying it.

Inspect torrent resolves the magnet through the configured downloader, validates the resulting torrent's identity and stores a private artifact. The common manifest page then uses the existing work/request selection and download action. Inspecting does not start a payload transfer or adopt an unrelated existing torrent. The returned metadata may describe multiple books; normal collection matching and per-child import rules still apply.

## Metadata and automatic selection

Magnet inspection uses qBittorrent's 5.2+ metadata APIs, after the normal client capability check. `fetchMetadata` may return pending; `saveMetadata` exports the resolved torrent. When the metadata cache is absent but qBit reports an existing transfer, read-only torrent export is allowed only with subsequent requested-hash validation. No add/start/stop fallback exists. Older supported clients can still handle ordinary torrent-file acquisition, but cannot perform this inspection.

Automatic selection uses the downloader selected in the request, with its expected generation, rather than the manual source default. A profile can explicitly enable **Allow AudiobookBay releases after torrent metadata resolves** under Unknown seed counts. It is off by default. This permits unknown counts only for ABB and still requires metadata resolution before final selection. It does not invent a count, permit reported zero seeders, prove current swarm health, or bypass identity, language, recording, format, size, scope or import checks. Unset legacy profiles retain their previous serialization; explicit false overrides an inherited true.

A successful metadata lookup is not proof that the entire payload will finish. Normal transfer monitoring and repair remain authoritative. Newly acquired content receives the ownership check only after matching accessible ABS inventory confirms it.

## Boundaries and recovery

- ABB requests share a persisted source lease and cooldown across workers. A client spaces its warm-up/search or detail requests; responses are bounded to 2 MiB and fixed deadlines. Markup changes are parser failures, not empty searches.
- Site detail links stay on the configured origin; redirects do not silently switch it. Proxy failure never falls back to direct. Source credentials and artifacts stay encrypted; no magnet/credential is returned by detail APIs.
- Magnet parsing supports v1 and v2 identities, strips web-fetch parameters and rejects conflicting identities. Torrent parsing remains offline in the existing bounded subprocess boundary.
- qBit metadata inspection shares its bounded diagnostic lease. No database transaction spans HTTP/metadata waiting. Cancelled or crashed reads leave an expiring lease rather than a permanently stuck session.
- Source/downloader generations and account access are rechecked after I/O and before artifact persistence. Source settings lock precedes downloader settings lock wherever both are needed. Late results cannot clear a newer lease or publish under stale settings.
- Search observations expire after 25 minutes and are owner-scoped. Repeating inspection of identical bytes returns the existing artifact. Shared selection/dispatch handles downstream replay and reservations.
- HTTP source routing and qBittorrent peer/tracker routing are separate deployment concerns. Configure the downloader's network separately; a Gluetun HTTP proxy setting in this app does not route its torrent traffic.

## Verification and limits

`test_audiobookbay_sources.py` covers configuration, real adapter HTTP transports, ownership/expiry, source/downloader changes, revoked accounts, capability errors, rate/lease behavior, manual submission and opted-in automatic selection. `test_audiobookbay_import.py` uses generated audio, actual torrent metadata, real hardlinks and the fixture ABS scanner to prove single submission, source-byte preservation, immediate/delayed confirmation and replay. The browser journey exercises setup, source claims, metadata inspection, manifest reload and mobile layout against synthetic HTTP services.

These checks do not certify a public ABB host or an installed real qBittorrent 5.2 server. Broader source equivalence, all collection/recording combinations and production deployment remain stage obligations. Collections are subject to the existing evidence requirements; this parser does not make a claimed series list authoritative. ABB does not supply a comprehensive recording catalog, and uncorroborated title/author results remain reviewable instead of automatically selected.

## Interface references

The independent parser follows public page shapes inspected through [Shelfmark's ABB module](https://github.com/calibrain/shelfmark/tree/cdd001bdd9c3b76c34dfbfe3a85ce8ccd843fa83/shelfmark/release_sources/audiobookbay). No Shelfmark application implementation is bundled. The qBittorrent interface reference is [the 5.2.0 metadata actions](https://github.com/qbittorrent/qBittorrent/blob/release-5.2.0/src/webui/api/torrentscontroller.cpp). HTTP interface inspection does not incorporate upstream server code. [Beautiful Soup](https://pypi.org/project/beautifulsoup4/) supplies HTML parsing; its locked distribution and SoupSieve retain their installed MIT notices.
