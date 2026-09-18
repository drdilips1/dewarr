# Automatic series-pack coverage

The automatic selector can now acquire a known series pack for one missing requested book. This implements the catalog/manifest eligibility dependency of automatic pack acquisition. [Automatic pack groups](AUTOMATIC-PACK-GROUPS.md) now combine independently authorized compatible selections before dispatch. Additional series target expansion, later/submitted-transfer reuse and import of unrequested books remain outside this checkpoint.

## Default behavior

`prefer_series_packs` is an inherited release preference, enabled by the built-in default. It uses the existing installation → personal → profile → list → request override resolver and appears under Series search in download preferences. Turning it off makes this automatic selector choose single-book candidates only. This is independent of `search_series`, which controls extra search queries. Reviewed source selection remains available.

A qualifying pack precedes single-book candidates. Among eligible packs, the existing ordered format/source/seed preferences apply. Once inspected, format ranking uses the requested child's files; an unrelated sibling's M4B cannot improve an MP3 target's format score. Pack-level narrator names do not establish the requested child's preferred narrator. Exact editions/recordings, required narrators and required abridgment remain reviewable until per-child source evidence is supported.

The normal single-book ceilings remain 1 GiB for ebooks and 10 GiB for audio. A catalog-qualified pack has a 50 GiB whole-transfer ceiling and at most 20 additional identified published books. Profile and independent request limits may lower the size ceiling. Padding and extras count toward transfer bytes. The existing five-manifest inspection budget, slots, automatic-transfer budget and destination storage checks still apply. Administrative customization of all pack-specific limits remains part of the full policy workstream.

[Automatic series preparation](SERIES-PREPARATION.md) now loads missing or stale supported catalogs before source queries begin. Unavailable metadata leaves ordinary source search available with a warning.

## Coverage evidence

Each new automatic-selection operation freezes a bounded context from the requester's own series catalogs fetched within 24 hours, using only currently accessible canonical works. It examines at most three series and 200 members per series. A series beyond that member limit is not used. Unknown publication, future publication, compilations, partial records, canonical aliases and ambiguous/unknown positions cannot contribute automatic child coverage. The target itself must qualify.

A matching catalog series name plus corroborating source author makes a collection eligible for torrent inspection. Neither that name nor tracker `coverage` claims prove the contents. The actual manifest must map each primary file to exactly one catalog book using an exact normalized book-title filename or parent folder, optionally preceded by an explicit position. Substring matches, numbers without titles, unknown siblings and ambiguous alternatives fail closed.

An ebook child has one primary file. An audio child has one folder and encoding, at most 500 files, and recognizable track names when there are multiple files. Multi-disc, alternative-encoding and omnibus ambiguities stay reviewable. Actual downloaded track tags/completeness, embedded identity and version requirements are still checked by the importer. Supported companions remain companions and never establish ebook ownership.

Queued receipts expose separate single-book and eligible-pack ceilings; the selected receipt shows the chosen transfer ceiling. The saved evidence is labelled `catalog-and-manifest`, not verified file contents. The API and candidate details show the series, matched book titles and which book was requested. Frozen series context and current work identity are checked again after manifest resolution and before downloader submission. Changed catalog scope or access holds the operation/attempt. Legacy operations without a frozen pack context cannot gain collection eligibility through replay.

## Acquisition and import

Manual automatic-selection commands and standing list automation call the same selector. A supported pack goes through the existing atomic selection/attempt/capacity/job transaction, qBittorrent association and importer. Current route approval and all original requester/list authority checks remain binding.

Only the existing target is authorized by this operation. Other pack books are retained in the seeded download and exposed for review; they do not create wanted requests or owned badges. If the requested book was fulfilled before dispatch, normal inventory/reservation checks prevent a new download. The target gains availability only after its correct destination item/files are confirmed in Audiobookshelf. Replaying the command or list tick does not submit again.

This boundary is deliberate incremental implementation, not the final series experience. The next work must automatically populate/refresh missing series catalogs under the existing provider budget, then use the explicit transfer-membership ledger to authorize and reserve every compatible missing child, retain independent list reasons, select coverage across overlapping requests, and reuse the shared attempt without granting authority through a hash match. Complete-series expansion, omnibus containment, mixed routes/media, full recording equivalence, source parity and live-service qualification remain required.

## Verification and deployment

Unit coverage exercises filename/folder boundaries, unsupported alternatives, wrong authors, ambiguous series, per-child constraints, target formats and byte/book limits. Database tests exercise immutable catalog evidence, preference opt-out, changed access/publication, pre-dispatch revocation, legacy replay and pack preference over a more-seeded single book. Real EPUB/hardlink workflows exercise both an explicit automatic request and a standing-list addition, with immediate/delayed ABS fixture confirmation, retained unrequested siblings and one submission.

This change adds no database table or migration. It adds frozen JSON evidence and an inherited preference; restart API and worker together at the same revision. It does not enable installation dispatch. Older binaries may reject the new frozen preference; rollback requires a compatible revision or the normal pre-deployment backup/restore procedure with dispatch paused. Live tracker/ABS compatibility and the full production gate are not implied by fixture success. See [implementation status](IMPLEMENTATION-STATUS.md) for actual results and remaining requirements.
