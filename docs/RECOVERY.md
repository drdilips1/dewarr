# Application-state backup and restore review

This is a partial implementation of **S09-02 / FR-36 / AT-25**. It provides a versioned offline backup, a restore into a new database with a persistent pause, and [read-only external observations](RECOVERY-OBSERVATIONS.md). It now supports [reviewed recording of matching existing transfers](RECOVERY-RECONCILIATION.md) and [fresh ABS inventory reconciliation](RECOVERY-INVENTORY.md), but does **not** yet provide complete external-state reconciliation or a supported resume command. Use it for a recovery rehearsal; do not switch your working installation to a restored database expecting automation to resume in this build.

## What the bundle preserves

| File | Contents |
| --- | --- |
| `manifest.json` | Format version, backup UUID/time, application schema, PostgreSQL major version and SHA-256/size for each payload |
| `database.dump` | PostgreSQL custom archive of application tables and the durable queue |
| `app_key` | The encryption key required to decrypt restored provider credentials and private references |
| `settings.json` | Effective application configuration: origin, cookie/session settings, provider origins, paths and pool size |
| `journals/<entry UUID>.json` | Publication receipts copied from the configured staging root |

The key is checked against every non-null encrypted column before backup and after restore. The original database URL/password and bootstrap token are not exported as configuration. Credentials already encrypted in the database remain in its archive. The complete bundle is sensitive: directories are created with mode `0700`, files with mode `0600`. Store the complete directory in private backup storage and preserve those permissions. Checksums detect corruption; they do not authenticate an archive from an untrusted party.

Downloads, library media, staged media and temporary publication files are **not** in this bundle. Back those up separately and preserve their current state during a rehearsal. PostgreSQL cluster roles, TLS certificates and external secret files are deployment responsibilities. An application-state backup is not a replacement for a production PostgreSQL backup/WAL policy.

The implementation uses PostgreSQL's [custom archive format](https://www.postgresql.org/docs/current/app-pgdump.html) and [single-transaction restore](https://www.postgresql.org/docs/current/app-pgrestore.html). A dump can contain executable database code; restore only a trusted installation's backup. The current command requires the same application schema revision and PostgreSQL server major version at source and target. Install matching `pg_dump` and `pg_restore` binaries on the operator host; the application container does not currently package these tools. Container and cross-version qualification remain open.

## Take a backup

1. Stop **all** API and worker processes for this installation, including processes from older builds. Leave PostgreSQL running. Wait at least 60 seconds after the last worker heartbeat if the worker did not remove its heartbeat on shutdown.
2. Ensure the configured staging/journal directory is mounted and readable. Keep other programs from modifying the app database or journals during the backup. Current API/worker entrypoints hold shared maintenance locks; the command takes an exclusive lock and refuses to run while these processes are active. The lock is cooperative, not a substitute for stopping older processes or arbitrary SQL writers.
3. From the repository and its configured environment, run:

```sh
uv run python -m app.state_bundle backup /private/backups/book-search-2026-09-19
uv run python -m app.state_bundle verify /private/backups/book-search-2026-09-19
```

The directory must not already exist. A completed manifest is written last. Failures retain an incomplete private directory for inspection; verification refuses missing, corrupt, undeclared or unsupported entries. Existing import history requires a configured journal root. If you previously changed staging roots, preserve those older roots separately as additional recovery evidence: the command snapshots the currently configured root. Journal limits are 10,000 receipts, 4 MiB per receipt and 256 MiB total; exceeding a limit fails the backup instead of silently omitting evidence. Symbolic-link entries and non-regular files are rejected.

Restart the original API and worker after verification if the original installation should continue operating. An old database backup can lag current remote downloads, files and list changes; the restore process accounts for this by withholding all automation.

## Restore into a new database

The configured PostgreSQL role must be able to create databases on the selected server and connect to its `postgres` maintenance database. The restore uses that role's existing connection settings; it does not provision database roles. Supply the username of an active administrator **already present in the backup** as the designated recovery operator.

```sh
uv run python -m app.state_bundle restore /private/backups/book-search-2026-09-19 \
  --database book_search_rehearsal \
  --operator your_admin_username \
  --output /private/recovery/book-search-rehearsal
```

