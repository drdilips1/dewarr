# Inherited acquisition scope

The same preference layers now carry desired media, Either's first medium, required language, abridgment, required narrators, standalone-copy requirements and ebook/audio library choices: request → list → selected profile → personal → installation → built-in. Exact edition/recording IDs remain book-specific request options. They are not global profile defaults.

The built-in media choice is unset: choose media on the request or save a default. Either defaults to trying audio first when neither medium is already available. Existing library ownership still means either complete medium. Both can remain partially wanted when the work already has an ebook. Scope preferences do not remove ownership badges, rename files or replace an existing transfer.

A browse-only list needs no media setup. When no media choice exists, its inventory preview uses Either and labels the origin **Browse inventory**. This is not an acquisition default or download authorization. A later manual or automatic acquisition still needs an explicit or inherited media choice.

## Editing and preview

The defaults and profile editors expose **Media, language and library defaults**. Request/list media selectors offer inheritance. Other request scope choices are available with the existing request preference controls. **Effective request scope** on previews and saved request cards shows the actual resolved media, language, abridgment, standalone requirement and library choices with their origins; release ordering remains a separate summary.

Omitting an option inherits. Explicit `language: null` means any language; `abridged: null` accepts either abridgment; `standalone: false` permits an omnibus; a null library leaves destination selection for acquisition. Reset removes the override. The first-medium preference is relevant only to Either. Defaults belonging to the other medium do not become contradictory constraints on a one-medium request. Explicit contradictory request options are rejected.

A library preference identifies the desired serving library. It does not grant access, select an arbitrary filesystem path or authorize automatic imports. Automatic list policies still require verified per-medium import routes and current standing approval. A route that conflicts with an inherited required library is rejected. The preview attributes an automatic policy's final library to its selected import route.

## Narrator requirements and preferences

**Required narrators** is an audio-only, all-of requirement. Every listed name must be established; unknown names do not pass. `required_narrators: []` explicitly clears inheritance. Ebook-only requests ignore inherited narrator requirements; explicit nonempty audio requirements on an ebook-only request are rejected. Both/Either apply the narrator requirement only to their audio target. Existing overall ownership remains independent: a complete accessible ebook still gives the book its green check.

Names normalize Unicode compatibility forms, whitespace and case for comparison. Duplicate names are removed without inferring aliases or stripping meaningful punctuation. Input accepts up to 32 names, each up to 200 characters. An exact recording request also retains its catalog version identity; matching names alone never establishes that recording.

Planned compatible reservations combine all required names. An already selected transfer is immutable: a stricter narrator reason shares only when existing requirements or frozen exact-recording evidence establish the names. A tracker-only claim is insufficient for that reuse. Final inventory satisfaction checks the target's own requirements, not another request's preferences.

Selection checks the source's narrator claims. Import checks both the chosen catalog version and inspected audio credits before freezing the plan; automatic matching continues to require recording evidence. Missing or conflicting credits hold the group for review. Explicit semicolon-separated embedded credits are supported; commas and slashes are not guessed as separators. No source tags are rewritten. Frozen version revisions and publication checks prevent later catalog changes from altering an accepted import silently.

**Preferred narrators** is separate soft ranking, described in [Download preferences](DOWNLOAD-PREFERENCES.md). It never changes ownership or rejects an otherwise eligible recording by itself.

## Durable contracts

`RequestOptions` is the sparse input. `RequestSpec` remains the strict resolved contract stored on an intent and used for inventory satisfaction, compatible reservations, source selection and import. Request previews now return `specification` alongside the profile snapshot. Accepted requests and their independent reasons retain policy provenance. Per-book edition/recording constraints and independent transfer restrictions remain binding.

List configuration retains both original sparse `scope_options` and resolved `specification`, plus the original preference overrides. Revalidation must use the original options. An empty object means inherit everything; it must not be treated as absent and replaced by the resolved values. Doing so would turn inherited choices into overrides and misattribute later changes.

A manual list batch freezes its effective request specification before acceptance. The worker uses that specification and the accepted profile. Repeating a request or batch key returns its recorded result; pre-inheritance request commands can replay against their original explicit defaults. New commands distinguish an omitted option from an explicit clear.

General source searches remain usable for compatible strict scope targets; they do not bypass language, version, destination or transfer restrictions. A request with custom release overrides still needs a bound search, and a general search cannot silently substitute a different explicitly selected request profile. An otherwise-default request can use a profile deliberately chosen for its source search.

Default changes can invalidate unsubmitted previews or standing list authority. They do not rewrite accepted requests or running transfers. A separate reviewed revision workflow is still required to apply changed scope to already-unsatisfied requests.

## Compatibility and remaining work

This extends existing JSON policy records without adding a database table or column; schema remains `0032_request_release_policy`. Back up before upgrading and restart API and worker together. Expanded effective-profile fingerprints can require refreshing old previews/searches and reactivating a standing list. Do not run an old binary against newly written policy JSON; rollback uses the pre-upgrade backup and existing external-transfer reconciliation procedure.

Full series policy/expansion and reviewed revisions of unsatisfied requests remain unfinished. Narrator requirements and preferences do not establish automatic recording equivalence. Existing library preferences do not complete destination-route default inheritance: automatic route selection/approval remains explicit. Live provider, deployment and full S06/S07 qualification remain separate gates.

Implementation and test evidence are recorded in [Implementation Status](IMPLEMENTATION-STATUS.md). Fixture services do not certify live MAM, qBittorrent or Hardcover accounts.
