# Registry Daemon Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One loopback daemon owns the registry files, the CLI becomes its client, and the existing board shows engine marks, live usage, parent nesting, and per-session Archive, Kill, and Send.

**Architecture:** `agent_registry/daemon.py` serves the current board plus `GET /api/health` and `POST /api/command`. Session logic stays in `ops`, `lifecycle`, `archive`, `summarize`, and `transport`. `agent_registry/client.py` starts that process when it is down and is the only production caller. CPU, memory, and tokens are attached while building `/api/live` and are not written back to `registry.json`.

**Tech Stack:** Python 3 stdlib (`http.server.ThreadingHTTPServer`, `urllib`, `subprocess`), pytest, the existing `dashboard.html`. No new dependencies.

**Slice:** 1 of 2. The macOS menu-bar app in `desktop/` is a later plan. Do not scaffold Tauri in this plan.

**Living spec:** When the daemon behavior lands, write `docs/specs/daemon.md` and add its row to `docs/specs/README.md` in that same commit. Do not edit `docs/superpowers/specs/2026-11-16-registry-daemon-design.md` to match later code.

---

## File map

| File | Responsibility |
|---|---|
| `agent_registry/daemon.py` | Bind `127.0.0.1`, pid and port files, HTTP routes, command dispatch, graceful stop |
| `agent_registry/usage.py` | `ps` sample and Claude/Codex token reads. No registry writes |
| `agent_registry/client.py` | Resolve the live port, start-if-down, `POST /api/command` |
| `agent_registry/cli.py` | Keep argparse. Replace in-process ops calls with `client.call` |
| `agent_registry/dashboard.py` | Keep `DashboardHandler` read routes. Daemon subclasses it |
| `agent_registry/static/dashboard.html` | Engine mark, usage line, Archive / Kill / Send. Nesting stays |
| `tests/test_daemon.py` | Health, command roundtrip, bind races, usage, actions |
| `tests/conftest.py` | Skip `tests/blackbox` unless that path was requested |
| `tests/blackbox/test_claude_board.py` | Real `claude -p`, token appears on the board |
| `docs/specs/daemon.md` | Living spec for the daemon and the board actions |

Ops, archive, lifecycle, and model tests keep calling those modules directly. They must not start a daemon.

---

### Task 1: Health and bind

**Files:**
- Create: `agent_registry/daemon.py`
- Create: `tests/test_daemon.py`
- Modify: `agent_registry/constants.py`

- [ ] **Step 1: Write the failing test**

```python
import json
import os
import urllib.request
from pathlib import Path

from agent_registry.daemon import serve_in_thread, stop_server


def test_health_and_pid_files(tmp_registry):
    httpd = serve_in_thread("127.0.0.1", 0)
    port = httpd.server_address[1]
    try:
        body = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health").read())
        assert body == {"ok": True, "service": "agent-registry"}
        reg_dir = Path(os.environ["AGENT_REGISTRY_PATH"]).parent
        assert (reg_dir / "daemon.port").read_text().strip() == str(port)
        pid = int((reg_dir / "daemon.pid").read_text().strip())
        assert pid == os.getpid()
    finally:
        stop_server(httpd)
        reg_dir = Path(os.environ["AGENT_REGISTRY_PATH"]).parent
        assert not (reg_dir / "daemon.pid").exists()
        assert not (reg_dir / "daemon.port").exists()
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/test_daemon.py::test_health_and_pid_files -v`
Expected: FAIL with `cannot import name 'serve_in_thread'`

- [ ] **Step 3: Implement the server**

Add to `agent_registry/constants.py`:

```python
DAEMON_SERVICE = "agent-registry"
DAEMON_START_TIMEOUT = 5.0
```

`agent_registry/daemon.py`:

```python
from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from agent_registry.constants import DAEMON_SERVICE
from agent_registry.dashboard import DashboardHandler
from agent_registry.store import registry_path


def _reg_dir() -> Path:
    return registry_path().parent


def _write_identity(port: int) -> None:
    directory = _reg_dir()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "daemon.pid").write_text(str(os.getpid()), encoding="utf-8")
    (directory / "daemon.port").write_text(str(port), encoding="utf-8")


def _clear_identity() -> None:
    for name in ("daemon.pid", "daemon.port"):
        path = _reg_dir() / name
        try:
            path.unlink()
        except FileNotFoundError:
            pass


class DaemonHandler(DashboardHandler):
    def do_GET(self) -> None:
        if urlparse(self.path).path == "/api/health":
            self._json({"ok": True, "service": DAEMON_SERVICE})
            return
        super().do_GET()

    def _json(self, payload: Any, *, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def make_daemon(host: str, port: int) -> ThreadingHTTPServer:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise OSError(f"daemon refuses non-loopback host {host}")
    return ThreadingHTTPServer((host, port), DaemonHandler)


def serve_in_thread(host: str, port: int) -> ThreadingHTTPServer:
    httpd = make_daemon(host, port)
    _write_identity(httpd.server_address[1])
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def stop_server(httpd: ThreadingHTTPServer) -> None:
    httpd.shutdown()
    httpd.server_close()
    _clear_identity()


def run_foreground(host: str = "127.0.0.1", port: int = 8765) -> None:
    httpd = make_daemon(host, port)
    _write_identity(httpd.server_address[1])
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
        _clear_identity()
```

