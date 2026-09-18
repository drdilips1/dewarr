# Single-file downloads and imports

Inspection accepts a completed file or a completed directory beneath a configured worker download root. The API retains the same `relative_path` input; the worker determines whether that path is a regular file or directory. The UI labels it **Download path** and explains when only one file was inspected.

## Scope and source integrity

A file-scoped snapshot records `source_kind: file`, the original selected path, the parent directory's identity, and exactly one filename with its byte hash, identity and inspected metadata. It does not enumerate the parent or include neighboring downloads. Parent-directory activity from unrelated downloads does not invalidate an otherwise stable selected file; replacing the selected file or parent does.

Descriptor-relative reads reject symlinks, traversal, special files and unsafe ancestors. File reads retain the existing bounded media parsers, byte limits and mutation checks. The configured source root remains mandatory: an empty path or filesystem-root scan is not introduced.

The frozen import plan carries the scope into destination probing and publication. A file-scoped publication specification permits exactly one source file, whose name must match the selected path's leaf. It cannot expand to sibling files through grouping or an edited manifest. Naming still produces a complete library item directory with independently generated sidecars and artwork. Hardlink/copy handling, no-replace publication, cancellation, journal recovery and ABS confirmation use the existing pipeline.

Directory snapshots retain their previous representation. The publication fingerprint omits the default directory scope, preserving receipts created before this addition. New file-scoped receipts include the scope. There is no database migration; the additional evidence is stored in the existing snapshot/plan/specification JSON.

## Acquisition handoff

A saved torrent manifest can resolve to either a common torrent directory or one top-level file. The download worker derives the inspection path from the validated descriptor and frozen worker mapping, checks the path length before submission, and hands off that exact path after transfer reconciliation. Both direct-root and nested save mappings are supported.

No source file is moved into a new folder to accommodate the importer. The original qBittorrent path and bytes remain intact. A completed transfer still needs file inspection, reviewed book/version mapping, publication and backend confirmation before ownership is established. Dispatch remains an opt-in development capability; see [Download attempts](DOWNLOAD-ATTEMPTS.md).

## Evidence and limits

- Unit tests cover root/nested file selection without parent enumeration, sibling activity, selected-file/parent replacement, symlink/FIFO rejection, hardlink/copy publication, interrupted recovery, scope expansion rejection and directory-receipt compatibility.
- Integration tests run a standalone EPUB through selection → durable synthetic qBittorrent submission/observation → queued inspection → reviewed plan → actual destination probe/hardlink publication → synthetic ABS confirmation, for both root and nested save paths. Neighbor files remain untouched, ownership stays false before confirmation, repeated download commands reuse the attempt, and repeated imports skip the owned version.
- The real disposable ABS 2.36.1 harness adds single-EPUB and single-audio application workflows. Both confirm the catalog version, preserve source bytes/inodes, retain media formats after inventory refresh, support queued cancellation and skip duplicate imports. The wider native harness now has eight scanner cases and eight application workflows.
- The browser journey selects one EPUB by path, shows the scope explanation, matches it and saves a file-scoped plan. Existing directory/source/download flows remain exercised.

These checks do not certify a live MAM account or real qBittorrent transfer. Format/collection coverage, automatic matching/import, held-attempt configuration repair and post-import reservation/identity-claim reconciliation remain separate work. No full PRD stage is marked complete.
