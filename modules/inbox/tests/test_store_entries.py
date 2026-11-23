import subprocess

import pytest

from agent_inbox import store
from agent_inbox.errors import NotFoundError, ValidationError
from agent_inbox.validate import validate_request

CHOICE = {"type": "choice", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}


def make_ask(conn, cwd=None, **over):
    req = validate_request({"title": "Which split?", "control": CHOICE, **over}, "ask")
    return store.create_entry(conn, "ask", req, engine="claude", model="opus", session_id="s-1", cwd=cwd)


def test_create_ask_records_asker_and_opens(conn, tmp_path):
    e = make_ask(conn, cwd=str(tmp_path))
    assert e["id"].startswith("ib-")
    assert e["state"] == "open"
    assert e["mode"] == "resume"
    assert e["asker"] == {"engine": "claude", "model": "opus", "session_id": "s-1",
                          "cwd": str(tmp_path), "project": str(tmp_path), "script": None}
    assert e["thread"] == [] and e["revisions"] == []


def test_project_is_git_root(conn, tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    sub = tmp_path / "deep" / "dir"
    sub.mkdir(parents=True)
    e = make_ask(conn, cwd=str(sub))
    assert e["asker"]["project"] == str(tmp_path.resolve())


def test_ask_needs_engine_and_session(conn):
    req = validate_request({"title": "t", "control": CHOICE}, "ask")
    with pytest.raises(ValidationError, match="--engine and --session-id"):
        store.create_entry(conn, "ask", req, engine="claude", session_id=None)
    with pytest.raises(ValidationError, match="--engine and --session-id"):
        store.create_entry(conn, "ask", req, engine=None, session_id="s")


def test_post_from_script_or_session(conn):
    req = validate_request({"title": "Nightly run done"}, "post")
    e = store.create_entry(conn, "post", req, script="nightly-backup")
    assert e["state"] == "unread" and e["mode"] is None and e["asker"]["script"] == "nightly-backup"
    with pytest.raises(ValidationError, match="--session-id or --script"):
        store.create_entry(conn, "post", req)
    with pytest.raises(ValidationError, match="needs --engine"):
        store.create_entry(conn, "post", req, session_id="s")


def test_get_unknown_raises(conn):
    with pytest.raises(NotFoundError):
        store.get_entry(conn, "ib-zzzz")


def test_list_orders_urgent_first_then_oldest_and_filters(conn):
    first = make_ask(conn)
    second = make_ask(conn, priority="urgent")
    third = make_ask(conn)
    post = store.create_entry(conn, "post", validate_request({"title": "info"}, "post"), script="x")
    ids = [e["id"] for e in store.list_entries(conn)]
    assert ids == [second["id"], first["id"], third["id"], post["id"]]
    assert [e["id"] for e in store.list_entries(conn, kind="post")] == [post["id"]]
    assert [e["id"] for e in store.list_entries(conn, states=["unread"])] == [post["id"]]
    assert len(store.list_entries(conn, limit=2)) == 2
    assert "html" not in store.list_entries(conn)[0]
