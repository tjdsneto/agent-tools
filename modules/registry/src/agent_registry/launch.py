"""Permission flags a Claude session was launched with, kept for a later resume.

A resumed run gets only the flags of the new command. Without this record a resume
cannot keep the limits the session started with (for example a narrowed --allowedTools).
The record lives in its own file because SessionEnd deletes the sidecar.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import json
import os
import sys
import tempfile
from pathlib import Path

from agent_registry.models import now_iso
from agent_registry.session_state import data_dir

# Flags that take no value.
SWITCHES = frozenset({"--dangerously-skip-permissions", "--allow-dangerously-skip-permissions"})
# Flags that take one value.
SINGLE = frozenset({"--permission-mode"})
# Flags that take values up to the next flag.
VARIADIC = frozenset({
    "--allowedTools", "--allowed-tools",
    "--disallowedTools", "--disallowed-tools",
    "--tools", "--add-dir",
})

_CTL_KERN, _KERN_ARGMAX, _KERN_PROCARGS2 = 1, 8, 49


def _macos_argv(pid: int) -> list[str] | None:
    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    argmax = ctypes.c_int(0)
    size = ctypes.c_size_t(ctypes.sizeof(argmax))
    if libc.sysctl((ctypes.c_int * 2)(_CTL_KERN, _KERN_ARGMAX), 2, ctypes.byref(argmax), ctypes.byref(size), None, 0):
        return None
    buf = ctypes.create_string_buffer(argmax.value)
    size = ctypes.c_size_t(argmax.value)
    if libc.sysctl((ctypes.c_int * 3)(_CTL_KERN, _KERN_PROCARGS2, pid), 3, buf, ctypes.byref(size), None, 0):
        return None
    raw = buf.raw[: size.value]
    argc = int.from_bytes(raw[:4], sys.byteorder)
    # argc, then the exec path, NUL padding, then argv.
    rest = raw[4:]
    rest = rest[rest.find(b"\0"):].lstrip(b"\0")
    return [part.decode(errors="replace") for part in rest.split(b"\0")[:argc]]


def process_argv(pid: int) -> list[str] | None:
    """Exact argv of a process. ps joins it with spaces, which loses rules like `Bash(git log:*)`."""
    try:
        if sys.platform == "darwin":
            return _macos_argv(pid)
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
        return [part.decode(errors="replace") for part in raw.split(b"\0") if part]
    except (OSError, ValueError):
        return None


def permission_args(argv: list[str]) -> list[str]:
    """The permission flags in a Claude argv, normalized to `--flag value...` form."""
    out: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        name, eq, inline = arg.partition("=")
        if arg in SWITCHES:
            out.append(arg)
        elif name in SINGLE:
            if eq:
                out += [name, inline]
            elif i + 1 < len(argv):
                out += [name, argv[i + 1]]
                i += 1
        elif name in VARIADIC:
            values = [inline] if eq else []
            while not eq and i + 1 < len(argv) and not argv[i + 1].startswith("-"):
                values.append(argv[i + 1])
                i += 1
            if values:
                out += [name, *values]
        i += 1
    return out


def path(session_id: str) -> Path:
    return data_dir() / "launch" / "claude" / f"{session_id.strip().replace('/', '_')}.json"


def record(session_id: str, pid: int, *, argv_of=None) -> list[str] | None:
    """Save the permission flags of the session's process. None when its argv is unreadable."""
    argv = (argv_of or process_argv)(pid)
    if not argv:
        return None
    args = permission_args(argv[1:])
    target = path(session_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"pid": pid, "recorded_at": now_iso(), "args": args}, f)
            f.write("\n")
        os.replace(tmp, target)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise
    return args


def load(session_id: str) -> list[str] | None:
    """Saved flags ([] when it launched with none), or None when nothing was recorded."""
    try:
        data = json.loads(path(session_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    args = data.get("args")
    return args if isinstance(args, list) and all(isinstance(a, str) for a in args) else None
