from __future__ import annotations

import os
from pathlib import Path

from agent_registry import archive, ops, session_state, store
from agent_registry.constants import EXIT_IO, EXIT_OK


def _parent_writable(path: Path) -> tuple[bool, str]:
    parent = path.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return False, f"cannot create parent {parent}: {e}"
    if not os.access(parent, os.W_OK):
        return False, f"parent not writable: {parent}"
    return True, f"ok ({parent})"


def collect() -> dict:
    """Same checks as ``run_doctor``, as ``{"ok": bool, "lines": [str, ...]}``."""
    ok = True
    lines: list[str] = []

    reg = store.registry_path()
    writable, detail = _parent_writable(reg)
    lines.append(f"registry path: {reg}")
    if writable:
        lines.append(f"  parent writable: {detail}")
    else:
        lines.append(f"  parent writable: FAIL — {detail}")
        ok = False

    try:
        with store.hold_lock():
            pass
        lines.append("lock: ok (acquirable)")
    except OSError as e:
        lines.append(f"lock: FAIL — {e}")
        ok = False

    arch = archive.archive_path()
    lines.append(f"archive path: {arch}")
    arch_writable, arch_detail = _parent_writable(arch)
    if arch_writable:
        lines.append(f"  sibling of registry: ok ({arch_detail})")
    else:
        lines.append(f"  parent writable: FAIL — {arch_detail}")
        ok = False

    data = session_state.data_dir()
    by_session = data / "by-session"
    try:
        data.mkdir(parents=True, exist_ok=True)
        by_session.mkdir(parents=True, exist_ok=True)
        if not os.access(data, os.W_OK):
            lines.append(f"sidecar/data dir: FAIL — not writable: {data}")
            ok = False
        else:
            lines.append(f"sidecar/data dir: ok ({by_session})")
    except OSError as e:
        lines.append(f"sidecar/data dir: FAIL — {e}")
        ok = False

    return {"ok": ok, "lines": lines}


def run_doctor() -> int:
    """Print human-readable health checks. Exit 0 if all ok else EXIT_IO."""
    result = collect()
    print("\n".join(result["lines"]))
    return EXIT_OK if result["ok"] else EXIT_IO


def status_payload() -> dict:
    active, stale = ops.list_split()
    return {
        "active": len(active),
        "stale": len(stale),
        "archived": len(archive.read_events()),
        "registry_path": str(store.registry_path()),
        "archive_path": str(archive.archive_path()),
    }


def format_status(payload: dict) -> str:
    return (
        f"active: {payload['active']}\n"
        f"stale: {payload['stale']}\n"
        f"archived: {payload['archived']}\n"
        f"registry: {payload['registry_path']}\n"
        f"archive: {payload['archive_path']}\n"
    )
