from __future__ import annotations

import ctypes
import json
import os
import re
import sqlite3
import subprocess
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

_CACHE_TTL_SECONDS = 5.0
_CODEX_READ_CHUNK = 65536
_CLAUDE_TOKEN_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)
_CODEX_TOKEN_KEYS = (
    "input_tokens",
    "output_tokens",
    "cached_input_tokens",
    "cache_write_input_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)

_cache: dict[tuple[str, str], tuple[float, dict[str, Any] | None]] = {}
_cache_lock = threading.Lock()


def _ps(pid: int) -> str | None:
    try:
        proc = subprocess.run(
            ["ps", "-o", "pcpu=,rss=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    stdout = proc.stdout
    if not stdout or not stdout.strip():
        return None
    return stdout


def sample_process(pid: int) -> dict[str, float | int] | None:
    raw = _ps(pid)
    if not raw:
        return None
    parts = raw.split()
    if len(parts) != 2:
        return None
    try:
        cpu = float(parts[0])
        rss_kib = int(parts[1])
    except ValueError:
        return None
    return {"cpu_percent": cpu, "memory_bytes": rss_kib * 1024}


def claude_tokens(
    session_id: str, projects_root: Path | None = None
) -> dict[str, int] | None:
    if projects_root is not None:
        return _sum_claude(session_id, Path(projects_root))
    root = Path.home() / ".claude" / "projects"
    return _cached("claude", session_id, lambda: _sum_claude(session_id, root))


def codex_tokens(
    session_id: str, sessions_root: Path | None = None
) -> dict[str, Any] | None:
    if sessions_root is not None:
        return _latest_codex(session_id, Path(sessions_root))
    root = Path.home() / ".codex" / "sessions"
    return _cached("codex", session_id, lambda: _latest_codex(session_id, root))


def tokens_for(session: dict[str, Any]) -> dict[str, Any] | None:
    agent_type = session.get("agent_type")
    session_id = session.get("session_id")
    if agent_type == "cursor":
        return None
    if not isinstance(session_id, str) or not session_id:
        return None
    if agent_type == "claude":
        return claude_tokens(session_id)
    if agent_type == "codex":
        return codex_tokens(session_id)
    return None


def attach_usage(view: dict[str, Any]) -> dict[str, Any]:
    """Add a read-time cpu, memory, and token snapshot. Does not write the registry."""
    pid = view.get("pid")
    if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0:
        sample = sample_process(pid)
        if sample is not None:
            view["cpu_percent"] = float(sample["cpu_percent"])
            view["memory_bytes"] = int(sample["memory_bytes"])
    try:
        tokens = tokens_for(view)
    except Exception:
        tokens = None
    if isinstance(tokens, dict):
        view["tokens"] = tokens
    return view


def cursor_window_projects() -> set[str]:
    """Folder names of the Cursor windows that are open. Empty when Cursor is closed."""
    names: set[str] = set()
    for title in _cursor_window_titles():
        project = _window_project_name(title)
        if project:
            names.add(project)
    return names


def _window_project_name(title: str) -> str:
    """Leaf shown after the em dash in a Cursor window title.

    Multi-root windows are titled ``… — <name> (Workspace)``. Strip that
    suffix so it matches the workspace folder / .code-workspace parent name.
    """
    project = title.split(" — ")[-1].strip()
    if not project or project in {"Item-0", "Focus Proxy"}:
        return ""
    if project.endswith(" (Workspace)"):
        project = project[: -len(" (Workspace)")].strip()
    return project


def _cursor_window_titles() -> list[str]:
    """On-screen and other-desktop Cursor window titles. System Events sees none."""
    try:
        import ctypes
        from ctypes import c_void_p
    except Exception:
        return []
    try:
        cg = ctypes.CDLL(
            "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
        )
        cf = ctypes.CDLL(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
        )
    except OSError:
        return []
    cg.CGWindowListCopyWindowInfo.restype = c_void_p
    cg.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    cf.CFArrayGetCount.restype = ctypes.c_long
    cf.CFArrayGetCount.argtypes = [c_void_p]
    cf.CFArrayGetValueAtIndex.restype = c_void_p
    cf.CFArrayGetValueAtIndex.argtypes = [c_void_p, ctypes.c_long]
    cf.CFDictionaryGetValue.restype = c_void_p
    cf.CFDictionaryGetValue.argtypes = [c_void_p, c_void_p]
    cf.CFStringGetLength.restype = ctypes.c_long
    cf.CFStringGetLength.argtypes = [c_void_p]
    cf.CFStringGetCharacters.restype = None
    cf.CFStringGetCharacters.argtypes = [c_void_p, _CFRange, ctypes.POINTER(ctypes.c_uint16)]
    cf.CFRelease.argtypes = [c_void_p]
    try:
        owner_key = c_void_p.in_dll(cg, "kCGWindowOwnerName")
        name_key = c_void_p.in_dll(cg, "kCGWindowName")
    except ValueError:
        return []
    # Exclude desktop elements. Include windows on other desktops.
    array = cg.CGWindowListCopyWindowInfo(16, 0)
    if not array:
        return []
    titles: list[str] = []
    try:
        count = cf.CFArrayGetCount(array)
        for index in range(count):
            item = cf.CFArrayGetValueAtIndex(array, index)
            owner = _cfstring(cf, cf.CFDictionaryGetValue(item, owner_key))
            if owner != "Cursor":
                continue
            title = _cfstring(cf, cf.CFDictionaryGetValue(item, name_key))
            if title:
                titles.append(title)
    finally:
        cf.CFRelease(array)
    return titles


def _cfstring(cf: Any, value: Any) -> str:
    if not value:
        return ""
    import ctypes
    length = cf.CFStringGetLength(value)
    if length <= 0:
        return ""
    buf = (ctypes.c_uint16 * length)()
    cf.CFStringGetCharacters(value, _CFRange(0, length), buf)
    return bytes(buf).decode("utf-16-le", "replace")


class _CFRange(ctypes.Structure):
    _fields_ = [("location", ctypes.c_long), ("length", ctypes.c_long)]


def open_cursor_session_ids(storage_root: Path | None = None) -> set[str]:
    """Composer ids selected in a Cursor window that is open."""
    return set(open_cursor_chats(storage_root))


def open_cursor_chats(storage_root: Path | None = None) -> dict[str, str]:
    """Selected composer id to its workspace directory, for open Cursor windows.

    A Cursor chat has no process of its own. The open window's selected
    composers are the live chats.
    """
    projects = cursor_window_projects()
    if not projects:
        return {}
    root = storage_root or (
        Path.home() / "Library/Application Support/Cursor/User/workspaceStorage"
    )
    if not root.is_dir():
        return {}
    found: dict[str, str] = {}
    try:
        folders = list(root.iterdir())
    except OSError:
        return {}
    for folder in folders:
        directory = _workspace_directory(folder / "workspace.json")
        if not directory or Path(directory).name not in projects:
            continue
        for session_id in _selected_composer_ids(folder / "state.vscdb"):
            found.setdefault(session_id, directory)
    return found


def cursor_composer_names(
    session_ids: set[str], db_path: Path | None = None
) -> dict[str, str]:
    """Composer display names, looked up by id. Missing names are omitted.

    Prefer ``composerHeaders``. When a chat has no header row (common for older
    or migrated composers), fall back to ``cursorDiskKV`` key
    ``composerData:<id>`` which still carries ``name``.
    """
    if not session_ids:
        return {}
    path = db_path or (
        Path.home()
        / "Library/Application Support/Cursor/User/globalStorage/state.vscdb"
    )
    if not path.is_file():
        return {}
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1)
    except sqlite3.Error:
        return {}
    names: dict[str, str] = {}
    try:
        rows = con.execute(
            "SELECT composerId, value FROM composerHeaders WHERE composerId IN ({})".format(
                ",".join("?" for _ in session_ids)
            ),
            tuple(session_ids),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    for composer_id, raw in rows:
        name = _composer_name_from_json(raw)
        if isinstance(composer_id, str) and name:
            names[composer_id] = name
    missing = [sid for sid in session_ids if sid not in names]
    if not missing:
        return names
    try:
        kv_rows = con.execute(
            "SELECT key, value FROM cursorDiskKV WHERE key IN ({})".format(
                ",".join("?" for _ in missing)
            ),
            tuple(f"composerData:{sid}" for sid in missing),
        ).fetchall()
    except sqlite3.Error:
        return names
    for key, raw in kv_rows:
        if not isinstance(key, str) or not key.startswith("composerData:"):
            continue
        composer_id = key[len("composerData:") :]
        name = _composer_name_from_json(raw)
        if composer_id and name:
            names[composer_id] = name
    return names


def _composer_name_from_json(raw: Any) -> str:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    if not isinstance(raw, str):
        return ""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    if not isinstance(data, dict):
        return ""
    name = data.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return ""


def _workspace_directory(path: Path) -> str:
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return ""
    if not isinstance(meta, dict):
        return ""
    raw = meta.get("folder") or meta.get("workspace") or ""
    if not isinstance(raw, str) or not raw:
        return ""
    location = unquote(urlparse(raw).path)
    if not location:
        return ""
    # Multi-root: workspace.json points at a .code-workspace file. Use its
    # parent directory as the window's project root (matches the title leaf).
    if location.endswith(".code-workspace"):
        parent = Path(location).parent
        return str(parent) if str(parent) not in {"", "."} else ""
    return location


def _workspace_folder_name(path: Path) -> str:
    location = _workspace_directory(path)
    return Path(location).name if location else ""


def _selected_composer_ids(db_path: Path) -> set[str]:
    if not db_path.is_file():
        return set()
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        row = con.execute(
            "SELECT value FROM ItemTable WHERE key = ?",
            ("composer.composerData",),
        ).fetchone()
    except sqlite3.Error:
        return set()
    if not row:
        return set()
    raw = row[0]
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return set()
    if not isinstance(data, dict):
        return set()
    ids = data.get("selectedComposerIds") or []
    if not isinstance(ids, list):
        return set()
    return {item for item in ids if isinstance(item, str) and item}


def _cached(
    agent_type: str, session_id: str, load: Any
) -> dict[str, Any] | None:
    # Explicit roots never reach here. Default-home reads are the poll path,
    # and tests reuse session ids under different temp roots.
    key = (agent_type, session_id)
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None and now - hit[0] < _CACHE_TTL_SECONDS:
            return _copy_tokens(hit[1])
    value = load()
    stored = _copy_tokens(value)
    with _cache_lock:
        _cache[key] = (time.monotonic(), stored)
    return _copy_tokens(stored)


def _copy_tokens(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return dict(value)


def _safe_session_id(session_id: str) -> bool:
    return bool(session_id) and "/" not in session_id and "\\" not in session_id


def _claude_files(root: Path, session_id: str) -> list[Path]:
    if not _safe_session_id(session_id):
        return []
    filename = f"{session_id}.jsonl"
    try:
        children = list(root.iterdir())
    except OSError:
        return []
    found: list[Path] = []
    for child in children:
        candidate = child / filename
        try:
            if child.is_dir() and candidate.is_file():
                found.append(candidate)
        except OSError:
            continue
    return found


def _sum_claude(session_id: str, root: Path) -> dict[str, int] | None:
    totals = {key: 0 for key in _CLAUDE_TOKEN_KEYS}
    found_usage = False
    for path in _claude_files(root, session_id):
        for obj in _iter_json_objects(path):
            usage = _message_usage(obj)
            if usage is None:
                continue
            found_usage = True
            for key in _CLAUDE_TOKEN_KEYS:
                totals[key] += _as_int(usage.get(key))
    if not found_usage:
        return None
    return totals


def _codex_name_matches(name: str, session_id: str) -> bool:
    escaped = re.escape(session_id)
    stamped = (
        rf"rollout-\d{{4}}-\d{{2}}-\d{{2}}T\d{{2}}-\d{{2}}-\d{{2}}-{escaped}\.jsonl"
    )
    return (
        re.fullmatch(stamped, name) is not None
        or re.fullmatch(rf"rollout-x-{escaped}\.jsonl", name) is not None
    )


def _codex_files(root: Path, session_id: str) -> list[Path]:
    if not _safe_session_id(session_id):
        return []
    try:
        matches = list(root.glob("*/*/*/rollout-*.jsonl"))
    except OSError:
        return []
    found = [path for path in matches if _codex_name_matches(path.name, session_id)]
    found.sort()
    return found


def _latest_codex(session_id: str, root: Path) -> dict[str, Any] | None:
    for path in reversed(_codex_files(root, session_id)):
        total = _last_total_token_usage(path)
        if total is not None:
            return total
    return None


def _last_total_token_usage(path: Path) -> dict[str, int] | None:
    try:
        for raw in _reversed_lines(path):
            obj = _parse_json_object(raw)
            if obj is None:
                continue
            total = _total_token_usage(obj)
            if total is None:
                continue
            cleaned = _codex_ints(total)
            if cleaned is not None:
                return cleaned
    except OSError:
        return None
    return None


def _reversed_lines(path: Path):
    """Yield JSONL lines from the end, one chunk at a time."""
    try:
        fh = path.open("rb")
    except OSError:
        return
    with fh:
        fh.seek(0, os.SEEK_END)
        position = fh.tell()
        pending = b""
        while position > 0:
            size = min(_CODEX_READ_CHUNK, position)
            position -= size
            fh.seek(position)
            pending = fh.read(size) + pending
            parts = pending.split(b"\n")
            if position > 0:
                pending = parts[0]
                parts = parts[1:]
            else:
                pending = b""
            for part in reversed(parts):
                if part.strip():
                    yield part


def _iter_json_objects(path: Path):
    try:
        fh = path.open("rb")
    except OSError:
        return
    with fh:
        for raw in fh:
            obj = _parse_json_object(raw)
            if obj is not None:
                yield obj


def _parse_json_object(raw: bytes) -> dict[str, Any] | None:
    try:
        line = raw.decode("utf-8").strip()
        if not line:
            return None
        obj = json.loads(line)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    return obj


def _message_usage(obj: dict[str, Any]) -> dict[str, Any] | None:
    message = obj.get("message")
    if not isinstance(message, dict):
        return None
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None
    return usage


def _total_token_usage(obj: dict[str, Any]) -> dict[str, Any] | None:
    payload = obj.get("payload")
    if not isinstance(payload, dict):
        return None
    info = payload.get("info")
    if not isinstance(info, dict):
        return None
    total = info.get("total_token_usage")
    if not isinstance(total, dict):
        return None
    return total


def _codex_ints(total: dict[str, Any]) -> dict[str, int] | None:
    cleaned: dict[str, int] = {}
    for key in _CODEX_TOKEN_KEYS:
        if key not in total:
            continue
        value = total[key]
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        cleaned[key] = value
    return cleaned or None


def _as_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    try:
        return int(value)
    except (OverflowError, ValueError):
        return 0
