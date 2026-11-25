import psycopg
import pytest

from agent_inbox import store, topics
from agent_inbox.errors import ValidationError
from agent_inbox.validate import validate_request

CHOICE = {"type": "choice", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}
PATH = [{"id": "tp-root", "title": "Ship it", "kind": "intent"}, {"id": "tp-plan", "title": "Plan", "kind": "topic"}]


def ask(conn, **over):
    req = validate_request({"title": "Which split?", "control": CHOICE, **over}, "ask")
    return store.create_entry(conn, "ask", req, engine="claude", session_id="s-1")


def committed(dsn, entry_id):
    """The entry's state as another connection sees it: committed rows only."""
    with psycopg.connect(dsn) as other:
        row = other.execute("SELECT state FROM entries WHERE id = %s", (entry_id,)).fetchone()
    return row[0] if row else None


def test_an_ask_stores_the_session_path(conn, fake_registry):
    fake_registry.replies["topic-path"] = PATH
    e = ask(conn)
    assert e["topic_path"] == PATH
    assert store.get_entry(conn, e["id"])["topic_path"] == PATH
    assert fake_registry.calls[0] == ["topic-path", "--type=claude", "--session-id=s-1"]


def test_a_script_ask_resolves_its_named_topic(conn, fake_registry):
    fake_registry.replies["topic-path"] = PATH
    req = validate_request({"title": "Q", "control": CHOICE, "topic": "tp-plan"}, "ask")
    e = store.create_entry(conn, "ask", req, script="autopilot")
    assert e["topic_path"] == PATH
    assert fake_registry.calls[0] == ["topic-path", "--topic=tp-plan"]


def test_an_unknown_named_topic_is_rejected_and_nothing_is_stored(conn, fake_registry):
    fake_registry.replies["topic-path"] = topics.NOT_FOUND
    req = validate_request({"title": "Q", "control": CHOICE, "topic": "tp-nope"}, "ask")
    with pytest.raises(ValidationError, match="unknown topic tp-nope"):
        store.create_entry(conn, "ask", req, script="autopilot")
    assert conn.execute("SELECT count(*) AS n FROM entries").fetchone()["n"] == 0
    assert fake_registry.notes() == []


def test_a_registry_failure_still_creates_the_entry(conn, fake_registry):
    e = ask(conn)  # the fake answers None, like a registry that is down
    assert e["state"] == "open" and e["topic_path"] is None
    assert fake_registry.notes() == []


def test_ask_and_post_note_after_the_insert_commits(conn, inbox_db, fake_registry):
    fake_registry.replies["topic-path"] = PATH
    seen = []
    fake_registry.replies["topic-note"] = lambda *args: seen.append(committed(inbox_db, args[3].split("=", 1)[1]))
    q = ask(conn)
    p = store.create_entry(conn, "post", validate_request({"title": "Backup done"}, "post"), engine="claude", session_id="s-1")
    assert fake_registry.notes() == [
        ["asked", "--topic=tp-plan", f"--entry={q['id']}", "--title=Which split?", "--type=claude", "--session-id=s-1"],
        ["posted", "--topic=tp-plan", f"--entry={p['id']}", "--title=Backup done", "--type=claude", "--session-id=s-1"],
    ]
    assert seen == ["open", "unread"]
