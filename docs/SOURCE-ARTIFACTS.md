# Source artifact inspection

Members can open a native MAM result, choose **Inspect torrent manifest**, and view the saved file list. This resolves and validates the `.torrent` metadata, not the book content. No downloader call, catalog edition, ownership claim or library file is created. Persisted selection and dispatch remain separate S05 work.

## Resolution and identity

The MAM adapter requests an exact release with its download reference, verifies the returned ID, and fetches the binary through the same configured session/proxy. A rotated cookie is immediately used for the second request and then persisted through the connection lease. Only a bounded relative download reference is accepted; redirects and arbitrary origins are rejected. An existing `tid` is replaced with the requested release ID. Other query options, including personal freeleech spending, are unsupported rather than silently enabled. The two-request operation has a longer lease, while each HTTP request retains its existing deadline and response budget. Requests are separated by the configured application interval; a cooldown from detail lookup blocks the binary fetch and is persisted with the rotated cookie.

Original bytes are passed to libtorrent 2.1.1 in a disposable process. Its native v1/v2 hashes are retained, including both full hashes for a hybrid. A separate SHA-256 identifies the exact original artifact. Bytes are never re-encoded for later submission. The parser does not create a libtorrent network session.

The descriptor exposes safe file paths, original file indexes, sizes, private flag and hashes. Padding is excluded from the material file list. `content_bytes` is the sum of material files; `torrent_bytes` is the represented transfer payload including padding, **not the size of the `.torrent` document**. Native layout and original path components must agree; ambiguous normalization, duplicate names, symlinks, traversal and conflicting hybrid layouts are rejected. File names remain evidence, not verified work or recording identities.

The limits are 8 MiB input, 10,000 material files, 2,048-character paths, 255-byte path components and a 15-second parent deadline. Native decoding also bounds pieces, tokens and nesting. The child has an eight-second CPU limit and, on Linux, a 512 MiB address-space limit. Timeout and cancellation kill and reap the child. An output over 8 MiB is rejected. These limits may hold unusually large valid collections for review rather than accepting them partially.

Primary interface references: [libtorrent torrent information and loading limits](https://libtorrent.org/reference-Torrent_Info.html), [BEP 52 v2 metainfo and hybrid compatibility](https://www.bittorrent.org/beps/bep_0052.html). The installed Python API and synthetic v1/v2/hybrid files are exercised directly; documentation alone is not a runtime certificate.

## Storage and access

`POST /api/sources/mam/releases/{id}/artifact` requires a member/admin session and CSRF/origin checks. `GET /api/source-artifacts/{id}` is restricted to that artifact's owner. Other accounts, including another administrator, receive 404. A viewer cannot resolve or read artifacts.

Original bytes can contain private tracker credentials. They are encrypted with the installation key in `source_artifacts` and never returned to the browser. The public descriptor omits trackers, web seeds, comments and download references. The adapter suppresses HTTPX request logs for MAM's credential-bearing download path. This does not claim that arbitrary debug wire logging or external proxy logs are safe to expose.

Storage rechecks the actor and source configuration after network/parsing work, then writes under the source lock. Identical artifacts deduplicate by owner, source/release, configuration generation and exact-byte digest. Repeated inspection preserves the original snapshot and timestamp. A later connection edit marks the saved artifact stale; it does not rewrite historical evidence. Internal decryption verifies the digest before exposing bytes to a future dispatcher.

Migration `0016_artifacts` adds the table. Populated artifact history blocks lossy downgrade; retain the installation key and a pre-upgrade backup. Future retention must preserve artifacts referenced by active or historical acquisition attempts.

## Evidence and remaining gate

Twenty native-parser tests cover single and multifile v1/v2/hybrid layouts, padding, independent digest checks, unsafe paths, invalid inputs, limits, timeout and cancellation. Twenty database/API cases cover encrypted storage, owner isolation, deduplication, both cookie rotations, mid-resolution cooldowns, credential-free responses/logs, rejected download references, changed configuration/permissions, integrity failure and migration guards. The browser journey saves a manifest, reloads it and checks desktop/mobile presentation with a synthetic source.

No live MAM account or qBittorrent transfer was used. Linux/container packaging, wider torrent compatibility, source-to-catalog selection, tracker/web-seed dispatch policy, artifact retention, crash-recoverable dispatch and transfer-to-import reconciliation remain unfinished. The native macOS parser is verified; published Linux wheels do not substitute for running the production image. Artifact inspection alone cannot satisfy the complete S05 acquisition gate.
