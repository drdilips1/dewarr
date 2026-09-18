# Hardcover list subscriptions

The list connection panel now supports Hardcover alongside Goodreads RSS. Connect a personal Hardcover token in Metadata, open a local list, choose Hardcover, and select from **My lists**, **Lists I follow**, or **Public lists**. Each picker has cursor pagination; a numeric list ID can also be entered. The existing encrypted account is reused. Subscription settings and source observations remain owner-only even when the local list is shared.

This checkpoint implements inbound membership observation. It does not activate acquisition, write lists back to Hardcover, change reading status, or infer ownership from list membership. Library availability still comes from permitted Audiobookshelf inventory. List policy activation, baseline/backfill choice and automatic acquisition remain separate PRD work.

## Membership contract

A worker collects pages using increasing membership IDs, then reads the list again and requires the same list metadata and every membership record. Both passes must reach an empty terminal page and match the advertised count before publishing any change. A short page is not a completion signal. Hidden books, malformed records, conflicting assertions, changed counts or changed second-pass content reject the observation and preserve the prior local state.

The API does not provide a documented transactional snapshot. Two matching passes establish a **verified observation**, not an atomic remote snapshot; a change after verification appears on a later refresh. All pages bypass the metadata cache, including stale fallback. The adapter uses the existing shared credential budget and provider cooldowns. A rate limit retains the checkpoint; staging older than 15 minutes restarts from the first page. Observations are capped at 5,000 memberships and fail explicitly above that bound. This is a safety bound, not complete large-list support.

Publication is one transaction. Newly observed books become source memberships unless locally excluded. A missing book loses only this source membership after a verified observation; independent local membership remains. Books excluded by the user stay excluded if the source removes and later restores them. Restoring an absent observation does not add it until it reappears. Pausing preserves history and exclusions. Detaching keeps current books as local members. Changing the remote list requires a separate local list or an explicit detach first.

Goodreads RSS retains its different contract: omissions never prove removal, and its count describes books **observed**, not an authoritative current shelf. CSV imports remain additive reviewed snapshots.

## Identity and privacy

Hardcover and Goodreads IDs have separate namespaces, including when their numeric values happen to match. Hardcover observation first reuses the owner's binding or a uniquely matched, visible accepted Hardcover catalog source. Otherwise it creates a private provisional book. A subsequent full catalog import can enrich that same bound book after bibliographic checks; it does not duplicate it or promote it to a public catalog record. Ambiguous or conflicting identity requires review.

Multiple remote memberships for one book become one local book membership, while edition IDs, source positions and membership IDs remain source assertions. These hints do not create editions, recordings, files or ownership. Existing local ordering is preserved; this implementation does not mirror remote sorting. Complete cross-provider identity reconciliation remains pending.

Every worker transaction rechecks subscription generation, enabled state, current owner authority and Hardcover credential generation. Rotating/disabling an account fences an in-flight observation. Historical completed operations remain completed on redelivery, including after a later pause. A disabled account does not stop other due subscriptions. Actor, account and catalog locks have consistent ordering; database contention tests cover account-save audit records and concurrent catalog/list imports.

Network calls occur outside database transactions. Intermediate records are saved in the owner's durable operation; credentials are not. The Activity API does not return operation payloads. Settings use the existing authenticated encryption. Failures expose sanitized messages rather than tokens or provider bodies.

## Delivery and evidence

Migration `0027_hardcover_lists` adds provider separation and observation presence. Existing subscriptions default to Goodreads and existing observations stay present. Downgrade refuses to discard Hardcover subscription, operation, binding or absence history; use a pre-upgrade backup. Upgrade before running the API and worker at the same revision.

Fifteen adapter/state-machine tests and fifteen database/API tests cover pagination, malformed and hidden responses, list choices, two-pass verification, private identities, source removals, local membership, exclusions, outage preservation, cooldown recovery, expired staging, credential/pause fencing, terminal redelivery, disabled-account scheduling, cross-provider ID separation, no cached list fallback, catalog enrichment reuse, actor/account lock ordering and separate member credentials. The browser journey follows a list through the real app API and worker against synthetic Hardcover responses, verifies omission and later addition, persists exclusions and pause, and checks mobile layout and secret-free reload. Aggregate results are maintained in [Implementation Status](IMPLEMENTATION-STATUS.md).

No real Hardcover credentials were available for live compatibility certification. Official [list schema documentation](https://github.com/hardcoverapp/hardcover-docs/blob/main/src/content/docs/api/GraphQL/Schemas/Lists.mdx) and [user relationships](https://github.com/hardcoverapp/hardcover-docs/blob/main/src/content/docs/api/GraphQL/Schemas/Users.mdx) informed the original GraphQL operations. [API setup and scope guidance](https://github.com/hardcoverapp/hardcover-docs/blob/main/src/content/docs/api/Getting-Started.mdx) remains authoritative for tokens and service restrictions. No upstream application implementation was copied.
