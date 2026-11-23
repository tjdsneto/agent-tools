from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

HELD_PCT = 88


@dataclass(frozen=True)
class Reach:
    status: str  # live, resumable, held, unreachable
    agent_type: str | None = None
    reachable_at: str | None = None
    headless: bool = False


def classify(view: dict | None, *, budget: tuple[int | None, str | None] | None, last: str | None) -> Reach:
    if not view or not view.get("agent_type"):
        return Reach("unreachable")
    agent = view["agent_type"]
    if agent == "claude" and view.get("alive") and not view.get("peer_name"):
        return Reach("unreachable", agent)
    if agent == "claude" and budget and budget[0] is not None and budget[0] >= HELD_PCT:
        return Reach("held", agent, reachable_at=budget[1])
    if agent != "claude" and last == "held":
        return Reach("held", agent)
    if agent == "cursor":
        return Reach("resumable", agent, headless=True)
    if view.get("alive"):
        return Reach("live", agent)
    return Reach("resumable", agent)


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, timeout=30)


def resolve(session_id: str) -> dict | None:
    proc = _run(["agt", "registry", "resolve", session_id])
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


BUDGET_TTL = 60.0
_budget_cache: tuple[float, tuple[int | None, str | None]] | None = None


def parse_snapshot(text: str) -> tuple[int | None, str | None]:
    values = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    raw_pct = values.get("session_pct", "").strip()
    raw_reset = values.get("session_reset", "").strip()
    pct = int(raw_pct) if raw_pct.isdigit() else None
    when = datetime.fromtimestamp(int(raw_reset)).strftime("%Y-%m-%dT%H:%M:00") if raw_reset.isdigit() else None
    return pct, when


def claude_budget(now: Callable[[], float] = time.monotonic) -> tuple[int | None, str | None]:
    """Percent and local clock time, or (None, None) when the poll cannot be read.

    Each read launches a headless `claude -p /usage`, and the windows are account-wide,
    so one snapshot is shared by every entry for BUDGET_TTL seconds.
    """
    global _budget_cache
    if _budget_cache and now() - _budget_cache[0] < BUDGET_TTL:
        return _budget_cache[1]
    value = parse_snapshot(_run(["claude-budget", "snapshot"]).stdout)
    _budget_cache = (now(), value)
    return value


def for_entry(entry: dict) -> Reach:
    asker = entry.get("asker") or {}
    sid = asker.get("session_id")
    if not sid:
        return Reach("unreachable")
    view = resolve(sid)
    budget = claude_budget() if (view or {}).get("agent_type") == "claude" or asker.get("engine") == "claude" else None
    last = None
    results = (entry.get("delivery") or {}).get("results") or []
    if results:
        last = results[-1].get("result")
    return classify(view, budget=budget, last=last)
