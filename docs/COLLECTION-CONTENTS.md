# Verified books in one library collection

An inseparable ebook omnibus or audiobook collection remains one real Audiobookshelf item. An administrator can open **Review collection contents** from My Library or a book's library copies, select two to one hundred complete catalog books and confirm the item's contents. This is an explicit review of the actual library item, not an inference from its title, series name, tracker description or a neighboring file.

The collection retains one backend item and one Open in Audiobookshelf link. Its verified contents establish ebook or audio ownership for each selected work, with an **In collection** label. No child files, separately playable backend items or catalog editions are created. The collection's ISBN, narrator and language do not establish a particular edition or recording for each child. Standalone, exact-version and other uncorroborated version constraints remain unsatisfied.

## Review, reconciliation and correction

The review requires an available, complete, nonsupplementary backend observation with file inode and modification evidence. It freezes the selected works, bibliographic evidence and ordered file identities. Ordinary resync preserves unchanged coverage. Changed metadata, missing/invalid observations or changed file evidence invalidates the confirmation; returning to an earlier observation does not automatically restore it. The administrator must review the current item again.

Invalidated contents remain visible as needing verification, but do not report ownership. Compatible unconstrained requests wait for collection review before another copy can be acquired. An explicit standalone request remains independent. A currently confirmed separate copy can still satisfy a request.

Only administrators can change coverage. All readers see contents and ownership only through their existing library permissions. Library grants, inaccessible backends and current inventory state continue to control availability. Reviews use the same integration/asset lock order as inventory publication and optimistic revisions that include current file evidence. Concurrent reviews cannot overwrite each other silently.

The existing correction journal records the administrator, previous associations and accepted proof. Undo restores the previous ordinary match or collection when it is still the latest decision and evidence has not changed. Correct match deliberately replaces collection coverage; its history can restore the previous collection. Changed files prevent undo from resurrecting an old confirmation.

## Storage and deployment

Migration `0038_asset_containment` adds nullable `library_assets.containment`; ordinary assets retain their existing behavior. `asset_contains` remains the ownership projection. The collection proof and correction history retain the accepted set and evidence, while the inventory worker manages its validity. Old historical ordinary-match undo records retain their previous comparison contract.

Back up PostgreSQL and the encryption key, stop the old API/worker, apply the migration and restart both at the same revision. A populated collection or its correction history prevents a destructive downgrade; restore the pre-upgrade backup instead. No downloader, source or playback service is added.

## Verification scope and remaining work

Automated API/inventory tests use synthetic ABS HTTP observations with explicit file identities. They cover ebook/audio ownership, one physical item, no new catalog versions, standalone/narrator/language constraints, repeat sync, sticky invalidation, private grants, revision races, correction and undo. Browser verification uses the real application API with its synthetic backend fixture, including catalog selection, confirmation, reload, the shared item link, mobile layout and reversal.

This delivers reviewed containment for an already observed library item. [Reviewed omnibus import](COLLECTION-IMPORT.md) also carries explicitly confirmed contents through inspected-file publication and backend detection, retaining the independently verified physical collection edition. Automatic collection discovery and unattended contents verification remain required: a pack's claimed membership cannot authorize this proof. Per-child editions/language/narrator evidence, richer internal navigation and broader actual-service/filesystem qualification also remain open. These increments do not complete FR-26 or the full S04/S06 gates by themselves.
