# Native Audiobookshelf certification evidence

September 17, 2026. Bounded compatibility checks against a real disposable ABS server, including six application import workflows for ebooks, audio, reviewed formats and companions. This is not full S03/S04 certification.

## Reproduce

`scripts/certify_abs.py` launches its own loopback-only server with fresh temporary config, metadata and synthetic library roots. It refuses a different source commit or tracked modifications, generates an ephemeral root password, and stops the process/removes the fixture afterward. It never accepts the URL or credentials of an existing server. No ABS implementation code is bundled in this project.

```sh
git clone --branch v2.36.1 --depth 1 https://github.com/advplyr/audiobookshelf .local/reference/audiobookshelf
npm --prefix .local/reference/audiobookshelf ci --omit=dev
uv run python scripts/certify_abs.py --node /opt/homebrew/opt/node@24/bin/node
```

Use the installed ABS-compatible Node executable on other hosts. The clone command is for an absent checkout; do not rerun it over an existing directory.

To additionally exercise the application API, database reservations, durable worker and final availability, create a dedicated disposable database whose name ends `_abs_test` and pass it explicitly:

```sh
createdb -h 127.0.0.1 -p 55438 -U book book_search_abs_test
uv run python scripts/certify_abs.py --node /opt/homebrew/opt/node@24/bin/node --workflow-database postgresql+psycopg://book@127.0.0.1:55438/book_search_abs_test
```

The application fixture migrates and clears that database, then truncates its fixture application/queue tables on completion. Never use a database containing wanted data. It generates temporary application credentials and connects only to the harness's disposable ABS process. These credentials are not retained in the evidence report.

Tested: ABS 2.36.1, commit `4b67c170ce46fd6ba770dc55c189ca13fef89b02`, macOS arm64, Node 24, Python 3.13.14 and ffmpeg/ffprobe 8.1.2. The upstream server failed to start under this host's Node 26.7 because its `buffer-equal-constant-time` dependency expects `SlowBuffer`. No upstream dependency patch or audit fix was applied. Optional SQLite Unicode extension was not loaded. This does not certify the production Docker image, other runtimes or all ABS API behavior.

## Eight passing item cases

| Case | Verified result |
|---|---|
| First ebook edition | One ebook item at its exact expected folder |
| Revised ebook edition | Separate ebook item, same clean work title |
| Jordan Lee recording | One audio item with the expected narrator |
| Casey Reed recording | Separate audio item, same clean work title |
| Two-track recording, series position 1.5 | One audio item with both files and decimal series sequence |
| Nested Jordan Lee recording | One leaf item; OPF supplies correct title, author and series despite extra folder depth |
| Nested Casey Reed recording | Separate leaf item with correct narrator and metadata |
| Unicode title and XML metacharacters | Exact clean title survives production OPF export and real ABS parsing |

All media are generated original synthetic EPUBs or short silent audio. The harness uses the production filesystem publisher primitive to hardlink complete items, writes OPF through the production initial metadata exporter, retries each publication and checks source hashes/inodes. It checks the real API's authorization, library listing, manual scan, paginated membership, expanded batch items and individual item retrieval through our adapter. It verifies exact media paths, counts, ownership classification, author/title/narrator/year and series metadata. A second manual scan preserves item IDs and count. The server uses a URL prefix to exercise prefixed adapter endpoints.

The default ABS metadata precedence applies the generated OPF after folder and audio-tag metadata. The fixture deliberately supplies a different embedded audio title and asserts that the OPF title wins. This does not establish that an arbitrary user's library has compatible precedence.

## Explicit boundaries

The additional application tests pass bootstrap → ABS connection/inventory → file inspection → frozen plan → destination probe → import API/worker → real ABS scan/confirmation for six cases:

| Application case | Additional assertion |
|---|---|
| EPUB | Complete ebook availability |
| Two-track audiobook | Separate source groups merged; reviewed playback order confirmed |
| PDF | Structurally inspected PDF recognized as a complete standalone ebook |
| CBZ | Decoded image-page container recognized as an ebook |
| EPUB + PDF | Explicit same-edition review; one catalog version/item, both formats retained after inventory refresh |
| Audio + PDF companion | PDF stays with the recording; no ebook availability or phantom ebook edition |

Every case first stops a queued import, confirms no media was published and sources are unchanged, then submits a fresh import. Each verifies exact-version ownership, source byte/inode preservation, inventory refresh and a second request skipping the owned version. Each also retrieves synthetic artwork through the production bounded HTTP/decoder path, verifies that real ABS selects the generated independent cover, changes that cover locally, and proves a duplicate import leaves the changed bytes intact. The image HTTP transport is a fixture; decoding and ABS scanning are real. Catalog versions are seeded deliberately; this does not certify an external metadata provider or acquisition source. All content is generated in disposable directories.

The script disables the watcher and triggers manual scans. The actual backend path-existence endpoint passes an absent → visible → absent empty-folder challenge, verifying the worker/ABS root mapping. Library media settings and OPF precedence are read through the real API. Watcher-driven imports, additional formats, omnibus coverage, wider international metadata, full disc-order, deletion/move, user-progress, permission and crash/scanner matrices remain pending. The audio application case establishes one two-track ordering scenario, not the complete matrix. Concurrent reservation and permission-race cases use the separate HTTP fixture integration tests.

Nested layouts remain preview-only in the app. No complete stage or acceptance gate is marked passed from these eight item checks and six application workflows. Logs and sanitized JSON evidence are saved in ignored `.local/evidence/abs-native.*`; server credentials and fixture databases are not retained in the JSON report.

Reference: [pinned ABS source](https://github.com/advplyr/audiobookshelf/tree/v2.36.1), [OPF parser](https://github.com/advplyr/audiobookshelf/blob/v2.36.1/server/utils/parsers/parseOpfMetadata.js), [library metadata defaults](https://github.com/advplyr/audiobookshelf/blob/v2.36.1/server/models/Library.js).
