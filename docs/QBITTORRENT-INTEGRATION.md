# qBittorrent transport and reconciliation contract

Implementation checkpoint: the adapter and association rules exist and are tested against synthetic HTTP responses. There is no downloader settings UI, persisted dispatch workflow or live qBittorrent certification yet. Nothing in the application currently calls this adapter to start a download.

## Implemented boundary

`services/app/adapters/qbittorrent.py` implements the download-client protocol: capability detection, one-artifact submission, lookup, status and file observations. It supports the qBittorrent 5.x HTTP contract and administrator-configured POSIX server paths. Server configuration stays separate from the worker's later path mapping. Connection credentials are confined to the configured endpoint, redirects are not followed, environment proxies are ignored and responses have byte/time limits.

API contract references are the [official 5.x wiki](https://github.com/qbittorrent/qBittorrent/wiki/WebUI-API-%28qBittorrent-5.0%29) and the release-5.2.3 source interfaces. The latter is necessary because the wiki's older login/add examples do not fully describe the selected release:

- [Authentication controller](https://github.com/qbittorrent/qBittorrent/blob/release-5.2.3/src/webui/api/authcontroller.cpp) and [HTTP response mapping](https://github.com/qbittorrent/qBittorrent/blob/release-5.2.3/src/webui/webapplication.cpp): the current login can return 204; earlier clients return `Ok.`.
- [Torrent controller](https://github.com/qbittorrent/qBittorrent/blob/release-5.2.3/src/webui/api/torrentscontroller.cpp): structured add acknowledgements, optional asynchronous acceptance, torrent properties and file observations.
- [Web API version](https://github.com/qbittorrent/qBittorrent/blob/release-5.2.3/src/webui/webapplication.h): the selected release declares 2.15.1.

These references describe external interfaces. No qBittorrent implementation is bundled or translated into the application. Actual server and filesystem compatibility still needs its own evidence.

## Submission and association

Submission accepts one bounded torrent byte payload or one supported v1/v2/hybrid magnet. Remote torrent URLs must be resolved by their source adapter. Magnet identity validation rejects conflicting hashes and multiple-line inputs. Opaque torrent bytes still require the planned descriptor parser and acquisition validation before they can enter a production dispatch workflow.

Every add specifies the application attempt tag, category, save path, original content layout, enabled hash checking and disabled automatic torrent management. It does not set ratio/seeding limits, rename files, choose partial file priorities or copy MAM credentials into the downloader. This preserves the planned whole-pack and tracker-seeding behavior.

`SubmissionReceipt` is an acknowledgement, not completion or association. Legacy acknowledgements provide no identifier; newer replies may contain a client key or report pending acceptance. The adapter validates that a structured response describes the one submitted artifact. Ambiguous responses, timeouts, connection loss, redirects, malformed receipts and server failures remain uncertain. It never retries an add automatically. Cancellation propagates; a durable caller must already have recorded that submission may have started.

Lookup separately queries the attempt tag and known hash so an unrelated hash match cannot be hidden by a tag filter. Candidate counts and response sizes are bounded. Full v1 and v2 identities come from torrent properties; the client key can be a truncated v2 digest and is not automatically a v1 identity. Lookup reads each candidate's properties and files without modifying it.

Association requires one candidate, the expected attempt tag, all known artifact identities, the frozen destination/category and disabled automatic torrent management. An untagged existing torrent, changed path/category, mismatched identity or multiple candidates produces an actionable conflict. No retagging, adoption, movement or deletion occurs. No observed candidate means only “not observed”; it does not authorize resubmitting an uncertain operation.

## Completion evidence

The adapter reports a transfer ready only when the client is in a stable complete state, progress and remaining-byte values agree, every file is selected and complete, and the file-size sum matches the torrent total. Checking, moving, missing-file, error, metadata-only and unknown states cannot become ready merely because their progress is one. Paths, file indexes and sizes are validated; duplicate or unsafe file records fail the observation.

This is client evidence only. The importer must still map paths, inspect actual bytes, verify the manifest and publish safely. Audiobookshelf observation remains necessary for the book's in-library indicator.

## Evidence and remaining work

Seventy-five adapter cases cover the selected 5.2.3 response shapes, legacy and asynchronous receipts, session reuse, rejected login, expired access, lost submission response, cancellation, v2/hybrid identity, unrelated preexisting transfers, destination changes, partial files, unsafe paths, malformed data and bounded responses. A stateful HTTP fixture models successful and response-lost adds followed by independent lookup. It is not a live-client or crash-recoverable database workflow test.

The next integration slice must supply:

1. Encrypted administrator connection settings, capability diagnostics and path mappings.
2. Source artifact resolution and a validated v1/v2/hybrid torrent descriptor, retaining source credentials privately.
3. Persisted release selection, attempt identity, client configuration revision and reservations before network side effects.
4. A preflight existing-transfer check, dispatch journaling and recovery that reconciles before any retry; no adoption of unrelated torrents.
5. Monitoring linked to the current inspection/import pipeline, with current permission and configuration checks.
6. API/UI selection and Activity states, fixture-driven crash tests and actual supported-client certification.

The adapter must remain behind that workflow. A generic add endpoint would bypass the PRD's identity, authorization and duplicate-prevention requirements.
