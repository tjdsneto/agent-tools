from __future__ import annotations

import errno
import html
import http.client
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_registry.constants import (
    DAEMON_SERVICE,
    DAEMON_START_TIMEOUT,
    DASHBOARD_DEFAULT_PORT,
    EXIT_IO,
    EXIT_USAGE,
)
from agent_registry.store import registry_path

# Spawn this file, not sys.argv[0]. Under pytest argv[0] is pytest, and the
# daemon subcommand requires `run`. There is no package __main__.
_CLI_FILE = Path(__file__).resolve().parent / "cli.py"
_OURS = {"ok": True, "service": DAEMON_SERVICE}
_POLL_SECONDS = 0.1
_MIN_SOCKET_TIMEOUT = 0.1
_STOP_WAIT_SECONDS = 2.0
# Empty map: do not honor HTTP_PROXY, HTTPS_PROXY, or ALL_PROXY for loopback.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

_child: subprocess.Popen[bytes] | None = None


def call(op: str, params: dict, port: int | None = None) -> dict[str, Any]:
    """POST one command, starting the daemon when the port refuses the connection."""
    chosen = ensure_daemon(port)
    if isinstance(chosen, dict):
        return chosen
    return _post_command(chosen, op, params)


def ensure_daemon(port: int | None = None) -> int | dict[str, Any]:
    """Start the daemon when it is down. Returns its port, or an error envelope."""
    try:
        chosen = _resolve_port(port)
    except ValueError as e:
        return {"exit_code": EXIT_USAGE, "data": None, "error": str(e)}
    if isinstance(chosen, dict):
        return chosen
    timeout = _start_timeout()
    kind = _classify_health(chosen, _socket_timeout(timeout))
    if kind == "refused":
        try:
            _spawn(chosen)
        except OSError as e:
            return {"exit_code": EXIT_IO, "data": None, "error": str(e)}
        if not _wait_until_healthy(chosen, timeout):
            return {
                "exit_code": EXIT_IO,
                "data": None,
                "error": "daemon did not become healthy",
            }
    elif kind != "ours":
        return {
            "exit_code": EXIT_IO,
            "data": None,
            "error": "port is not agent-registry",
        }
    return chosen


def stop_if_ours() -> None:
    """SIGTERM the pid in daemon.pid when it is alive. Tests use this to avoid leaks."""
    pid = _read_int(_identity_dir() / "daemon.pid")
    if pid is not None and _pid_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    child = _child
    if child is not None:
        try:
            child.wait(timeout=_STOP_WAIT_SECONDS)
        except subprocess.TimeoutExpired:
            pass
        return
    if pid is None:
        return
    deadline = time.monotonic() + _STOP_WAIT_SECONDS
    while time.monotonic() < deadline:
        try:
            waited, _status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            return
        if waited == pid or not _pid_alive(pid):
            return
        time.sleep(0.05)


def _resolve_port(explicit: int | None) -> int | dict[str, Any]:
    live = _live_daemon_port()
    env_port = _env_port()
    if live is not None:
        if (explicit is not None and explicit != live) or (
            env_port is not None and env_port != live
        ):
            return {
                "exit_code": EXIT_USAGE,
                "data": None,
                "error": f"daemon already listening on {live}",
            }
        return live
    if explicit is not None:
        return explicit
    if env_port is not None:
        return env_port
    return DASHBOARD_DEFAULT_PORT


def _identity_dir() -> Path:
    return registry_path().parent


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _live_daemon_port() -> int | None:
    directory = _identity_dir()
    pid = _read_int(directory / "daemon.pid")
    if pid is None or not _pid_alive(pid):
        return None
    return _read_int(directory / "daemon.port")


def _env_port() -> int | None:
    raw = os.environ.get("AGENT_REGISTRY_DAEMON_PORT")
    if raw is None or raw.strip() == "":
        return None
    return int(raw.strip())


def _start_timeout() -> float:
    raw = os.environ.get("AGENT_REGISTRY_DAEMON_START_TIMEOUT")
    if raw is None or raw.strip() == "":
        return DAEMON_START_TIMEOUT
    return float(raw.strip())


def _socket_timeout(start_timeout: float) -> float:
    # A silent acceptor must finish within the start timeout, and a zero
    # timeout would not block long enough to tell a hang from a refusal.
    return max(start_timeout, _MIN_SOCKET_TIMEOUT)


def _is_refused(exc: BaseException | None) -> bool:
    if isinstance(exc, ConnectionRefusedError):
        return True
    return isinstance(exc, OSError) and exc.errno == errno.ECONNREFUSED


