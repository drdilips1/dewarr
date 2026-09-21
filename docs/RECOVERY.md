# Backup and recovery

Keep the database, `config/app_key`, and library media together in your backup plan. The app key decrypts saved integration credentials; losing it makes those credentials unrecoverable.

The [Docker guide](DOCKER.md#backups) describes a stopped-writer PostgreSQL backup. Keep backups private and outside the repository.

Dewarr also includes an offline state-bundle tool:

```sh
uv run python -m app.state_bundle --help
uv run python -m app.state_bundle backup --help
uv run python -m app.state_bundle restore --help
```

Stop the Dewarr container (or both native API and worker processes) before backup or restore. Use the same Dewarr version that created the bundle and restore into a new database. Keep the source database and backup until you have verified the restored installation.

A restored bundle enters recovery review. Ordinary jobs and historical download approvals remain blocked, and only the designated administrator can sign in. The recovery worker performs supported reconciliation tasks:

```sh
BOOK_ENV_FILE=/path/to/restore.env uv run python -m app.jobs.worker --recovery
```

Follow the generated restore configuration and review instructions. Do not remove recovery flags or directly start an old download queue to bypass review. Automated return to normal operation is not yet supported; retain the original installation until recovery has been verified.
