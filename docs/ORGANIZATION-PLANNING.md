# Organization, inspection and frozen plans

September 17, 2026. Implemented S04 foundation; the importer stage is not complete.

The administrator can edit naming presets, inspect a completed download directory, map proposed file groups to existing catalog versions, save an immutable review plan, and configure/test a destination. No endpoint publishes media into the library. Destination tests create and remove their own temporary hardlinks, a small copy sentinel and empty folders. An inspected file, saved plan or successful filesystem check never establishes library ownership.

## Naming

`Organization` provides conventional and nested-layout previews, optional metadata segments, a token picker, reset and optimistic-revision saves. Examples use illustrative `ebooks` and `audiobooks` roots. Nested layout is preview-only pending actual ABS certification. Each recording/edition has a separate item leaf; equivalent file formats do not establish a new catalog version.

The DSL accepts named `{tokens}` and nonnested `[optional segments]`. An optional segment disappears if any of its tokens is missing. Arbitrary expressions, traversal, absolute paths, control characters and file-specific folder tokens are rejected. Work publication, edition, recording and tracker-posting years are distinct. Extensions reflect the source, never an implied conversion. Unicode normalization, byte limits, reserved names, deterministic collisions and conflicting item ancestry are handled by the planner. Custom multi-disc/track naming must retain verified ordering tokens.

