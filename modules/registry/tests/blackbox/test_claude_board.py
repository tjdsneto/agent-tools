"""Real Claude session on a temp registry. Default pytest does not collect this."""

import json
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
from pathlib import Path

from agent_registry.client import _OPENER, call, stop_if_ours


def test_claude_session_shows_tokens_on_the_board(tmp_path, monkeypatch):
    claude = shutil.which("claude")
    assert claude, "claude is not on PATH"
    registry = tmp_path / "registry.json"
    monkeypatch.setenv("AGENT_REGISTRY_PATH", str(registry))
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    monkeypatch.setenv("AGENT_REGISTRY_DAEMON_PORT", str(port))
    monkeypatch.setenv("AGENT_REGISTRY_DAEMON_START_TIMEOUT", "5")

    # SessionEnd unregisters the row before `claude -p` returns, and the daemon
    # caches a token read for 5s. Poll /api/live while the process is alive, and
    # do the first read only after this cwd's transcript has output_tokens.
    box: dict = {}

    def run_claude():
        try:
            box["proc"] = subprocess.run(
                [claude, "-p", "Reply with the single word pong."],
                cwd=tmp_path,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            box["timeout"] = True

    worker = None
    try:
        assert call("list", {})["exit_code"] == 0
        started = time.monotonic()
        worker = threading.Thread(target=run_claude)
        worker.start()
        found, last_live = _poll_live(port, tmp_path, started)
        worker.join(timeout=130)
        assert "timeout" not in box, "claude timed out"
        assert not worker.is_alive(), "claude timed out"
        proc = box["proc"]
        assert proc.returncode == 0, proc.returncode
        assert found is not None, _miss_message(last_live)
        assert "registry_id" not in found
        assert found["session_id"]
        with _OPENER.open(f"http://127.0.0.1:{port}/", timeout=5) as resp:
            html = resp.read().decode()
        assert "engine-claude" in html
        assert "tokens" in html
    finally:
        if worker is not None:
            worker.join(timeout=130)
        stop_if_ours()


def _poll_live(port: int, cwd: Path, started: float):
    deadline = started + 60
    found = None
    last_live = None
    armed = False
    while time.monotonic() < deadline:
        if not armed and _cwd_transcript_has_output_tokens(cwd, started):
            armed = True
        if armed:
            found, last_live = _claude_row_with_output_tokens(port)
            if found is not None:
                return found, last_live
        time.sleep(0.25)
    if not armed:
        found, last_live = _claude_row_with_output_tokens(port)
    return found, last_live


def _claude_row_with_output_tokens(port: int):
    url = f"http://127.0.0.1:{port}/api/live"
    try:
        with _OPENER.open(url, timeout=5) as resp:
            live = json.loads(resp.read().decode())
    except (OSError, UnicodeError, json.JSONDecodeError, urllib.error.URLError):
        return None, None
    if not isinstance(live, dict):
        return None, None
    for key in ("active", "attention", "stale"):
        rows = live.get(key) or []
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict) or row.get("agent_type") != "claude":
                continue
            tokens = row.get("tokens") or {}
            if not isinstance(tokens, dict):
                continue
            output = tokens.get("output_tokens", 0)
            if isinstance(output, bool) or not isinstance(output, (int, float)):
                continue
            if output > 0:
                return row, live
    return None, live


def _cwd_transcript_has_output_tokens(cwd: Path, started: float) -> bool:
    started_wall = time.time() - (time.monotonic() - started)
    for directory in _project_dirs(cwd):
        try:
            files = list(directory.glob("*.jsonl"))
        except OSError:
            continue
        for path in files:
            try:
                if path.stat().st_mtime < started_wall - 2:
                    continue
            except OSError:
                continue
            if _jsonl_has_output_tokens(path):
                return True
    return False


def claude_project_dir_name(path: Path) -> str:
    """Claude encodes a cwd by turning '/' and '_' into '-'."""
    return str(path).replace("/", "-").replace("_", "-")


def test_claude_project_dir_name_matches_claude_encoding():
    path = Path(
        "/private/var/folders/7g/zpstdp1528j9bb_gljk1dbz80000gn/T/"
        "pytest-of-tjdsneto/pytest-71/test_claude_session_shows_toke0"
    )
    assert claude_project_dir_name(path) == (
        "-private-var-folders-7g-zpstdp1528j9bb-gljk1dbz80000gn-T-"
        "pytest-of-tjdsneto-pytest-71-test-claude-session-shows-toke0"
    )


def _project_dirs(cwd: Path) -> list[Path]:
    root = Path.home() / ".claude" / "projects"
    if not root.is_dir():
        return []
    found: list[Path] = []
    for candidate in (cwd, cwd.resolve()):
        exact = root / claude_project_dir_name(candidate)
        if exact.is_dir() and exact not in found:
            found.append(exact)
    needle = claude_project_dir_name(Path(cwd.name)).lstrip("-")
    if not needle:
        return found
    try:
        children = list(root.iterdir())
    except OSError:
        return found
    for child in children:
        try:
            if child.is_dir() and needle in child.name and child not in found:
                found.append(child)
        except OSError:
            continue
    return found


def _jsonl_has_output_tokens(path: Path) -> bool:
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if '"output_tokens"' not in line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                usage = _message_usage(obj)
                if usage is None:
                    continue
                output = usage.get("output_tokens")
                if isinstance(output, bool) or not isinstance(output, (int, float)):
                    continue
                if output > 0:
                    return True
    except OSError:
        return False
    return False


def _message_usage(obj: object):
    if not isinstance(obj, dict):
        return None
    message = obj.get("message")
    if not isinstance(message, dict):
        return None
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None
    return usage


def _miss_message(live: dict | None) -> str:
    if not isinstance(live, dict):
        return "claude session did not report output_tokens"
    counts = []
    for key in ("active", "attention", "stale"):
        rows = live.get(key) or []
        count = len(rows) if isinstance(rows, list) else 0
        counts.append(f"{key}={count}")
    return "claude session did not report output_tokens (" + ", ".join(counts) + ")"
