# Reading accounts

Onboarding and **Settings → Reading accounts** share the same connections and controls. Members and administrators can connect and follow lists; viewer accounts remain read-only.

## Goodreads

Open **My Goodreads books**, sign in on Goodreads if needed, and paste the resulting My Books or profile address. Numeric user IDs and shelf RSS links also work. The app validates the feed, discovers shelf names/counts from the public profile (including `tag=` links and empty shelves), and supplements discovery with shelf names present in the feed. If profile HTML is unavailable, the UI explicitly labels discovery as partial. A pasted shelf is selected by default; otherwise Want to Read is selected.

Goodreads data travels one way into local lists. RSS is a partial observation: missing books never imply removal. A one-time CSV import remains available from each list for historical coverage. **Find new Goodreads shelves** explicitly refreshes discovery; new shelves are not automatically followed. The profile/RSS key is stored encrypted per reader and never returned in account views. Changing the linked profile leaves previously tracked lists intact, and they remain visible under Tracked lists.

## Hardcover

Create the API token before pasting it into onboarding or **Settings → Metadata**. [Open Hardcover’s new-key form with these scopes selected](https://hardcover.app/account/api/keys/new?scope=read:catalog+read:me:content+read:lists+read:library:public+read:users+write:lists):

| Scope | Dewarr uses it for |
| --- | --- |
| `read:catalog` | Search, book, author, series, and edition details. Test connection runs a catalog search. |
| `read:me:content` | Your user id, so your lists stay separate from lists you follow. Email and role access are not required. |
| `read:lists` | Your lists, lists you follow, and private lists. |
| `read:library:public` | Public reviews on book pages. |
| `read:users` | Usernames on those reviews. |
| `write:lists` | Adding and removing books on lists you own. |

These six scopes cover discovery, list tracking, reviews, and list write-back. Tokens created before August 2026 already include this access. The same list is in the Metadata setup info button.

Use the saved Hardcover API token, or add it in the reading-accounts step. Browse paginated **My lists** and **Lists I follow**, then select lists to track. The same scheduling, manual refresh, and tracking controls apply. Private lists are supported when the token grants `read:lists`. Existing verified-membership and opt-in writeback controls remain available within each local list and need `write:lists`. Connecting or following a list does not enable writeback or downloads.

## Checks and persistence

New subscriptions queue their first check immediately and default to hourly checks. The existing durable worker schedules due lists every minute, with up to three minutes of stable per-list jitter. Frequency can be set between 30 minutes and 24 hours. Goodreads uses conditional requests when validators are available, a shared request budget, and delayed retries/backoff. Closing the browser does not stop the worker.

**Check for updates** queues a manual observation. Turning **Track** off pauses checks, fences in-flight observations, and preserves saved books/exclusions. Turn it on again to schedule another check. Discovery, list counts, and last/next-check times are distinct: a feed count is not proof that a complete Goodreads library has been imported.

Deploy the API and UI together and run `uv run alembic upgrade head` for migration `0046_goodreads_accounts`. The backup schema revision is updated accordingly. Keep the worker running for automatic checks.

Tests cover URL validation, bounded same-account profile redirects, tag/empty-shelf discovery, RSS fallback, encrypted keys, per-user isolation, duplicate follows, scheduled checks, pause preservation, private Hardcover lists, and onboarding/settings controls on desktop/mobile. Browser Goodreads responses are fixtures; the actual discovery adapter was separately checked against the supplied public profile.
