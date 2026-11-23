from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from agent_inbox import store
from agent_inbox.reach import Reach, for_entry

MAX_ATTEMPTS = 3

# Wake processes this serve started. A finished child stays a zombie until polled,
# and os.kill(zombie, 0) succeeds, so children are checked through their Popen.
_children: dict[int, subprocess.Popen] = {}


def pid_alive(pid: int) -> bool:
    child = _children.get(pid)
    if child is not None:
        if child.poll() is None:
            return True
        _children.pop(pid, None)
        return False
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


def _work_dir() -> Path:
    path = Path(os.environ.get("TMPDIR", "/tmp")) / "agent-inbox"
    path.mkdir(parents=True, exist_ok=True)
    return path


def start_wake(entry_id: str, session_id: str, message: str) -> dict:
    """Start `agt registry wake` detached and return at once.

    Resuming an exited session runs the agent's whole turn inside that command, which
    can take many minutes. Serve must not block on it, and must not start it twice.
    """
    stem = _work_dir() / f"{entry_id}-{uuid.uuid4().hex[:8]}"
    msg, out = stem.with_suffix(".msg"), stem.with_suffix(".out")
    msg.write_text(message)
    with out.open("w") as fh:
        proc = subprocess.Popen(
            ["agt", "registry", "wake", session_id, "--message", str(msg)],
            stdout=fh, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    _children[proc.pid] = proc
    return {"pid": proc.pid, "msg": str(msg), "out": str(out), "started_at": store._now_iso()}


def wake_result(inflight: dict) -> dict:
    """Read a finished wake's JSON result and remove its files."""
    try:
        text = Path(inflight["out"]).read_text()
    except OSError:
        text = ""
    for key in ("msg", "out"):
        Path(inflight[key]).unlink(missing_ok=True)
    try:
        return json.loads(text) if text.strip() else {"result": "undelivered", "mode": None}
    except json.JSONDecodeError:
        return {"result": "undelivered", "mode": None}


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


def _record(conn, entry_id: str, delivery: dict, inflight: dict, result: dict) -> str:
    event = inflight["event"]
    ok = result.get("result") in {"landed", "already_awake"}
    delivery["attempts"] = delivery["attempts"] + 1
    # Failures since the last success: an entry's answer and each follow-up get their own retries.
    delivery["failures"] = 0 if ok else delivery.get("failures", 0) + 1
    delivery["results"] = [
        *delivery["results"],
        {"at": store._now_iso(), "result": result.get("result"), "mode": result.get("mode")},
    ]
    if ok:
        if event["event"] == "followup":
            delivery["delivered_seq"] = event["seq"]
        delivery["headless"] = bool(inflight.get("headless"))
        _save(conn, entry_id, delivery, state="delivered" if event["event"] == "answer" else None)
        return "delivered"
    state = "undelivered" if delivery["failures"] >= MAX_ATTEMPTS else None
    _save(conn, entry_id, delivery, state=state)
    return "undelivered" if state else "retry"


def dispatch_entry(conn: psycopg.Connection, entry_id: str) -> str | None:
    """Advance delivery of the pending answer or follow-up by one step.

    Returns "started" when a wake was launched, "inflight" while it runs, the outcome
    once it finishes, the reachability when it cannot be sent, or None when nothing
    is pending or a live waiter owns it.
    """
    entry = store.get_entry(conn, entry_id)
    if not entry["asker"].get("session_id"):
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
    inflight = delivery.get("inflight")
    if inflight:
        if pid_alive(inflight["pid"]):
            return "inflight"
        result = wake_result(inflight)
        delivery.pop("inflight")
        return _record(conn, entry_id, delivery, inflight, result)
    event = _pending(entry, delivery)
    if event is None:
        return None
    reach = reach_for(entry)
    delivery["reachability"] = reach.status
    delivery["reachable_at"] = reach.reachable_at
    if reach.status in ("held", "unreachable"):
        _save(conn, entry_id, delivery)
        return reach.status
    inflight = start_wake(entry_id, entry["asker"]["session_id"], render_message(entry, event))
    delivery["inflight"] = {**inflight, "event": event, "headless": bool(reach.headless)}
    _save(conn, entry_id, delivery)
    return "started"


def _pending(entry: dict, delivery: dict) -> dict | None:
    if entry["state"] == "answered" and entry.get("answer"):
        return {"event": "answer", **entry["answer"]}
    after = delivery.get("delivered_seq") or 0
    for item in entry.get("thread") or []:
        if item["type"] == "followup" and item["seq"] > after:
            return {"event": "followup", "seq": item["seq"], "text": item.get("text"), "via": item.get("via")}
    return None