The [ABS structure contract](https://audiobookshelf.org/docs/documentation/libraries/book-library/directory-structure/) determines actual book/item boundaries. A displayed path and expected count are predictions, not scanner evidence. Narrator/series export and metadata precedence require the still-pending sidecar and backend-certification work.

## Configure read-only inspection

Set the same logical root mapping in API and worker configuration, for example:

```dotenv
BOOK_IMPORT_SOURCES='{"downloads":"/data/downloads"}'
```

For Compose, add a read-only mount to the worker in a local override:

```yaml
services:
  worker:
    volumes:
      - /actual/downloads:/data/downloads:ro
```

The API needs the mapping but does not need the media mount. The default mapping is empty. Native paths must be absolute and contain no symlink ancestors; use their actual resolved location. The filesystem root is forbidden. Configured keys use lowercase letters, numbers, hyphens and underscores. The UI accepts a relative completed-download folder, never an arbitrary host path. Changes to the configured source path invalidate dependent pending work. The runtime image declares ffmpeg as a package dependency; native audio inspection requires `ffprobe`. The container build remains unverified on this Docker-less host.

Choose **Inspect completed downloads** from Organization. Confirm that the download has finished, inspect it, then use the proposed groups to find the corresponding catalog book/version. Confirm full-book contents when known. Unconfirmed completeness produces a held plan entry. This manual assertion does not replace the future qBittorrent completion/association check. Catalog identity is never inferred merely from a folder name.

## Configure destinations and actual capability probes

Use the same mappings in API and worker settings. The worker needs access to the actual mounts; the API still needs no media mount.

```dotenv
BOOK_IMPORT_DESTINATIONS='{"ebooks":"/data/library/ebooks","audiobooks":"/data/library/audiobooks"}'
BOOK_IMPORT_STAGING_ROOT=/data/import-staging
```

Create staging with mode `0700`, owned by the worker UID. It must be outside every scanned library and download root, on the destination filesystem. Destination and staging mounts need worker write access. Source mounts must permit the actual hardlink operation when hardlinks are selected; the earlier read-only example supports inspection only. Merely putting all paths below `/data` does not prove Docker mount compatibility. The actual probe decides whether the selected route works. One staging root currently limits destinations to a compatible publication filesystem; per-filesystem staging remains future work.

Open **Organization → Configure library destinations**. Bind each configured root to an accessible ABS library, its absolute path as ABS sees it, media type and import method. Hardlink required is the default; copy is explicit and consumes extra storage. The probe now proves that both processes see the selected folder through the ABS path-existence API; a saved but untested binding is still only a declaration.

From a saved import plan choose **Check destination**, save the binding and run **Test destination route**. A durable worker operation checks the selected source hash, creates a temporary hardlink, writes/re-reads a copy sentinel, tests atomic no-replace directory publication and collision refusal, and reports available space. It removes only temporary objects it actually created. The filesystem portion is not a full-file copy test or an import reservation. The backend portion separately checks folder mapping, settings and detection capabilities. Hardlink failure never silently chooses copying. Source/staging/library overlap is rejected using configured paths; bind-mount aliases and roots not declared to the app still require the backend mapping gate.

Settings are revision protected. Jobs fence obsolete worker attempts and recheck account, library, connection and route configuration before accepting results. Changing roots, source mappings or bindings invalidates previous probe evidence. A successful check keeps `publication_available=false` until the complete import workflow exists.

The backend check reads ABS version and library settings, requires the exact selected library-folder root, checks that ebooks are permitted, and verifies that OPF runs after folder/audio tags in metadata precedence. It requires either scan capability or an enabled watcher. The currently certified baseline is ABS 2.36.1; other versions remain usable for inventory but do not pass this import check yet. The app does not change ABS settings.

The worker then checks that a random challenge path is absent in ABS, creates an empty directory in the worker root, confirms it is visible through ABS, removes only its own held directory identity, and verifies disappearance. No synthetic book is introduced. The ABS path-existence endpoint is read-only despite using POST, but upstream requires upload permission; inventory-only tokens can still sync without that permission. A network error removes the owned empty marker; a replaced or nonempty marker is preserved and fails the probe. A crash can leave an empty challenge directory, so full orphan recovery remains pending.

Library settings are re-read before accepting the result. Credential generation, connection URL/enabled state and library accessibility join the frozen configuration revision. Changing any of these invalidates saved evidence; changes during a probe discard its result. Evidence is a point-in-time observation and must be refreshed at publication, never treated as a permanent guarantee of remote settings or mounts.

## Initial metadata export

New frozen plans use document schema 2 and record deterministic per-group `metadata.opf` contents under `initial_sidecars`. The content participates in the immutable plan revision. Older schema-1 plans remain readable; they do not gain invented export data and must be freshly planned before future publication.

The exporter writes clean title/subtitle, credited authors, audio narrators, language, the relevant edition/recording year, publisher, description, genres, supported identifiers and selected filing-series sequence when resolved. It escapes XML, preserves Unicode, rejects invalid XML characters and validates ISBN checksums. Original-work and tracker-posting dates do not substitute for a missing version year. Ebook exports do not invent narrator metadata. Uncertified fields such as abridgment, edition labels and app IDs remain in app metadata rather than pretending to be supported ABS OPF fields or identifiers.

This is initial export only. It never edits seeded tags or existing library/ABS metadata. Generated-file hashes remain part of the publisher's frozen specification. The current plan builder supplies resolved title/contributors/language/year, identifiers and work description; canonical series selection and broader edition/publisher metadata still need their domain/UI work before they flow automatically into export. Cover download/validation and later metadata reconciliation remain pending. Nine exporter tests and the real ABS cases verify the supported initial OPF path.

## File evidence

The worker opens each directory component relative to an already-open descriptor, refuses symlinks/special files, hashes regular files and compares identity/size/timestamps before and after inspection. It enumerates the tree again before committing a snapshot. Files are opened read-only. Limits currently bound a batch to 10,000 entries, 20 directory levels, 200 GiB and a 300-second inspection budget. Blocking operating-system I/O is not made cancellable by the wall-clock budget; production mount and resource behavior still needs certification.

- Audio: bounded `ffprobe` JSON, forced demuxer by supported extension, an inherited file descriptor, local-file protocol only, disabled MOV external references, one identifiable audio stream and positive duration. Capture known tags, codec, duration and disc/track evidence. Probe timeout is 20 seconds; output is capped at 1 MiB. [ffprobe documentation](https://ffmpeg.org/ffprobe.html).
- EPUB: bounded ZIP directory and metadata reads, defused XML parsing, container/package/spine validation and existing nonempty spine entries. Read title, authors, language and identifier assertions. EPUB stays intact; no extraction occurs. This is structural inspection, not full chapter decoding or proof that the book is complete.
- Other ebook formats, extras and generic archives remain held for review because their byte-level inspectors are not yet implemented. Invalid supported files are held independently so other inspectable groups remain usable. A compromised or changing directory invalidates the entire snapshot instead of committing a partial tree.

Grouping uses directory boundaries and observed album/author/narrator/format evidence. Disc directories are folded into their parent recording; contradictory disc evidence is held. Flat ebooks remain separate groups. Filename-only track inference, grouping corrections, automatic provider-identifier matching, collection/omnibus verification, companion classification and broader formats remain S04 work. All proposed groups begin with unresolved identity and unverified full contents.

## Persistence and API

| Resource | Behavior |
|---|---|
| `GET/PUT /api/organization/settings` | Read/save naming profile with expected content revision |
| `POST /api/organization/preview` | Pure sample/supplied-fact preview; no file reads |
| `GET /api/organization/download-roots` | Configured logical root keys |
| `POST /api/organization/inspections` | Queue durable inspection; requires idempotency key, configured source and completed-download assertion |
| `GET /api/organization/inspections` | Owner-scoped history, 25 summaries per page without loading file snapshots |
| `GET /api/organization/inspections/{id}` | Owner-scoped result, file evidence and proposed groups |
| `POST /api/organization/inspections/{id}/plans` | Validate selected catalog versions and profile/inspection revisions; save immutable plan |
| `GET /api/organization/plans/{id}` | Reload the recorded plan independently of later settings changes |
| `GET /api/organization/destination-roots` | Configured destination keys |
| `GET /api/organization/destinations` | Bindings and current probe evidence |
| `PUT /api/organization/destinations/{root_key}` | Save library/path/media/method binding with expected revision |
| `POST /api/organization/destinations/{id}/probe` | Queue a real worker filesystem check using an owned frozen plan and idempotency key |

Administrator access is enforced server-side. Each inspection belongs to its initiating administrator. Queue enqueue and inspection creation share one PostgreSQL transaction. Worker attempts use generation tokens; a superseded attempt cannot commit over the newer one. Check actor/root configuration before and after filesystem work. Stalled read-only jobs are eligible for existing worker recovery. Deterministic file failures expose an actionable state; a new inspection command retries after repair.

Frozen plans retain source identity/hash evidence, original version/work bindings, selected groups, unselected-group keys, the naming profile, resolved relative destinations and pending publication checks. Concurrent equivalent saves share one plan record. Changing settings cannot mutate a saved plan. Existing-media satisfaction, final roots, link/copy capability, source revalidation, active permissions and ABS boundaries must be checked before any future publisher consumes a plan. The API has no publish command. Plan revisions do not yet implement selective edit/replanning of already published entries.

Migrations 0008 and 0009 add organization settings, download inspections and frozen plans. Populated settings/history guard against lossy downgrade; restore a pre-upgrade backup for such rollback. A new installation can round-trip the empty schema.

Migration 0010 adds destination bindings and fenced probe state, with the same populated-state downgrade guard.

## Filesystem publisher primitive

`app.importing.publication.publish_item` implements and tests complete-item staging, source identity/hash revalidation, hardlink or explicit copy, independently generated sidecar files, journaled interruptions and atomic no-replace publication. It is not exposed by the API or a publication worker. Its tests and certification harness operate only on synthetic media.

All receipts, locks and partial staging stay outside scanned roots. Existing destination folders are never adopted by filename alone or overwritten. Recovery recognizes a published item through recorded directory identity and an exact file/hash manifest, including when the seeded download has subsequently gone away. Staged copy recovery removes only the recorded partial inode; unknown files and unconfirmed staging directories remain untouched for review. A missing or changed published item is held instead of silently recreated. Source media bytes, names, modes and timestamps are not rewritten; hardlink creation necessarily changes link counts and inode change time.

The implementation uses Linux [renameat2 with RENAME_NOREPLACE](https://man7.org/linux/man-pages/man2/rename.2.html) and Darwin [renameatx_np with RENAME_EXCL](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/stdio.h). Only Darwin has been executed locally. Ordinary overwrite-capable rename is not a fallback. Kernel I/O interruption, Linux/container behavior, bind aliases, full recovery/cleanup for orphaned probe/staging objects, cross-process database reservations, per-child ownership checks, generated covers, broader export/identity mapping and ABS reconciliation remain gate work.

## Verification and remaining gate

The current corpus exercises naming, actual generated EPUB/MP3/M4B inspection, source integrity, symlinks/FIFOs/traversal, malformed/entity-bearing EPUB metadata, probe bounds, changing files, concurrent commands, worker redelivery/supersession, revocation, frozen-plan persistence and downgrade guards. The browser follows inspection → catalog/version mapping → saved plan → reload on a mobile viewport.

The publisher adds 25 tests for hardlink/copy integrity, interrupted/replayed publication, concurrent workers, collisions, stale sources and symlink escapes. Ten destination integration tests cover actual probes, concurrent commands, stale configuration, obsolete workers, access and downgrade guards. The browser additionally saves a destination and verifies its actual route on a mobile viewport.

The [native ABS certification](ABS-NATIVE-CERTIFICATION.md) passed eight pinned-server scanner cases through the actual publisher and inventory adapter. The production initial OPF exporter now participates in these checks. Generated covers, watcher behavior and integrated import confirmation remain unverified; nested layout is still preview-only.

Next: publication database state/reservations, generation/permission/recovery fencing at external writes, generated covers, actual ABS item confirmation in the app, fuller grouping/format coverage and existing-owned child reconciliation. These remain required before enabling the MAM/qBittorrent acquisition path. No S04 acceptance gate is claimed complete.
