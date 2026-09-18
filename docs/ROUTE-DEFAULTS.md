# Inherited downloader and import destinations

Downloader and ebook/audiobook destination choices now use the existing sparse preference hierarchy: request override → list override → selected profile → personal default → installation default. An explicit acquisition route takes precedence over these defaults. No default grants permission or enables automatic acquisition.

## Settings and user experience

**Downloader and destination defaults** is a collapsed section in the default, profile and request preference editors. Choose a default downloader and separate ebook/audio destinations. Each field shows its origin and an action to restore inheritance. **No saved default** writes an explicit null; resetting removes the override so a lower layer can apply again.

Manual release selection, automatic single-book selection, list policy activation and reviewed-series acquisition use the resolved preferences. A unique compatible route can still be offered when there is no preference. An unavailable or incompatible saved choice is not replaced with another route just because only one other option exists; choose another route or fix the preference. Library names remain restricted to accessible integration options.

List and series forms distinguish an inherited default from an explicit selector choice. Saved automatic list configuration retains the original route options as well as the resolved route. Reopening a list editor preserves inheritance; it does not silently turn the previously resolved default into a permanent override. The activation preview remains authoritative for the accepted configuration.

## API and execution contract

`ReleasePreferences` and sparse `PreferenceOverrides` accept `downloader_id`, `ebook_destination_id` and `audio_destination_id`. Their values are references to existing configured integrations/destinations, not paths, credentials or approval records. Defaults can be stored before routes are ready, but use requires current validation.

Automatic list previews may omit downloader/generation and individual medium routes to inherit them. A series request may send `automatic: {}` to opt into acquisition through configured defaults. Explicit downloader choices still require their observed generation, and explicit destinations retain their observed revision. Both/Either require a resolvable route for each medium.

The server resolves omitted choices, validates current visibility, downloader readiness, path mapping, destination probe and automatic-import approval, then freezes actual IDs, generations and approval evidence with the preview. A route cannot conflict with the request's required library. The preview shows the final serving library separately from the overall work ownership indicator.

Activation checks the preview again. Standing list execution reconstructs the original options and compares the resulting full configuration with the accepted one. A changed preference, destination, downloader or approval requires review; re-resolution cannot silently renew consent. Series execution retains its accepted profile and concrete route snapshot. Dispatch and publication continue to use the existing final authority checks.

`PolicyConfiguration.route_options`, when present, reports the original route choices so editors preserve inheritance. Its concrete `downloader_id`, `downloader_generation` and `routes` fields remain the accepted result. Existing explicit-route policies remain valid without `route_options`.

## Compatibility and evidence

No schema migration is required beyond `0037_download_joins`: preferences and frozen policies already use JSON. Unset route fields are omitted from full snapshots so adding this capability does not change legacy no-route effective revisions. Sparse override serialization preserves explicit nulls. API and worker should be deployed from the same revision before saving new route preferences; older binaries do not understand these added preference fields.

Tests cover precedence and clearing, private destination rejection, unavailable-default handling, explicit override, stale approval rejection, list execution with inherited routes, and series execution with inherited routes. Four real-file workflows cover list and series acquisition with immediate/delayed ABS confirmation using inherited routes. Source/downloader/ABS responses remain synthetic; the database, queue, inspection, hardlinks and import records are real. Exact suite, browser and runtime evidence is in [Implementation status](IMPLEMENTATION-STATUS.md).

This implements destination-route defaults. Inherited Complete series expansion, reviewed changes to accepted unsatisfied requests, broader version/omnibus semantics and the remaining PRD stages are still required.