Both the database name and output directory must be new. The command never cleans, drops or overwrites an existing database. It sets a persistent database-level pause before importing the archive, verifies the restored schema/key, removes every old login session, and records an active restore checkpoint naming the operator. Queue rows, command receipts, workflow states and existing publication evidence remain intact for later reconciliation. The restored copy does not modify the source database.

The output directory contains `restore.env`, the key, the original manifest and reference copies of publication journals. These copied journals are **not** written over the live staging root. They may describe an earlier filesystem state and must be compared with current receipts and physical files.

Start only the API on a separate port after reviewing the generated origin, cookie settings and path mappings:

```sh
BOOK_ENV_FILE=/private/recovery/book-search-rehearsal/restore.env \
BOOK_PUBLIC_URL=http://localhost:8002 BOOK_COOKIE_SECURE=false \
uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8002
```

The localhost example uses HTTP; configure the correct HTTPS origin/cookie settings for a proxied deployment. `BOOK_*` environment variables override the generated file, so remove stale shell/container overrides, especially `BOOK_DATABASE_URL` and `BOOK_SECRET_KEY_FILE`. Let the app parse `restore.env`; **do not source it as shell code**. The generated configuration sets recovery mode and disables download dispatch. The active checkpoint and database pause independently block ordinary worker startup even if the environment flag is changed. The explicit recovery worker is restricted to observations and approved local transfer, inventory, [publication corrections](RECOVERY-PUBLICATION.md) and [list baselines](RECOVERY-LISTS.md).

Sign in with the selected operator's existing credentials. The recovery screen replaces ordinary navigation, labels workflow counts as saved evidence, and explains why automation cannot resume. Other users cannot sign in; normal authenticated routes return `423`. The operator can read their session/recovery review, start read-only observations, inspect their findings, review matching-transfer, inventory, per-book publication and external-list baseline, outbound-evidence and historical-command corrections and sign out. To process observations, start `uv run python -m app.jobs.worker --recovery` with the same restored `BOOK_ENV_FILE`; see the [observation contract](RECOVERY-OBSERVATIONS.md). Existing temporary `BOOK_RECOVERY_MODE=true` diagnostic behavior on a database without a restore checkpoint is unchanged.

## Interrupted or rejected restore

A failure after database creation retains the new database and output directory. It never resumes work or alters the source. A database pause survives interruption after `pg_restore` commits but before checkpoint insertion; API startup then refuses an incomplete restore, and workers cannot start. Inspect the failure offline, correct its cause and rehearse into another new database/output directory. Remove an abandoned test database only after confirming its exact identity and that it is no longer needed; the command deliberately supplies no force-cleanup option.

A missing/wrong operator, mismatched encryption key, incompatible schema, failed PostgreSQL command or corrupt bundle is a failed restore. Do not remove the pause to get past it. PostgreSQL command errors are deliberately summarized without echoing connection strings, provider data or archive content into application logs.

[Outbound recovery](RECOVERY-OUTBOUND.md) can now record current saved-command outcomes, invalidate old write leases and retain unresolved sent attempts without replay. It does not resume automation or resolve all uncertain effects.

## Remaining reconciliation and resume contract

No supported resume control is available yet. Read-only observations now collect the following evidence; the remaining S09-02 implementation must review and reconcile it against current authority before permitting effects:

- Current downloader census by application tags, hashes, save path and category, including transfers created after the backup and therefore absent from the restored ledger.
- Current source/staging/published-file evidence, with receipt/inode/path checks and independent outcomes for each child of a partially imported pack. A historical receipt alone cannot authorize a move, replacement or deletion.
- Qualify the reviewed fresh ABS inventory and repair current library permissions; media deleted or moved after backup must not retain an automatic owned badge merely because it was present in the database snapshot.
- Current external list memberships and uncertain outbound results, with no historic backlog or blind replay of sent writes. Expired comparisons and approvals require fresh evidence.
- Explicit, durable resolution of every ambiguous or untracked effect; old queued work must not resume merely because its restored state says it had not yet been sent.

Final AT-25 qualification still requires a populated restore with an actual external transfer ahead of the backup, partial publication, deleted library media, list changes and a deliberate resume without duplicate download/write/import. Measured RPO/RTO, upgrade fixtures, container execution and shipped-platform qualification remain separate open release gates.
