# Reviewed download connection repairs

An administrator can now repair their outstanding submitted acquisition after saved MAM, qBittorrent or Audiobookshelf connection generations change. The original release selection remains immutable. A separate repair ledger records what was reviewed and whether the existing transfer verified it.

## User flow

1. Update the connection in Settings and test the saved qBittorrent connection. If ABS credentials changed, reverify the destination route.
2. Open the download in Activity. **Review updated connections** appears when its saved configuration no longer matches the accepted configuration.
3. Review the affected connections and choose **Confirm and check existing transfer**.
4. The worker checks the existing transfer. Activity reports the repair outcome and retains the original download progress and history.

The preview and command are owner-only and administrator-only. Preview returns a revision and plain-language changes, not credentials, source artifacts or private filesystem settings. Other administrators cannot use this route to access another owner's attempt. Member-to-administrator operational handoff remains a separate pending capability.

## What can change

- MAM connection generation, while preserving the original encrypted artifact and selected release. Repair performs no MAM request or torrent-file refresh.
- qBittorrent credential generation on the same normalized endpoint, with the same submitted save path, category and worker mapping.
- Audiobookshelf credential generation with a freshly verified destination. The library identity, endpoint, root mapping, staging path, item layout and publication mode remain the recorded contract.

Changed download/library paths, another downloader endpoint, a changed selected version/canonical book, an invalidated probe or disabled connection are rejected with an actionable reason. This repair is not a server migration, torrent adoption, artifact replacement or importer-manifest rewrite. Previously frozen import plans need their own existing validation and repair flow.

## Durable behavior

Migration `0020_repairs` adds immutable proposed configurations and reviewed change summaries, with pending/applied/held states, operation receipts and an applied timestamp. One pending repair per attempt and command-key receipts prevent duplicate review jobs. Domain state, repair history and enqueue commit atomically; failed enqueue rolls everything back.

The existing acquisition worker and its lease/recovery scheduler execute the read-only check. It validates current authority and reviewed generations before network work, then again before recording its outcome. The observed full torrent identity, unique attempt tag, save path, category and management mode must match the original selection. Only then does the proposed configuration become the accepted overlay for future observation. No repair path calls qBittorrent add, changes file priorities, renames paths, removes torrents or updates tracker URLs.

An invisible transfer remains uncertain with the repair pending. Transient failures retry under the existing scheduler; process death preserves the lease, sticky submission boundary and reviewed proposal. Conflicting identity, revoked reviewing administrator access or changed settings hold the repair without accepting it. Earlier applied repairs remain historical records when another change is reviewed later.

New download dispatch may be disabled while an existing transfer is repaired and observed. Recovery mode blocks repair. Automatic inspection still requires its normal authorization and dispatch gate. If a completed transfer's request is already satisfied, it can close through library evidence without enqueueing a duplicate inspection/import; a withdrawn request needs review before importing.

## Verification and remaining scope

Integration cases cover each connection generation, preview staleness, concurrent/replayed commands, pending-repair guards, endpoint/path/category/destination/probe changes, permission/configuration changes during I/O, unknown/transient/conflicting observations, worker death, recovery mode, disabled dispatch, atomic rollback, successive repairs, completed-file handoff, already-satisfied completion and guarded downgrade. The browser edits a saved downloader, tests it, reviews and applies a repair, retains one synthetic transfer and verifies reload plus desktop/mobile layout.

These are fixture-based source/downloader checks. Live account/client certification, migration to a different physical endpoint or file route, shared-pack reuse, withdrawn-owner resolution and administrator handoff for member-owned work remain pending. A populated repair ledger refuses lossy downgrade; restore a pre-upgrade backup with external-state reconciliation rather than discarding repair history.
