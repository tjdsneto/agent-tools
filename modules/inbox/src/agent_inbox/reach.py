from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

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


def claude_budget() -> tuple[int | None, str | None]:
    """Percent and local clock time, or (None, None) when the poll cannot be read."""
    check = _run(["claude-budget", "check"])
    raw = check.stdout.strip()
    pct = int(raw) if raw.isdigit() else None
    reset = _run(["claude-budget", "reset-at"])
    parts = reset.stdout.split()
    when = None
    if len(parts) >= 3 and parts[0].isdigit():
        when = parts[1] + "T" + parts[2] + ":00"
    return pct, when


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
