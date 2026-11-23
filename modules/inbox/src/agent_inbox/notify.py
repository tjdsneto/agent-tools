from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from psycopg.types.json import Jsonb

LOCAL = ZoneInfo("America/Sao_Paulo")
QUIET = (22, 8)
NORMAL_GAP = timedelta(minutes=15)


def quiet(now: datetime) -> bool:
    hour = now.astimezone(LOCAL).hour
    return hour >= QUIET[0] or hour < QUIET[1]


def due(entries: list[dict], *, now: datetime, last_normal_at: datetime | None) -> list[dict]:
    send_normal = not quiet(now) and (last_normal_at is None or now - last_normal_at >= NORMAL_GAP)
    urgent = [entry for entry in entries if entry["priority"] == "urgent"]
    normal = [entry for entry in entries if entry["priority"] == "normal" and send_normal]
    return urgent + normal


def card(entry: dict, *, ui: str) -> str:
    project = os.path.basename((entry.get("asker") or {}).get("project") or "") or "-"
    lines = [f"{entry['priority']}  {project}", entry["title"]]
    control = entry.get("control") or {}
    ctype = control.get("type")
    if ctype in ("choice", "multi"):
        for i, opt in enumerate(control.get("options") or [], start=1):
            mark = " (recommended)" if opt.get("recommended") else ""
            lines.append(f"{i}. {opt['label']}{mark}")
        lines.append("reply 1" if ctype == "choice" else "reply the numbers")
    elif ctype == "text":
        lines.append("reply with the text")
    elif ctype == "approve":
        lines.append('reply "approve" or "revise: reason"')
    lines.append(ui)
    return "\n".join(lines)


_warned_unset = False


def hermes_send(to: str, text: str) -> None:
    subprocess.run(["hermes", "send", "--to", to, text], check=False, timeout=60)


def notify_mac(title: str, body: str) -> None:
    safe = body.replace('"', "'")[:180]
    title_safe = title.replace('"', "'")[:80]
    subprocess.run(
        ["osascript", "-e", f'display notification "{safe}" with title "{title_safe}"'],
        check=False, timeout=10,
    )


def say(text: str) -> None:
    if os.environ.get("AGENT_INBOX_SAY") != "1":
        return
    subprocess.run(["agt", "say", "--text", text[:500]], check=False, timeout=30)


def _ops_get(conn, key: str):
    row = conn.execute("SELECT value FROM ops WHERE key = %s", (key,)).fetchone()
    return row["value"] if row else None


def _ops_put(conn, key: str, value: dict) -> None:
    conn.execute(
        """
        INSERT INTO ops (key, value) VALUES (%s, %s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """,
        (key, Jsonb(value)),
    )


def _notified(conn) -> set[str]:
    value = _ops_get(conn, "notified") or {}
    return set(value.get("ids") or [])


def _mark_notified(conn, ids: list[str]) -> None:
    if not ids:
        return
    merged = sorted(_notified(conn) | set(ids))
    _ops_put(conn, "notified", {"ids": merged})


def _last_normal(conn) -> datetime | None:
    raw = (_ops_get(conn, "last_normal_push") or {}).get("at")
    if not raw:
        return None
    return datetime.fromisoformat(raw)


def _link(entry: dict, ui: str) -> str:
    if ui.rstrip("/").endswith(str(entry["id"])):
        return ui
    return f"{ui.rstrip('/')}/e/{entry['id']}"


def _visible(entry: dict) -> bool:
    if entry.get("kind") == "post":
        return entry.get("state") == "unread"
    return entry.get("state", "open") == "open"


def _warn_unset() -> None:
    global _warned_unset
    if _warned_unset:
        return
    print("telegram target unset", file=sys.stderr)
    _warned_unset = True


def _send(to: str, text: str) -> None:
    try:
        hermes_send(to, text)
    except OSError as exc:
        print(f"telegram send failed: {exc}", file=sys.stderr)


def push_new(conn, entries: list[dict], *, now: datetime, ui: str) -> None:
    seen = _notified(conn)
    fresh = [entry for entry in entries if _visible(entry) and entry["id"] not in seen]
    batch = due(fresh, now=now, last_normal_at=_last_normal(conn))
    if not batch:
        return
    target = os.environ.get("AGENT_INBOX_TELEGRAM_TO")
    urgent = [entry for entry in batch if entry["priority"] == "urgent"]
    normal = [entry for entry in batch if entry["priority"] == "normal"]
    if target:
        for entry in urgent:
            _send(target, card(entry, ui=_link(entry, ui)))
        if normal:
            _send(target, "\n\n".join(card(entry, ui=_link(entry, ui)) for entry in normal))
    else:
        _warn_unset()
    for entry in urgent:
        notify_mac(entry["title"], entry["title"])
        say(entry["title"])
    _mark_notified(conn, [entry["id"] for entry in batch])
    if normal:
        _ops_put(conn, "last_normal_push", {"at": now.isoformat()})


def push_pending(conn, *, now: datetime | None = None, ui: str | None = None) -> None:
    from agent_inbox import store
    asks = store.list_entries(conn, kind="ask", states=["open"], limit=200)
    posts = store.list_entries(conn, kind="post", states=["unread"], limit=200)
    when = now or datetime.now(LOCAL)
    origin = ui or os.environ.get("INBOX_UI_ORIGIN", "http://127.0.0.1:8797")
    push_new(conn, asks + posts, now=when, ui=origin)


def push_answerable(conn, ids: list[str], priority: str) -> None:
    if not ids:
        return
    target = os.environ.get("AGENT_INBOX_TELEGRAM_TO")
    text = f"{len(ids)} entries are answerable again\n" + "\n".join(ids)
    if not target:
        _warn_unset()
        return
    _send(target, text)
    if priority == "urgent":
        notify_mac("answerable again", text)
        say(text)


def note_answered(entry_id: str, via: str, value) -> None:
    target = os.environ.get("AGENT_INBOX_TELEGRAM_TO")
    if not target:
        return
    shown = ", ".join(value) if isinstance(value, list) else value
    _send(target, f"{entry_id} answered via {via}: {shown}")


def urgent_counts(conn) -> str:
    rows = conn.execute(
        """
        SELECT engine, count(*) AS n FROM entries
        WHERE priority = 'urgent' AND engine IS NOT NULL
        GROUP BY engine
        """
    ).fetchall()
    counts = {row["engine"]: row["n"] for row in rows}
    parts = [f"{name} {counts[name]}" for name in ("claude", "codex", "cursor") if counts.get(name)]
    if not parts:
        return ""
    return "urgent: " + ", ".join(parts)
