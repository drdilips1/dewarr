"""Install/remove a restore-review UI fixture in the disposable browser database only.

This is not a restore rehearsal: real offline dump/restore is tested separately.
"""

import json
import os
import sys
from urllib.parse import urlsplit
from uuid import UUID

import psycopg

outbound_id = UUID("bcfc24e9-e3a7-4b9f-97a3-463c259a880b")
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
        subscriptions = connection.execute(
            "SELECT s.id, s.enabled, s.next_sync_at FROM list_subscriptions s "
            "JOIN book_lists l ON l.id=s.list_id WHERE l.owner_id=%s "
            "AND l.name='Recovery RSS baseline'",
            (actor[0],),
        ).fetchall()
        connection.execute("DELETE FROM login_sessions")
        connection.execute(
            "INSERT INTO restore_checkpoints(id, operator_id, backup_id, active, snapshot) "
            "VALUES (%s, %s, %s, true, %s::jsonb)",
            (
                checkpoint_id,
                actor[0],
                checkpoint_id,
                json.dumps(
                    {
                        "fixture_connections": {str(key): enabled for key, enabled in previous},
                        "fixture_subscriptions": {
                            str(key): {
                                "enabled": enabled,
                                "next_sync_at": due.isoformat() if due else None,
                            }
                            for key, enabled, due in subscriptions
                        },
                    }
                ),
            ),
        )
        for key, _ in previous:
            connection.execute("UPDATE integrations SET enabled = true WHERE id = %s", (key,))
        for key, _, _ in subscriptions:
            # The UI harness worker predates this synthetic checkpoint. Keep its
            # ordinary scheduler from racing the explicitly queued recovery jobs.
            connection.execute(
                "UPDATE list_subscriptions SET enabled=true, next_sync_at=NULL WHERE id=%s", (key,)
            )
    elif sys.argv[1:] == ["outbound"]:
        saved = connection.execute(
            "SELECT l.id, l.owner_id FROM book_lists l JOIN restore_checkpoints r "
            "ON r.operator_id=l.owner_id WHERE r.id=%s AND r.active "
            "AND l.name='Recovery RSS baseline'",
            (checkpoint_id,),
        ).fetchone()
        if not saved:
            raise SystemExit("The paused baseline fixture is required")
        connection.execute(
            "INSERT INTO operations(id,owner_id,kind,idempotency_key,status,message,payload) "
            "VALUES (%s,%s,'lists.writeback','recovery-outbound-fixture','attention',%s,%s::jsonb)",
            (
                outbound_id,
                saved[1],
                "Synthetic lost write response",
                json.dumps(
                    {
                        "list_id": str(saved[0]),
                        "remote_owner_id": 7,
                        "external_list_id": 92,
                        "book_id": 42,
                        "desired": True,
                        "attempts": 1,
                        "base": {"owner_id": 7, "list_id": 92, "book_id": 42, "memberships": []},
                        "pending_attempt": {
                            "action": "add",
                            "entry_id": None,
                            "sent_at": "2026-09-19T00:00:00Z",
                        },
                    }
                ),
            ),
        )
    elif sys.argv[1:] == ["clear"]:
        checkpoint = connection.execute(
            "SELECT snapshot FROM restore_checkpoints WHERE id = %s", (checkpoint_id,)
        ).fetchone()
        if checkpoint:
            for key, enabled in checkpoint[0].get("fixture_connections", {}).items():
                connection.execute(
                    "UPDATE integrations SET enabled = %s WHERE id = %s", (enabled, UUID(key))
                )
            for key, saved in checkpoint[0].get("fixture_subscriptions", {}).items():
                connection.execute(
                    "UPDATE list_subscriptions SET enabled=%s, next_sync_at=%s WHERE id=%s",
                    (saved["enabled"], saved["next_sync_at"], UUID(key)),
                )
        connection.execute("DELETE FROM operations WHERE id=%s", (outbound_id,))
        connection.execute("DELETE FROM recovery_scans WHERE checkpoint_id = %s", (checkpoint_id,))
        connection.execute("DELETE FROM restore_checkpoints WHERE id = %s", (checkpoint_id,))
    else:
        raise SystemExit("Choose pause, outbound or clear")
