import threading

import pytest

from agent_inbox import db, store
from agent_inbox.errors import ConflictError, ValidationError
from agent_inbox.validate import validate_request

CHOICE = {"type": "choice", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}


def make_ask(conn, control=CHOICE):
    req = validate_request({"title": "Which split?", "control": control}, "ask")
    return store.create_entry(conn, "ask", req, engine="claude", session_id="s-1")


def test_answer_records_value_comment_via(conn):
    e = make_ask(conn)
    out = store.answer(conn, e["id"], "b", comment="keep it thin", via="web")
    assert out["state"] == "answered" and out["value"] == "b"
    got = store.get_entry(conn, e["id"])
    assert got["state"] == "answered"
    assert got["answer"]["value"] == "b"
    assert got["answer"]["comment"] == "keep it thin"
    assert got["answer"]["via"] == "web"
    assert got["answer"]["at"]


def test_second_answer_conflicts_and_names_the_first(conn):
    e = make_ask(conn)
    store.answer(conn, e["id"], "a", via="telegram")
    with pytest.raises(ConflictError, match="already answered via telegram: a"):
        store.answer(conn, e["id"], "b", via="web")


def test_invalid_answer_leaves_entry_open(conn):
    e = make_ask(conn)
    with pytest.raises(ValidationError):
        store.answer(conn, e["id"], "zzz", via="web")
    assert store.get_entry(conn, e["id"])["state"] == "open"


def test_bad_via_rejected(conn):
    e = make_ask(conn)
    with pytest.raises(ValidationError, match="via"):
        store.answer(conn, e["id"], "a", via="slack")


def test_post_takes_no_answer(conn):
    p = store.create_entry(conn, "post", validate_request({"title": "info"}, "post"), script="x")
    with pytest.raises(ValidationError, match="not a question"):
        store.answer(conn, p["id"], "a", via="web")


def test_concurrent_answers_exactly_one_wins(inbox_db, conn):
    e = make_ask(conn)
    results: list[str] = []
    barrier = threading.Barrier(2)

    def attempt(value):
        c = db.connect()
        barrier.wait()
        try:
            store.answer(c, e["id"], value, via="web")
            results.append("won")
        except ConflictError:
            results.append("lost")
        finally:
            c.close()

    threads = [threading.Thread(target=attempt, args=(v,)) for v in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["lost", "won"]
