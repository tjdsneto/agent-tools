from __future__ import annotations

import errno
import http.client
import json
import os
import shutil
import signal
import subprocess
import threading
import traceback
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from agent_registry import archive, doctor, lifecycle, ops, store, summarize, transport, usage
from agent_registry.constants import (
    DAEMON_SERVICE,
    EXIT_IO,
    EXIT_NOT_FOUND,
    EXIT_OK,
    EXIT_USAGE,
)
from agent_registry.dashboard import DashboardHandler
from agent_registry.store import CorruptRegistryError, registry_path

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


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


def _is_json_content_type(value: str | None) -> bool:
    if not value:
        return False
    media_type = value.split(";", 1)[0].strip().lower()
    return media_type == "application/json"


def _request_hostname(value: str | None) -> str:
    if not value:
        return ""
    host = value.strip()
    if host.startswith("["):
        end = host.find("]")
        return host[1:end] if end != -1 else host
    if host.count(":") == 1:
        name, port = host.split(":", 1)
        if port.isdigit():
            return name.lower()
    return host.lower()


def _require_str(params: dict, name: str) -> str:
    value = params[name]
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    return value


def _older_than_days(value: str) -> int:
    from agent_registry.cli import _parse_older_than

    return _parse_older_than(value)


def _session_by_id(session_id: str):
    """Live row for a public session id. A registry_id in the request is ignored."""
    for session in store.load().sessions:
        if session.session_id == session_id:
            return session
    return None