`DashboardHandler._json` already exists. Delete the duplicate `_json` on `DaemonHandler` and call `self._json` from the parent. The snippet above repeats it so the first test passes even if the parent method is easy to miss; after the test is green, remove the subclass `_json` and re-run.

- [ ] **Step 4: Run the test**

Run: `pytest tests/test_daemon.py::test_health_and_pid_files -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent_registry/daemon.py agent_registry/constants.py tests/test_daemon.py
git commit -m "feat: loopback daemon health and pid files"
```

---

### Task 2: Command dispatch for ensure, list, and end

**Files:**
- Modify: `agent_registry/daemon.py`
- Modify: `tests/test_daemon.py`

- [ ] **Step 1: Write the failing test**

```python
def test_command_ensure_list_end_strips_registry_id_on_list(tmp_registry):
    httpd = serve_in_thread("127.0.0.1", 0)
    port = httpd.server_address[1]
    url = f"http://127.0.0.1:{port}/api/command"

    def post(op, params):
        req = urllib.request.Request(
            url,
            data=json.dumps({"op": op, "params": params}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return json.loads(urllib.request.urlopen(req).read())

    try:
        ensured = post("ensure", {
            "agent_type": "cursor",
            "session_id": "s1",
            "directory": "/proj",
            "parent_session": "parent-1",
        })
        assert ensured["exit_code"] == 0
        assert ensured["data"]["session"]["registry_id"]
        assert ensured["data"]["session"]["parent_session_id"] == "parent-1"
        listed = post("list", {})
        assert listed["exit_code"] == 0
        assert "registry_id" not in listed["data"]["active"][0]
        assert listed["data"]["active"][0]["parent_session_id"] == "parent-1"
        ended = post("end", {"agent_type": "cursor", "session_id": "s1"})
        assert ended["exit_code"] == 0
        again = post("list", {})
        assert again["data"]["active"] == []
    finally:
        stop_server(httpd)
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/test_daemon.py::test_command_ensure_list_end_strips_registry_id_on_list -v`
Expected: FAIL. `POST /api/command` is 404 or the handler has no `do_POST`.

- [ ] **Step 3: Implement dispatch**

Add `do_POST` on `DaemonHandler`. Read the body, require `op` and `params`, call `dispatch`, always answer HTTP 200 with `{exit_code, data, error}`. Map exceptions the way `cli.main` does today:

- `ops.ValidationError`, `archive.ValidationError`, `ops.DuplicateSessionError`, `transport.UnsupportedTransportError` → exit 1
- `ops.UnknownRegistryIdError`, `transport.SessionNotFoundError` → exit 2
- `CorruptRegistryError`, `archive.ArchiveIOError`, `OSError` → exit 3

`dispatch(op, params)`:

```python
def dispatch(op: str, params: dict) -> tuple[int, Any, str | None]:
    from agent_registry.constants import EXIT_NOT_FOUND, EXIT_OK
    if op == "ensure":
        result = lifecycle.ensure(
            params["agent_type"],
            params["session_id"],
            params["directory"],
            parent_session=params.get("parent_session"),
            model=params.get("model"),
            title=params.get("title"),
            replace=not params.get("no_replace", False),
            peer_name=params.get("peer_name"),
            socket=params.get("socket"),
            pid=params.get("pid"),
            peer_status=params.get("peer_status"),
        )
        session = result["session"]
        if not isinstance(session, dict):
            session = session.to_dict()
        result = {"created": result["created"], "session": session}
        return EXIT_OK, result, None
    if op == "list":
        active, stale = ops.list_split()
        return EXIT_OK, {"active": active, "stale": stale}, None
    if op == "end":
        return EXIT_OK, lifecycle.end(params["agent_type"], params["session_id"]), None
    return 1, None, f"unknown op {op}"
```

`lifecycle.ensure` already returns a dict whose `session` value may be a `Session`. Convert with `session.to_dict()` when it is not a dict, before JSON encoding. `lifecycle.end` returns a dict. Confirm both against the functions before pasting, and return JSON-ready dicts only.

- [ ] **Step 4: Run the test**

Run: `pytest tests/test_daemon.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent_registry/daemon.py tests/test_daemon.py
git commit -m "feat: daemon command endpoint for ensure, list, and end"
```

---

### Task 3: Remaining command ops

**Files:**
- Modify: `agent_registry/daemon.py`
- Modify: `tests/test_daemon.py`

- [ ] **Step 1: Write the failing test**

