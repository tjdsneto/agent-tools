import threading
import time

from agent_inbox import db, store, waiting
from agent_inbox.validate import validate_request

CHOICE = {"type": "choice", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}


def make_ask(conn):
    req = validate_request({"title": "Which split?", "control": CHOICE}, "ask")
    return store.create_entry(conn, "ask", req, engine="claude", session_id="s-1", mode="wait")


def later(delay, fn):
    def run():
        time.sleep(delay)
        c = db.connect()
        try:
            fn(c)
        finally:
            c.close()
    t = threading.Thread(target=run)
    t.start()
    return t


def test_answer_wakes_the_waiter_and_marks_delivered(conn):
    e = make_ask(conn)
    t = later(0.3, lambda c: store.answer(c, e["id"], "b", via="web"))
    started = time.monotonic()
    ev = waiting.wait_for(e["id"], timeout=10, poll=30)
    t.join()
    assert time.monotonic() - started < 3, "woke by NOTIFY, not by the 30s poll"
    assert ev["event"] == "answer" and ev["value"] == "b" and ev["via"] == "web"
    got = store.get_entry(conn, e["id"])
    assert got["state"] == "delivered"
    assert got["waiter_pid"] is None


def test_answer_before_wait_returns_immediately(conn):
    e = make_ask(conn)
    store.answer(conn, e["id"], "a", via="cli")
    assert waiting.wait_for(e["id"], timeout=5)["value"] == "a"


def test_followup_returns_with_seq_then_wait_after_it(conn):
    e = make_ask(conn)
    t = later(0.2, lambda c: store.add_followup(c, e["id"], "why not C?", via="telegram"))
    ev = waiting.wait_for(e["id"], timeout=10, poll=30)
    t.join()
    assert ev["event"] == "followup" and ev["text"] == "why not C?"
    t = later(0.2, lambda c: store.answer(c, e["id"], "a", via="web"))
    ev2 = waiting.wait_for(e["id"], after=ev["seq"], timeout=10, poll=30)
    t.join()
    assert ev2["event"] == "answer"


def test_timeout_switches_to_resume(conn):
    e = make_ask(conn)
    ev = waiting.wait_for(e["id"], timeout=0.5, poll=0.2)
    assert ev == {"entry": e["id"], "event": "timeout"}
    got = store.get_entry(conn, e["id"])
    assert got["mode"] == "resume" and got["state"] == "open" and got["waiter_pid"] is None


def test_withdrawn_entry_returns_its_state(conn):
    e = make_ask(conn)
    store.withdraw(conn, e["id"])
    assert waiting.wait_for(e["id"], timeout=5)["event"] == "withdrawn"


def test_waiter_pid_set_while_blocking(conn):
    e = make_ask(conn)
    seen = {}
    t = later(0.3, lambda c: seen.setdefault("pid", store.get_entry(c, e["id"])["waiter_pid"]))
    waiting.wait_for(e["id"], timeout=0.8, poll=0.2)
    t.join()
    assert seen["pid"] is not None