def _classify_health(port: int, timeout: float) -> str:
    if timeout <= 0:
        return "timeout"
    url = f"http://127.0.0.1:{port}/api/health"
    try:
        with _OPENER.open(url, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError:
        return "mismatch"
    except urllib.error.URLError as e:
        if _is_refused(e.reason):
            return "refused"
        if isinstance(e.reason, TimeoutError):
            return "timeout"
        return "error"
    except TimeoutError:
        return "timeout"
    except ConnectionRefusedError:
        return "refused"
    except http.client.HTTPException:
        return "error"
    except OSError:
        return "error"
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return "mismatch"
    if body == _OURS:
        return "ours"
    return "mismatch"


def _spawn(port: int) -> None:
    global _child
    log_path = _identity_dir() / "daemon.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "ab") as log:
        _child = subprocess.Popen(
            [
                sys.executable,
                str(_CLI_FILE),
                "daemon",
                "run",
                "--port",
                str(port),
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )


def _wait_until_healthy(port: int, timeout: float) -> bool:
    deadline = time.monotonic() + max(timeout, 0.0)
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        kind = _classify_health(port, min(0.2, remaining))
        if kind == "ours":
            return True
        if kind == "mismatch":
            return False
        time.sleep(min(_POLL_SECONDS, max(0.0, deadline - time.monotonic())))


def _post_command(port: int, op: str, params: dict) -> dict[str, Any]:
    url = f"http://127.0.0.1:{port}/api/command"
    req = urllib.request.Request(
        url,
        data=json.dumps({"op": op, "params": params}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _OPENER.open(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (
        OSError,
        urllib.error.URLError,
        http.client.HTTPException,
        json.JSONDecodeError,
        UnicodeDecodeError,
        ValueError,
    ) as e:
        return {"exit_code": EXIT_IO, "data": None, "error": str(e)}
    if isinstance(body, dict):
        return body
    return {
        "exit_code": EXIT_IO,
        "data": None,
        "error": "daemon returned an invalid command response",
    }


_LAUNCHD_LABEL = "com.tjdsneto.agent-registry"
_PLIST_NAME = f"{_LAUNCHD_LABEL}.plist"


def plist_text(program: str) -> str:
    """LaunchAgent XML. Logs live beside the registry file."""
    log = str(_identity_dir() / "daemon.log")
    arguments = "\n".join(
        f"        <string>{_xml_text(part)}</string>"
        for part in (program, "daemon", "run")
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        "<dict>\n"
        "    <key>Label</key>\n"
        f"    <string>{_xml_text(_LAUNCHD_LABEL)}</string>\n"
        "    <key>ProgramArguments</key>\n"
        "    <array>\n"
        f"{arguments}\n"
        "    </array>\n"
        "    <key>RunAtLoad</key>\n"
        "    <true/>\n"
        "    <key>KeepAlive</key>\n"
        "    <true/>\n"
        "    <key>StandardOutPath</key>\n"
        f"    <string>{_xml_text(log)}</string>\n"
        "    <key>StandardErrorPath</key>\n"
        f"    <string>{_xml_text(log)}</string>\n"
        "</dict>\n"
        "</plist>\n"
    )


def install_launchd(
    directory: Path,
    program: str,
    bootstrap: Callable[..., object],
) -> Path:
    """Write the plist and bootstrap it. `bootstrap` receives the launchctl args."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / _PLIST_NAME
    path.write_text(plist_text(program), encoding="utf-8")
    bootstrap(_launchd_domain(), str(path))
    return path


def uninstall_launchd(directory: Path, bootout: Callable[..., object]) -> int:
    """Bootout the plist, then delete it. A missing file is success."""
    path = Path(directory) / _PLIST_NAME
    if not path.is_file():
        return 0
    bootout(_launchd_domain(), str(path))
    path.unlink()
    return 0


def start_daemon(
    directory: Path,
    bootstrap: Callable[..., object],
    port: int | None = None,
) -> int | dict[str, Any]:
    """Bootstrap an installed agent, or spawn the detached daemon."""
    path = Path(directory) / _PLIST_NAME
    if path.is_file():
        bootstrap(_launchd_domain(), str(path))
        return 0
    chosen = _resolve_port(port)
    if isinstance(chosen, dict):
        return chosen
    _spawn(chosen)
    return 0


def stop_daemon(directory: Path, bootout: Callable[..., object]) -> int:
    """SIGTERM a live daemon pid, then bootout so KeepAlive stays down."""
    pid = _read_int(_identity_dir() / "daemon.pid")
    if pid is not None and _pid_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    path = Path(directory) / _PLIST_NAME
    if path.is_file():
        bootout(_launchd_domain(), str(path))
    return 0


def _launchd_domain() -> str:
    return f"gui/{os.getuid()}"


def _xml_text(value: str) -> str:
    return html.escape(value, quote=False)