Cover one call each, all through `POST /api/command` on a thread server, and assert exit codes:

- `register` returns `data.registry_id`
- `update` with no fields returns exit 1
- `ping` of an unknown id returns exit 2
- `unregister` then `archive_list` returns the event without `registry_id`
- `archive_show` without `--full` omits `registry_id`; with `full: true` includes it
- `prune` without `yes` or `dry_run` returns exit 1
- `self` after `ensure` returns `registry_id`
- `status` returns `active`, `stale`, `archived`, `registry_path`, `archive_path`
- `doctor` returns `{"lines": [...], "ok": true}` when the temp registry parent is writable
- `resolve` of an unknown id returns exit 2
- `summarize` with the provider forced off returns exit 0 and `data.ok` false or skipped

Set `AGENT_REGISTRY_SUMMARY_PROVIDER=off` in the summarize test so it does not call Ollama.

- [ ] **Step 2: Run the test**

Run: `pytest tests/test_daemon.py::test_remaining_ops -v`
Expected: FAIL with `unknown op`

- [ ] **Step 3: Extend `dispatch`**

Add ops whose names match the CLI commands: `register`, `update`, `ping`, `unregister`, `prune`, `heartbeat`, `self`, `summarize`, `archive_list`, `archive_show`, `archive_purge`, `resolve`, `wake`, `status`, `doctor`.

Each branch calls the existing function and returns its current JSON-ready value:

- `ops.register`, `ops.update`, `ops.ping` → `session.to_dict()`
- `ops.unregister` → `{"ok": True}`
- `ops.prune` → the list of public session dicts it already returns
- `lifecycle.heartbeat` and `lifecycle.self_view` → the dicts they already return; `self` with `None` is exit 2 and error `session not found`
- `archive.list_events` mapped through `archive.public_event`
- `archive.purge_older_than`
- `transport.resolve_session`, `transport.wake`
- `doctor.status_payload`
- doctor lines: call the same checks as `doctor.run_doctor` but return `{"ok": bool, "lines": [str, ...]}` instead of printing. Extract `doctor.collect()` from the current print loop so `run_doctor` prints `collect()` and the daemon returns it. Do not duplicate the path and lock checks.

`wake` params are `session_id` and `message` (the text, not a file path). The CLI still accepts `--message` as a file path and reads it before calling the daemon.

Unknown op stays exit 1.

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_daemon.py tests/test_ops.py tests/test_cli.py -v`
Expected: `test_daemon.py` PASS. `test_cli.py` still passes because `main()` has not moved yet.

- [ ] **Step 5: Commit**

```bash
git add agent_registry/daemon.py agent_registry/doctor.py tests/test_daemon.py
git commit -m "feat: daemon dispatch for the remaining registry commands"
```

---

### Task 4: CLI client that starts the daemon

**Files:**
- Create: `agent_registry/client.py`
- Create: `tests/test_client.py`
- Modify: `agent_registry/cli.py` to add the `daemon` subcommand only. Do not switch other commands yet.

- [ ] **Step 1: Write the failing tests**

```python
def test_call_starts_daemon_and_lists(tmp_registry, monkeypatch):
    monkeypatch.setenv("AGENT_REGISTRY_DAEMON_PORT", "0")  # replaced below
    # Ask for a free port by binding and closing one, then set the env to that port.
    import socket
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    monkeypatch.setenv("AGENT_REGISTRY_DAEMON_PORT", str(port))
    monkeypatch.setenv("AGENT_REGISTRY_DAEMON_START_TIMEOUT", "5")
    from agent_registry.client import call, stop_if_ours
    try:
        result = call("ensure", {
            "agent_type": "cursor", "session_id": "s1", "directory": "/proj",
        })
        assert result["exit_code"] == 0
        listed = call("list", {})
        assert listed["data"]["active"][0]["session_id"] == "s1"
    finally:
        stop_if_ours()
```

```python
def test_stranger_on_port_does_not_write_registry(tmp_registry, monkeypatch):
    import socket
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.listen(1)
    monkeypatch.setenv("AGENT_REGISTRY_DAEMON_PORT", str(port))
    monkeypatch.setenv("AGENT_REGISTRY_DAEMON_START_TIMEOUT", "0.2")
    from agent_registry.client import call
    try:
        result = call("list", {})
        assert result["exit_code"] == 3
        assert not tmp_registry.exists()
    finally:
        sock.close()
