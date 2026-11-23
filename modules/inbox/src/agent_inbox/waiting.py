from __future__ import annotations

import os
import time
from typing import Callable

import psycopg

from agent_inbox import db, store
from agent_inbox.constants import NOTIFY_CHANNEL, WAIT_POLL_SEC, WAIT_TIMEOUT_SEC
from agent_inbox.errors import ValidationError


def wait_for(
    entry_id: str,
    *,
    after: int = 0,
    timeout: float = WAIT_TIMEOUT_SEC,
    poll: float = WAIT_POLL_SEC,
    connect: Callable[[], psycopg.Connection] = db.connect,
    clock: Callable[[], float] = time.monotonic,
) -> dict:
    """Block until an answer, a follow-up newer than `after`, a closed state, or the timeout."""
    conn = connect()
    pid = os.getpid()
    try:
        if store.get_entry(conn, entry_id)["kind"] != "ask":
            raise ValidationError(f"{entry_id} is not a question")
        # LISTEN before the first check, so a change between check and sleep still wakes us.
        conn.execute(f"LISTEN {NOTIFY_CHANNEL}")
        store.set_waiter(conn, entry_id, pid)
        deadline = clock() + timeout
        while True:
            event = store.take_waiter_event(conn, entry_id, after)
            if event is not None:
                return event
            remaining = deadline - clock()
            if remaining <= 0:
                store.switch_to_resume(conn, entry_id)
                return {"entry": entry_id, "event": "timeout"}
            for _ in conn.notifies(timeout=min(remaining, poll), stop_after=1):
                pass
    finally:
        try:
            store.clear_waiter(conn, entry_id, pid)
        finally:
            conn.close()