def _prepare_command(op: str, params: Any):
    """Read op params. KeyError and TypeError here are client usage errors.

    The returned callable performs the operation, so a later bug inside
    lifecycle is not reported as a bad param.
    """
    if not isinstance(params, dict):
        raise TypeError("params must be an object")
    if op == "ensure":
        agent_type = params["agent_type"]
        session_id = params["session_id"]
        directory = params["directory"]
        for name, value in (
            ("agent_type", agent_type),
            ("session_id", session_id),
            ("directory", directory),
        ):
            if not isinstance(value, str):
                raise TypeError(f"{name} must be a string")
        kwargs = {
            "parent_session": params.get("parent_session"),
            "model": params.get("model"),
            "title": params.get("title"),
            "replace": not params.get("no_replace", False),
            "peer_name": params.get("peer_name"),
            "socket": params.get("socket"),
            "pid": params.get("pid"),
            "peer_status": params.get("peer_status"),
        }

        def run() -> tuple[int, Any, str | None]:
            result = lifecycle.ensure(agent_type, session_id, directory, **kwargs)
            session = result["session"]
            if not isinstance(session, dict):
                session = session.to_dict()
            return EXIT_OK, {"created": result["created"], "session": session}, None

        return run
    if op == "list":

        def run() -> tuple[int, Any, str | None]:
            active, stale = ops.list_split()
            return EXIT_OK, {"active": active, "stale": stale}, None

        return run
    if op == "end":
        agent_type = params["agent_type"]
        session_id = params["session_id"]

        def run() -> tuple[int, Any, str | None]:
            return EXIT_OK, lifecycle.end(agent_type, session_id), None

        return run
    if op == "register":
        agent_type = _require_str(params, "agent_type")
        session_id = _require_str(params, "session_id")
        directory = _require_str(params, "directory")

        def run() -> tuple[int, Any, str | None]:
            session = ops.register(
                agent_type=agent_type,
                session_id=session_id,
                directory=directory,
                parent_session_id=params.get("parent_session"),
                model=params.get("model"),
                title=params.get("title"),
                peer_name=params.get("peer_name"),
                socket=params.get("socket"),
                pid=params.get("pid"),
                peer_status=params.get("peer_status"),
                replace=params.get("replace", False),
            )
            return EXIT_OK, session.to_dict(), None

        return run
    if op == "update":
        registry_id = _require_str(params, "registry_id")
        patches = {
            key: params.get(key)
            for key in (
                "status",
                "summary",
                "title",
                "issue",
                "pr_title",
                "pr_url",
                "branch",
                "directory",
                "model",
                "goflow_timer_id",
                "parent_session_id",
            )
        }
        for key in (
            "clear_issue",
            "clear_pr",
            "clear_branch",
            "clear_goflow_timer",
            "clear_summary",
            "clear_parent_session",
            "clear_model",
            "clear_title",
        ):
            patches[key] = params.get(key, False)

        def run() -> tuple[int, Any, str | None]:
            return EXIT_OK, ops.update(registry_id, **patches).to_dict(), None

        return run
    if op == "ping":
        registry_id = _require_str(params, "registry_id")

        def run() -> tuple[int, Any, str | None]:
            session = ops.ping(
                registry_id,
                model=params.get("model"),
                title=params.get("title"),
            )
            return EXIT_OK, session.to_dict(), None

        return run
    if op == "unregister":
        registry_id = _require_str(params, "registry_id")

        def run() -> tuple[int, Any, str | None]:
            ops.unregister(registry_id)
            return EXIT_OK, {"ok": True}, None

        return run
    if op == "prune":
        dry_run = params.get("dry_run", False)
        yes = params.get("yes", False)

        def run() -> tuple[int, Any, str | None]:
            return EXIT_OK, ops.prune(dry_run=dry_run, yes=yes), None

        return run
    if op == "heartbeat":
        agent_type = _require_str(params, "agent_type")
        session_id = _require_str(params, "session_id")

        def run() -> tuple[int, Any, str | None]:
            return EXIT_OK, lifecycle.heartbeat(
                agent_type,
                session_id,
                model=params.get("model"),
                title=params.get("title"),
                peer_name=params.get("peer_name"),
                socket=params.get("socket"),
                pid=params.get("pid"),
                peer_status=params.get("peer_status"),
                status=params.get("status"),
            ), None

        return run
    if op == "self":
        agent_type = _require_str(params, "agent_type")
        session_id = _require_str(params, "session_id")

        def run() -> tuple[int, Any, str | None]:
            view = lifecycle.self_view(agent_type, session_id)
            if view is None:
                return EXIT_NOT_FOUND, None, "session not found"
            return EXIT_OK, view, None

        return run
    if op == "summarize":
        agent_type = _require_str(params, "agent_type")
        session_id = _require_str(params, "session_id")

        def run() -> tuple[int, Any, str | None]:
            result = summarize.summarize_sidecar(
                agent_type,
                session_id,
                transcript_path=params.get("transcript"),
                force=params.get("force", False),
            )
            return EXIT_OK, result, None

        return run
    if op == "archive_list":
        reason = params.get("reason")
        limit = params.get("limit", 100)
        if limit is not None and not isinstance(limit, int):
            raise TypeError("limit must be an int")

        def run() -> tuple[int, Any, str | None]:
            events = [
                archive.public_event(event)
                for event in archive.list_events(reason=reason, limit=limit)
            ]
            return EXIT_OK, events, None

        return run
    if op == "archive_show":
        session_id = _require_str(params, "session_id")
        full = params.get("full", False)

        def run() -> tuple[int, Any, str | None]:
            match = None
            for event in reversed(archive.read_events()):
                sess = event.get("session") or {}
                if sess.get("session_id") == session_id:
                    match = event
                    break
            if match is None:
                return EXIT_NOT_FOUND, None, "session not found"
            shown = match if full else archive.public_event(match)
            return EXIT_OK, shown, None

        return run
    if op == "archive_purge":
        older_than = _require_str(params, "older_than")
        yes = params.get("yes", False)

        def run() -> tuple[int, Any, str | None]:
            days = _older_than_days(older_than)
            return EXIT_OK, archive.purge_older_than(days=days, yes=yes), None

        return run
    if op == "resolve":
        session_id = _require_str(params, "session_id")

        def run() -> tuple[int, Any, str | None]:
            return EXIT_OK, transport.resolve_session(session_id), None

        return run
    if op == "wake":
        session_id = _require_str(params, "session_id")
        message = _require_str(params, "message")

        def run() -> tuple[int, Any, str | None]:
            result = transport.wake(session_id, message)
            code = EXIT_OK if result.get("result") in {"landed", "already_awake"} else EXIT_USAGE
            return code, result, None

        return run
    if op == "status":

        def run() -> tuple[int, Any, str | None]:
            return EXIT_OK, doctor.status_payload(), None

        return run
    if op == "doctor":

        def run() -> tuple[int, Any, str | None]:
            result = doctor.collect()
            code = EXIT_OK if result["ok"] else EXIT_IO
            return code, result, None

        return run
    if op == "archive_session":
        session_id = _require_str(params, "session_id")

        def run() -> tuple[int, Any, str | None]:
            session = _session_by_id(session_id)
            if session is None:
                return EXIT_NOT_FOUND, None, "session not found"
            try:
                ops.unregister(session.registry_id)
            except ops.UnknownRegistryIdError:
                return EXIT_NOT_FOUND, None, "session not found"
            return EXIT_OK, {"ok": True, "session_id": session_id}, None

        return run
    if op == "kill_session":
        session_id = _require_str(params, "session_id")

        def run() -> tuple[int, Any, str | None]:
            session = _session_by_id(session_id)
            if session is None:
                return EXIT_NOT_FOUND, None, "session not found"
            pid = session.pid
            if pid is None or usage.sample_process(pid) is None:
                return EXIT_USAGE, None, "no live pid"
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                return EXIT_USAGE, None, "no live pid"
            try:
                ops.unregister(session.registry_id)
            except ops.UnknownRegistryIdError:
                pass
            return EXIT_OK, {"ok": True, "session_id": session_id}, None

        return run
    if op == "send_session":
        session_id = _require_str(params, "session_id")
        message = _require_str(params, "message")
        if not message.strip():
            raise TypeError("message must be non-empty")

        def run() -> tuple[int, Any, str | None]:
            result = transport.wake(session_id, message)
            code = EXIT_OK if result.get("result") in {"landed", "already_awake"} else EXIT_USAGE
            return code, result, None

        return run
    if op == "open_workspace":
        session_id = _require_str(params, "session_id")

        def run() -> tuple[int, Any, str | None]:
            session = _session_by_id(session_id)
            if session is None:
                return EXIT_NOT_FOUND, None, "session not found"
            directory = (session.directory or "").strip()
            if not directory:
                return EXIT_USAGE, None, "directory missing"
            path = Path(directory).expanduser()
            try:
                path = path.resolve()
            except OSError:
                return EXIT_USAGE, None, "directory missing"
            if not path.exists():
                return EXIT_USAGE, None, "directory missing"
            try:
                opened = _open_path_in_cursor(path)
            except OSError as e:
                return EXIT_IO, None, str(e)
            if not opened:
                return EXIT_USAGE, None, "could not open workspace"
            return EXIT_OK, {"ok": True, "session_id": session_id, "directory": str(path)}, None

        return run
    return None


