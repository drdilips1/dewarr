# Ebook formats and companion imports

S04 implementation checkpoint. PDF and CBZ inspection, reviewed same-edition formats and PDF companions now use the existing frozen-plan/publication workflow. This does not complete the importer or acquisition stages.

## Supported inspection

| Format | Evidence collected | Boundary |
|---|---|---|
| EPUB | Package metadata and nonempty, local spine resources | Structural inspection; no content extraction or completeness inference |
| PDF | Document title/author/language where present, page count, valid page dimensions and readable content streams | Strict pypdf parsing; no rendering, OCR, document scripts, attachment execution or automatic decryption |
| CBZ | Decoded JPEG/PNG/WebP pages and optional ComicInfo title/writer/language/series evidence | Container stays intact; no extraction; unsupported page types, animation and unsafe entries are held |

All formats still require a work/version match and complete-book confirmation. A valid PDF can be a sample or companion. Neither filenames nor page counts establish that it is a complete edition.

PDF/CBZ parsing runs in a disposable child with only the pinned read-only source descriptor passed as input. The parent limits elapsed time to 20 seconds and output to 1 MiB; the child uses a 15-second CPU limit and, on Linux, a 1 GiB address-space limit. Inputs are capped at 512 MiB. PDF/CBZ limits include 10,000 pages, 32 MiB per content/image page and 512 MiB cumulative expanded content. CBZ additionally bounds decoded dimensions/pixels and rejects special entries, path traversal, duplicates and encryption. EPUB/CBZ reject oversized, multipart and ZIP64 directories before ZIP allocation. macOS lacks the Linux address-space enforcement; production container/resource certification remains required. A child process is resource isolation, not a complete OS sandbox.

Generic archives remain separate from these book containers. ZIP/RAR/7z extraction is not enabled. MOBI/AZW3/CBR and other formats without a byte inspector remain held; a naming preview is not proof that a format can be imported.

## Review and grouping

Ordinary ebooks start in separate proposed groups. To combine EPUB and PDF copies, move them into one group and confirm **these files are different formats of the same complete ebook edition**. A group can contain one file per format. Different editions and multiple ebooks of the same format remain separate. Changing group membership or roles clears the editor's confirmation. Conflicting embedded titles/authors are not resolved by choosing the first file; the catalog match remains a separate decision.

A PDF's file-role selector offers **Complete ebook** or **Audiobook companion document**. A companion must belong to an audiobook group and does not participate in audio track ordering, ebook ownership or catalog-edition creation. Audio metadata supplies the group's title/contributors. The PDF is hardlinked/copied alongside that recording and must appear in the exact ABS file set before confirmation. Source originals remain unchanged.

Reviewed roles and same-edition assertions are stored in immutable grouping history. A plan freezes its group revision, metadata and destinations. Existing cancellation, protected-sibling and stale-plan checks apply unchanged. These fields use existing JSON documents; no database migration is needed.

## ABS inventory and format evidence

ABS chooses a primary ebook file, preferring EPUB in the certified version. It can label other ebook files supplementary even when the user reviewed them as complete formats of the same edition. Consequently, generic inventory must not promote every neighboring PDF into another book.

After a confirmed reviewed import, the app records the selected complete formats against one library asset/version. Subsequent inventory retains those assertions only while backend path, format, size, inode and modification-time evidence agree. Changing or removing an alternate format removes its complete-format assertion while leaving an unchanged primary book owned. Reappearing at an old path does not silently restore that assertion. A primary-file switch preserves the other reviewed format when its evidence remains unchanged.

An audiobook's PDF companion is retained as a supporting-file observation without a new ebook catalog version or verified work coverage. Existing historical versions are not destructively deleted. The work's overall availability still follows confirmed complete media.

## Verification and remaining work

The tests cover actual PDF/CBZ bytes, malformed/encrypted files, XML entities, ZIP directory budgets, pinned-descriptor probing, grouping consent, incompatible groupings and companion roles. Database tests exercise reviewed EPUB+PDF publication, repeat-import suppression, refreshed format projection, a changed primary, and lost verification after an alternate changes. Browser coverage exercises consent reset/persistence and companion selection on mobile.

The [native ABS harness](ABS-NATIVE-CERTIFICATION.md) includes six application workflows: EPUB, two-track audio, PDF, CBZ, EPUB+PDF and audio+PDF companion. Each checks exact backend confirmation, unchanged source bytes/hardlinks, inventory refresh and duplicate skip. These fixtures do not certify every possible PDF/CBZ, scanner mode or filesystem.

Remaining S04 work includes automatic identity matching, inseparable omnibus coverage, other format inspectors, file-alias reconciliation, watcher detection and the complete recovery/compatibility matrix. The source/downloader and external-list stages remain separate pending work.

References: [pypdf reader contract](https://pypdf.readthedocs.io/en/6.19.0/modules/PdfReader.html), [Pillow decoding and limits](https://pillow.readthedocs.io/en/stable/reference/Image.html), [certified ABS scanner](https://github.com/advplyr/audiobookshelf/blob/v2.36.1/server/scanner/BookScanner.js). Parser usage is original app code; dependency notices are recorded in the [reuse ledger](REUSE-LEDGER.md).
