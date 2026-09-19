# Optional Hardcover list write-back

This implements the local-membership portion of S08-03 / FR-34 / AT-23. It adds explicit outbound changes to the existing [Hardcover subscription](HARDCOVER-LISTS.md), [list curation](LIST-CURATION.md) and [paged list](LIST-PAGINATION.md) services. Goodreads remains an inbound RSS/CSV integration. This checkpoint does not certify the complete S08 stage or a live Hardcover account.

## User contract

On an owned local list with a saved Hardcover subscription, expand **Sync local changes back to Hardcover**. Complete the first verified inbound observation, review the connected remote list, then choose **Enable future changes**. The remote list must belong to the connected Hardcover account. Following a public or collaborative list does not grant outbound authority.

Enablement is off by default and applies to subsequent local additions/removals. Enabling or re-enabling sends no backlog. Existing differences are not silently reconciled. Ordinary catalog additions, removals and accepted CSV additions participate; inbound observations do not create outbound changes. Each operation appears in the private Membership changes history. Sharing a local list does not expose these account controls or history.

**Pause write-back** stops further mutations under that policy generation. An already-sent change may still finish remotely; the app can observe its outcome without sending another mutation. A changed account, subscription, local membership episode or accepted book identity invalidates old unsent authority. Deleting the local list or detaching its subscription is held while a sent attempt remains uncertain, preserving access to its reconciliation controls. Both actions remain available once that uncertainty is resolved.

A conflict offers **Review difference**, showing the current local membership and a fresh remote observation. **Apply local state** records a new checked outbound intent; **Keep Hardcover state** adjusts this local list without echoing an outbound write. Reviews expire after five minutes and reject intervening changes. An unresolved earlier external attempt must be reconciled first. **Check remote state** performs reads only: it never authorizes a resend.

Library files, reading progress and download completion are independent. This increment has no automatic “downloaded → add to an available list” rule, no reading-status write and no remote-list creation, renaming, ordering or deletion. Acquisition continues through the separately configured [list policy](LIST-POLICIES.md).

## Provider contract and evidence

The adapter targets the [official Hardcover GraphQL schema at revision e8d38c8b7bd53cada7e97121ab0cacfa0804013c](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/e8d38c8b7bd53cada7e97121ab0cacfa0804013c/schema.graphql). Its four query/mutation documents have been validated against that schema. The official [action and scope reference](https://github.com/hardcoverapp/hardcover-docs/blob/main/src/content/docs/api/GraphQL/Actions.mdx) identifies the supported actions; actual account permissions still require live qualification.

| Operation | Contract |
|---|---|
| Ownership | Read `me.id` and the selected `lists.user_id`; require an exact owner match. Account access needs the applicable `read:me` scope, and list access needs the applicable list-reading scope. |
| Observe | Query the selected book within that list, including membership IDs and edition IDs. Ask for 101 rows and hold anything beyond the supported 100 rather than infer complete coverage. Malformed, hidden or partial responses prove neither absence nor permission. |
| Add | `insert_list_book(object: {list_id, book_id})`, with `write:lists`; validate the returned membership identity. Local work identity uses an accepted Hardcover identifier, never title similarity. |
| Remove | `delete_list_book(id: membership_id)`, with `write:lists`; remove only a membership observed for the selected book. Multiple edition memberships are handled independently. |
| Confirm | Re-read uncached membership. A mutation acknowledgement alone does not complete the operation. |

The enablement preview establishes ownership and readable state, not a successful write scope. A confirmed actual mutation supplies that evidence. Known permission rejection remains actionable; unsupported accounts retain inbound behavior. No upstream idempotency or compare-and-swap guarantee is assumed. A remote edit can race a read and mutation, so the app cannot promise atomic coordination with third-party writers; changed membership IDs and subsequent observations expose known conflicts.

## Durable implementation

Migration `0039_list_writeback` adds per-list policies and shared remote-list leases. Outbound records use the existing operation ledger and `lists.writeback` worker. The local curation edit, sequence and queued intent commit together, preventing a saved local command from losing its outbound record when queue insertion fails.

An intent retains the current policy/account/subscription generations, accepted book identity, local membership episode, observed remote membership, sequence and attempt history. Worker authority is checked again after network reads and before effects. Database transactions do not remain open across remote requests. A two-minute lease serializes mutations for the same remote owner/list even when several local lists reference it. Lease tokens fence stale worker responses; a persisted pending attempt survives process termination.

Mutations bypass the metadata cache and use one HTTP attempt. The existing account budget and cooldown still apply. Definite pre-send or rate-limit rejection can be scheduled under bounded rules. Timeout, ambiguous server error or malformed acknowledgement preserves an uncertain attempt. Observation retries never blindly repeat that mutation; after five unresolved observations the operation requests attention. A missing or exhausted worker job also becomes actionable without discarding its pending attempt.

Newer confirmed self-writes can supply the membership baseline before the next inbound snapshot catches up. This supports remove → confirm → re-add without mistaking the app’s own confirmed removal for an external conflict. A genuinely replaced membership ID remains a different remote episode. Uncertain prior attempts for the same book/list block subsequent mutations, including through another local binding.

Ordinary unsent intents expire after seven days. Explicit read-only reconciliation remains available for uncertain history. Re-enabling never replays expired or paused commands. Idempotent review/resolve receipts prevent repeated confirmation clicks from creating another local edit or outbound intent.

## Deployment and recovery

Back up the database, encryption key and installation configuration before upgrading. Stop the old API and worker, migrate to `0039_list_writeback`, deploy the generated client/frontend with matching backend code, then restart both processes. No extra service or dependency is required. Download dispatch remains independently disabled unless explicitly configured elsewhere.

Populated policies or outbound history block destructive downgrade: restore a verified pre-upgrade backup for rollback. An empty schema downgrade/upgrade is tested. Recovery mode prevents outbound network activity while preserving queued intentions. Full populated backup/restore reconciliation across actual external effects remains an S09 gate; testing the recovery flag is not equivalent to certifying that workflow.

Keep tokens in the existing encrypted account store and server-side gateway. Operation history contains identity and reconciliation evidence, not credentials. Do not clear uncertain records to force a resend: the original request may still have applied remotely.

## Qualification boundaries

Automated evidence covers adapter/schema parsing, cache bypass and error classification, API authorization and receipts, transactional queueing, worker concurrency/crash recovery, inbound echo suppression, remote membership replacement, pause/re-enable, local re-addition, migrations, and desktop/mobile conflict review. Exact results and deployed revision belong in [implementation status](IMPLEMENTATION-STATUS.md).

Remaining gates include live Hardcover permissions and mutation behavior, full restore reconciliation, broader provider/network failures under the declared compatibility matrix, and complete S08 task-based usability/accessibility/performance. Initial full-list difference review and an explicitly configured available-list rule are not implemented by this increment. No real account was mutated during fixture qualification.
