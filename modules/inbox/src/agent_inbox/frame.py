from __future__ import annotations

import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from agent_inbox import db, store
from agent_inbox.constants import FRAME_PORT, HTTP_PORT
from agent_inbox.errors import NotFoundError

DEFAULT_UI_ORIGIN = f"http://127.0.0.1:{HTTP_PORT}"


def _ancestors() -> str:
    configured = os.environ.get("INBOX_UI_ORIGIN", DEFAULT_UI_ORIGIN).rstrip("/")
    ancestors: list[str] = []
    for origin in (configured, DEFAULT_UI_ORIGIN, f"http://localhost:{HTTP_PORT}"):
        if origin not in ancestors:
            ancestors.append(origin)
    return " ".join(ancestors)


def _document(html: str) -> bytes:
    page = "<!doctype html>\n<meta charset=\"utf-8\">\n<base target=\"_blank\">\n" + (html or "")
    return page.encode()


class FrameHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        return

    def do_GET(self) -> None:
        match = re.fullmatch(r"/h/([^/]+)", self.path.split("?", 1)[0])
        if not match:
            self._bytes(404, b"not found")
            return
        try:
            with db.connect() as conn:
                entry = store.get_entry(conn, match.group(1))
        except NotFoundError:
            self._bytes(404, b"not found")
            return
        payload = _document(entry.get("html") or "")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header(
            "Content-Security-Policy",
            f"frame-ancestors {_ancestors()}; sandbox allow-scripts allow-popups",
        )
        self.send_header("X-Frame-Options", "ALLOWALL")
        self.end_headers()
        self.wfile.write(payload)

    def _bytes(self, status: int, payload: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def make_server(host: str = "127.0.0.1", port: int | None = None) -> ThreadingHTTPServer:
    if port is None:
        port = int(os.environ.get("INBOX_FRAME_PORT", str(FRAME_PORT)))
    return ThreadingHTTPServer((host, port), FrameHandler)
