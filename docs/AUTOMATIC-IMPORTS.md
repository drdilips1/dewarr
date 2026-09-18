# Automatic continuation of completed downloads

Administrators can enable automatic importing on a verified destination. Newly completed, associated acquisitions then use the same inspection, frozen-plan and publication services as reviewed imports. A qualifying book reaches Audiobookshelf confirmation without a per-book approval. This is an implemented part of the acquisition path, not external-list automation or the complete S05 release gate.

## Configuration and user behavior

Open a saved destination, verify its source/library route, and choose **Enable automatic import**. The destination must support publication and the current naming layout must be conventional. The approval records the administrator, destination revision, source mapping and policy generation. Setup does not import a historical backlog or submit a download.

When a new acquisition completes, the worker claims its administrator inspection under this standing approval. Original requester permissions, request reasons, selected medium, language and any exact edition/recording constraints remain in force. Members see progress and current availability without gaining access to administrator file inspection.

Choose **Disable automatic import** to hold automatic work before publication. Already published files remain intact and can finish library confirmation. Changing the route or renewing approval does not silently authorize jobs created under an older policy generation. Those jobs remain available through administrator review. If another administrator must take responsibility, use the existing review assignment controls before any import reserves or publishes files.

## Matching and completeness evidence

The current automatic path requires all of the following:

- The inspected file names and sizes exactly match the completed torrent manifest.
- Exactly one eligible file group resolves to the requested canonical work and one trusted local catalog edition/recording. Matching uses a valid embedded identifier plus compatible title, author, language and, for audio, narrator evidence. Conflicts and ambiguous versions are held.
- The group passes format and completeness checks: one inspected EPUB, one inspected M4B/MP3 with no multi-part track/disc signal, or a single-disc M4B/MP3 track set with explicit contiguous track totals.
- Neither the release title nor media paths signal sample, excerpt, preview, incomplete or truncated content.
- Current requester, administrator and destination authority still permits publication.

Completeness here is a recorded **complete-transfer-and-supported-container** heuristic. It is not an independent publisher certification that every chapter is present. Transfer completion cannot by itself establish book identity or library ownership. Source files are revalidated by the existing publisher, and ownership is established only by matching Audiobookshelf item/file evidence.

The automatic record retains group hold reasons and exclusions. Qualifying requested content can proceed while unrelated collection titles remain for review; expanding authorization to other series books belongs to the remaining series-selection work. Multiple candidate groups for the same requested work stay held rather than importing several versions implicitly.

## Durability and recovery

Migration `0022_auto_import` adds one policy per destination and one automatic continuation per download attempt. Queueing and domain changes commit atomically. Inspection completion schedules continuation in its transaction; periodic reconciliation repairs a lost continuation. Concurrent workers serialize the same attempt, and stable command keys reuse its review, plan and import.

Retries remain bounded. An automatic or inspection job that exhausts retries becomes actionable held work instead of receiving a fresh retry budget on every scheduler tick. Failed inspections use the existing administrator retry action; identity, grouping and format holds use file review. Disabling and reenabling a policy does not replay these historical exceptions.

The final publication guard checks the policy generation while holding its shared database lock, in addition to the existing requester/reviewer and destination guards. A policy change cannot commit between that check and publication. The importer preserves seeded bytes and original paths, publishes without replacing unrelated files and confirms availability through Audiobookshelf.

Populated policy or automatic-import history prevents lossy schema downgrade. Restore a pre-upgrade database backup with the corresponding configuration/key material and reconcile external state when rolling back; a downgrade must not erase publication authority/history while files still exist.

## Verification and remaining work

PostgreSQL/API and real-file tests cover opt-in defaults, stale settings, route approval, revoked authority, recovery mode, concurrent continuation, queue rollback, lost callbacks, exhausted jobs and guarded downgrade. The acquisition workflow exercises automatic EPUB/MP3 publication from a member request through a fixture downloader and ABS HTTP backend, preserving source bytes/inodes, original-owner fulfillment and one transfer. Changed manifests, ambiguous identifiers, sample releases and final-publication disable are held. Unit cases cover track/format completeness decisions.

The browser verifies enabling, persisted reload and disabling the policy on a verified route. The actual ABS 2.36.1 scanner and application import harness remains a regression check for the shared importer; it does not yet certify this automatic acquisition path against a live MAM account and real qBittorrent.

When no trusted local edition matches, [catalog resolution](IMPORT-CATALOG-RESOLUTION.md) now performs a bounded provider lookup using the original requester's connection and compatible public sources. It requires valid file identifiers, rechecks identity/authority and then resumes this same importer. The advanced metadata setting can disable that lookup independently of route approval.

[Reviewed shared downloads](SHARED-DOWNLOADS.md) now allow distinct authorized books from one transfer to continue independently. Current missing demand is checked before planning; ambiguous alternatives for one book do not block other qualifying books, and satisfied books are skipped. Each imported version must satisfy its own member requirements and receive backend confirmation.

Remaining work includes resolution without embedded identifiers, broader formats and multi-disc/collection coverage, automatic series expansion/coverage selection, later shared-pack reuse, additional sources, complete external-list policies and the supported deployment/service matrix. See [implementation status](IMPLEMENTATION-STATUS.md) and [the PRD unattended-operation contract](../PRD.md#18-unattended-operation-and-exception-review).
