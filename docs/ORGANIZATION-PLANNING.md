# Organization, inspection and frozen plans

September 17, 2026. Implemented S04 foundation; the importer stage is not complete.

The administrator can edit naming presets, inspect a completed download directory, map proposed file groups to existing catalog versions, save an immutable review plan, configure/test a destination, and import the resolved books. Each item is independently published and confirmed through ABS. An inspected file, saved plan, completed publication or successful scan request never establishes library ownership by itself.

## Naming

`Organization` provides conventional and nested-layout previews, optional metadata segments, a token picker, reset and optimistic-revision saves. Examples use illustrative `ebooks` and `audiobooks` roots. Nested layout is preview-only pending actual ABS certification. Each recording/edition has a separate item leaf; equivalent file formats do not establish a new catalog version.

The DSL accepts named `{tokens}` and nonnested `[optional segments]`. An optional segment disappears if any of its tokens is missing. Arbitrary expressions, traversal, absolute paths, control characters and file-specific folder tokens are rejected. Work publication, edition, recording and tracker-posting years are distinct. Extensions reflect the source, never an implied conversion. Unicode normalization, byte limits, reserved names, deterministic collisions and conflicting item ancestry are handled by the planner. Custom multi-disc/track naming must retain verified ordering tokens.

The [ABS structure contract](https://audiobookshelf.org/docs/documentation/libraries/book-library/directory-structure/) determines actual book/item boundaries. A displayed path and expected count are predictions, not scanner evidence. Initial OPF export and eight native scanner cases cover the supported narrator/series fields; the complete compatibility matrix remains pending.

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

Settings are revision protected. Jobs fence obsolete worker attempts and recheck account, library, connection and route configuration before accepting results. Changing roots, source mappings or bindings invalidates previous probe evidence. A successful current route check enables reviewed conventional-layout imports; the worker refreshes backend checks before publication.

The backend check reads ABS version and library settings, requires the exact selected library-folder root, checks that ebooks are permitted, and verifies that OPF runs after folder/audio tags in metadata precedence. It requires either scan capability or an enabled watcher. The currently certified baseline is ABS 2.36.1; other versions remain usable for inventory but do not pass this import check yet. The app does not change ABS settings.

The worker then checks that a random challenge path is absent in ABS, creates an empty directory in the worker root, confirms it is visible through ABS, removes only its own held directory identity, and verifies disappearance. No synthetic book is introduced. The ABS path-existence endpoint is read-only despite using POST, but upstream requires upload permission; inventory-only tokens can still sync without that permission. A network error removes the owned empty marker; a replaced or nonempty marker is preserved and fails the probe. A crash can leave an empty challenge directory, so full orphan recovery remains pending.

Library settings are re-read before accepting the result. Credential generation, connection URL/enabled state and library accessibility join the frozen configuration revision. Changing any of these invalidates saved evidence; changes during a probe discard its result. Evidence is a point-in-time observation and must be refreshed at publication, never treated as a permanent guarantee of remote settings or mounts.

## Initial metadata export

New frozen plans use document schema 2 and record deterministic per-group `metadata.opf` contents under `initial_sidecars`, plus selected catalog-version fingerprints. Both participate in the immutable plan revision. Older plans remain readable; a plan missing either export or version evidence must be freshly planned before publication.

The exporter writes clean title/subtitle, credited authors, audio narrators, language, the relevant edition/recording year, publisher, description, genres, supported identifiers and selected filing-series sequence when resolved. It escapes XML, preserves Unicode, rejects invalid XML characters and validates ISBN checksums. Original-work and tracker-posting dates do not substitute for a missing version year. Ebook exports do not invent narrator metadata. Uncertified fields such as abridgment, edition labels and app IDs remain in app metadata rather than pretending to be supported ABS OPF fields or identifiers.

This is initial export only. It never edits seeded tags or existing library/ABS metadata. Generated-file hashes remain part of the publisher's frozen specification. The current plan builder supplies resolved title/contributors/language/year, identifiers and work description; canonical series selection and broader edition/publisher metadata still need their domain/UI work before they flow automatically into export. Selected catalog covers now export as independent frozen JPEGs; see [Initial cover export](COVER-EXPORT.md). Later metadata reconciliation remains pending. Nine exporter tests and the real ABS cases verify the supported initial OPF path.

## File evidence

The worker opens each directory component relative to an already-open descriptor, refuses symlinks/special files, hashes regular files and compares identity/size/timestamps before and after inspection. It enumerates the tree again before committing a snapshot. Files are opened read-only. Limits currently bound a batch to 10,000 entries, 20 directory levels, 200 GiB and a 300-second inspection budget. Blocking operating-system I/O is not made cancellable by the wall-clock budget; production mount and resource behavior still needs certification.

- Audio: bounded `ffprobe` JSON, forced demuxer by supported extension, an inherited file descriptor, local-file protocol only, disabled MOV external references, one identifiable audio stream and positive duration. Capture known tags, codec, duration and disc/track evidence. Probe timeout is 20 seconds; output is capped at 1 MiB. [ffprobe documentation](https://ffmpeg.org/ffprobe.html).
- EPUB: bounded ZIP directory and metadata reads, defused XML parsing, container/package/spine validation and existing nonempty spine entries. Read title, authors, language and identifier assertions. EPUB stays intact; no extraction occurs. This is structural inspection, not full chapter decoding or proof that the book is complete.
- Other ebook formats, extras and generic archives remain held for review because their byte-level inspectors are not yet implemented. Invalid supported files are held independently so other inspectable groups remain usable. A compromised or changing directory invalidates the entire snapshot instead of committing a partial tree.

Grouping uses directory boundaries and observed album/author/narrator/format evidence. Disc directories are folded into their parent recording; contradictory disc evidence is held. Flat ebooks remain separate groups. Filename-only track inference, automatic provider-identifier matching, verified omnibus coverage, companion classification and broader formats remain S04 work. All proposed groups begin with unresolved identity and unverified full contents.

## Correct collection groups

Choose **Review file groups** on a completed inspection. Assign files to an existing group to join them, choose **New group** to separate files, or exclude a file with a reason. Review disc/track numbers for multi-file audio. Every inspected file must be assigned once or explicitly excluded; source bytes and the original inspection are never changed. Unsupported or failed files cannot be promoted into valid media by this editor. Ebook and audio remain separate, alternate audio encodings cannot be combined, and each currently supported EPUB stays intact in its own group. A single omnibus is not split into invented standalone books.

Saving creates an immutable grouping revision, clears the current catalog selections and asks the user to map the resulting groups. Common embedded metadata supplies suggestions only; identity and completeness remain unverified until reviewed. An excluded file remains in the seeded download. **Restore proposed groups** saves a new revision of the original proposals, preserving previous review history. Optimistic revision checks reject stale competing edits; replaying the same saved change returns its existing revision.

Frozen plans include the reviewed grouping revision and exclusions. A later grouping correction leaves the old plan readable but prevents starting a new import from it. Creating import reservations and saving group changes share a transaction lock; reserved or published groups must remain unchanged while unresolved siblings may be corrected. Stop unpublished reserved children and await worker reconciliation before regrouping their files. See [Import cancellation and replanning](IMPORT-CANCELLATION.md).

New multi-file audio imports also freeze the expected playback sequence. Confirmation compares that sequence with ABS's explicit audio-file indices, not the order of an API array. Missing, duplicate or differing indices hold confirmation. ABS can prefer embedded tags over filename numbers; the app does not rewrite seeded tags to force an order. A real two-track merged-group workflow passes the pinned-server check, but the full disc/track and manual-order repair matrix remains pending.

## Persistence and API

| Resource | Behavior |
|---|---|
| `GET/PUT /api/organization/settings` | Read/save naming profile with expected content revision |
| `POST /api/organization/preview` | Pure sample/supplied-fact preview; no file reads |
| `GET /api/organization/download-roots` | Configured logical root keys |
| `POST /api/organization/inspections` | Queue durable inspection; requires idempotency key, configured source and completed-download assertion |
| `GET /api/organization/inspections` | Owner-scoped history, 25 summaries per page without loading file snapshots |
| `GET /api/organization/inspections/{id}` | Owner-scoped result, file evidence and proposed groups |
| `GET/PUT /api/organization/inspections/{id}/grouping` | Read/save reviewed membership, ordering and exclusions, or restore proposals with expected revision |
| `POST /api/organization/inspections/{id}/plans` | Validate selected catalog versions and profile/inspection revisions; save immutable plan |
| `GET /api/organization/plans/{id}` | Reload the recorded plan independently of later settings changes |
| `GET /api/organization/destination-roots` | Configured destination keys |
| `GET /api/organization/destinations` | Bindings and current probe evidence |
| `PUT /api/organization/destinations/{root_key}` | Save library/path/media/method binding with expected revision |
| `POST /api/organization/destinations/{id}/probe` | Queue a real worker filesystem check using an owned frozen plan and idempotency key |
| `POST /api/organization/plans/{id}/imports` | Reserve resolved versions and atomically enqueue per-book publication; requires a command key and current plan/destination revisions |
| `GET /api/organization/plans/{id}/imports` | Latest 25 owner-scoped runs and per-child states |
| `GET /api/organization/imports/{id}` | Owner-scoped publication and backend-confirmation state |
| `POST /api/organization/imports/{id}/entries/{entry_id}/cancel` | Stop unpublished work through durable filesystem reconciliation; preserve published items |
| `POST /api/organization/imports/{id}/entries/{entry_id}/retry` | Retry a held reserved import or pending detection without duplicating an active queue job |

Administrator access is enforced server-side. Each inspection belongs to its initiating administrator. Queue enqueue and inspection creation share one PostgreSQL transaction. Worker attempts use generation tokens; a superseded attempt cannot commit over the newer one. Check actor/root configuration before and after filesystem work. Stalled read-only jobs are eligible for existing worker recovery. Deterministic file failures expose an actionable state; a new inspection command retries after repair.

Frozen plans retain source identity/hash evidence, original version/work bindings, selected groups, unselected-group keys, the naming profile, resolved relative destinations and pending publication checks. Concurrent equivalent saves share one plan record. Changing settings cannot mutate a saved plan. Publication freezes its route and checks existing-media satisfaction, source evidence, active permissions and ABS boundaries. Unresolved children can be corrected in a new plan while published groups stay unchanged. Editing already published entries remains separate work.

Migrations 0008 and 0009 add organization settings, download inspections and frozen plans. Populated settings/history guard against lossy downgrade; restore a pre-upgrade backup for such rollback. A new installation can round-trip the empty schema.

Migration 0010 adds destination bindings and fenced probe state, with the same populated-state downgrade guard.

Migration 0011 adds durable runs, per-child publication state and reservations. Populated import history prevents destructive downgrade. Preserve database state and the private filesystem journal together; complete restore reconciliation remains S09 work.

Migration 0012 adds immutable file-group review history. Its populated-state guard prevents lossy rollback. The latest grouping is separate from the original inspection snapshot and from every frozen plan.

Migration 0013 adds initial-cover export evidence. Prepared JPEG bytes are frozen in the publication specification; populated history requires a pre-upgrade backup for rollback.

Migration 0014 adds recoverable cancellation states and a populated-state downgrade guard. Cancellation receipts fence delayed publishers and preserve cleanup progress.

## Reviewed publication and availability

After saving a conventional-layout plan, select a verified destination for each medium and choose **Import resolved books**. The UI chooses a destination automatically only when exactly one verified binding matches the medium. Unresolved or unverified children remain held; other children proceed independently. Full ownership of this exact version in the selected ABS library skips publication. Another reserved import for the version in that library holds the new entry, including when different destination bindings point to the same library. Reservations and queue jobs commit atomically; command replay returns the same run.

The state flow is `queued → publishing → awaiting-library → confirmed`, with independent `held` and `skipped` outcomes. A per-entry attempt token fences stale workers. Bulk file work happens outside database transactions; a short final guard locks the current actor, connection, library, route, version and entry around no-replace publication and receipt persistence. Revoked access, changed identity or a changed route blocks that write. A receipt can recover the publication after a crash before the database acknowledgement.

Once published, detection retries verify the selected library bytes without republishing or requiring the source download to remain present. The worker requests a scan when permitted; otherwise it waits for the enabled watcher. Confirmation requires the exact ABS item folder, exact media paths and sizes, full-medium classification, compatible exported metadata and a direct item re-read. Only then does it bind the observed asset to the selected version and update availability. A conflicting manual library match is held for review.

Pending detection is checked every minute while workers are running. After 30 minutes without confirmation it becomes actionable attention. Retry does not duplicate a live queue job or replace media. An explicit retry can accept a rotated credential generation for the same frozen server/library/paths; changed bindings still require resolution. Unrelated destination content is never overwritten or adopted by its filename. A failed route does not silently switch from hardlink to copy.

Current limits: published entries retain reservations. Unpublished entries can be stopped through journaled reconciliation and unresolved siblings can be replanned; replacement and modification of published entries are not exposed. Confirmation currently scans the library inventory per entry; batched/coalesced lookup remains future work. Equivalent libraries registered through different integration records and filesystem aliases require broader reconciliation. Existing user library content is not reorganized. Source downloads, external lists and automatic acquisition are not connected to this manual workflow yet.

## Filesystem publisher primitive

`app.importing.publication.publish_item` implements complete-item staging, source identity/hash revalidation, hardlink or explicit copy, independently generated sidecar files, journaled interruptions and atomic no-replace publication. The reviewed API/worker workflow now uses it. Tests and native certification operate only on generated synthetic media; no user's library files were used as fixtures.

All receipts, locks and partial staging stay outside scanned roots. Existing destination folders are never adopted by filename alone or overwritten. Recovery recognizes a published item through recorded directory identity and an exact file/hash manifest, including when the seeded download has subsequently gone away. Staged copy recovery removes only the recorded partial inode; unknown files and unconfirmed staging directories remain untouched for review. A missing or changed published item is held instead of silently recreated. Source media bytes, names, modes and timestamps are not rewritten; hardlink creation necessarily changes link counts and inode change time.

The implementation uses Linux [renameat2 with RENAME_NOREPLACE](https://man7.org/linux/man-pages/man2/rename.2.html) and Darwin [renameatx_np with RENAME_EXCL](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/stdio.h). Only Darwin has been executed locally. Ordinary overwrite-capable rename is not a fallback. Kernel I/O interruption, Linux/container behavior, bind aliases, full orphan cleanup/restore recovery and broader export/identity mapping remain gate work.

## Verification and remaining gate

The current corpus exercises naming, actual generated EPUB/MP3/M4B inspection, source integrity, symlinks/FIFOs/traversal, malformed/entity-bearing EPUB metadata, probe bounds, changing files, concurrent commands, worker redelivery/supersession, revocation, frozen-plan persistence and downgrade guards. The browser follows inspection → catalog/version mapping → saved plan → reload on a mobile viewport.

The publisher adds 25 tests for hardlink/copy integrity, interrupted/replayed publication, concurrent workers, collisions, stale sources and symlink escapes. Ten destination integration tests cover actual probes, concurrent commands, stale configuration, obsolete workers, access and downgrade guards. The browser additionally saves a destination and verifies its actual route on a mobile viewport.

Fourteen integrated publication tests cover command/reservation races, shared-library bindings, per-child partial success, exact-version satisfaction, mismatched backend metadata/files, final permission/identity fencing, post-rename crash recovery, periodic confirmation, credential retry and downgrade protection. The browser submits a reviewed import, observes waiting state, confirms fixture detection and retains availability after reload.

Twelve grouping integration cases cover merge/split/reset, immutable source evidence, stale/concurrent reviews, invalid file assignments, frozen-plan invalidation, active-import protection, owner isolation and downgrade protection. Four additional cases reject reversed, missing or duplicate playback indices while accepting explicit correct indices independent of API array order. The browser persists exclusions, restores proposals, maps the restored group and completes its import.

The [native ABS certification](ABS-NATIVE-CERTIFICATION.md) passed eight pinned-server scanner cases through the publisher and inventory adapter, plus real ebook and merged two-track audio application workflows through the import API and durable worker. The audio case confirms playback order. Initial OPF and cover export participate in these checks; ABS selects generated artwork and later changed cover bytes remain untouched. Actual watcher behavior and broader compatibility remain unverified; nested layout is still preview-only.

Forty cover unit cases and seven integration cases cover bounded retrieval/decoding, publication consistency, optional failure and artwork-edit preservation. See [Initial cover export](COVER-EXPORT.md) for the live-provider evidence and remaining limits.

Seventeen filesystem and nine API/database cases verify cancellation, uncertain-publication recovery, reserved-file protection and replanning beside a confirmed sibling. The browser also stops a held import and submits it again after repair.

Next: fuller grouping/format/omnibus coverage, file-alias reconciliation and the complete recovery/compatibility matrix. These remain required before enabling the MAM/qBittorrent acquisition path. No S04 acceptance gate is claimed complete.
