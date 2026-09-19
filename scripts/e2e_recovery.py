"""Install/remove a restore-review UI fixture in the disposable browser database only.

This is not a restore rehearsal: real offline dump/restore is tested separately.
"""

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
        connection.execute("DELETE FROM login_sessions")
        connection.execute(
            "INSERT INTO restore_checkpoints(id, operator_id, backup_id, active, snapshot) "
            "VALUES (%s, %s, %s, true, '{}'::jsonb)",
            (checkpoint_id, actor[0], checkpoint_id),
        )
    elif sys.argv[1:] == ["clear"]:
        connection.execute("DELETE FROM restore_checkpoints WHERE id = %s", (checkpoint_id,))
    else:
        raise SystemExit("Choose pause or clear")
