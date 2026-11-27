"""Find the registered session that spawned this process.

The registry only stored a parent when a caller passed one. A headless
``claude -p`` started by another session has an OS parent chain — the hook,
this process, the launcher, then the spawning session — and that chain is
readable while the process is alive. ``ensure`` runs inside that chain, so
it can record the nearest listed ancestor. A session that already names a
parent is left alone. Dead rows are not walked.
"""

from __future__ import annotations

import subprocess


def ppid_of(pid: int) -> int | None:
    try:
        out = subprocess.check_output(
            ["ps", "-o", "ppid=", "-p", str(pid)],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, OSError, ValueError):
        return None
    text = (out or "").strip()
    if not text:
        return None
    try:
        return int(text.split()[0])
    except ValueError:
        return None


def ancestor_pids(start: int, ppid_of_fn=ppid_of, limit: int = 16) -> list[int]:
    """Pids above ``start``, nearest first. Stops at launchd (pid 1) or a cycle."""
    found: list[int] = []
    pid = start
    for _ in range(limit):
        parent = ppid_of_fn(pid)
        if parent is None or parent <= 1 or parent in found:
            break
        found.append(parent)
        pid = parent
    return found


def match_parent(
    ancestor_pids_list: list[int],
    rows: list[dict],
    session_id: str,
    own_pid: int | None = None,
) -> str | None:
    """Nearest listed session in the ancestor chain, other than this session."""
    skip = {own_pid} if own_pid else set()
    by_pid: dict[int, str] = {}
    for row in rows:
        pid = row.get("pid")
        sid = row.get("session_id")
        if not isinstance(pid, int) or pid <= 1 or not sid or sid == session_id:
            continue
        if pid in skip:
            continue
        by_pid.setdefault(pid, sid)
    for pid in ancestor_pids_list:
        if pid in skip:
            continue
        sid = by_pid.get(pid)
        if sid:
            return sid
    return None
