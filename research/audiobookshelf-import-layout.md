# Audiobookshelf import and organization contract

Planning specification, September 17, 2026. Source inspection and current documentation inform this design; it has not been validated against a running ABS installation. This refines [the architecture](../PRODUCT-ARCHITECTURE.md) and [collection handling](metadata-and-collections.md). No existing library is being reorganized.

## Backend constraints we must respect

ABS's [directory documentation](https://audiobookshelf.org/docs/documentation/libraries/book-library/directory-structure/) describes author / optional series / book paths. Media at a structural ancestor can collapse descendants into a single item. Disc subfolders have special grouping support. Audio files within an item are tracks, so two complete narrations do not become selectable editions merely by changing their filenames.

Its [ebook documentation](https://audiobookshelf.org/docs/documentation/libraries/book-library/ebooks/) allows audio and ebooks in one item, with at most one primary ebook and supplementary files. Only the primary ebook has reading progress; EPUB is preferred during initial primary selection. Separate editions needing independent identity/progress therefore need separate items. An ebook destination must use an appropriate book library with “Audiobooks only” disabled.

The inspected [directory scanner](https://github.com/advplyr/audiobookshelf/blob/master/server/utils/scandir.js) creates leaf groups but parses folder metadata from the last three path components. Thus author / series / book / version can produce separate leaf items, yet infer the wrong title, series and author. Watcher scans also consider scannable non-media files, so structural parents must not hold shared covers or sidecars. This behavior supports investigating nested layouts with explicit metadata; it is not an unconditional compatibility guarantee for every ABS version.

The [book scanner](https://github.com/advplyr/audiobookshelf/blob/master/server/scanner/BookScanner.js) applies configured metadata precedence and reads sidecars. The [OPF parser](https://github.com/advplyr/audiobookshelf/blob/master/server/utils/parsers/parseOpfMetadata.js) supports title, author, narrator, identifiers, language and series/sequence information. We can export resolved item metadata without rewriting seeded media.

## Recommended default: one book version per item folder

Use separate audiobook and ebook destinations, mapped to ABS library folders. They may be separate ABS libraries or appropriately configured roots; the connector records their actual IDs and paths. Example names below are fictional.

```text
/data/library/
  audiobooks/                         ← ABS library folder root
    Alex Morgan/
      Harbor Trilogy/
        01 - 2018 - The First Harbor {Jordan Lee}/
          The First Harbor.m4b
          metadata.opf
          cover.jpg
        01 - 2024 - The First Harbor {Casey Reed}/
          The First Harbor.m4b
          metadata.opf
          cover.jpg
        02 - 2020 - Beyond the Harbor {Jordan Lee}/
          001 - Beyond the Harbor.mp3
          002 - Beyond the Harbor.mp3
          metadata.opf
  ebooks/                             ← ABS library folder root
    Alex Morgan/
      Harbor Trilogy/
        01 - 2017 - The First Harbor [First edition]/
          The First Harbor.epub
          metadata.opf
        01 - 2023 - The First Harbor [Revised edition]/
          The First Harbor.epub
          metadata.opf
```

This layout makes the book/version the ABS item boundary while retaining author and series hierarchy. Our app joins all those items under one work. Sidecars supply the clean title so labels such as “[Revised edition]” need not pollute display titles. Audio year means recording release year here; ebook year means edition publication year. Original work year remains separately available. Missing dates omit the date segment rather than guessing from tracker posting time.

For a standalone book, omit the series segment. Series numbering is optional and preserves decimals. Canonical series membership and a selected filing author determine one physical home even when catalog data lists several series/authors. Preserve all credited authors and series in metadata; do not duplicate hardlinks into multiple scanned folders merely to represent those relationships.

Same narrator does not imply same recording. When natural labels collide, add an edition/recording descriptor and stable short internal version key. Do not put arbitrary internal IDs in ASIN syntax: export a real ASIN only when known. Human labels can change without changing our identity mapping.

## Optional layout: group versions beneath the book

Offer a second preset for the requested physical grouping:

```text
/data/library/audiobooks/
  Alex Morgan/
    Harbor Trilogy/
      01 - The First Harbor/           ← structural container only
        2018 - The First Harbor {Jordan Lee}/
          The First Harbor.m4b
          metadata.opf
          cover.jpg
        2024 - The First Harbor {Casey Reed}/
          The First Harbor.m4b
          metadata.opf
          cover.jpg
```

The analogous ebook preset places each distinct edition in its own leaf under the shared book container. This remains several ABS items, aggregated as one work by our app. It does not add native version switching to ABS.

The integration must ensure that generated leaf metadata takes precedence over misleading folder inference, and verify the resulting item boundaries and identity. Ancestors contain only structural directories: no audio, ebooks, shared cover images, OPF/NFO/JSON metadata, or description files. Put our import bookkeeping in our database outside scanned roots. Do not name a version directory “Disc 1” or “CD 1,” which has grouping semantics. Keep actual disc folders inside a recording leaf.

Treat this preset as a compatibility-gated option until scanner and live import fixtures pass for supported ABS versions. Default to the conventional layout; do not promise that simply adding another folder level gives correct metadata. Setup diagnoses a metadata-priority mismatch and explains the required adjustment rather than silently changing global settings.

## Version and format grouping rules

| Content | Default destination treatment |
|---|---|
| One recording with many MP3 tracks | One leaf item, ordered track files; optional supported Disc folders |
| Two narrators performing the same work | Separate leaf items |
| Two recordings by the same narrator | Separate leaf items with recording identity disambiguation |
| Full M4B plus full MP3 rendition of the same recording | Select preferred representation; keep unused rendition outside scanned library, or explicitly import as separate items |
| EPUB and PDF of the same verified edition | May share an ebook item; one primary and one supplementary |
| Revised, translated, or otherwise distinct ebook editions | Separate leaf items by default |
| Companion PDF with an audiobook | Supplementary within that recording's item; not automatically ownership of a full ebook |
| Full ebook alongside one recording | Optional combined item; default separate destinations preserve independent edition metadata |
| Indivisible omnibus | One asset with verified constituent-work mappings; no invented separate files |

File presence alone does not establish a complete ebook: distinguish companion material using source evidence and inspected contents. Equivalent file formats do not create catalog editions. Multiple audio encodings also remain one recording in our catalog even if explicitly retained as separate backend items.

## Parsing a tracker collection into individual destinations

Folder names are useful evidence, alongside source metadata and embedded file tags. Tracker pack-level title, author, year or narrator cannot automatically become the metadata of every child book.

1. Preserve source release ID, original paths, file list and description. Wait for download completion and stable readable paths.
2. Identify candidate book/recording groups from immediate folders, disc folders, tags and filename patterns. Flat collections require per-file identity; numbered MP3 files may be chapters of one book, not separate books.
3. Match each group against known series works and candidate editions. Use file/source clues to corroborate title, author, sequence, narrator, language, identifiers and duration; do not assume global source metadata applies to all groups.
4. Resolve per-item naming metadata under the configured provider rules. Source and filesystem details remain available as optional tokens; clean catalog fields supply default names.
5. Produce an import manifest mapping every selected source file to a work, version, backend item group and destination. Each group records confidence and a reason for any unresolved mapping.
6. Skip already-owned acceptable versions; isolate ambiguous groups for correction while importing confidently resolved books. Reserve covered targets to avoid concurrent duplicate acquisition.
7. Create each completed item in staging, with hardlinked media and newly generated sidecars. Publish it to its final path and reconcile with ABS.

Example transformation:

```text
Download: Harbor.Complete.Collection/
  Book_01_First_Harbor_JLee/track01.mp3
  Book_01_First_Harbor_JLee/track02.mp3
  Book_02_Beyond_Harbor_JLee/Beyond.m4b

Library: Alex Morgan/Harbor Trilogy/
  01 - 2018 - The First Harbor {Jordan Lee}/001 - The First Harbor.mp3
  01 - 2018 - The First Harbor {Jordan Lee}/002 - The First Harbor.mp3
  02 - 2020 - Beyond the Harbor {Jordan Lee}/Beyond the Harbor.m4b
```

Renaming destination hardlinks does not rename source files. Archive extraction and media conversion produce independent outputs; preserve the seeded originals and account for additional storage.

## Naming settings and preview

Normal setup chooses roots, a layout preset and whether to rename imported files. Defaults are already complete. “Customize naming” exposes folder and filename templates separately for audio and ebooks, with a token picker rather than requiring users to learn a template language.

Supported token groups should include:

- Catalog: author/author-sort, title, subtitle, series, sequence, original-publication year.
- Version: edition name/ID, publisher, edition-publication year, recording-release year, narrator(s), language, abridgment, ISBN and ASIN where known.
- File: actual extension, codec where applicable, track/disc number, original basename.
- Source: provider name, release ID, original release title and posting date, explicitly distinguished from publication date.

Use explicit token names such as `recording_year`, `edition_year`, `original_year`, and `source_posted_year`; a generic “year” must state its policy. Conditional segments remove empty punctuation. Fallback narrator/edition labels must not imply guessed facts. Sanitize separators, reserved characters and path lengths after interpolation; constrain all results to the configured destination. Token syntax in the eventual UI is not decided by these illustrative names.

Preserve true extensions; naming must not turn MP3 into M4B. Track names use stable zero-padded ordering derived from verified disc/track information. Ambiguous ordering stays reviewable. Filename simplification must not collapse several tracks to the same path. Case-insensitive collisions, different editions with identical labels, and pre-existing unrelated files all require deterministic disambiguation.

Preview displays original path → final path, grouped book/version, resulting ABS item count, and fields missing from metadata. It includes both first import and addition of another recording. Structural validation detects mixed media at parents, alternate recordings combined as tracks, improper disc folder use and unintended metadata inference. Changing a template affects future imports; existing managed items require a deliberate migration plan to preserve backend identity and progress.

## Publishing and confirming the import

Keep staging outside all ABS library roots on the destination filesystem. Validate each item before an atomic directory rename into its final place. A multi-book pack is published as several complete items; it is not globally atomic. Avoid exposing loose media in author, series or work-container directories even temporarily. Existing-item updates need a separate coordinated strategy, not an assumed atomic directory replacement.

Hardlinks require compatible source/destination filesystems and path mappings. Sidecars and covers are new managed files, not blindly copied pack-wide metadata. Do not rewrite embedded tags through a hardlink: that changes seeded bytes. Do not carry a stale source `metadata.json` into the leaf if it would override freshly resolved data.

The connector checks effective metadata precedence for the target library and writes only supported sidecar fields. OPF is the initial export candidate; unsupported version attributes remain in our own database. We must not assume arbitrary custom OPF fields are understood by ABS. If ABS exports its own metadata.json, define ownership and precedence before attempting future metadata refreshes.

After scanning, confirm expected item path, selected media files, author/title/series/sequence, narrator/edition evidence and actual media availability. A successful scan request alone is not confirmation. Store our version ID → ABS instance/library/item ID mapping. Missing or merged items become actionable import issues, not additional download requests. ABS libraries scope items independently; our app provides cross-library work aggregation.

## Implementation acceptance cases

Before enabling the preset in the eventual app, verify against supported ABS releases:

- Standalone and series books, decimal sequence, missing year/narrator and non-Latin names.
- A series pack creates the expected separate book items and correct track order.
- Two narrators create two backend items while our app shows one owned work.
- Identical narrator/year labels but different recordings remain distinct.
- Nested versions keep title, author and series correct through sidecars and precedence.
- Multiple ebook editions remain separate; equivalent-format supplements do not pretend to have independent progress.
- A companion PDF does not falsely satisfy a full-ebook acquisition intent.
- No partial publication or parent sidecar causes watcher grouping errors.
- Retries and collisions preserve seeded source files and existing library items.
- Changing naming defaults alone does not move existing files or reset progress.

These are future compatibility acceptance checks, not a request to evaluate or replace the user's current stack.
