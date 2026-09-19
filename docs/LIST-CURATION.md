# Local list curation and household sharing

List owners can edit a name and description, choose household sharing, add catalog books in batches, select/remove entries and change their order. These actions operate on local membership. They do not alter reading status or write to an external provider list.

## Reader controls

Books appear before external connection settings. Catalog addition and list editing open only when requested. **Edit list** opens one form for the name, description and **Share with this household** setting. Sharing deliberately exposes that list and its permitted book metadata to signed-in accounts on the installation. It does not grant editing rights, library access, acquisition-policy access or the owner's provider credentials. The index distinguishes **Shared by you**, **Shared with you** and **Private**.

**Add books from catalog** offers title/author search, twenty results per page and a selection of up to one hundred catalog books. Selections survive catalog-search pages. Existing memberships, including unloaded pages, are labeled and the server always deduplicates canonical identities. The picker explains that adding a book to a list with an active automatic policy can acquire missing media through that existing policy.

The list grid fetches fifty books per page from the server. Owners can select the displayed page, clear selection or remove selected entries. Single-book remove buttons use the same receipt-backed command. Removing a synced entry preserves its exclusion; a deliberate local re-add keeps it as local membership without silently clearing that external exclusion. Removal does not delete files, cancel unrelated reasons or remove other lists' memberships.

Move earlier/later uses a server-side relative move with a current-membership revision, including across page boundaries. Hidden memberships left after source/library access revocation retain their positions; owners can reorder visible books without submitting inaccessible IDs. Canonical aliases remain one displayed book.

## Concurrency and replay

`POST /api/lists/{list_id}/curation` accepts `action=add|remove`, one to one hundred distinct work IDs, an optional expected content revision and an `Idempotency-Key`. The list owner and current member role are rechecked under the ordinary owner context. A command locks list → actor → command → identity graph, matching existing list operations.

The full batch validates accessible identities before mutations. Adds preserve the selected canonical order and existing local entries. Removes exclude matching external observations, delete the appropriate canonical-family memberships, and withdraw only that list's ordinary/automatic reasons in canonical lock order. The changes, completed operation receipt and redacted audit event commit together. A failure rolls the whole batch back. The action creates no separate download pipeline or unconditional acquisition job.

Repeating the same key and command returns the saved receipt. It cannot re-add books removed since the original addition, or remove a new membership episode after the original removal. Reusing a key for different options is rejected. Deleted lists and revoked edit permissions cannot be recovered through old receipts. The UI retains failed mutation variables for **Retry same edit/addition**, or lets the user explicitly refresh and clear the selection.

Content revisions include actual membership-row identities, origin/canonical IDs and positions. Removing and re-adding a work is therefore a new revision even if its position is unchanged. The list detail response holds a shared list lock and shared identity lock while producing the displayed order and revision; a concurrent writer cannot stamp old content with a new revision. An optional revision also protects the legacy full-order endpoint.

`PATCH /api/lists/{list_id}` now changes only supplied fields. A sharing-only patch preserves the name and description; explicit `description: null` clears it. Name/shared cannot be null. The editor submits its captured settings revision, so another tab's change produces an actionable conflict instead of a lost update. Reload is deliberate and closes that editor; ordinary polling does not replace an unsaved draft.

## Privacy and refresh

List index/detail queries fetch fresh data on remount/focus, discard inactive cache and refresh every fifteen seconds while active. Errors hide retained list content. Unsharing returns 404 to another reader, causing the open view to disappear on its next refresh. This is polling-based revocation, not an instantaneous push guarantee. Book detail uses the same freshness/error rules so a revoked shared catalog link does not keep displaying a cached private book.

Library badges are computed for the reader. A shared title can be owned for the list owner and unowned for another account without exposing the owner's inventory. Subscription, policy and request-history endpoints retain their owner-only controls. Viewer accounts can read eligible lists but cannot curate them, including by calling the API directly.

## Evidence and delivery limits

Coverage includes atomic/concurrent edits, exact replay, changed command keys, canonical aliases, membership episodes, external exclusions, rollback, independent reasons, stale settings/order and simultaneous read/write snapshots. Member/viewer tests cover shared catalog metadata, reader-specific ownership, private connection endpoints and revocation. Separate ebook/audio journeys exercise list addition → automatic search/dispatch → real-file hardlink import → delayed synthetic ABS confirmation → membership removal with media retained.

The browser journey covers catalog bulk add, ordering, editing, conflicting tabs, explicit sharing, a separate household viewer, revocation, keyboard bulk removal and preserved library ownership. Results and deployment evidence are recorded in [Implementation Status](IMPLEMENTATION-STATUS.md).

The subsequent [list pagination increment](LIST-PAGINATION.md) adds server pages, full-list membership checks and searchable destination/request/backlog selectors. The complete large-list performance gate still requires the reference benchmark corpus. Optional Hardcover write-back, full task-based usability, actual-service qualification and remaining S08/S09 gates also remain open. It does not complete the full PRD.

No database migration, runtime dependency or new provider credential is needed. Deploy the generated API client/frontend and matching API/worker code on `0038_asset_containment`. New completed `lists.curate` operations are command receipts, not queued jobs.
