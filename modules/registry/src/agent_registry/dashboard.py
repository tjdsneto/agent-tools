from __future__ import annotations

import json
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from agent_registry import archive, ops
from agent_registry.constants import DASHBOARD_DEFAULT_PORT, EXIT_IO
from agent_registry.project import project_key
from agent_registry.store import CorruptRegistryError

_STATIC_DIR = Path(__file__).parent / "static"
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        # Quiet by default; dashboard is a local viewer.
        pass

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            self._serve_html()
        elif path == "/api/live":
            self._serve_live()
        elif path == "/api/archive":
            self._serve_archive(parsed.query)
        else:
            self.send_error(404, "Not Found")

    def _serve_live(self) -> None:
        try:
            self._json(ops.live_views())
        except CorruptRegistryError:
            self._json(
                {"active": [], "stale": [], "attention": [], "corrupt": True}
            )

    def _serve_html(self) -> None:
        html_path = _STATIC_DIR / "dashboard.html"
        try:
            body = html_path.read_bytes()
        except OSError as e:
            self.send_error(500, f"dashboard.html missing: {e}")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_archive(self, query: str) -> None:
        qs = parse_qs(query)
        reason = qs.get("reason", [None])[0] or None
        limit_raw = qs.get("limit", [None])[0]
        limit: int | None = 100
        if limit_raw is not None:
            try:
                limit = int(limit_raw)
            except ValueError:
                self._json({"error": "invalid limit"}, status=400)
                return
            if limit < 0:
                self._json({"error": "limit must be >= 0"}, status=400)
                return
        try:
            events = []
            for e in archive.list_events(reason=reason, limit=limit):
                pub = archive.public_event(e)
                sess = pub.get("session")
                if isinstance(sess, dict) and sess.get("directory"):
                    sess["project"] = project_key(sess["directory"])
                events.append(pub)
        except archive.ValidationError as e:
            self._json({"error": str(e)}, status=400)
            return
        self._json({"events": events, "corrupt": archive.is_corrupt()})

    def _json(self, payload: Any, *, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def make_server(host: str, port: int) -> HTTPServer:
    return HTTPServer((host, port), DashboardHandler)


def _find_free_port(host: str, port: int) -> HTTPServer:
    last_err: OSError | None = None
    for candidate in range(port, port + 11):
        try:
            return make_server(host, candidate)
        except OSError as e:
            last_err = e
            continue
    raise OSError(
        f"could not bind {host}:{port}..{port + 10}"
        + (f": {last_err}" if last_err else "")
    )


def _warn_if_non_loopback(host: str) -> None:
    if host not in _LOOPBACK_HOSTS:
        print(
            "WARNING: dashboard is bound to a non-loopback host.\n"
            "Anyone who can reach this port can read session paths and summaries.\n"
            f"Host: {host}",
            file=sys.stderr,
        )


def run_dashboard(
    host: str = "127.0.0.1",
    port: int = DASHBOARD_DEFAULT_PORT,
    *,
    open_browser: bool = True,
) -> None:
    _warn_if_non_loopback(host)
    try:
        httpd = _find_free_port(host, port)
    except OSError as e:
        print(f"agent-registry: {e}", file=sys.stderr)
        raise SystemExit(EXIT_IO) from e

    bound_port = httpd.server_address[1]
    url = f"http://{host}:{bound_port}/"
    print(f"agent-registry dashboard at {url}", flush=True)
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down dashboard.", flush=True)
    finally:
        httpd.server_close()
