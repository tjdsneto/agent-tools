from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from agent_inbox import store
from agent_inbox.reach import Reach, for_entry

MAX_ATTEMPTS = 3


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def reach_for(entry: dict) -> Reach:
    return for_entry(entry)


def render_message(entry: dict, event: dict) -> str:
    label = "answer" if event["event"] == "answer" else "follow-up"
    value = event.get("value", event.get("text", ""))
    lines = [f'Inbox {label} for {entry["id"]} ("{entry["title"]}"): {value}']
    if event.get("comment"):
        lines.append(f"Comment: {event['comment']}")
    lines.append(json.dumps({"entry": entry["id"], **event}, default=str))
    lines.append(f"Full entry: agt inbox get {entry['id']}")
    return "\n".join(lines) + "\n"


def wake(session_id: str, message: str) -> dict:
    path = Path(os.environ.get("TMPDIR", "/tmp")) / f"inbox-{session_id}.txt"
    path.write_text(message)
    proc = subprocess.run(
        ["agt", "registry", "wake", session_id, "--message", str(path)],
        capture_output=True, text=True, timeout=120,
    )
    try:
        return json.loads(proc.stdout) if proc.stdout.strip() else {"result": "undelivered", "mode": None}
    except json.JSONDecodeError:
        return {"result": "undelivered", "mode": None, "error": proc.stderr[-400:]}


def _save(conn, entry_id: str, delivery: dict, *, state: str | None = None) -> None:
    if state:
        conn.execute(
            "UPDATE entries SET delivery = %s, state = %s, waiter_pid = NULL, updated_at = now() WHERE id = %s",
            (Jsonb(delivery), state, entry_id),
        )
    else:
        conn.execute(
            "UPDATE entries SET delivery = %s, updated_at = now() WHERE id = %s",
            (Jsonb(delivery), entry_id),
        )


def dispatch_entry(conn: psycopg.Connection, entry_id: str) -> str | None:
    """Deliver the pending answer or follow-up. Return the outcome, or None when a live waiter owns it."""
    entry = store.get_entry(conn, entry_id)
    if entry["kind"] != "ask":
        return None
    pid = entry.get("waiter_pid")
    if pid and pid_alive(pid):
        return None
    if pid:
        store.clear_waiter(conn, entry_id, pid)
        entry = store.get_entry(conn, entry_id)
    delivery = dict(entry.get("delivery") or {})
    delivery.setdefault("attempts", 0)
    delivery.setdefault("results", [])
    delivery.setdefault("delivered_seq", 0)
    reach = reach_for(entry)
    delivery["reachability"] = reach.status
    delivery["reachable_at"] = reach.reachable_at
    if reach.status in ("held", "unreachable"):
        _save(conn, entry_id, delivery)
        return reach.status
    event = _pending(entry, delivery)
    if event is None:
        return None
    result = wake(entry["asker"]["session_id"], render_message(entry, event))
    ok = result.get("result") in {"landed", "already_awake"}
    delivery["attempts"] = delivery["attempts"] + 1
    delivery["results"] = [
        *delivery["results"],
        {"at": store._now_iso(), "result": result.get("result"), "mode": result.get("mode")},
    ]
    if ok:
        if event["event"] == "followup":
            delivery["delivered_seq"] = event["seq"]
        delivery["headless"] = bool(reach.headless)
        _save(conn, entry_id, delivery, state="delivered" if event["event"] == "answer" else None)
        return "delivered"
    state = "undelivered" if delivery["attempts"] >= MAX_ATTEMPTS else None
    _save(conn, entry_id, delivery, state=state)
    return "undelivered" if state else "retry"


def _pending(entry: dict, delivery: dict) -> dict | None:
    if entry["state"] == "answered" and entry.get("answer"):
        return {"event": "answer", **entry["answer"]}
    after = delivery.get("delivered_seq") or 0
    for item in entry.get("thread") or []:
        if item["type"] == "followup" and item["seq"] > after:
            return {"event": "followup", "seq": item["seq"], "text": item.get("text"), "via": item.get("via")}
    return None
