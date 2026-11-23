from __future__ import annotations

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

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
