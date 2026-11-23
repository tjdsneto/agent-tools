import threading
from http.client import HTTPConnection

from agent_inbox import store
from agent_inbox.frame import make_server
from agent_inbox.validate import validate_request

CHOICE = {"type": "choice", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}


def get_frame(conn, path):
    server = make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        client = HTTPConnection(host, port, timeout=5)
        client.request("GET", path)
        resp = client.getresponse()
        return resp.status, {k: v for k, v in resp.getheaders()}, resp.read().decode()
    finally:
        server.shutdown()
        server.server_close()


def test_frame_serves_the_agent_document(conn):
    e = store.create_entry(
        conn, "ask",
        validate_request({
            "title": "t",
            "html": "<p>diagram</p><a href=\"https://example.com\">x</a>",
            "control": CHOICE,
        }, "ask"),
        engine="claude", session_id="s-1",
    )
    status, headers, body = get_frame(conn, f"/h/{e['id']}")
    assert status == 200
    assert "<p>diagram</p>" in body
    assert '<base target="_blank">' in body
    csp = headers["Content-Security-Policy"]
    assert "frame-ancestors http://127.0.0.1:8797" in csp
    assert "sandbox allow-scripts allow-popups" in csp
    assert "8797" not in body


def test_frame_unknown_id_is_404(conn):
    status, _, _ = get_frame(conn, "/h/ib-none")
    assert status == 404