```

The stranger socket accepts TCP and is not `/api/health`. `call` must not spawn, and must not create `registry.json`.

- [ ] **Step 2: Run the tests**

Run: `pytest tests/test_client.py -v`
Expected: FAIL with `No module named 'agent_registry.client'`

- [ ] **Step 3: Implement `client.py`**

`call(op, params) -> {"exit_code", "data", "error"}`:

1. Port is `daemon.port` when `daemon.pid` is alive. If `AGENT_REGISTRY_DAEMON_PORT` or an explicit port argument disagrees, return exit 1 and error `daemon already listening on <port>`.
2. Otherwise the port is `AGENT_REGISTRY_DAEMON_PORT` or `DASHBOARD_DEFAULT_PORT` (8765).
3. `GET /api/health`. Our document is `{"ok": true, "service": "agent-registry"}`.
4. Connection accepted but the body differs: return exit 3, do not spawn.
5. Connection refused: re-exec `sys.argv[0]` with `["daemon", "--port", str(port)]` via `subprocess.Popen(..., start_new_session=True)`, stdout and stderr appended to `<registry-dir>/daemon.log`. Inherit the environment, including `AGENT_REGISTRY_PATH`.
6. Poll health every 100ms until the timeout. Timeout is `AGENT_REGISTRY_DAEMON_START_TIMEOUT` or 5 seconds. Return as soon as health matches.
7. POST `/api/command` once. Return the JSON body.
8. If health never arrives, return exit 3 and error `daemon did not become healthy`. Do not import `ops` or `store` write helpers.

`stop_if_ours()` reads `daemon.pid`, sends `SIGTERM` if the pid is alive, and is used by tests. Production stop is Task 6.

Add CLI:

```python
p_daemon = sub.add_parser("daemon")
daemon_sub = p_daemon.add_subparsers(dest="daemon_cmd", required=True)
p_run = daemon_sub.add_parser("run")
p_run.add_argument("--port", type=int, default=None)
```

`agent-registry daemon run --port N` calls `daemon.run_foreground("127.0.0.1", port)`. The client spawns `daemon run`. Port `0` is not used in production. Tests pick a free port, set the env, and the child binds that port.

If bind raises `EADDRINUSE`, `run_foreground` catches it, GETs `/api/health` on that port, and exits 0 when the service matches. Otherwise it exits 3.

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_client.py tests/test_daemon.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent_registry/client.py agent_registry/cli.py agent_registry/daemon.py tests/test_client.py
git commit -m "feat: CLI client starts the daemon when it is down"
```

---

### Task 5: Point every registry command at the client

**Files:**
- Modify: `agent_registry/cli.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Write the failing test in `tests/test_client.py`**

```python
def test_main_list_goes_through_the_daemon(tmp_registry, capsys, monkeypatch):
    import socket
    from agent_registry.cli import main
    from agent_registry.client import stop_if_ours
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    monkeypatch.setenv("AGENT_REGISTRY_DAEMON_PORT", str(port))
    monkeypatch.setenv("AGENT_REGISTRY_DAEMON_START_TIMEOUT", "5")
    try:
        assert main(["register", "--type", "cursor", "--session-id", "s1", "--directory", "/proj"]) == 0
        out = capsys.readouterr().out
        assert "registry_id" in out  # owner command
        assert main(["list"]) == 0
        text = capsys.readouterr().out
        assert "Active" in text and "registry_id" not in text
    finally:
        stop_if_ours()
```

- [ ] **Step 2: Run it**

Run: `pytest tests/test_client.py::test_main_list_goes_through_the_daemon -v`
Expected: FAIL until `main` uses `client.call`. Today `main` still calls `ops.register` in-process, so this test passes for the wrong reason if a daemon is not required. Assert the daemon pid file exists after `register`:

```python
pidfile = tmp_registry.parent / "daemon.pid"
assert pidfile.exists()
```

Expected before the switch: FAIL because `daemon.pid` is missing.

- [ ] **Step 3: Switch `main`**

Keep argparse. After `parse_args`, build `op` and `params` from `args` and call `client.call`. Print `data` the way each command prints today:

- JSON commands: `print(json.dumps(data))`
- `list` without `--json`: `print(format_list(data["active"], data["stale"]), end="")`
- `archive list` without `--json`: `print(format_archive_list(data["events"]), end="")`
- `status` without `--json`: `print(doctor.format_status(data), end="")`
- `doctor`: print `data["lines"]` joined by newlines and return 0 or 3 from `data["ok"]`
- On `error`: `print(f"agent-registry: {error}", file=sys.stderr)` and return `exit_code`

`dashboard` does not use `call`. It calls `client.ensure_daemon(port)`, then opens the browser unless `--no-open`. `--host` other than loopback prints `agent-registry: dashboard host must be loopback` and returns 1. Delete `_find_free_port` usage from this command.

`wake` reads the message file in the CLI, then `call("wake", {"session_id", "message"})`.

Do not import `ops` inside the command branches. `ops` may remain imported only if something else in the file still needs it; after the switch, drop that import.

Add a session-scoped cleanup is unnecessary. Each CLI test that calls `main` must `stop_if_ours()` in `finally`, or a fixture in `tests/conftest.py`:

```python
@pytest.fixture
def daemon_port(tmp_registry, monkeypatch):
    import socket
    from agent_registry.client import stop_if_ours
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    monkeypatch.setenv("AGENT_REGISTRY_DAEMON_PORT", str(port))
    monkeypatch.setenv("AGENT_REGISTRY_DAEMON_START_TIMEOUT", "5")
    yield port
    stop_if_ours()
