# Audiobookshelf inventory integration

Current implementation checkpoint, September 17, 2026. This is a partial S03 delivery; the complete PRD remains active. Tests use synthetic data and real PostgreSQL. No actual ABS installation has yet been certified.

## Connection and UX

Administrators open **Connections → Connect Audiobookshelf**, enter the backend-reachable URL and API token, and optionally a separate browser URL. URL prefixes are preserved. Tokens are encrypted server-side and never returned in API views. Local/private service URLs are intentionally supported; redirects are rejected so a configured token is not forwarded to another host.

Test connection reads account/library capabilities and reports scan access separately. It does not scan or alter the upstream library. **Sync library** enqueues durable inventory work; Activity shows its result. The scheduler checks due connections every five minutes; successful inventory schedules the next pass approximately 30 minutes later. Failed auth/permission/parser checks pause scheduled sync until repaired/restarted. Other typed failures schedule a later attempt.

My Library shows accessible copies, ebook/audio type, format, narrator evidence, state and a browser link into ABS. Book detail aggregates copies under the app work. Administrators grant member/viewer access per library; tokens and filesystem paths remain private. A manual match/unmatch persists across refreshes. Changed recording evidence is held for review even if its work was manually matched.

## Inspected upstream contract

The initial reference is ABS **v2.36.1** source, not an unversioned claim about every ABS server:

- [API router](https://github.com/advplyr/audiobookshelf/blob/v2.36.1/server/routers/ApiRouter.js)
- [Library controller](https://github.com/advplyr/audiobookshelf/blob/v2.36.1/server/controllers/LibraryController.js)
- [Library item controller](https://github.com/advplyr/audiobookshelf/blob/v2.36.1/server/controllers/LibraryItemController.js)

| Operation | Endpoint | Evidence used |
|---|---|---|
| Account/capabilities | `POST api/authorize` | Account identity, type, permissions and reported version |
| Accessible libraries | `GET api/libraries` | Book library IDs and names |
| Paginated membership | `GET api/libraries/{id}/items` | Uncollapsed minified IDs, total, update/missing/invalid markers |
| Expanded details | `POST api/items/batch/get` | Exact requested item set, book metadata and listed file evidence |
| Absence/move confirmation | `GET api/items/{id}?expanded=1` | Direct identity/library/media evidence or a typed 404 |
| Optional future import scan | `POST api/libraries/{id}/scan` | Adapter method exists; inventory sync does not invoke it |

The authorization response must not be persisted verbatim because it can contain sensitive session data. Only sanitized capabilities and a permission-scope fingerprint are stored. Unknown server version stays unknown.

## Snapshot and matching behavior

The workflow stages expanded items under an inventory run, verifies page totals/IDs and a second membership pass, then publishes bounded batches under a credential generation and renewable lease. Complete snapshots for accessible libraries are collected before publication so confirmed item moves can be reconciled across libraries. A final account/library check detects changed access. This is conservative reconciliation over a nontransactional upstream API, not an upstream snapshot guarantee.

A partial fetch never marks an omitted item deleted. Transient failure preserves prior confirmed ownership as stale. Known auth/permission revocation hides cached libraries until a fresh authorized pass succeeds. First healthy absence is suspected; a later healthy pass with a grace interval and direct lookup can confirm missing state. These observations never initiate replacement downloads.

Work matching uses persistent provider links or exact normalized title/contributor evidence, preserving ambiguous cases. ABS-originated works are private to granted inventory unless an independently public catalog record already exists. Recording/edition IDs remain app-owned. Distinct narrator/year/identifier evidence cannot overwrite an existing linked version. Cross-item equivalence requires corroborating version identity; narrator equality alone is insufficient. Companion PDFs alongside audio are conservatively supplementary.

Expired workers lose the right to publish. A replacement run discards abandoned staged observations; the former owner cannot overwrite the replacement operation's completion. Queue-terminal jobs are distinguished from live jobs before scheduling replacement work. Manual correction and publication use the same integration lock order.

## Evidence and remaining gates

`tests/contracts/test_audiobookshelf.py` exercises HTTP fixtures, database transitions, duplicate/concurrent commands, stale owners, interrupted pagination, permissions, manual links, missing assets and stable-ID library moves. The Playwright journey starts an isolated synthetic ABS HTTP service plus the actual app API/worker and validates connections, inventory, corrections and grants in the browser.

Manual match/unmatch now has administrator correction history and guarded undo; see [Identity corrections](IDENTITY-CORRECTIONS.md). Still required: actual-version ABS inventory/scanner certification; change-event handling; broader file/identifier move detection; canonical work merge/split; repair/ignore/replacement intents; full cross-provider identity reconciliation. File import, hardlink/layout certification and qBittorrent acquisition belong to later gates and are not established by these inventory tests.
