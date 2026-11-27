"""One snapshot of a filtered inbox list, waiting on the store's notify channel."""

from __future__ import annotations

import hashlib
import json
import time

from agent_inbox import db, store
from agent_inbox.constants import NOTIFY_CHANNEL


def revision(entries: list[dict]) -> str:
    """Changes when a listed row's id, state, or update time changes, or the order does."""
    raw = json.dumps(
        [[entry["id"], entry.get("updated_at"), entry.get("state")] for entry in entries],
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def poll_snapshot(
    *,
    since: str | None,
    timeout: float,
    kind: str | None = None,
    states: list[str] | None = None,
    project: str | None = None,
    engine: str | None = None,
    session_id: str | None = None,
    limit: int = 50,
) -> dict:
    """The filtered list. With `since` equal to the current revision, wait for a change or `timeout`."""
    conn = db.connect()
    try:
        # LISTEN before the first read, so a commit between the read and the wait is still seen.
        conn.execute(f"LISTEN {NOTIFY_CHANNEL}")
        snap = _snapshot(conn, kind, states, project, engine, session_id, limit)
        if since is None or snap["rev"] != since or timeout <= 0:
            return snap
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return _snapshot(conn, kind, states, project, engine, session_id, limit)
            notified = False
            for _note in conn.notifies(timeout=remaining, stop_after=1):
                notified = True
            snap = _snapshot(conn, kind, states, project, engine, session_id, limit)
            if snap["rev"] != since:
                return snap
            if not notified:
                return snap
    finally:
        conn.close()


def follow(
    *,
    kind: str | None = None,
    states: list[str] | None = None,
    project: str | None = None,
    engine: str | None = None,
    session_id: str | None = None,
    limit: int = 50,
):
    """Yield a snapshot now, and another each time this filtered list changes."""
    conn = db.connect()
    try:
        conn.execute(f"LISTEN {NOTIFY_CHANNEL}")
        last = None
        while True:
            snap = _snapshot(conn, kind, states, project, engine, session_id, limit)
            if snap["rev"] != last:
                last = snap["rev"]
                yield snap
            for _note in conn.notifies(timeout=None, stop_after=1):
                pass
    finally:
        conn.close()


def _snapshot(conn, kind, states, project, engine, session_id, limit) -> dict:
    entries = store.list_entries(
        conn,
        kind=kind,
        states=states,
        project=project,
        engine=engine,
        session_id=session_id,
        limit=limit,
    )
    return {"rev": revision(entries), "entries": entries}
