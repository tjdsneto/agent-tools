from __future__ import annotations

import html
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from psycopg.types.json import Jsonb

from agent_inbox import db, store
from agent_inbox.constants import FRAME_PORT, HTTP_PORT, NOTIFY_CHANNEL
from agent_inbox.errors import ConflictError, NotFoundError, StoreError, ValidationError

HISTORY_STATES = ("delivered", "expired", "withdrawn", "superseded", "undelivered", "archived")
HIDDEN_STATES = {"archived", "withdrawn", "superseded"}
FRAME_ORIGIN = f"http://127.0.0.1:{FRAME_PORT}"

_HEAD = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 16px; background: #fff; color: #1a1a1a; overflow-wrap: anywhere; }}
a {{ color: #0645ad; }}
article {{ padding: 12px; border: 1px solid #ccc; margin-bottom: 12px; }}
a, button, input, select, textarea {{ min-height: 44px; box-sizing: border-box; max-width: 100%; }}
a {{ display: inline-block; }}
pre {{ white-space: pre-wrap; }}
form label {{ display: block; padding: 6px 0; }}
form input[name="comment"], form input[name="text"] {{ display: block; width: 100%; margin: 6px 0; }}
iframe {{ width: 100%; min-height: 240px; border: 1px solid #ccc; box-sizing: border-box; }}
</style>
</head>
<body>
"""

_SCRIPT = """<script>
const es = new EventSource("/events");
let open = false;
es.onmessage = () => { if (open) location.reload(); open = true; };
</script>
</body></html>
"""


def _esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _frame_origin(host_header: str | None = None) -> str:
    configured = os.environ.get("INBOX_FRAME_ORIGIN")
    if configured:
        return configured.rstrip("/")
    host = (host_header or "").split(":")[0]
    if host.endswith(".ts.net"):
        https_port = os.environ.get("INBOX_FRAME_HTTPS_PORT", "8445")
        return f"https://{host}:{https_port}"
    return FRAME_ORIGIN


def _authorized(handler: BaseHTTPRequestHandler) -> bool:
    """Direct localhost has no Tailscale header. The port is bound to 127.0.0.1,
    and Tailscale Serve adds the header on every proxied request."""
    if os.environ.get("INBOX_ALLOW_INSECURE") == "1":
        return True
    login = handler.headers.get("Tailscale-User-Login")
    if not login:
        return True
    return login.startswith("tjdsneto@")


def _allowed_origins(handler: BaseHTTPRequestHandler) -> set[str]:
    port = handler.server.server_address[1]
    origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    configured = os.environ.get("INBOX_UI_ORIGIN")
    if configured:
        origins.add(configured.rstrip("/"))
    return origins


def _same_site(handler: BaseHTTPRequestHandler) -> bool:
    """Refuse what a foreign page can make the browser send: a cross-site form post
    (including one from the sandboxed agent frame, whose origin is "null") and a
    DNS-rebound Host. Non-browser callers send neither Origin nor Sec-Fetch-Site."""
    origins = _allowed_origins(handler)
    host = (handler.headers.get("Host") or "").rsplit(":", 1)[0]
    if host and host not in {urlparse(o).hostname for o in origins}:
        return False
    if handler.command != "POST":
        return True
    site = handler.headers.get("Sec-Fetch-Site")
    if site and site != "same-origin":
        return False
    origin = handler.headers.get("Origin")
    return origin is None or origin in origins


def _query_value(qs: dict, key: str) -> str | None:
    values = qs.get(key)
    if not values or values[0] == "":
        return None
    return values[0]


def _dismissed(row: dict) -> bool:
    flag = (row.get("delivery") or {}).get("dismissed")
    return flag is True or flag == "true"


def load_feed(conn, qs: dict) -> list[dict]:
    kind = _query_value(qs, "kind")
    engine = _query_value(qs, "engine")
    state = _query_value(qs, "state")
    project = _query_value(qs, "project")
    common = {"kind": kind, "engine": engine, "project": project, "limit": 200}
    if _query_value(qs, "history") == "1":
        states = [state] if state else list(HISTORY_STATES)
        return store.list_entries(conn, states=states, **common)
    rows = store.list_entries(conn, states=[state] if state else None, **common)
    visible = [row for row in rows if row["state"] not in HIDDEN_STATES and not _dismissed(row)]
    opened = [row for row in visible if row["kind"] == "ask" and row["state"] == "open"]
    unread = [row for row in visible if row["kind"] == "post" and row["state"] == "unread"]
    seen = {row["id"] for row in opened + unread}
    rest = [row for row in visible if row["id"] not in seen]
    return opened + unread + rest


def _reach(delivery: dict) -> str:
    word = delivery.get("reachability")
    if not word:
        return ""
    when = delivery.get("reachable_at")
    if word == "held" and when:
        raw = str(when)
        clock = raw.split("T", 1)[1][:5] if "T" in raw else raw
        return f"{word} answerable at ~{clock}"
    return str(word)


def _card(row: dict) -> str:
    project = (row.get("asker") or {}).get("project")
    base = Path(project).name if project else ""
    bits = [row["id"], row["title"], row["priority"], base, row["state"], _reach(row.get("delivery") or {})]
    label = " · ".join(_esc(bit) for bit in bits if bit)
    return (
        "<article>"
        f'<input type="checkbox" name="id" value="{_esc(row["id"])}">'
        f' <a href="/e/{_esc(row["id"])}">{label}</a>'
        "</article>"
    )


def _nav(qs: dict) -> str:
    project = _query_value(qs, "project")
    hidden = f'<input type="hidden" name="project" value="{_esc(project)}">' if project else ""
    engines = "".join(f'<option value="{name}">{name}</option>' for name in ("claude", "codex", "cursor"))
    states = "".join(f'<option value="{name}">{name}</option>' for name in ("open", "unread", "answered", "delivered", "undelivered", "expired", "read"))
    return (
        "<nav>"
        '<a href="/">all</a> '
        '<a href="/?kind=ask&state=open">needs answer</a> '
        '<a href="/?kind=post">info</a> '
        '<a href="/?history=1">history</a>'
        "</nav>"
        '<form method="get" action="/">'
        + hidden
        + f'<select name="engine"><option value="">engine</option>{engines}</select>'
        + f'<select name="state"><option value="">state</option>{states}</select>'
        + '<button type="submit">filter</button></form>'
    )


def _feed_page(rows: list[dict], qs: dict, error: str | None = None, banner: str = "") -> str:
    err = f"<p>{_esc(error)}</p>" if error else ""
    line = f"<p>{_esc(banner)}</p>" if banner else ""
    cards = "".join(_card(row) for row in rows)
    return (
        _HEAD.format(title="feed")
        + _nav(qs)
        + line
        + err
        + '<form method="post" action="/batch">'
        + cards
        + '<button type="submit" name="action" value="withdraw">withdraw</button>'
        + '<button type="submit" name="action" value="dismiss">dismiss</button>'
        + "</form>"
        + _SCRIPT
    )


def _control_fields(control: dict) -> str:
    ctype = control.get("type")
    if ctype in ("choice", "multi"):
        kind = "radio" if ctype == "choice" else "checkbox"
        fields = []
        for opt in control.get("options") or []:
            rec = " (recommended)" if opt.get("recommended") else ""
            checked = " checked" if opt.get("default") else ""
            desc = f"<br><small>{_esc(opt['description'])}</small>" if opt.get("description") else ""
            fields.append(
                f'<label><input type="{kind}" name="value" value="{_esc(opt["id"])}"{checked}> '
                f'{_esc(opt["label"])}{rec}{desc}</label>'
            )
        return "".join(fields)
    if ctype == "text":
        return "<textarea name=\"value\"></textarea>" if control.get("size") == "long" else "<input name=\"value\">"
    return ""


def _control_buttons(control: dict) -> str:
    if control.get("type") == "approve":
        return (
            '<button type="submit" name="value" value="approve">approve</button>'
            '<button type="submit" name="value" value="revise">revise</button>'
        )
    return "<button type=\"submit\">answer</button>" if control.get("type") else ""


def _entry_page(entry: dict, error: str | None = None, frame_origin: str | None = None) -> str:
    eid = _esc(entry["id"])
    parts = [_HEAD.format(title=_esc(entry["title"]))]
    if error:
        parts.append(f"<p>{_esc(error)}</p>")
    parts.append(f"<h1>{_esc(entry['title'])}</h1><p>{_esc(entry['state'])}</p>")
    if entry.get("summary"):
        parts.append(f"<p>{_esc(entry['summary'])}</p>")
    if entry.get("html"):
        src = f"{(frame_origin or _frame_origin()).rstrip('/')}/h/{eid}"
        parts.append(f'<iframe sandbox="allow-scripts allow-popups" src="{src}"></iframe>')
        parts.append("<p>Reference only. Answer below.</p>")
    if entry.get("detail"):
        parts.append(f"<pre>{_esc(entry['detail'])}</pre>")
    source = entry.get("source") or {}
    if source.get("url"):
        parts.append(f'<p><a href="{_esc(source["url"])}" target="_blank" rel="noopener">source</a></p>')
    for event in entry.get("thread") or []:
        kind = "follow-up" if event.get("type") == "followup" else "reply"
        parts.append(f"<p>{kind}: {_esc(event.get('text') or '')}</p>")
    if entry["kind"] == "ask" and entry["state"] == "open":
        parts.append(
            f'<form method="post" action="/e/{eid}/answer">{_control_fields(entry.get("control") or {})}'
            '<input name="comment" placeholder="comment (a reason is required to revise)">'
            f'{_control_buttons(entry.get("control") or {})}</form>'
        )
    if (entry.get("asker") or {}).get("session_id"):
        parts.append(
            f'<form method="post" action="/e/{eid}/followup"><input name="text">'
            '<button type="submit">follow up</button></form>'
        )
    parts.append(f'<p><a href="/">feed</a></p>{_SCRIPT}')
    return "".join(parts)


def dismiss(conn, entry_id: str) -> None:
    row = conn.execute("SELECT id, kind, state FROM entries WHERE id = %s", (entry_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"no entry {entry_id}")
    if row["kind"] == "post":
        if row["state"] not in ("unread", "read"):
            raise ValidationError(f"{entry_id} cannot be dismissed")
        store.archive(conn, entry_id)
        return
    if row["kind"] != "ask" or row["state"] != "undelivered":
        raise ValidationError(f"{entry_id} cannot be dismissed")
    with conn.transaction():
        locked = conn.execute("SELECT delivery FROM entries WHERE id = %s FOR UPDATE", (entry_id,)).fetchone()
        delivery = dict(locked["delivery"] or {})
        delivery["dismissed"] = True
        conn.execute(
            "UPDATE entries SET delivery = %s, updated_at = now() WHERE id = %s",
            (Jsonb(delivery), entry_id),
        )


class InboxHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        return

    def do_GET(self) -> None:
        self._route("GET")

    def do_POST(self) -> None:
        self._route("POST")

    def _route(self, method: str) -> None:
        if not _authorized(self):
            self._bytes(403, b"tailnet login required", "text/plain; charset=utf-8")
            return
        if not _same_site(self):
            self._bytes(403, b"cross-site request refused", "text/plain; charset=utf-8")
            return
        try:
            self._dispatch(method)
        except NotFoundError as exc:
            self._bytes(404, _esc(exc).encode(), "text/plain; charset=utf-8")
        except StoreError:
            self._bytes(503, b"store unreachable", "text/plain; charset=utf-8")

    def _dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        if method == "GET" and path == "/events":
            self._events()
            return
        if method == "GET" and path == "/":
            with db.connect() as conn:
                from agent_inbox.notify import urgent_counts
                self._html(200, _feed_page(load_feed(conn, qs), qs, banner=urgent_counts(conn)))
            return
        match = re.fullmatch(r"/e/([^/]+)", path)
        if method == "GET" and match:
            self._show(match.group(1), 200, None)
            return
        match = re.fullmatch(r"/e/([^/]+)/(answer|followup)", path)
        if method == "POST" and match:
            self._post_entry(match.group(1), match.group(2))
            return
        if method == "POST" and path == "/batch":
            self._batch()
            return
        self._bytes(404, b"not found", "text/plain; charset=utf-8")

    def _show(self, entry_id: str, status: int, error: str | None) -> None:
        with db.connect() as conn:
            entry = store.get_entry(conn, entry_id)
            if entry["kind"] == "post" and entry["state"] in ("unread", "read"):
                store.mark_read(conn, entry_id)
                entry = store.get_entry(conn, entry_id)
            self._html(status, _entry_page(entry, error, _frame_origin(self.headers.get("Host"))))

    def _post_entry(self, entry_id: str, action: str) -> None:
        form = self._form()
        try:
            with db.connect() as conn:
                if action == "answer":
                    entry = store.get_entry(conn, entry_id)
                    values = form.get("value") or []
                    control = entry.get("control") or {}
                    value = values if control.get("type") == "multi" else (values[0] if values else "")
                    store.answer(
                        conn, entry_id, value,
                        comment=(form.get("comment") or [""])[0],
                        via="web",
                    )
                else:
                    store.add_followup(
                        conn, entry_id, (form.get("text") or [""])[0],
                        via="web",
                    )
        except ConflictError as exc:
            self._show(entry_id, 409, str(exc))
            return
        except ValidationError as exc:
            self._show(entry_id, 400, str(exc))
            return
        self._redirect(f"/e/{quote(entry_id)}")

    def _batch(self) -> None:
        form = self._form()
        action = (form.get("action") or [""])[0]
        applied = 0
        errors: list[str] = []
        with db.connect() as conn:
            for entry_id in form.get("id") or []:
                try:
                    if action == "withdraw":
                        store.withdraw(conn, entry_id)
                    elif action == "dismiss":
                        dismiss(conn, entry_id)
                    else:
                        raise ValidationError("action must be withdraw or dismiss")
                    applied += 1
                except (ConflictError, ValidationError, NotFoundError) as exc:
                    errors.append(str(exc))
            if applied == 0:
                message = errors[0] if errors else "nothing selected"
                from agent_inbox.notify import urgent_counts
                self._html(409, _feed_page(load_feed(conn, {}), {}, message, banner=urgent_counts(conn)))
                return
        self._redirect("/")

    def _events(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(b"data: refresh\n\n")
        self.wfile.flush()
        conn = db.connect()
        try:
            conn.execute(f"LISTEN {NOTIFY_CHANNEL}")
            while True:
                for _note in conn.notifies(timeout=25, stop_after=1):
                    self.wfile.write(b"data: refresh\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            return
        finally:
            conn.close()

    def _form(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(min(length, 1_000_000)).decode()
        return parse_qs(raw, keep_blank_values=True)

    def _bytes(self, status: int, payload: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _html(self, status: int, page: str) -> None:
        self._bytes(status, page.encode(), "text/html; charset=utf-8")

    def _redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()


def make_server(host: str = "127.0.0.1", port: int | None = None) -> ThreadingHTTPServer:
    if port is None:
        port = int(os.environ.get("INBOX_HTTP_PORT", str(HTTP_PORT)))
    return ThreadingHTTPServer((host, port), InboxHandler)
