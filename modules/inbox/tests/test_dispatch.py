import json
import os
import time

from agent_inbox import dispatch, store
from agent_inbox.dispatch import dispatch_entry, render_message
from agent_inbox.validate import validate_request

CHOICE = {"type": "choice", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}


def _ask(conn):
    req = validate_request({"title": "Which split?", "control": CHOICE}, "ask")
    return store.create_entry(conn, "ask", req, engine="claude", session_id="s-1")


def _fake_wake(monkeypatch, result):
    """Wake starts instantly and has finished by the next sweep."""
    started = []
    monkeypatch.setattr(
        "agent_inbox.dispatch.start_wake",
        lambda entry_id, sid, message: started.append(message) or {"pid": 424242, "msg": "m", "out": "o"},
    )
    monkeypatch.setattr("agent_inbox.dispatch.wake_result", lambda inflight: result)
    return started


def _deliver(conn, entry_id):
    out = dispatch_entry(conn, entry_id)
    return dispatch_entry(conn, entry_id) if out == "started" else out


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
    monkeypatch.setattr("agent_inbox.dispatch.start_wake", lambda *a, **k: called.setdefault("n", 1))
    assert dispatch_entry(conn, e["id"]) is None
    assert called == {}


def test_dead_waiter_falls_through_to_wake(conn, monkeypatch):
    e = _ask(conn)
    store.answer(conn, e["id"], "a", via="cli")
    store.set_waiter(conn, e["id"], 999999)
    monkeypatch.setattr("agent_inbox.dispatch.pid_alive", lambda pid: False)
    monkeypatch.setattr("agent_inbox.dispatch.reach_for", lambda entry: _Reach("resumable"))
    _fake_wake(monkeypatch, {"result": "landed", "mode": "resume"})
    out = _deliver(conn, e["id"])
    assert out == "delivered"
    got = store.get_entry(conn, e["id"])
    assert got["state"] == "delivered"
    assert got["waiter_pid"] is None
    assert got["delivery"]["attempts"] == 1


def test_third_failure_marks_undelivered(conn, monkeypatch):
    e = _ask(conn)
    store.answer(conn, e["id"], "a", via="cli")
    monkeypatch.setattr("agent_inbox.dispatch.reach_for", lambda entry: _Reach("resumable"))
    _fake_wake(monkeypatch, {"result": "undelivered", "mode": "resume"})
    monkeypatch.setattr("agent_inbox.dispatch.pid_alive", lambda pid: False)
    for _ in range(3):
        _deliver(conn, e["id"])
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


def test_a_running_wake_is_never_started_twice(conn, monkeypatch):
    e = _ask(conn)
    store.answer(conn, e["id"], "a", via="cli")
    monkeypatch.setattr("agent_inbox.dispatch.reach_for", lambda entry: _Reach("resumable"))
    started = _fake_wake(monkeypatch, {"result": "landed", "mode": "resume"})
    monkeypatch.setattr("agent_inbox.dispatch.pid_alive", lambda pid: True)
    assert dispatch_entry(conn, e["id"]) == "started"
    for _ in range(5):
        assert dispatch_entry(conn, e["id"]) == "inflight"
    assert len(started) == 1
    assert store.get_entry(conn, e["id"])["state"] == "answered"
    monkeypatch.setattr("agent_inbox.dispatch.pid_alive", lambda pid: False)
    assert dispatch_entry(conn, e["id"]) == "delivered"
    got = store.get_entry(conn, e["id"])
    assert got["state"] == "delivered" and "inflight" not in got["delivery"]


def test_nothing_pending_skips_reachability(conn, monkeypatch):
    e = _ask(conn)
    called = []
    monkeypatch.setattr("agent_inbox.dispatch.reach_for", lambda entry: called.append(1) or _Reach("live"))
    assert dispatch_entry(conn, e["id"]) is None
    assert called == []


def test_start_wake_returns_before_a_slow_wake_finishes(tmp_path, monkeypatch):
    fake = tmp_path / "agt"
    fake.write_text('#!/bin/sh\nsleep 1\necho \'{"result": "landed", "mode": "resume"}\'\n')
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    began = time.monotonic()
    inflight = dispatch.start_wake("ib-test", "s-1", "hello")
    assert time.monotonic() - began < 0.5
    assert dispatch.pid_alive(inflight["pid"])
    deadline = time.monotonic() + 5
    while dispatch.pid_alive(inflight["pid"]) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not dispatch.pid_alive(inflight["pid"])
    assert dispatch.wake_result(inflight) == {"result": "landed", "mode": "resume"}
    assert not os.path.exists(inflight["msg"]) and not os.path.exists(inflight["out"])
