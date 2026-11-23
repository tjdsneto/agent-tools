from __future__ import annotations

import psycopg
from psycopg.types.json import Jsonb

from agent_inbox import db
from agent_inbox.constants import NOTIFY_CHANNEL
from agent_inbox.dispatch import dispatch_entry


def expire_due(conn: psycopg.Connection) -> int:
    rows = conn.execute(
        """
        UPDATE entries SET state = 'expired', updated_at = now()
        WHERE kind = 'ask' AND state = 'open' AND expires_at IS NOT NULL AND expires_at <= now()
        RETURNING id
        """
    ).fetchall()
    for row in rows:
        conn.execute(
            "INSERT INTO events (entry_id, type, body) VALUES (%s, 'state', %s)",
            (row["id"], Jsonb({"from": "open", "to": "expired"})),
        )
    return len(rows)


def sweep(conn: psycopg.Connection) -> None:
    expire_due(conn)
    rows = conn.execute(
        """
        SELECT id FROM entries
        WHERE kind = 'ask' AND state IN ('answered', 'delivered')
        ORDER BY updated_at
        """
    ).fetchall()
    for row in rows:
        dispatch_entry(conn, row["id"])


def run_once() -> None:
    with db.connect() as conn:
        sweep(conn)


def run(poll: float = 5.0) -> None:
    conn = db.connect()
    conn.execute(f"LISTEN {NOTIFY_CHANNEL}")
    try:
        while True:
            sweep(conn)
            for _ in conn.notifies(timeout=poll, stop_after=1):
                break
    finally:
        conn.close()
