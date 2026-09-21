# qBittorrent transport and reconciliation contract

Implementation checkpoint: the adapter, association rules, administrator settings UI/API, read-only connection diagnostics and path mapping preview are implemented and fixture verified. The opt-in [durable attempt workflow](DOWNLOAD-ATTEMPTS.md) now calls this adapter for reviewed acquisitions and observation-based recovery. Live qBittorrent certification and the complete acquisition/import gate remain pending; dispatch defaults off.

## Configure a downloader

Open **Settings → Downloaders → Connect qBittorrent**. Enter its Web UI URL or IP address, optional username and password, and optional category (blank by default). Addresses without a scheme use HTTP. Save, then test the saved connection. Editing retains credentials when both fields are blank; changing the endpoint clears saved credentials unless replacements are supplied.

Download folders, layout, automatic torrent management, and other torrent preferences belong in qBittorrent. The connection form does not expose storage settings or require worker download roots. Connection testing reads qBittorrent's selected download location for later import planning, without changing server preferences.

Connection records use the existing generic integration table with kind `qbittorrent`. Library connection endpoints and inventory scheduling exclude them. No schema migration is needed for this checkpoint. Credentials are encrypted and never returned by the API, included in audit details or populated into the browser after reload. Reads, writes, tests and previews require administrator access; writes additionally require the existing session/origin/CSRF checks.

Settings use an optimistic generation and serialized writes. A concurrent edit cannot silently overwrite another edit, and a test of an old generation cannot mark new settings connected. Diagnostic calls run outside database transactions, have a total deadline and a persisted lease, and impose a cooldown after failures. Cancellation leaves a lease that expires before another test can authenticate. Configuration edits retain active leases and cooldowns. A diagnostic never queries or changes torrents. A connected status confirms API access only, not acquisition or filesystem readiness.

### Import storage compatibility

Legacy API clients and existing import bindings retain path-mapping compatibility. New connections automatically recognize a configured worker root when qBittorrent uses the same absolute path. Different container mounts still require deployment-level storage alignment before importing; this does not block saving or testing a connection.

For example, qBittorrent root `/data/downloads` can map to the configured worker root `downloads`, whose host/container path is `/storage/downloads`. Then `/data/downloads/Series/Book` previews as `/storage/downloads/Series/Book`, with inspection-relative path `Series/Book`. Prefixes are matched on directory boundaries, so `/data/downloads-other` is not inside `/data/downloads`.

Multiple disjoint mappings are supported. The save folder must lie inside one mapping; overlapping roots, traversal and unconfigured worker roots are rejected. Worker paths come from configured `BOOK_IMPORT_SOURCES`, not arbitrary browser-supplied filesystem paths. Saving snapshots those bindings. If a configured worker root changes, mappings become stale and require review/save before preview or later acquisition use.

Preview shows the predicted mapping and performs no filesystem access. It never asserts that files exist, mounts refer to the same storage or hardlinks work. The existing inspection and destination-probe workflow remains responsible for actual filesystem evidence and source confinement. The settings API does not submit torrents. The separate reviewed-selection lifecycle remains gated by `BOOK_DOWNLOAD_DISPATCH_ENABLED`; see [Download attempts](DOWNLOAD-ATTEMPTS.md).

## Implemented boundary

`services/app/adapters/qbittorrent.py` implements the download-client protocol: capability detection, one-artifact submission, lookup, status and file observations. It supports the qBittorrent 5.x HTTP contract and administrator-configured POSIX server paths. Server configuration stays separate from the worker's later path mapping. Connection credentials are confined to the configured endpoint, redirects are not followed, environment proxies are ignored and responses have byte/time limits.

