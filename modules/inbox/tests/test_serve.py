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


def test_sweep_skips_entries_with_nothing_to_deliver(conn, monkeypatch):
    def ask():
        req = validate_request({"title": "t", "control": CHOICE}, "ask")
        return store.create_entry(conn, "ask", req, engine="claude", session_id="s-1")

    idle_open, answered, done, followed = ask(), ask(), ask(), ask()
    store.answer(conn, answered["id"], "a", via="cli")
    store.answer(conn, done["id"], "a", via="cli")
    conn.execute("UPDATE entries SET state = 'delivered' WHERE id = %s", (done["id"],))
    store.add_followup(conn, followed["id"], "why?", via="web")
    seen = []
    monkeypatch.setattr("agent_inbox.serve.dispatch_entry", lambda c, i: seen.append(i))
    serve.sweep(conn)
    assert sorted(seen) == sorted([answered["id"], followed["id"]])


def test_a_follow_up_on_an_agent_post_is_swept(conn, monkeypatch):
    post = store.create_entry(conn, "post", validate_request({"title": "run done"}, "post"), engine="codex", session_id="s-2")
    scripted = store.create_entry(conn, "post", validate_request({"title": "cron"}, "post"), script="cron")
    store.add_followup(conn, post["id"], "why did X fail?", via="web")
    seen = []
    monkeypatch.setattr("agent_inbox.serve.dispatch_entry", lambda c, i: seen.append(i))
    serve.sweep(conn)
    assert seen == [post["id"]]


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _open_ask(conn, priority="normal"):
    req = validate_request({"title": "Which?", "control": CHOICE, "priority": priority}, "ask")
    return store.create_entry(conn, "ask", req, engine="claude", session_id="s-1")


def _reach_seq(monkeypatch, statuses):
    from agent_inbox.reach import Reach
    calls = []

    def fake(entry):
        status, when = statuses[min(len(calls), len(statuses) - 1)]
        calls.append(entry["id"])
        return Reach(status, "claude", reachable_at=when)

    monkeypatch.setattr("agent_inbox.reach.for_entry", fake)
    return calls


def test_open_questions_get_reachability_on_a_slow_cadence(conn, monkeypatch):
    monkeypatch.setattr(serve, "_checked", {})
    e = _open_ask(conn)
    calls = _reach_seq(monkeypatch, [("held", "2026-11-24T02:00:00")])
    clock = _Clock()
    serve.refresh_reach(conn, now=clock)
    delivery = store.get_entry(conn, e["id"])["delivery"]
    assert (delivery["reachability"], delivery["reachable_at"]) == ("held", "2026-11-24T02:00:00")
    clock.t += serve.HELD_EVERY - 1
    serve.refresh_reach(conn, now=clock)
    assert calls == [e["id"]]
    clock.t += 1
    serve.refresh_reach(conn, now=clock)
    assert calls == [e["id"], e["id"]]


def test_an_unchanged_reachability_is_not_written(conn, monkeypatch):
    monkeypatch.setattr(serve, "_checked", {})
    e = _open_ask(conn)
    _reach_seq(monkeypatch, [("resumable", None)])
    clock = _Clock()
    serve.refresh_reach(conn, now=clock)
    before = conn.execute("SELECT xmin::text AS v FROM entries WHERE id = %s", (e["id"],)).fetchone()["v"]
    clock.t += serve.REACH_EVERY
    serve.refresh_reach(conn, now=clock)
    after = conn.execute("SELECT xmin::text AS v FROM entries WHERE id = %s", (e["id"],)).fetchone()["v"]
    assert before == after


def test_a_held_question_that_frees_up_is_pushed_once(conn, monkeypatch):
    monkeypatch.setattr(serve, "_checked", {})
    monkeypatch.setattr("agent_inbox.notify.quiet", lambda now: False)
    monkeypatch.setattr("agent_inbox.notify.push_pending", lambda c: None)
    monkeypatch.setenv("AGENT_INBOX_TELEGRAM_TO", "telegram:1")
    sent = []
    monkeypatch.setattr("agent_inbox.notify.hermes_send", lambda to, text: sent.append(text))
    e = _open_ask(conn)
    _reach_seq(monkeypatch, [("held", None), ("resumable", None)])
    serve.sweep(conn)
    assert sent == []
    serve._checked.clear()
    serve.sweep(conn)
    serve._checked.clear()
    serve.sweep(conn)
    assert sent == [f"1 question is answerable again\n• Which? ({e['id']})"]


def test_a_normal_answerable_push_waits_out_quiet_hours(conn, monkeypatch):
    from agent_inbox import notify
    monkeypatch.setenv("AGENT_INBOX_TELEGRAM_TO", "telegram:1")
    sent = []
    monkeypatch.setattr("agent_inbox.notify.hermes_send", lambda to, text: sent.append(text))
    e = _open_ask(conn)
    night = datetime(2026, 11, 24, 2, 0, tzinfo=notify.LOCAL)
    morning = datetime(2026, 11, 24, 9, 0, tzinfo=notify.LOCAL)
    notify.push_answerable(conn, [e["id"]], "normal", now=night)
    assert sent == []
    notify.push_answerable(conn, [], "normal", now=morning)
    assert len(sent) == 1 and e["id"] in sent[0]
    notify.push_answerable(conn, [], "normal", now=morning)
    assert len(sent) == 1