```

Use it from CLI tests. Do not make it autouse. Ops tests must not start a daemon.

Update existing `tests/test_cli*.py` cases that call `main` so they request `daemon_port`. Their assertions stay.

- [ ] **Step 4: Run the suite**

Run: `pytest -v`
Expected: PASS. No test imports `ops` through `cli.main`.

- [ ] **Step 5: Commit**

```bash
git add agent_registry/cli.py tests/conftest.py tests/test_cli.py tests/test_cli_lifecycle.py tests/test_cli_archive.py tests/test_client.py
git commit -m "feat: registry commands talk to the daemon"
```

The `git add` list must include every CLI test file that gained the `daemon_port` fixture. Run `git status` and add those files. Do not add unrelated dirty files.

---

### Task 6: Launchd install, start, stop, uninstall

**Files:**
- Modify: `agent_registry/cli.py`
- Modify: `agent_registry/client.py`
- Create: `tests/test_daemon_launchd.py`

- [ ] **Step 1: Write the failing test**

Monkeypatch `Path.home()` is unnecessary. Pass the LaunchAgents directory into `client.install_launchd(directory, program)`.

```python
def test_install_writes_plist(tmp_path):
    from agent_registry.client import install_launchd, plist_text
    agents = tmp_path / "LaunchAgents"
    program = "/usr/local/bin/agent-registry"
    path = install_launchd(agents, program, bootstrap=lambda *a: None)
    text = path.read_text()
    assert "com.tjdsneto.agent-registry" in text
    assert "<key>RunAtLoad</key>" in text
    assert "<key>KeepAlive</key>" in text
    assert program in text
    assert "daemon" in text and "run" in text
```

```python
def test_install_rejects_non_darwin(monkeypatch):
    import sys
    monkeypatch.setattr(sys, "platform", "linux")
    from agent_registry.cli import main
    assert main(["daemon", "install"]) == 1
```

- [ ] **Step 2: Run the tests**

Run: `pytest tests/test_daemon_launchd.py -v`
Expected: FAIL with import errors.

- [ ] **Step 3: Implement the plist and subcommands**

`plist_text(program)` returns the XML. `ProgramArguments` is `[program, "daemon", "run"]`. Label `com.tjdsneto.agent-registry`. `RunAtLoad` true. `KeepAlive` true. `StandardOutPath` and `StandardErrorPath` are `<registry-dir>/daemon.log`.

Subcommands under `daemon`:

- `run` — already added
- `install` — exit 1 when `sys.platform != "darwin"` with stderr `agent-registry: daemon install is macOS only`. Otherwise write `~/Library/LaunchAgents/com.tjdsneto.agent-registry.plist` and `launchctl bootstrap gui/<uid> <plist>`.
- `uninstall` — `launchctl bootout` that plist, then delete it. Missing plist is exit 0.
- `start` — bootstrap when the plist exists, otherwise `Popen` the same detached `daemon run` the client uses.
- `stop` — `SIGTERM` to `daemon.pid` when alive, then `launchctl bootout` when the plist exists, so KeepAlive does not restart it.

Tests pass `bootstrap` and `bootout` callables. The CLI wires those to `subprocess.run(["launchctl", ...], check=False)`.

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_daemon_launchd.py tests/test_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent_registry/client.py agent_registry/cli.py tests/test_daemon_launchd.py
git commit -m "feat: launchd install and stop for the registry daemon"
```

---

### Task 7: Usage on the live read

