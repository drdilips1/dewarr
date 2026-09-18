# Download defaults and profile inheritance

Release preferences resolve per field: a saved profile's explicit values override personal defaults, which override installation defaults, which override the built-in Balanced values. Leaving a field unset inherits it. Editing one field in the UI records only that override; “Use inherited …” removes it again. Existing profiles with complete stored preferences remain explicit and keep their previous values.

This applies to ebook/audio format order, source order, ranking criteria, blocked formats and maximum transfer bytes. Empty format/source preference lists are invalid. An explicit empty blocked-format list clears an inherited preference; an explicit null maximum removes an inherited profile limit. These are ordinary preferences. Independent request restrictions, administrator-approved destinations, permissions and installation capacity limits remain enforced and cannot be relaxed here. Ownership is unchanged.

Open **Personal and installation download defaults** from a book's Sources preferences, or `/download-preferences`. Members edit their own defaults. Administrators additionally edit installation defaults. Saved profiles are still private. The editor keeps inherited values visible, and the effective-preferences view shows the source of each value. Changing defaults does not rewrite files or replace running torrents.

## Acquisition behavior

Source search, reviewed selection and list activation use the same resolver. Their snapshots include effective values, field origins and an effective revision. The browser sends that revision when starting search, selecting an inspected release or previewing a list policy; stale resolved preferences return a conflict instead of silently using new values. Replaying an already accepted idempotent search still returns its original receipt and frozen preferences.

Automatic selection and pre-dispatch authorization compare current effective preferences with the original snapshot. A changed effective policy holds an unsubmitted automatic acquisition. An existing external transfer keeps its original selection and is observed without a replacement download. A changed default used by a standing list requires another activation preview. Existing submitted acquisition/import decisions continue to retain their original snapshots.

A fully explicit profile masks changes to lower-level defaults. Sparse profiles inherit changes only for fields they omit. Older receipts without field origins remain readable; matching compares their actual saved values and profile identity/generation rather than requiring newly added presentation fields.

The current slice does **not** claim the entire FR-20 inheritance contract. Independent request restrictions and list media/routes already have their own policy behavior, but arbitrary request/list ranking overrides and inheritance of language, desired media, narrator, series scope and destination preferences remain unfinished. Those settings must join the same explicit precedence model before S06/S07 acceptance.

## API and storage

| Route | Behavior |
|---|---|
| `GET /api/acquisition/preferences/personal` | Own explicit overrides, effective/inherited values, field origins and edit revision |
| `PUT /api/acquisition/preferences/personal` | Replace own sparse overrides with expected revision |
| `GET/PUT /api/acquisition/preferences/installation` | Same contract, administrator only |
| `/api/acquisition/profiles` | Existing profile routes now persist sparse preferences and return their resolved snapshot |

Replacing overrides with `{}` restores inheritance. Revision checks include the edited layer's generation and inherited effective values, so stale concurrent edits and an edit made before installation defaults changed are rejected. Profile/search/selection generation checks remain active. No API accepts a target user ID for personal settings.

Migration `0031_acquisition_defaults` adds installation/personal override records. Existing complete profile JSON is not rewritten. Populated defaults block downgrade to avoid dropping preferences; recover from a pre-upgrade backup. Restart API and worker together after migration. No additional service or secret is needed. Older standing-list configurations may request reactivation when their stored snapshot lacks the new resolution evidence; this preserves their authority boundary instead of silently adopting changed defaults.

## Evidence boundaries

Integration coverage exercises precedence, explicit clearing and restoration, sparse profile persistence, invalid values, concurrent/stale edits, private scopes, administrator/member/viewer authorization, frozen search replay, old snapshot compatibility, list authority changes, unsubmitted versus already-running automatic transfers, and the populated downgrade guard. Browser coverage is recorded separately in [Implementation Status](IMPLEMENTATION-STATUS.md). Fixture qBittorrent/source traffic is not live account certification. Full policy inheritance, collection/recording automation and remaining production qualification remain in scope.
