from __future__ import annotations

import json
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


def buttons(entry: dict) -> list[list[str]] | None:
    """Answer buttons for the inbox-buttons Hermes plugin, as [label, callback data] rows.

    Only choice and approve: multi needs toggles, text and revise need words. None when any
    callback data passes Telegram's 64-byte limit, so the card falls back to a text reply.
    """
    control = entry.get("control") or {}
    ctype = control.get("type")
    if ctype == "choice":
        pairs = [
            [("⭐ " if opt.get("recommended") else "") + opt["label"], f"ib:{entry['id']}:{opt['id']}"]
            for opt in control.get("options") or []
        ]
    elif ctype == "approve":
        pairs = [["Approve", f"ib:{entry['id']}:approve"]]
    else:
        return None
    if any(len(data.encode()) > 64 for _, data in pairs):
        return None
    return pairs


def card(entry: dict, *, ui: str, tappable: bool = False) -> str:
    """Telegram card. hermes send renders Markdown, so the title is bold and the UI is a short link.

    A tappable card goes out with buttons(), so a choice drops its numbered list.
    """
    project = os.path.basename((entry.get("asker") or {}).get("project") or "")
    head = f"*{entry['title']}*"
    if entry.get("priority") == "urgent":
        head = "🚨 Urgent: " + head
    lines = [head, " · ".join(([f"from {project}"] if project else []) + [entry["id"]])]
    control = entry.get("control") or {}
    ctype = control.get("type")
    options = control.get("options") or []
    if ctype == "choice" and tappable:
        pass
    elif ctype in ("choice", "multi"):
        for i, opt in enumerate(options, start=1):
            mark = " (recommended)" if opt.get("recommended") else ""
            lines.append(f"{i}. {opt['label']}{mark}")
        lines.append(f"Reply with a number (1–{len(options)})" if ctype == "choice" else "Reply with numbers, e.g. 1 3")
    elif ctype == "text":
        lines.append("Reply with your answer")
    elif ctype == "approve":
        lines.append('Tap Approve, or reply "revise: reason"' if tappable else 'Reply "approve" or "revise: reason"')
    lines.append(f"[Open details]({ui})")
    return "\n".join(lines)


_warned_unset = False


# Hermes's home Telegram channel. An empty AGENT_INBOX_TELEGRAM_TO turns pushes off.
DEFAULT_TELEGRAM_TO = "telegram"


def _target() -> str:
    return os.environ.get("AGENT_INBOX_TELEGRAM_TO", DEFAULT_TELEGRAM_TO)


def hermes_send(to: str, text: str) -> None:
    subprocess.run(["hermes", "send", "--to", to, text], check=False, timeout=60)


def hermes_card(to: str, text: str, pairs: list[list[str]]) -> bool:
    """Send through the inbox-buttons plugin. False when it is missing or the send failed."""
    try:
        proc = subprocess.run(
            ["hermes", "inbox-card", "--to", to, "--buttons", json.dumps(pairs)],
            input=text, text=True, capture_output=True, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if proc.returncode != 0:
        print(f"inbox-card failed, sending without buttons: {proc.stdout.strip() or proc.stderr.strip()}", file=sys.stderr)
    return proc.returncode == 0


def notify_mac(title: str, body: str) -> None:
    safe = body.replace('"', "'")[:180]
    title_safe = title.replace('"', "'")[:80]
    subprocess.run(
        ["osascript", "-e", f'display notification "{safe}" with title "{title_safe}"'],
        check=False, timeout=10,
    )


def say(text: str) -> None:
    """Opt-in voice. agt read speaks in the background; agt say is a blocking dialog."""
    if os.environ.get("AGENT_INBOX_SAY") != "1":
        return
    try:
        subprocess.Popen(
            ["agt", "read", "--title", "Inbox", "--text", text[:500], "--background"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
    except OSError as exc:
        print(f"voice failed: {exc}", file=sys.stderr)


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
    print("telegram pushes off (AGENT_INBOX_TELEGRAM_TO is empty)", file=sys.stderr)
    _warned_unset = True


def _send(to: str, text: str) -> None:
    try:
        hermes_send(to, text)
    except OSError as exc:
        print(f"telegram send failed: {exc}", file=sys.stderr)


def _send_card(to: str, entry: dict, ui: str) -> None:
    link = _link(entry, ui)
    pairs = buttons(entry)
    if pairs and hermes_card(to, card(entry, ui=link, tappable=True), pairs):
        return
    _send(to, card(entry, ui=link))


def push_new(conn, entries: list[dict], *, now: datetime, ui: str) -> None:
    seen = _notified(conn)
    fresh = [entry for entry in entries if _visible(entry) and entry["id"] not in seen]
    batch = due(fresh, now=now, last_normal_at=_last_normal(conn))
    if not batch:
        return
    target = _target()
    urgent = [entry for entry in batch if entry["priority"] == "urgent"]
    normal = [entry for entry in batch if entry["priority"] == "normal"]
    if target:
        # A card with buttons is its own message; the rest of a normal batch is one message.
        for entry in urgent + [entry for entry in normal if buttons(entry)]:
            _send_card(target, entry, ui)
        plain = [entry for entry in normal if not buttons(entry)]
        if plain:
            _send(target, "\n\n".join(card(entry, ui=_link(entry, ui)) for entry in plain))
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


def push_answerable(conn, ids: list[str], priority: str, *, now: datetime | None = None) -> None:
    """One batched push for questions whose session can hear an answer again.

    A normal batch in quiet hours is kept in ops and sent with the first sweep after.
    """
    pending = _ops_get(conn, "answerable") or {}
    ids = sorted(set(pending.get("ids") or []) | set(ids))
    if not ids:
        return
    urgent = priority == "urgent" or bool(pending.get("urgent"))
    if not urgent and quiet(now or datetime.now(LOCAL)):
        _ops_put(conn, "answerable", {"ids": ids, "urgent": False})
        return
    _ops_put(conn, "answerable", {"ids": [], "urgent": False})
    rows = conn.execute(
        "SELECT id, title FROM entries WHERE id = ANY(%s) AND state = 'open' ORDER BY created_at",
        (ids,),
    ).fetchall()
    if not rows:
        return
    noun = "question is" if len(rows) == 1 else "questions are"
    text = f"{len(rows)} {noun} answerable again\n" + "\n".join(f"• {row['title']} ({row['id']})" for row in rows)
    target = _target()
    if target:
        _send(target, text)
    else:
        _warn_unset()
    if urgent:
        notify_mac("answerable again", text)
        say(text)


def note_answered(entry_id: str, via: str, value) -> None:
    target = _target()
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