API contract references are the [official 5.x wiki](https://github.com/qbittorrent/qBittorrent/wiki/WebUI-API-%28qBittorrent-5.0%29) and the release-5.2.3 source interfaces. The latter is necessary because the wiki's older login/add examples do not fully describe the selected release:

- [Authentication controller](https://github.com/qbittorrent/qBittorrent/blob/release-5.2.3/src/webui/api/authcontroller.cpp) and [HTTP response mapping](https://github.com/qbittorrent/qBittorrent/blob/release-5.2.3/src/webui/webapplication.cpp): the current login can return 204; earlier clients return `Ok.`.
- [Torrent controller](https://github.com/qbittorrent/qBittorrent/blob/release-5.2.3/src/webui/api/torrentscontroller.cpp): structured add acknowledgements, optional asynchronous acceptance, torrent properties and file observations.
- [Web API version](https://github.com/qbittorrent/qBittorrent/blob/release-5.2.3/src/webui/webapplication.h): the selected release declares 2.15.1.

These references describe external interfaces. No qBittorrent implementation is bundled or translated into the application. Actual server and filesystem compatibility still needs its own evidence.

## Submission and association

Submission accepts one bounded torrent byte payload or one supported v1/v2/hybrid magnet. Remote torrent URLs must be resolved by their source adapter. Magnet identity validation rejects conflicting hashes and multiple-line inputs. The [source artifact parser](SOURCE-ARTIFACTS.md) now validates native MAM torrent descriptors; the opt-in download-attempt workflow now consumes that frozen evidence.

Every add supplies the torrent artifact, application attempt tag, and category. It leaves save paths, content layout, automatic torrent management, start state, and other transfer preferences to qBittorrent. It does not copy MAM credentials into the downloader.

`SubmissionReceipt` is an acknowledgement, not completion or association. Legacy acknowledgements provide no identifier; newer replies may contain a client key or report pending acceptance. The adapter validates that a structured response describes the one submitted artifact. Ambiguous responses, timeouts, connection loss, redirects, malformed receipts and server failures remain uncertain. It never retries an add automatically. Cancellation propagates; a durable caller must already have recorded that submission may have started.

Lookup separately queries the attempt tag and known hash so an unrelated hash match cannot be hidden by a tag filter. Candidate counts and response sizes are bounded. Full v1 and v2 identities come from torrent properties; the client key can be a truncated v2 digest and is not automatically a v1 identity. Lookup reads each candidate's properties and files without modifying it.

Association requires one candidate, the expected attempt tag, all known artifact identities, the frozen destination/category. Automatic torrent management is accepted; changes to the observed destination still require reconciliation. An untagged existing torrent, changed path/category, mismatched identity or multiple candidates produces an actionable conflict. No retagging, adoption, movement or deletion occurs. No observed candidate means only “not observed”; it does not authorize resubmitting an uncertain operation.

## Completion evidence

The adapter records reported completion only when the client is in a stable complete state, progress and remaining-byte values agree, and every returned file is selected and complete. Its conservative `completed` flag additionally requires the file-size sum to match the torrent total. Known padding is reconciled by the download workflow against the exact saved manifest and padding-inclusive total before inspection. Checking, moving, missing-file, error, metadata-only and unknown states cannot become ready merely because their progress is one. Paths, file indexes and sizes are validated; duplicate or unsafe file records fail the observation.

This is client evidence only. The importer must still map paths, inspect actual bytes, verify the manifest and publish safely. Audiobookshelf observation remains necessary for the book's in-library indicator.

## Evidence and remaining work

Seventy-six adapter cases cover the selected 5.2.3 response shapes, legacy and asynchronous receipts, session reuse, rejected login, expired access, lost submission response, cancellation, v2/hybrid identity, unrelated preexisting transfers, destination changes, partial files, unsafe paths, malformed data and bounded responses. Twenty-one PostgreSQL/API cases cover settings, encrypted credentials, authorization, path confinement and stale bindings, concurrent edits/tests, cooldowns, deadlines, account revocation and cancelled-test recovery. A stateful HTTP fixture models successful and response-lost adds followed by independent lookup. These are not live-client or crash-recoverable dispatch workflow tests.

The focused connection browser test covers the four-field form, saving without credentials, persistence after reload, mobile layout, and independence from worker-root queries. qBittorrent responses are synthetic; no personal client or torrents are used.

The [durable attempt workflow](DOWNLOAD-ATTEMPTS.md) now persists full identity claims, freezes committed reservations, journals submission before the side effect, observes uncertain outcomes and queues administrator inspection of verified completed directory and single-file manifests. API/Activity controls and crash/concurrency fixtures cover that workflow. It is opt-in and fixture verified, not live-client certification.

Remaining integration work includes explicit repair after saved connection changes, post-import reservation/claim reconciliation, member-to-administrator review handoff, broader collection matching, and actual supported-client/filesystem certification. No generic unreviewed add endpoint is exposed.