def _open_path_in_cursor(path: Path) -> bool:
    """Open a folder/file in Cursor (workspace-only; does not select a chat)."""
    target = str(path)
    cursor = shutil.which("cursor")
    if cursor:
        proc = subprocess.run(
            [cursor, "-r", target],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        if proc.returncode == 0:
            return True
    app = Path("/Applications/Cursor.app")
    if app.is_dir():
        proc = subprocess.run(
            ["open", "-a", "Cursor", target],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        return proc.returncode == 0
    return False


def dispatch(op: str, params: dict) -> tuple[int, Any, str | None]:
    try:
        command = _prepare_command(op, params)
    except (KeyError, TypeError) as e:
        return EXIT_USAGE, None, str(e)
    if command is None:
        return EXIT_USAGE, None, f"unknown op {op}"
    return command()


class DaemonHandler(DashboardHandler):
    def do_GET(self) -> None:
        if urlparse(self.path).path == "/api/health":
            self._json({"ok": True, "service": DAEMON_SERVICE})
            return
        super().do_GET()

    def _serve_live(self) -> None:
        try:
            views = ops.live_views()
        except CorruptRegistryError:
            self._json(
                {"active": [], "stale": [], "attention": [], "corrupt": True}
            )
            return
        try:
            open_chats = usage.open_cursor_chats()
        except Exception:
            open_chats = {}
        views = self._include_open_cursor_chats(views, open_chats)
        views = self._sync_cursor_titles(views)
        views = self._sync_claude_titles(views)
        open_ids = set(open_chats)
        interrupt_budget = 40
        for name in ("active", "stale", "attention"):
            for view in views[name]:
                usage.attach_usage(view)
                if (
                    view.get("agent_type") == "cursor"
                    and view.get("session_id") in open_ids
                ):
                    view["cursor_open"] = True
                if (
                    interrupt_budget > 0
                    and view.get("agent_type") == "claude"
                    and view.get("session_id")
                ):
                    interrupt_budget -= 1
                    try:
                        reason = usage.claude_interrupt_reason(view["session_id"])
                    except Exception:
                        reason = None
                    if reason:
                        view["interrupt_reason"] = reason
        self._json(views)

    def _cursor_views(self, views: dict[str, list]) -> list[dict]:
        return [
            view
            for name in ("active", "stale", "attention")
            for view in views[name]
            if view.get("agent_type") == "cursor" and view.get("session_id")
        ]

    def _sync_cursor_titles(self, views: dict[str, list]) -> dict[str, list]:
        """Persist Cursor composer `name` onto title when missing or renamed.

        Hook payloads omit the chat title. The composer name in state.vscdb is
        the harness display name — distinct from `summary` (agent/auto focus).
        """
        cursor_views = self._cursor_views(views)
        if not cursor_views:
            return views
        try:
            names = usage.cursor_composer_names(
                {view["session_id"] for view in cursor_views}
            )
        except Exception:
            return views
        if not names:
            return views
        return self._apply_harness_titles(views, names)

    def _sync_claude_titles(self, views: dict[str, list]) -> dict[str, list]:
        """Fill empty Claude titles from jsonl customTitle / aiTitle.

        Only backfills missing titles (does not chase every rename) and caps
        how many jsonl scans run per live poll. Prefer sessions with a pid.
        """
        candidates = [
            view
            for name in ("active", "stale", "attention")
            for view in views[name]
            if view.get("agent_type") == "claude"
            and view.get("session_id")
            and not (view.get("title") or "").strip()
        ]
        if not candidates:
            return views
        candidates.sort(key=lambda v: (0 if v.get("pid") else 1))
        names: dict[str, str] = {}
        for view in candidates[:40]:
            session_id = view["session_id"]
            try:
                title = usage.claude_session_title(session_id)
            except Exception:
                continue
            if title:
                names[session_id] = title
        if not names:
            return views
        return self._apply_harness_titles(views, names)

    def _apply_harness_titles(
        self, views: dict[str, list], names: dict[str, str]
    ) -> dict[str, list]:
        changed = False
        for session_id, name in names.items():
            session = _session_by_id(session_id)
            if session is None:
                continue
            current = (session.title or "").strip() or None
            if current == name:
                continue
            try:
                ops.update(session.registry_id, title=name)
                changed = True
            except Exception:
                continue
        if not changed:
            return views
        try:
            return ops.live_views()
        except CorruptRegistryError:
            return views

    def _include_open_cursor_chats(
        self, views: dict[str, list], open_chats: dict[str, str]
    ) -> dict[str, list]:
        """Register an open Cursor chat the hooks never recorded, then re-read."""
        if not open_chats:
            return views
        known = {
            view.get("session_id")
            for name in ("active", "stale", "attention")
            for view in views[name]
        }
        missing = [
            session_id
            for session_id, directory in open_chats.items()
            if session_id and session_id not in known and directory
        ]
        if not missing:
            return views
        try:
            titles = usage.cursor_composer_names(set(missing))
        except Exception:
            titles = {}
        created = False
        for session_id in missing:
            try:
                lifecycle.ensure(
                    "cursor",
                    session_id,
                    open_chats[session_id],
                    title=titles.get(session_id),
                    replace=False,
                )
                created = True
            except Exception:
                continue
        if not created:
            return views
        try:
            return ops.live_views()
        except CorruptRegistryError:
            return views

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/command":
            self.send_error(404)
            return
        if not _is_json_content_type(self.headers.get("Content-Type")):
            self._command_result(EXIT_USAGE, None, "content-type must be application/json")
            return
        if _request_hostname(self.headers.get("Host")) not in _LOOPBACK_HOSTS:
            self._command_result(EXIT_USAGE, None, "host must be loopback")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b""
            body = json.loads(raw.decode("utf-8"))
            if not isinstance(body, dict) or "op" not in body or "params" not in body:
                raise ValueError("missing op or params")
            op = body["op"]
            params = body["params"]
            if not isinstance(op, str):
                raise ValueError("op must be a string")
        except (ValueError, UnicodeDecodeError) as e:
            self._command_result(EXIT_USAGE, None, str(e))
            return
        try:
            exit_code, data, error = dispatch(op, params)
        except (
            ops.ValidationError,
            archive.ValidationError,
            ops.DuplicateSessionError,
            transport.UnsupportedTransportError,
        ) as e:
            exit_code, data, error = EXIT_USAGE, None, str(e)
        except ops.UnknownRegistryIdError as e:
            exit_code, data, error = EXIT_NOT_FOUND, None, f"unknown registry_id: {e}"
        except transport.SessionNotFoundError as e:
            exit_code, data, error = EXIT_NOT_FOUND, None, f"session not found: {e}"
        except (CorruptRegistryError, archive.ArchiveIOError, OSError) as e:
            exit_code, data, error = EXIT_IO, None, str(e)
        except Exception as e:
            traceback.print_exc()
            exit_code, data, error = EXIT_IO, None, str(e)
        self._command_result(exit_code, data, error)

    def _command_result(self, exit_code: int, data: Any, error: str | None) -> None:
        self._json({"exit_code": exit_code, "data": data, "error": error})


def make_daemon(host: str, port: int) -> ThreadingHTTPServer:
    if host not in _LOOPBACK_HOSTS:
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


def _health_is_ours(host: str, port: int) -> bool:
    from agent_registry.client import _OPENER

    url = f"http://{host}:{port}/api/health"
    try:
        with _OPENER.open(url, timeout=1) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (
        OSError,
        urllib.error.URLError,
        http.client.HTTPException,
        json.JSONDecodeError,
        UnicodeDecodeError,
        ValueError,
    ):
        return False
    return body == {"ok": True, "service": DAEMON_SERVICE}


def run_foreground(host: str = "127.0.0.1", port: int = 8765) -> int:
    try:
        httpd = make_daemon(host, port)
    except OSError as e:
        if e.errno != errno.EADDRINUSE:
            raise
        if _health_is_ours(host, port):
            return EXIT_OK
        return EXIT_IO
    _write_identity(httpd.server_address[1])
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
        _clear_identity()
    return EXIT_OK