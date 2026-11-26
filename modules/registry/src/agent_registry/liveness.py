"""Which sessions are live, for the topic tree. Read from the registry file in this process, as
the daemon's own `list` does, so it adds no daemon call."""
from __future__ import annotations

from datetime import datetime

from agent_registry import archive, store
from agent_registry.models import is_stale

UNKNOWN = {"live": False, "state": "unknown", "directory": None}


def lookup(keys: set[tuple[str, str]], *, now: datetime | None = None) -> dict[tuple[str, str], dict]:
    """(agent_type, session_id) -> {live, state, directory}. A row that pinged within the stale
    window is live and an older one idle. A session with no row has ended; its directory comes
    from its latest archive record, and the archive is read only when some session has no row."""
    if not keys:
        return {}
    try:
        rows = store.load().sessions
    except (store.CorruptRegistryError, OSError):
        return {key: dict(UNKNOWN) for key in keys}
    found: dict[tuple[str, str], dict] = {}
    for session in rows:
        key = (session.agent_type, session.session_id)
        if key not in keys or (key in found and found[key]["live"]):
            continue
        try:
            stale = is_stale(session, now=now)
        except (TypeError, ValueError, AttributeError):
            stale = True
        found[key] = {"live": not stale, "state": "idle" if stale else "live", "directory": session.directory}
    missing = keys - found.keys()
    if missing:
        ended: dict[tuple[str, str], str] = {}
        for event in archive.read_events():
            row = event.get("session")
            if not isinstance(row, dict):
                continue
            key = (row.get("agent_type"), row.get("session_id"))
            if key in missing and isinstance(row.get("directory"), str):
                ended[key] = row["directory"]
        for key in missing:
            found[key] = {"live": False, "state": "ended", "directory": ended.get(key)}
    return found


def annotate(roots: list[dict], *, now: datetime | None = None) -> list[dict]:
    """Give every session entry in the tree its live, state and directory, in place."""
    nodes: list[dict] = []
    stack = list(roots)
    while stack:
        node = stack.pop()
        nodes.append(node)
        stack.extend(node["children"])
    seen = lookup({(s["agent_type"], s["session_id"]) for node in nodes for s in node["sessions"]}, now=now)
    for node in nodes:
        for session in node["sessions"]:
            session.update(seen.get((session["agent_type"], session["session_id"]), UNKNOWN))
    return roots
