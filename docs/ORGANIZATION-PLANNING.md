# Organization, inspection and frozen plans

September 17, 2026. Implemented S04 foundation; the importer stage is not complete.

The administrator can edit naming presets, inspect a completed download directory, map proposed file groups to existing catalog versions, and save an immutable review plan. No endpoint publishes, renames, hardlinks, copies or modifies media. An inspected file or saved plan never establishes library ownership.

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

Administrator access is enforced server-side. Each inspection belongs to its initiating administrator. Queue enqueue and inspection creation share one PostgreSQL transaction. Worker attempts use generation tokens; a superseded attempt cannot commit over the newer one. Check actor/root configuration before and after filesystem work. Stalled read-only jobs are eligible for existing worker recovery. Deterministic file failures expose an actionable state; a new inspection command retries after repair.

Frozen plans retain source identity/hash evidence, original version/work bindings, selected groups, unselected-group keys, the naming profile, resolved relative destinations and pending publication checks. Concurrent equivalent saves share one plan record. Changing settings cannot mutate a saved plan. Existing-media satisfaction, final roots, link/copy capability, source revalidation, active permissions and ABS boundaries must be checked before any future publisher consumes a plan. The API has no publish command. Plan revisions do not yet implement selective edit/replanning of already published entries.

Migrations 0008 and 0009 add organization settings, download inspections and frozen plans. Populated settings/history guard against lossy downgrade; restore a pre-upgrade backup for such rollback. A new installation can round-trip the empty schema.

## Verification and remaining gate

The current corpus exercises naming, actual generated EPUB/MP3/M4B inspection, source integrity, symlinks/FIFOs/traversal, malformed/entity-bearing EPUB metadata, probe bounds, changing files, concurrent commands, worker redelivery/supersession, revocation, frozen-plan persistence and downgrade guards. The browser follows inspection → catalog/version mapping → saved plan → reload on a mobile viewport.

Next: configured library destinations/path mapping, real link/copy probes, source revalidation against frozen manifests, no-replace staging/publication and recovery journals, sidecars, actual ABS item confirmation, fuller grouping/format coverage and existing-owned child reconciliation. These remain required before enabling the MAM/qBittorrent acquisition path. No S04 acceptance gate is claimed complete.
