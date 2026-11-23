from datetime import datetime, timedelta, timezone

from agent_inbox import serve, store
from agent_inbox.validate import validate_request

CHOICE = {"type": "choice", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}


def test_expiry_closes_open_questions_only(conn):
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    req = validate_request({"title": "t", "control": CHOICE, "expires_at": past}, "ask")
    e = store.create_entry(conn, "ask", req, engine="claude", session_id="s-1")
    info = store.create_entry(conn, "post", validate_request({"title": "i", "expires_at": past}, "post"), script="x")
    n = serve.expire_due(conn)
    assert n == 1
    assert store.get_entry(conn, e["id"])["state"] == "expired"
    assert store.get_entry(conn, info["id"])["state"] == "unread"


def test_sweep_dispatches_answered_entries(conn, monkeypatch):
    req = validate_request({"title": "t", "control": CHOICE}, "ask")
    e = store.create_entry(conn, "ask", req, engine="claude", session_id="s-1")
    store.answer(conn, e["id"], "a", via="cli")
    seen = []
    monkeypatch.setattr("agent_inbox.serve.dispatch_entry", lambda c, i: seen.append(i) or "delivered")
    serve.sweep(conn)
    assert seen == [e["id"]]


def test_one_failing_entry_does_not_stop_the_sweep(conn, monkeypatch):
    ids = []
    for _ in range(2):
        req = validate_request({"title": "t", "control": CHOICE}, "ask")
        e = store.create_entry(conn, "ask", req, engine="claude", session_id="s-1")
        store.answer(conn, e["id"], "a", via="cli")
        ids.append(e["id"])
    seen = []

    def flaky(c, entry_id):
        seen.append(entry_id)
        if entry_id == ids[0]:
            raise RuntimeError("boom")
        return "started"

    monkeypatch.setattr("agent_inbox.serve.dispatch_entry", flaky)
    serve.sweep(conn)
    assert seen == ids
