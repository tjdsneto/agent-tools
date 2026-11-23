import json

from agent_inbox import store
from agent_inbox.dispatch import dispatch_entry, render_message
from agent_inbox.validate import validate_request

CHOICE = {"type": "choice", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}


def _ask(conn):
    req = validate_request({"title": "Which split?", "control": CHOICE}, "ask")
    return store.create_entry(conn, "ask", req, engine="claude", session_id="s-1")


class _Reach:
    def __init__(self, status, reachable_at=None, headless=False):
        self.status = status
        self.reachable_at = reachable_at
        self.headless = headless


def test_message_shape():
    text = render_message(
        {"id": "ib-7k3q", "title": "Which split?", "answer": {"value": "b", "comment": "thin", "via": "web", "at": "t"}},
        {"event": "answer", "value": "b", "comment": "thin", "via": "web", "at": "t"},
    )
    assert 'Inbox answer for ib-7k3q ("Which split?")' in text
    assert "Comment: thin" in text
    payload = json.loads(text.strip().splitlines()[-2])
    assert payload["entry"] == "ib-7k3q" and payload["value"] == "b"
    assert text.strip().endswith("Full entry: agt inbox get ib-7k3q")


def test_skips_a_live_waiter(conn, monkeypatch):
    e = _ask(conn)
    store.answer(conn, e["id"], "b", via="web")
    store.set_waiter(conn, e["id"], 1)
    monkeypatch.setattr("agent_inbox.dispatch.pid_alive", lambda pid: True)
    called = {}
    monkeypatch.setattr("agent_inbox.dispatch.wake", lambda *a, **k: called.setdefault("n", 1))
    assert dispatch_entry(conn, e["id"]) is None
    assert called == {}


def test_dead_waiter_falls_through_to_wake(conn, monkeypatch):
    e = _ask(conn)
    store.answer(conn, e["id"], "a", via="cli")
    store.set_waiter(conn, e["id"], 999999)
    monkeypatch.setattr("agent_inbox.dispatch.pid_alive", lambda pid: False)
    monkeypatch.setattr("agent_inbox.dispatch.reach_for", lambda entry: _Reach("resumable"))
    monkeypatch.setattr("agent_inbox.dispatch.wake", lambda sid, message: {"result": "landed", "mode": "resume"})
    out = dispatch_entry(conn, e["id"])
    assert out == "delivered"
    got = store.get_entry(conn, e["id"])
    assert got["state"] == "delivered"
    assert got["waiter_pid"] is None
    assert got["delivery"]["attempts"] == 1


def test_third_failure_marks_undelivered(conn, monkeypatch):
    e = _ask(conn)
    store.answer(conn, e["id"], "a", via="cli")
    monkeypatch.setattr("agent_inbox.dispatch.reach_for", lambda entry: _Reach("resumable"))
    monkeypatch.setattr("agent_inbox.dispatch.wake", lambda sid, message: {"result": "undelivered", "mode": "resume"})
    for _ in range(3):
        dispatch_entry(conn, e["id"])
    assert store.get_entry(conn, e["id"])["state"] == "undelivered"


def test_held_does_not_burn_an_attempt(conn, monkeypatch):
    e = _ask(conn)
    store.answer(conn, e["id"], "a", via="cli")
    monkeypatch.setattr(
        "agent_inbox.dispatch.reach_for",
        lambda entry: _Reach("held", "2026-11-23T19:00:00"),
    )
    assert dispatch_entry(conn, e["id"]) == "held"
    got = store.get_entry(conn, e["id"])
    assert got["state"] == "answered"
    assert got["delivery"]["attempts"] == 0
    assert got["delivery"]["reachability"] == "held"