**Files:**
- Create: `agent_registry/usage.py`
- Modify: `agent_registry/daemon.py` (`GET /api/live` enriches `ops.live_views()`)
- Create: `tests/test_usage.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_ps_sample_omits_dead_pid(monkeypatch):
    from agent_registry.usage import sample_process
    monkeypatch.setattr("agent_registry.usage._ps", lambda pid: None)
    assert sample_process(999999) is None

def test_ps_sample_parses(monkeypatch):
    from agent_registry.usage import sample_process
    monkeypatch.setattr("agent_registry.usage._ps", lambda pid: "12.5 4096\n")
    assert sample_process(4) == {"cpu_percent": 12.5, "memory_bytes": 4096 * 1024}

def test_claude_tokens_sum_usage(tmp_path, monkeypatch):
    projects = tmp_path / "projects" / "abc"
    projects.mkdir(parents=True)
    sid = "sess-1"
    (projects / f"{sid}.jsonl").write_text(
        json.dumps({"message": {"usage": {
            "input_tokens": 10, "output_tokens": 2,
            "cache_read_input_tokens": 1, "cache_creation_input_tokens": 4,
        }}}) + "\n" +
        json.dumps({"message": {"usage": {
            "input_tokens": 3, "output_tokens": 5,
            "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
        }}}) + "\n",
        encoding="utf-8",
    )
    from agent_registry.usage import claude_tokens
    assert claude_tokens(sid, projects_root=tmp_path / "projects") == {
        "input_tokens": 13,
        "output_tokens": 7,
        "cache_read_input_tokens": 1,
        "cache_creation_input_tokens": 4,
    }

def test_codex_tokens_use_total(tmp_path):
    root = tmp_path / "sessions" / "2026" / "11" / "17"
    root.mkdir(parents=True)
    sid = "thread-1"
    line = json.dumps({"payload": {"info": {"total_token_usage": {
        "input_tokens": 8, "output_tokens": 1,
        "cached_input_tokens": 2, "cache_write_input_tokens": 0,
        "total_tokens": 9,
    }}}})
    (root / f"rollout-x-{sid}.jsonl").write_text(line + "\n", encoding="utf-8")
    from agent_registry.usage import codex_tokens
    assert codex_tokens(sid, sessions_root=tmp_path / "sessions")["total_tokens"] == 9

def test_live_attaches_usage_and_does_not_write_registry(tmp_registry):
    from agent_registry import ops
    ops.register(agent_type="claude", session_id="s1", directory="/p", pid=1)
    before = tmp_registry.read_text()
    httpd = serve_in_thread("127.0.0.1", 0)
    try:
        live = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{httpd.server_address[1]}/api/live"
        ).read())
        row = live["active"][0]
        assert "registry_id" not in row
        assert "cpu_percent" not in row or isinstance(row["cpu_percent"], float)
        assert tmp_registry.read_text() == before
    finally:
        stop_server(httpd)
```

`_ps` runs `ps -o pcpu=,rss= -p <pid>` and returns stdout, or `None` on any failure. `rss` is kibibytes on macOS; multiply by 1024 for `memory_bytes`.

- [ ] **Step 2: Run the tests**

Run: `pytest tests/test_usage.py -v`
Expected: FAIL with import errors

- [ ] **Step 3: Implement `usage.py` and enrich `/api/live`**

`claude_tokens` sums `message.usage` across every JSON object in `~/.claude/projects/*/<session_id>.jsonl`. Missing file returns `None`.

`codex_tokens` globs `~/.codex/sessions/*/*/*/rollout-*-<session_id>.jsonl`, walks lines from the end, and returns the first `payload.info.total_token_usage` dict. Missing returns `None`.

`cursor` has no reader. `tokens_for(session)` returns `None` for `agent_type == "cursor"`.

Cache successful and missing parses for 5 seconds keyed by `(agent_type, session_id)`, using `time.monotonic()`.

`attach_usage(view)` adds `cpu_percent` and `memory_bytes` only when `sample_process(view["pid"])` returns a dict. Adds `tokens` only when the reader returns a dict. Does not call `store` writes.

`DaemonHandler` `/api/live` calls `ops.live_views()` then `attach_usage` on every session in `active`, `stale`, and `attention`. Corrupt path stays `{"active": [], "stale": [], "attention": [], "corrupt": True}` with no usage walk.

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_usage.py tests/test_daemon.py tests/test_dashboard.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent_registry/usage.py agent_registry/daemon.py tests/test_usage.py
git commit -m "feat: attach cpu, memory, and token snapshots to the live read"
```

---

### Task 8: Archive, Kill, and Send by session id

**Files:**
- Modify: `agent_registry/daemon.py`
- Modify: `tests/test_daemon.py`

- [ ] **Step 1: Write the failing test**

```python
def test_archive_parent_leaves_child(tmp_registry):
    httpd = serve_in_thread("127.0.0.1", 0)
    port = httpd.server_address[1]
    try:
        post(port, "ensure", {"agent_type": "claude", "session_id": "parent", "directory": "/p", "pid": os.getpid()})
        post(port, "ensure", {
            "agent_type": "claude", "session_id": "child", "directory": "/p",
            "parent_session": "parent",
        })
        archived = post(port, "archive_session", {"session_id": "parent"})
        assert archived["exit_code"] == 0
        live = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/live").read())
        ids = [s["session_id"] for s in live["active"] + live["stale"] + live["attention"]]
        assert "parent" not in ids
        child = next(s for s in live["active"] if s["session_id"] == "child")
        assert child["parent_session_id"] == "parent"
        assert "registry_id" not in archived["data"]
    finally:
        stop_server(httpd)
```

```python
def test_kill_signals_only_that_pid(tmp_registry, monkeypatch):
    signaled = []
    monkeypatch.setattr("agent_registry.daemon.os.kill", lambda pid, sig: signaled.append((pid, sig)))
    httpd = serve_in_thread("127.0.0.1", 0)
    try:
        post(httpd.server_address[1], "ensure", {
            "agent_type": "claude", "session_id": "s", "directory": "/p", "pid": 4242,
        })
        killed = post(httpd.server_address[1], "kill_session", {"session_id": "s"})
        assert killed["exit_code"] == 0
        assert signaled == [(4242, signal.SIGTERM)]
        live = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{httpd.server_address[1]}/api/live"
        ).read())
        assert live["active"] == []
    finally:
        stop_server(httpd)
