# Automatic pack groups

Independently authorized automatic selections can now share one physical pack download. Each book must first complete its own source search, eligibility assessment, catalog/manifest coverage check and selection. The coordinator does not create requests from unrequested series members.

## From selection to dispatch

An automatic pack selection saves its prepared selection and a durable `acquisition.pack-dispatch` continuation atomically. Its status remains running while coordination is pending. Single-book releases retain the existing atomic selection/download path; preparation-only pack commands do not enter automatic dispatch.

The coordinator considers at most 100 waiting operations for the same owner and saved source artifact. If another covered book already has an active automatic-selection command but has not finished assessing releases, coordination retries for up to 60 seconds from the saved deadline. This bounded wait does not create authorization, wait for hypothetical future requests, or change the selected release. Expiry permits dispatch of the independently qualified selections already available.

Each child retains its own operation, intent, target, reservation, profile, work identity, catalog evidence, list-authority proof and approved route. Before grouping, the service locks command receipts, automatic operations, all relevant lists, principals and canonical works in deterministic order. It revalidates every child's current authority and requirements. A withdrawn or invalid child is held independently; an already-satisfied child is skipped and its unnecessary prepared selection is released.

Compatible children must have the same owner, artifact, medium, descriptor, source generation, downloader configuration, mapping and verified destination. Each needs its own automatic dispatch consent and pack coverage. Different routes/media are not silently combined. Existing endpoint/hash claims prevent a conflicting second physical transfer; incompatible scopes remain reviewable.

The shared download command explicitly records the representative and additional selection IDs. Each automatic root records the full group selection IDs and the same download ID. Memberships, committed reservations, one capacity record, torrent identity claims and one dispatch job commit together. Replays and competing coordinators cannot submit a second transfer.

## Authority and lifecycle

Every still-wanted child is revalidated at physical submission. One member's frozen approval is not group consent. A revoked required child proof holds the shared transfer before submission; a withdrawn/satisfied target no longer contributes demand. The existing sticky submission marker and association checks continue to reconcile uncertain outcomes without repeating add.

Cancelling a waiting automatic selection releases that child's prepared selection. It does not cancel another book's coordinator or a submitted shared transfer. After dispatch is accepted, the existing transfer cancellation and request-reason controls apply. A manual batch cannot repurpose automatic proofs, and the manual single-download route cannot bypass automatic transfer accounting while a prepared automatic selection waits for coordination.

The existing Activity view shows the shared transfer and its independently fulfilled books. Automatic-selection receipts show coordination progress and the number of independently authorized books when queued. The approved importer inspects actual files, retains seeded paths, checks each child's version/format/language requirements and confirms each expected ABS item before marking that child fulfilled. Unrequested files still do not gain import authority.

## Evidence and limits

The domain suite exercises concurrent coordination/replay, a pending peer assessment, deadline fallback, cancellation, ownership arriving before dispatch, withdrawn demand, changed catalog evidence, revoked child consent and manual-route bypass prevention.

Real synthetic EPUB/hardlink workflows cover two explicit requests and two overlapping automatic lists with distinct list-authority proofs. Both immediate and delayed ABS fixture confirmation are checked. The workflows assert one download, two memberships, two confirmed import entries, two fulfillments, retained source bytes, hardlinks and no repeat submission.

This coordinator coalesces selections ready before dispatch. [Saved-transfer reuse](DOWNLOAD-REUSE.md) now adds a separate join/import-continuation path for later compatible same-owner requests. Cross-owner or different-route/media sharing, inferred missing-book requests under Complete series, and omnibus/alternative-recording coverage remain required work, alongside native ABB, live integrations, discovery, production qualification and S10.

The original pre-dispatch coordinator required no schema migration; the subsequent reuse path requires `0037_download_joins`. Restart API and worker together; an older worker cannot execute the new continuation. Drain or reconcile pending coordination before rollback, or restore the compatible pre-deployment backup with dispatch paused. A production worker-shutdown issue already recorded in implementation status remains open; finite fixture tests are not a production certification.
