import pytest

from agent_inbox import store
from agent_inbox.errors import ConflictError, ValidationError
from agent_inbox.validate import validate_request

CHOICE = {"type": "choice", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}


def make_ask(conn):
    req = validate_request({"title": "Which split?", "control": CHOICE}, "ask")
    return store.create_entry(conn, "ask", req, engine="claude", session_id="s-1")


def test_followup_and_reply_build_the_thread_in_order(conn):
    e = make_ask(conn)
    f = store.add_followup(conn, e["id"], "why not C?", via="telegram")
    r = store.add_reply(conn, e["id"], "C breaks the tray", html="<p>diagram</p>")
    assert f["event"] == "followup" and r["event"] == "reply" and r["seq"] > f["seq"]
    thread = store.get_entry(conn, e["id"])["thread"]
    assert [(t["type"], t["text"]) for t in thread] == [("followup", "why not C?"), ("reply", "C breaks the tray")]
    assert thread[0]["via"] == "telegram" and thread[1]["via"] == "agent"
    assert thread[1]["html"] == "<p>diagram</p>"
    assert store.get_entry(conn, e["id"])["state"] == "open"


def test_followup_allowed_after_answer(conn):
    e = make_ask(conn)
    store.answer(conn, e["id"], "a", via="web")
    store.add_followup(conn, e["id"], "one more thing", via="web")


def test_empty_texts_rejected(conn):
    e = make_ask(conn)
    with pytest.raises(ValidationError, match="empty"):
        store.add_followup(conn, e["id"], "  ", via="web")
    with pytest.raises(ValidationError, match="empty"):
        store.add_reply(conn, e["id"], "")


def test_post_followup_needs_a_session_and_marks_read(conn):
    scripted = store.create_entry(conn, "post", validate_request({"title": "x"}, "post"), script="cron")
    with pytest.raises(ValidationError, match="no session"):
        store.add_followup(conn, scripted["id"], "why?", via="web")
    agent_post = store.create_entry(conn, "post", validate_request({"title": "y"}, "post"),
                                    engine="codex", session_id="s-2")
    store.add_followup(conn, agent_post["id"], "why?", via="web")
    assert store.get_entry(conn, agent_post["id"])["state"] == "read"


def test_revise_replaces_control_and_logs(conn):
    e = make_ask(conn)
    new = {"type": "choice", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}, {"id": "c", "label": "C"}]}
    store.revise(conn, e["id"], new)
    got = store.get_entry(conn, e["id"])
    assert [o["id"] for o in got["control"]["options"]] == ["a", "b", "c"]
    assert len(got["revisions"]) == 1
    assert [o["id"] for o in got["revisions"][0]["old"]["options"]] == ["a", "b"]


def test_revise_only_while_open(conn):
    e = make_ask(conn)
    store.answer(conn, e["id"], "a", via="web")
    with pytest.raises(ConflictError):
        store.revise(conn, e["id"], CHOICE)
