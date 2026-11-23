import pytest

from agent_inbox import store
from agent_inbox.errors import ConflictError, ValidationError
from agent_inbox.validate import validate_request

CHOICE = {"type": "choice", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}


def make_ask(conn):
    req = validate_request({"title": "Which split?", "control": CHOICE}, "ask")
    return store.create_entry(conn, "ask", req, engine="claude", session_id="s-1")


def make_post(conn):
    return store.create_entry(conn, "post", validate_request({"title": "info"}, "post"), script="cron")


def test_withdraw_open_question(conn):
    e = make_ask(conn)
    assert store.withdraw(conn, e["id"])["state"] == "withdrawn"
    with pytest.raises(ConflictError):
        store.withdraw(conn, e["id"])
    with pytest.raises(ConflictError):
        store.answer(conn, e["id"], "a", via="web")


def test_followup_on_withdrawn_conflicts(conn):
    e = make_ask(conn)
    store.withdraw(conn, e["id"])
    with pytest.raises(ConflictError):
        store.add_followup(conn, e["id"], "hello?", via="web")


def test_supersede_links_the_newer_entry(conn):
    old, new = make_ask(conn), make_ask(conn)
    store.supersede(conn, old["id"], by=new["id"])
    got = store.get_entry(conn, old["id"])
    assert got["state"] == "superseded" and got["superseded_by"] == new["id"]


def test_supersede_rules(conn):
    a = make_ask(conn)
    with pytest.raises(ValidationError, match="itself"):
        store.supersede(conn, a["id"], by=a["id"])
    with pytest.raises(ValidationError, match="not a question"):
        store.supersede(conn, a["id"], by=make_post(conn)["id"])


def test_read_and_archive_posts(conn):
    p = make_post(conn)
    assert store.mark_read(conn, p["id"])["state"] == "read"
    assert store.mark_read(conn, p["id"])["state"] == "read"
    assert store.archive(conn, p["id"])["state"] == "archived"
    assert store.archive(conn, p["id"])["state"] == "archived"
    with pytest.raises(ValidationError, match="not an info entry"):
        store.mark_read(conn, make_ask(conn)["id"])


def test_state_changes_are_logged(conn):
    e = make_ask(conn)
    store.withdraw(conn, e["id"])
    types = [r["type"] for r in conn.execute("SELECT type FROM events WHERE entry_id = %s", (e["id"],)).fetchall()]
    assert types == ["state"]