```

```python
def test_kill_without_pid_is_usage(tmp_registry):
    httpd = serve_in_thread("127.0.0.1", 0)
    try:
        post(httpd.server_address[1], "ensure", {
            "agent_type": "codex", "session_id": "s", "directory": "/p",
        })
        killed = post(httpd.server_address[1], "kill_session", {"session_id": "s"})
        assert killed["exit_code"] == 1
    finally:
        stop_server(httpd)
```

`send_session` calls `transport.wake(session_id, message)` and returns its dict. A test with `monkeypatch.setattr("agent_registry.transport.wake", lambda sid, msg, **k: {"result": "landed", "session_id": sid})` asserts exit 0 and that the message arrived. Empty message returns exit 1.

- [ ] **Step 2: Run the tests**

Run: `pytest tests/test_daemon.py::test_archive_parent_leaves_child tests/test_daemon.py::test_kill_signals_only_that_pid -v`
Expected: FAIL with `unknown op`

- [ ] **Step 3: Implement the three ops**

Look up the session by `session_id` inside the daemon via `store.load()`. Never accept a `registry_id` from the request.

- `archive_session`: `ops.unregister(session.registry_id)`. Missing session is exit 2. Response data is `{"ok": True, "session_id": ...}` with no `registry_id`.
- `kill_session`: if `pid` is missing or `usage.sample_process` is `None`, exit 1 and error `no live pid`. Otherwise `os.kill(pid, signal.SIGTERM)`, then `ops.unregister`. Do not walk `parent_session_id`.
- `send_session`: `transport.wake(session_id, message)`.

These ops are not CLI subcommands. The board calls them. The CLI stays without archive-by-button aliases.

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_daemon.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent_registry/daemon.py tests/test_daemon.py
git commit -m "feat: archive, kill, and send one session by public id"
```

---

### Task 9: Board row

**Files:**
- Modify: `agent_registry/static/dashboard.html`
- Modify: `tests/test_dashboard.py`

- [ ] **Step 1: Write the failing test**

Serve the dashboard HTML the way `test_api_live_and_archive` does. Register one Claude session with a pid and one Codex child whose parent is that Claude session. Fetch `/`. The HTML source is the shell; the behavior is in script. Assert the script contains:

- a mark element keyed by `agent_type` for `claude`, `codex`, and `cursor`
- `cpu_percent` and `tokens` rendered only when present
- buttons whose labels are `Archive`, `Kill`, and `Send`
- Kill hidden when `pid` is absent (`if (!sess.pid) return ""` in the kill button function)
- `archive_session` posted with `session_id` and not `registry_id`

Drive the nesting with a small node check rather than a browser if Playwright is not installed: extract is not required. Add a DOM-free unit by exporting the row rules is too large. Instead, assert the script text includes `parent_session_id` nesting via the existing `buildForest`, and add a comment-free string assert that `killBtn` returns `""` when `sess.pid` is missing. Then add one browser-free fetch of `/api/live` after `attach_usage` so a Claude row can carry `tokens`.

If a headless browser is already importable (`playwright`), use it in this task. If not, do not add the dependency. The black-box task adds the browser check.

- [ ] **Step 2: Run the test**

Run: `pytest tests/test_dashboard.py::test_board_actions_in_script -v`
Expected: FAIL because the buttons are absent.

- [ ] **Step 3: Edit `dashboard.html`**

In `rowHtml`, prepend a `<span class="engine engine-{type}">` using the lowercase `agent_type`. The visible text is `C`, `X`, or `>` for Claude, Codex, and Cursor. Those are the marks. Do not fetch remote logo assets.

Under the headline, when `sess.tokens` exists, show the total: Claude `input_tokens + output_tokens`, Codex `total_tokens`. When `cpu_percent` exists, show `cpu_percent` and `memory_bytes`.

Add buttons:

- Archive always. `POST /api/command` `{"op":"archive_session","params":{"session_id": sess.session_id}}`. On exit 0, poll immediately.
- Kill only when `sess.pid` is a positive number. Op `kill_session`.
- Send always for `claude`, `codex`, and `cursor`. `prompt()` for the message, then op `send_session`. Empty prompt does not POST.

