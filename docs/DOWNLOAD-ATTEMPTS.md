# Durable download attempts

The reviewed selection now has a persisted qBittorrent acquisition lifecycle, owner-scoped API, worker recovery, and Activity controls. This is an opt-in development capability: `BOOK_DOWNLOAD_DISPATCH_ENABLED` defaults to `false`. Set it on both API and worker only in an isolated test installation while the full S04/S05 certification remains incomplete. The browser harness explicitly enables it against synthetic services. It has not been enabled against the user's downloader.

## Command and side-effect contract

`POST /api/acquisition/downloads` takes a selection ID and an idempotency key. Within one PostgreSQL transaction it rechecks the requesting account, active reasons, current library inventory, destination grants, frozen source/client/version/mount settings, artifact integrity and the verified import route. It creates a `DownloadAttempt`, operation receipt, full torrent identity claims and the durable worker job. Repeated commands return the original attempt, including cancelled history; different payloads cannot reuse a key.

The selection and reservation enter `committed`. Their requirements remain frozen. Compatible requests may share that reservation; a stricter request cannot change an acquisition already underway. Full v1/v2 claims are unique per normalized downloader URL, including two connection records with the same URL. Different DNS aliases for one physical downloader are not automatically recognized as the same endpoint. Conflicting claims disclose no other owner's request, artifact or holdings.

The worker performs read-only preflight and checks both known hashes and the unique attempt tag. A pre-existing torrent is not adopted or retagged. Immediately before add, it rechecks authorization and settings and commits the sticky `external_may_exist` marker. No run whose marker is set can call add again. An absent transfer or a lost acknowledgement causes observation/reconciliation, not resubmission.

Every add retains the selected category/path, original layout, hash checking and disabled automatic torrent management. It selects the entire artifact; no file-priority, seeding-limit, delete, rename or cleanup commands are issued.

## Recovery and controls

| State | Meaning and next action |
|---|---|
| `queued` / `preflight` | No add has crossed the durable boundary; cancellation can release claims |
| `submitting` | Boundary committed; a transfer may exist even if the process dies |
| `uncertain` | Poll for the existing transfer; never repeat add |
| `downloading` | Full identity, attempt tag, destination, category and management mode agree |
| `held` | Permission, configuration, association or content needs attention; retains claims |
| `complete` | Download manifest reconciled; file inspection and ABS confirmation remain necessary |
| `cancelled` | Cancelled before the submission boundary; no torrent was removed |

A four-minute lease fences concurrent worker deliveries. The complete network phase is bounded to three minutes. A worker crash leaves the marker and lease intact; recovery after expiry observes external state. The minute scheduler re-enqueues due observations only when the recorded job is no longer active. Existing stalled-job recovery now includes the download tasks.

Owner-only GET/list, pre-submission cancellation, and cooldown-controlled recheck routes back the UI. A disabled/read-only account cannot mutate attempts; authenticated owners can still read their history. Cancellation during preflight invalidates the worker token and releases identity claims. Cancellation after the boundary is refused without changing qBittorrent. Recovery mode prevents new work. Disabling new dispatch still allows observation of an already-submitted attempt, but prevents automatic inspection handoff.

Changing saved credentials, source generation or import settings after submission holds the attempt and retains its claims. Rebinding an existing attempt to corrected settings is not implemented yet; do not edit database state or discard the history as a workaround. This repair workflow remains part of S05/S09.

Book merge/undo is refused while a committed reservation is outstanding. This prevents a canonical identity correction from releasing a possibly active transfer. [Fulfillment reconciliation](DOWNLOAD-FULFILLMENT.md) now closes completed, satisfied request reservations while preserving torrent identity claims. Historical fulfillment no longer permanently blocks book correction; uncertain transfers remain protected. Explicit identity repair and shared-file reuse remain pending.

## Completed-file handoff

The observed non-padding file paths and sizes must exactly match the saved native torrent manifest; the reported torrent total must match its padding-inclusive total. qBittorrent omits padding files from its file index while `totalSize()` uses libtorrent's total: [upstream file indexing and size](https://github.com/qbittorrent/qBittorrent/blob/release-5.2.3/src/base/bittorrent/torrentinfo.cpp), [API serialization](https://github.com/qbittorrent/qBittorrent/blob/release-5.2.3/src/webui/api/serialize/serialize_torrent.cpp). This integration consumes those interfaces; no upstream implementation is copied.

On administrator-owned completion, the worker atomically queues the existing read-only inspection under the frozen worker root and exact torrent directory or single-file path. Activity links to its review. Actual file identity, book/version assignment and safe publication still use the existing import workflow. Members receive an explicit administrator-review state; their filesystem permissions are not elevated. Neither completion nor inspection establishes ownership.

[Single-file inspection and publication](SINGLE-FILE-IMPORTS.md) now support both direct-root and nested save mappings without enumerating neighboring downloads. There is no automatic content matching/import, shared-pack reuse across different works, automatic ranking or list automation yet. Existing source endpoint policy and full live client/filesystem compatibility still require certification before normal activation.

## Evidence

Database/HTTP fixtures exercise atomic rollback, concurrent and aliased idempotency, identity conflicts across works and connection aliases, cancellation in preflight, permission/reason/config changes during network work, lost responses, invisible uncertain transfers, process death after add, unrelated transfers, exact completed manifests, known padding, inspection enqueue, scheduler recovery, cross-account privacy and guarded downgrade.

The browser journey saves a selection, starts one synthetic transfer, observes 25% progress in Activity, verifies cancellation is unavailable after submission, reloads and checks mobile/desktop layout. These fixtures are not real MAM/qBittorrent transfer certification. Original media and real user accounts were not used.
