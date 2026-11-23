from __future__ import annotations

import sys
import threading

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
        SELECT id, delivery, priority FROM entries
        WHERE kind = 'ask' AND state IN ('answered', 'delivered')
        ORDER BY updated_at
        """
    ).fetchall()
    freed: list[str] = []
    freed_urgent = False
    for row in rows:
        before = (row["delivery"] or {}).get("reachability")
        try:
            dispatch_entry(conn, row["id"])
        except Exception as exc:  # one bad entry must not stop delivery for the rest
            print(f"dispatch {row['id']} failed: {exc!r}", file=sys.stderr)
            continue
        after_row = conn.execute("SELECT delivery FROM entries WHERE id = %s", (row["id"],)).fetchone()
        after = ((after_row or {}).get("delivery") or {}).get("reachability")
        if before == "held" and after in ("live", "resumable"):
            freed.append(row["id"])
            freed_urgent = freed_urgent or row["priority"] == "urgent"
    from agent_inbox.notify import push_answerable, push_pending
    if freed:
        push_answerable(conn, freed, "urgent" if freed_urgent else "normal")
    push_pending(conn)
    purge_html(conn)


def purge_html(conn: psycopg.Connection) -> int:
    rows = conn.execute(
        """
        UPDATE entries SET html = NULL
        WHERE html IS NOT NULL
          AND state IN ('delivered', 'expired', 'withdrawn', 'superseded', 'undelivered', 'archived')
          AND updated_at < now() - interval '90 days'
        RETURNING id
        """
    ).fetchall()
    return len(rows)


def run_once() -> None:
    with db.connect() as conn:
        sweep(conn)


def _serve_http() -> None:
    from agent_inbox.web import make_server
    server = make_server()
    threading.Thread(target=server.serve_forever, name="inbox-http", daemon=True).start()


def _serve_frame() -> None:
    from agent_inbox.frame import make_server
    server = make_server()
    threading.Thread(target=server.serve_forever, name="inbox-frame", daemon=True).start()


def run(poll: float = 5.0) -> None:
    _serve_http()
    _serve_frame()
    conn = db.connect()
    conn.execute(f"LISTEN {NOTIFY_CHANNEL}")
    try:
        while True:
            sweep(conn)
            for _ in conn.notifies(timeout=poll, stop_after=1):
                break
    finally:
        conn.close()