`buildForest` stays the nesting. Do not remove the orphan parent id.

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_dashboard.py tests/test_daemon.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent_registry/static/dashboard.html tests/test_dashboard.py
git commit -m "feat: board shows engine marks, usage, and session actions"
```

---

### Task 10: Living daemon spec

**Files:**
- Create: `docs/specs/daemon.md`
- Modify: `docs/specs/README.md`

- [ ] **Step 1: Write `docs/specs/daemon.md` from the code, not from the historical design**

State the baseline as `master @ <git rev-parse --short HEAD>` after Task 9. Describe:

- The daemon is the only production opener of `registry.json`, `archive.jsonl`, the lock, and `by-session/`.
- `client.call` is the CLI path. Name `agent_registry.client.call` and `agent_registry.daemon.dispatch`.
- `/api/health`, `/api/live`, `/api/archive`, `POST /api/command`.
- Usage fields are read-time only. Name `agent_registry.usage.attach_usage`.
- Archive and Kill do not cascade. Name `archive_session` and `kill_session`.
- Parent link remains `parent_session_id`.

Every behavior line ends with the function that realizes it. No line numbers. No copy of the superpowers spec.

- [ ] **Step 2: Add the index row**

In `docs/specs/README.md`, replace the `*(none yet)*` row with a link to `daemon.md` and the one-line charter "Loopback daemon, CLI client, live usage, and board session actions."

- [ ] **Step 3: Commit**

```bash
git add docs/specs/daemon.md docs/specs/README.md
git commit -m "docs: living spec for the registry daemon"
```

---

### Task 11: Black-box Claude session

**Files:**
- Create: `tests/blackbox/test_claude_board.py`
- Modify: `tests/conftest.py`
- Modify: `docs/specs/daemon.md` with the command that runs this test

- [ ] **Step 1: Keep default pytest off this file**

In `tests/conftest.py`:

```python
def pytest_ignore_collect(collection_path, config):
    parts = getattr(collection_path, "parts", ())
    if "blackbox" not in parts:
        return False
    return not any("blackbox" in str(arg) for arg in config.args)
```

Confirm `pytest tests/test_daemon.py -q` does not import `tests/blackbox`, and `pytest tests/blackbox -q` collects `test_claude_board`.

- [ ] **Step 2: Write the test**

```python
def test_claude_session_shows_tokens_on_the_board(tmp_path, monkeypatch):
    import json
    import shutil
    import socket
    import subprocess
    import time
    import urllib.request
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
    from agent_registry.client import call, stop_if_ours
    try:
        assert call("list", {})["exit_code"] == 0
        proc = subprocess.run(
            [claude, "-p", "Reply with the single word pong."],
            cwd=tmp_path, capture_output=True, text=True, timeout=120,
        )
        assert proc.returncode == 0, proc.stderr
        deadline = time.monotonic() + 60
        found = None
        while time.monotonic() < deadline:
            live = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/live").read())
            for row in live["active"] + live["attention"]:
                tokens = row.get("tokens") or {}
                if row.get("agent_type") == "claude" and tokens.get("output_tokens", 0) > 0:
                    found = row
                    break
            if found:
                break
            time.sleep(1)
        assert found is not None, "claude session did not report output_tokens"
        html = urllib.request.urlopen(f"http://127.0.0.1:{port}/").read().decode()
        assert "engine-claude" in html
        assert "tokens" in html
        assert found["session_id"]
    finally:
        stop_if_ours()
```

The HTML shell does not contain the token digits. Those are filled by the page's fetch. The test asserts the digits on `/api/live` and asserts the shell contains `engine-claude` and `tokens`. Write that limit into `docs/specs/daemon.md`.

- [ ] **Step 3: Run unit tests, then the black box once**

Run: `pytest -q`
Expected: PASS, and `tests/blackbox` is not in the collected count.

Run: `pytest tests/blackbox -q`
Expected: PASS when `claude` is logged in. This spends tokens. Do not run it in a loop.

- [ ] **Step 4: Commit**

```bash
git add tests/conftest.py tests/blackbox/test_claude_board.py docs/specs/daemon.md
git commit -m "test: black-box a real Claude session onto the board"
```

---

## Spec coverage

| Spec requirement | Task |
|---|---|
| Daemon owns the files; CLI is a client | 4, 5 |
| Health, live, archive, board HTML | 1, 2 |
| Command API and exit codes | 2, 3 |
| Start-if-down, stranger port, second daemon exits 0 | 1, 4 |
| `daemon.port` wins over a conflicting request | 4 |
| Launchd install, KeepAlive, stop bootouts | 6 |
| Doctor split and status | 3, 5 |
| `dashboard --host` rejected, no port scan | 5 |
| Parent link kept; archive does not cascade | 2, 8 |
| CPU, memory, Claude and Codex tokens; Cursor tokens omitted | 7 |
| Usage not written to `registry.json` | 7 |
| Board engine marks, usage, Archive, Kill, Send | 9 |
| Kill only with a live pid | 8, 9 |
| Send uses `wake` for Claude, Codex, and Cursor | 8, 9 |
| Black box spends real tokens and is outside default pytest | 11 |
| Living spec | 10 |
| Menu-bar app, Dock icon, login item | Not this plan |

## Out of this plan

The Tauri app in `desktop/` waits until this plan is merged and the daemon is the only production reader. Its plan is a separate file. Do not start it from a task above.
