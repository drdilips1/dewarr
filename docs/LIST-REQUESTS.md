# Reviewed requests from a list

List owners can open **Request books**, select up to 100 titles and preview the media they want. Selection supports title/author filtering, 25-book pages, select-page and clear controls. It starts with Either medium, preferring audio only when neither medium is available. Both, ebook and audiobook are also available. Language, destinations, standalone copies and unabridged audio are optional controls. Specific catalog editions or recordings are still selected on the individual book page.

The preview counts **media targets**, not books: Both can show an available ebook and a missing audiobook for one title. Either is satisfied by an acceptable complete copy in either medium. Stale inventory remains a check-inventory state, and confirmed missing prior copies remain a decision state. Compatible active requests belonging to the same user are shown as already requested; another user's private requests and list reasons are not exposed. A pending target is not an ownership badge.

Saving creates ordinary wanted-media requests with this list as an independent reason. It does not select a release, submit a torrent, import files or change reading status. This implements the manual subset of FR-12/FR-33 and the shared batch request path for later automation. Per-list automatic policies, profile inheritance, future-only baselines, backfill/catch-up and unattended list-to-library acquisition remain unfinished requirements. The interface explicitly describes the current boundary.

## Durable command and receipt

`POST /api/lists/{list_id}/requests/preview` records a bounded, owner-only preview under an idempotency key. The selection, bibliographic identity and request specification are frozen; changing the selection creates another preview. At most ten unsubmitted previews are retained per owner, and a preview expires after 24 hours. Accepted operations and completed receipts are not pruned by that limit. Recent history has server pagination.

Submitting the preview atomically enqueues `lists.requests` in the existing PostgreSQL queue. The worker rechecks owner authority, membership, identity, destinations, preview lifetime and current inventory. It acquires canonical work locks in a consistent order and calls the same request service used by book pages. Compatible targets share its existing reservations; requests with different requirements retain separate intents. Every selected request, independent list reason, evaluation job, audit entry and completion receipt commits in one transaction. A worker crash rolls the entire batch back; retry cannot leave half the batch committed.

A completed receipt is historical evidence of saving requests. Reopening or resubmitting it never reactivates a reason removed afterward. A fresh preview is an explicit new request. Current target counts are recomputed independently of the receipt, including inventory changes and access loss. Titles that are no longer visible are redacted. Shared-list readers cannot inspect or submit the owner's previews.

Cancelling an uncompleted batch prevents it from saving requests. Cancellation and worker publication serialize on the list: if saving already completed, the UI directs the owner to manage the saved request reasons. This command never cancels a client transfer or deletes files. Removing a book from the list or deleting the list uses the existing reason-withdrawal path; reasons from another list or a direct request remain independent.

## Recovery and limits

Queue exhaustion produces a visible retry action. Retrying reuses the frozen command and revalidates it; changed membership/identity or an expired preview requires a fresh preview. Recovery mode blocks submission and worker execution. Stalled-job recovery includes the new task. Ordinary requests and batch children take command/list/work locks in compatible order, including when an ordinary request races the same child command.

The 100-book limit is explicit and validated server-side; no selected books are silently truncated. It bounds one atomic manual transaction. This does not implement complete large-list acquisition or the future bounded automatic backlog scheduler. The book picker uses the list's currently loaded catalog entries; the existing list-detail API's larger-list limitations remain pending.

This change uses the existing operation ledger and needs no new database migration. Run API and worker from the same revision so both recognize `lists.requests`; do not roll back worker code while those jobs remain queued. Normal download dispatch remains disabled by default.

## Verification

Twenty PostgreSQL/API scenarios cover medium-specific availability, Either, compatible pending targets, different destinations/languages, repeated/concurrent commands, overlapping lists, reason withdrawal, no downloader dispatch, worker rollback, queue failure/retry, cancelled batches, expiry, identity/membership/role changes, list deletion, destination revocation, private history, title redaction, retained receipts, bounded previews and an untruncated 100-book batch. A lock-contention test checks an ordinary request racing a batch child command.

The browser journey creates its own two-book list, previews Both, cancels before saving, requests a subset, waits for the real API/worker receipt, reloads it and checks mobile layout. Provider/download behavior elsewhere in the browser suite uses synthetic services. Aggregate results and remaining stage gates are recorded in [Implementation Status](IMPLEMENTATION-STATUS.md); this manual batch is not evidence that automatic list acquisition is complete.
