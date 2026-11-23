import os
import threading
from http.client import HTTPConnection

import pytest

from agent_inbox import store
from agent_inbox.validate import validate_request
from agent_inbox.web import make_server

CHOICE = {"type": "choice", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}
os.environ["INBOX_ALLOW_INSECURE"] = "1"


@pytest.fixture
def http(conn):
    server = make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    yield host, port
    server.shutdown()
    server.server_close()


def _get(http, path, headers=None):
    conn = HTTPConnection(http[0], http[1], timeout=5)
    conn.request("GET", path, headers=headers or {})
    resp = conn.getresponse()
    return resp.status, resp.read().decode()


def _post(http, path, body):
    conn = HTTPConnection(http[0], http[1], timeout=5)
    conn.request(
        "POST", path, body=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp = conn.getresponse()
    return resp.status, resp.getheader("Location"), resp.read().decode()


def test_feed_pins_open_questions_above_unread_info(conn, http):
    q = store.create_entry(conn, "ask", validate_request({"title": "Q", "control": CHOICE}, "ask"), engine="claude", session_id="s-1")
    info = store.create_entry(conn, "post", validate_request({"title": "I"}, "post"), script="cron")
    old = store.create_entry(conn, "post", validate_request({"title": "Old"}, "post"), script="cron")
    store.archive(conn, old["id"])
    status, body = _get(http, "/")
    assert status == 200
    assert body.index("Q") < body.index("I")
    assert "Old" not in body
    assert q["id"] in body and info["id"] in body
    assert "if (open) location.reload()" in body


def test_entry_layers(conn, http):
    e = store.create_entry(
        conn, "ask",
        validate_request({"title": "Which split?", "summary": "because", "html": "<p>diagram</p>", "control": CHOICE}, "ask"),
        engine="claude", session_id="s-1",
    )
    status, body = _get(http, f"/e/{e['id']}")
    assert status == 200
    assert "Which split?" in body and "because" in body
    assert 'sandbox="allow-scripts allow-popups"' in body
    assert "allow-same-origin" not in body and "allow-forms" not in body
    assert f"http://127.0.0.1:8798/h/{e['id']}" in body
    assert "Reference only. Answer below." in body


def test_anonymous_request_is_forbidden(conn, http, monkeypatch):
    monkeypatch.delenv("INBOX_ALLOW_INSECURE", raising=False)
    assert _get(http, "/")[0] == 403
    assert _get(http, "/", {"Tailscale-User-Login": "tjdsneto@example.com"})[0] == 200
    assert _get(http, "/", {"Tailscale-User-Login": "someone@example.com"})[0] == 403


def test_answer_posts_and_a_second_answer_conflicts(conn, http):
    e = store.create_entry(conn, "ask", validate_request({"title": "Q", "control": CHOICE}, "ask"), engine="claude", session_id="s-1")
    status, location, _ = _post(http, f"/e/{e['id']}/answer", "value=b&via=web")
    assert status == 303
    assert location == f"/e/{e['id']}"
    assert store.get_entry(conn, e["id"])["state"] == "answered"
    status, _, body = _post(http, f"/e/{e['id']}/answer", "value=a&via=web")
    assert status == 409
    assert "already answered" in body


def test_opening_info_marks_it_read(conn, http):
    info = store.create_entry(conn, "post", validate_request({"title": "note"}, "post"), script="cron")
    status, _ = _get(http, f"/e/{info['id']}")
    assert status == 200
    assert store.get_entry(conn, info["id"])["state"] == "read"


def test_dismiss_hides_an_undelivered_question(conn, http):
    e = store.create_entry(conn, "ask", validate_request({"title": "stuck", "control": CHOICE}, "ask"), engine="claude", session_id="s-1")
    conn.execute("UPDATE entries SET state = 'undelivered' WHERE id = %s", (e["id"],))
    status, location, _ = _post(http, "/batch", f"action=dismiss&id={e['id']}")
    assert status == 303
    assert location == "/"
    assert store.get_entry(conn, e["id"])["delivery"]["dismissed"] is True
    assert store.get_entry(conn, e["id"])["state"] == "undelivered"
    _, body = _get(http, "/")
    assert "stuck" not in body
