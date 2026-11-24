from __future__ import annotations

import sys
import threading
import time
from typing import Callable

import psycopg
from psycopg.types.json import Jsonb

from agent_inbox import db, reach, store
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


REACH_EVERY = 300.0
HELD_EVERY = 60.0
# Last check per open question. In memory: persisting it would update the row, and every
# update NOTIFYs the web page, which reloads and drops a half-typed comment.
_checked: dict[str, float] = {}


def refresh_reach(conn: psycopg.Connection, now: Callable[[], float] = time.monotonic) -> list[dict]:
    """Recompute reachability for open questions, so the UI can show it before an answer
    and a held session that gets its tokens back is noticed. Each check shells out to
    the registry (and for Claude to claude-budget), so it runs on a slow cadence and
    writes only when the status changes. Returns the questions that stopped being held."""
    global _checked
    rows = conn.execute(
        """
        SELECT id, priority, delivery FROM entries
        WHERE kind = 'ask' AND state = 'open' AND session_id IS NOT NULL
        ORDER BY created_at
        """
    ).fetchall()
    _checked = {row["id"]: _checked[row["id"]] for row in rows if row["id"] in _checked}
    freed = []
    for row in rows:
        delivery = row["delivery"] or {}
        before = delivery.get("reachability")
        every = HELD_EVERY if before == "held" else REACH_EVERY
        last = _checked.get(row["id"])
        if last is not None and now() - last < every:
            continue
        _checked[row["id"]] = now()
        try:
            found = reach.for_entry(store.get_entry(conn, row["id"]))
        except Exception as exc:
            print(f"reach {row['id']} failed: {exc!r}", file=sys.stderr)
            continue
        if (found.status, found.reachable_at) == (before, delivery.get("reachable_at")):
            continue
        conn.execute(
            "UPDATE entries SET delivery = delivery || %s WHERE id = %s",
            (Jsonb({"reachability": found.status, "reachable_at": found.reachable_at}), row["id"]),
        )
        if before == "held" and found.status in ("live", "resumable"):
            freed.append(row)
    return freed


def sweep(conn: psycopg.Connection) -> None:
    expire_due(conn)
    rows = conn.execute(
        """
        SELECT id, delivery, priority FROM entries
        WHERE session_id IS NOT NULL AND state IN ('open', 'answered', 'delivered', 'unread', 'read') AND (
            state = 'answered'
            OR delivery ? 'inflight'
            OR EXISTS (
                SELECT 1 FROM events ev
                WHERE ev.entry_id = entries.id AND ev.type = 'followup'
                  AND ev.seq > COALESCE((entries.delivery ->> 'delivered_seq')::bigint, 0)
            )
        )
        ORDER BY updated_at
        """
    ).fetchall()
    freed: list[str] = []
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
    for row in refresh_reach(conn):
        freed.append(row["id"])
    from agent_inbox.notify import push_answerable, push_pending
    push_answerable(conn, freed)
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
