# Exact edition and recording acquisition

This increment enables the existing automatic acquisition action for a single-book audiobook release whose explicit ISBN and full narrator credits corroborate the requested catalog recording. It uses the same request, source selection, downloader and importer as ordinary acquisition. It does not create a catalog version from a tracker posting or treat different encodings as different recordings.

## User behavior

Choose **Request this recording** on the book page, save the wanted request and open its source search. **Prepare best eligible release** saves a selection; **Select and download automatically** uses an approved import route and proceeds through the existing download lifecycle. The request remains specific to the selected catalog version. A different edition already in the library does not satisfy it, and overall work ownership remains independent.

An exact ebook candidate requires a valid explicit source ISBN matching the selected edition. An exact audiobook candidate additionally requires the source's complete normalized narrator credits to match the catalog recording's known credits. ISBN-10/ISBN-13 equivalents, hyphenation and explicit ISBN prefixes normalize to the same checksum-validated identifier. A shared invalid value cannot establish identity. Names, release titles, source IDs and description prose alone do not qualify an exact recording.

Explicit contradictory abridgment claims block automatic selection. An independently required abridgment still needs a clear matching source claim. All existing title/author, language, format, size, availability, permission and route checks remain in force. Sources without an explicit usable ISBN remain reviewable for exact-version requests; ordinary unconstrained book requests retain their existing eligibility rules.

## Evidence and lifecycle

Automatic preparation freezes the selected version's identity revision, including identifiers, title, language, narrator credits, abridgment and publication year. The worker compares that revision before artifact inspection and after network I/O. Changed evidence produces an actionable held receipt instead of silently applying the new identity. A pending provider metadata conflict also blocks preparation.

New version-specific manual and automatic selections retain the full identity revision alongside their existing frozen requirements. Before dispatch, configuration validation checks that revision; automatically prepared exact versions also reject new provider metadata conflicts. A stale selection requires fresh preparation. Existing compatible versionless requests and receipts retain their behavior. Legacy pending automatic exact-version operations and prepared automatic selections without frozen identity require fresh preparation; stored manually reviewed selections retain their previous validation contract. No database migration is required.

Once a transfer may exist, identity changes do not authorize a replacement download or stop read-only association/status checks. Connection repairs still verify the same external transfer and route. Import authority independently checks the frozen version revision, so changed catalog identity holds publication while the existing torrent remains tracked. Current account access and route verification remain required.

Saved request and selection history remains readable after a semantic metadata correction, but still requires access to the exact version. Withdrawal of that catalog visibility hides the recording again. When corrected metadata conflicts with a required narrator, the request pauses before automatic import is queued; the completed transfer explicitly reports that review is needed. Other frozen identity changes are held by import validation. Neither path publishes files or reports ownership.

Source corroboration only qualifies a download candidate. Completed-file inspection independently checks embedded identifiers, title, authors and narrator evidence and maps the bytes to the requested catalog version. A different identifier or narrator holds the import without publishing a file or reporting ownership. Successful imports preserve source bytes, use the approved hardlink/copy policy and become available only after backend inventory confirmation. Replaying a completed selection does not submit another torrent or create another catalog version.

## Verification boundary and remaining work

Unit tests cover valid equivalent ISBNs, malformed IDs, missing/extra/wrong narrator credits and conflicting abridgment labels. PostgreSQL/API tests cover preparation replay, stable version counts, metadata changes while queued, during inspection and before dispatch, provider conflicts and legacy pending operations. Real generated audio workflows prove exact-version publication, immediate/delayed ABS confirmation, unchanged source bytes, hardlinks and rejected conflicting audio. Those workflows use synthetic downloader and ABS services; actual-service certification remains separate.

This is the explicit-ISBN single-book path, currently available through native MAM's typed ISBN field. It does not infer ASINs from prose, add metadata fields unsupported by other source adapters, establish per-child recording evidence for generic packs, resolve cross-provider duplicate editions or complete omnibus containment. Those remain requirements in the version/collection and source qualification stages. Exact constrained packs remain held until their own per-book evidence is established.
