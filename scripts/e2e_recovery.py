"""Install/remove a restore-review UI fixture in the disposable browser database only.

This is not a restore rehearsal: real offline dump/restore is tested separately.
"""

import json
import os
import sys
from urllib.parse import urlsplit
from uuid import UUID

import psycopg

checkpoint_id = UUID("9e5673bc-2292-4b61-aea8-a6fa3059054e")
url = os.environ.get(
    "BOOK_E2E_DATABASE_URL",
    "postgresql+psycopg://book@127.0.0.1:55438/book_search_browser_test",
)
if not urlsplit(url).path.endswith("_browser_test"):
    raise SystemExit("Recovery UI fixtures require a disposable _browser_test database")
with psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://")) as connection:
    if sys.argv[1:] == ["pause"]:
        actor = connection.execute(
            "SELECT id FROM users WHERE username = 'reader' AND role = 'admin'"
        ).fetchone()
        if not actor:
            raise SystemExit("Run the baseline setup journey first")
        previous = connection.execute(
            "SELECT id, enabled FROM integrations WHERE kind = 'qbittorrent' "
            "AND base_url = 'http://127.0.0.1:13379/qbit'"
        ).fetchall()
        if not previous:
            raise SystemExit("The baseline synthetic downloader is required")
        connection.execute("DELETE FROM login_sessions")
        connection.execute(
            "INSERT INTO restore_checkpoints(id, operator_id, backup_id, active, snapshot) "
            "VALUES (%s, %s, %s, true, %s::jsonb)",
            (
                checkpoint_id,
                actor[0],
                checkpoint_id,
                json.dumps(
                    {"fixture_connections": {str(key): enabled for key, enabled in previous}}
                ),
            ),
        )
        for key, _ in previous:
            connection.execute("UPDATE integrations SET enabled = true WHERE id = %s", (key,))
    elif sys.argv[1:] == ["clear"]:
        checkpoint = connection.execute(
            "SELECT snapshot FROM restore_checkpoints WHERE id = %s", (checkpoint_id,)
        ).fetchone()
        if checkpoint:
            for key, enabled in checkpoint[0].get("fixture_connections", {}).items():
                connection.execute(
                    "UPDATE integrations SET enabled = %s WHERE id = %s", (enabled, UUID(key))
                )
        connection.execute("DELETE FROM recovery_scans WHERE checkpoint_id = %s", (checkpoint_id,))
        connection.execute("DELETE FROM restore_checkpoints WHERE id = %s", (checkpoint_id,))
    else:
        raise SystemExit("Choose pause or clear")
