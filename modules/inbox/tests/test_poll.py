import json
import threading
import time

from agent_inbox import db
from agent_inbox.cli import main
from agent_inbox.constants import EXIT_OK, EXIT_USAGE
from agent_inbox.poll import poll_snapshot
from agent_inbox.store import create_entry
from agent_inbox.validate import validate_request

CHOICE = {"type": "choice", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}


def make_ask(conn, title="Which split?"):
    req = validate_request({"title": title, "control": CHOICE}, "ask")
    return create_entry(conn, "ask", req, engine="claude", session_id="s-1")


def make_post(conn, title="Note"):
    req = validate_request({"title": title}, "post")
    return create_entry(conn, "post", req, engine="claude", session_id="s-1")


def test_poll_returns_the_current_list(conn):
    entry = make_ask(conn)
    snap = poll_snapshot(since=None, timeout=1, kind="ask", states=["open"])
    assert snap["entries"][0]["id"] == entry["id"]
    assert "html" not in snap["entries"][0]
    again = poll_snapshot(since=None, timeout=1, kind="ask", states=["open"])
    assert again["rev"] == snap["rev"]


def later(delay, fn):
    def run():
        time.sleep(delay)
        c = db.connect()
        try:
            fn(c)
        finally:
            c.close()

    thread = threading.Thread(target=run)
    thread.start()
    return thread


def test_poll_waits_until_the_filtered_list_changes(conn):
    make_ask(conn, "first")
    first = poll_snapshot(since=None, timeout=1, kind="ask", states=["open"])
    thread = later(0.3, lambda c: make_ask(c, "second"))
    started = time.monotonic()
    snap = poll_snapshot(since=first["rev"], timeout=5, kind="ask", states=["open"])
    thread.join()
    assert time.monotonic() - started < 3
    assert snap["rev"] != first["rev"]
    assert len(snap["entries"]) == 2


def test_poll_returns_the_same_list_when_the_wait_times_out(conn):
    make_ask(conn)
    first = poll_snapshot(since=None, timeout=1, kind="ask", states=["open"])
    started = time.monotonic()
    again = poll_snapshot(since=first["rev"], timeout=0.4, kind="ask", states=["open"])
    elapsed = time.monotonic() - started
    assert 0.3 <= elapsed < 2
    assert again["rev"] == first["rev"]
    assert [row["id"] for row in again["entries"]] == [row["id"] for row in first["entries"]]


def test_cli_poll_prints_one_json_line(conn, capsys):
    entry = make_ask(conn)
    assert main(["poll", "--kind", "ask", "--state", "open"]) == EXIT_OK
    line = json.loads(capsys.readouterr().out)
    assert line["entries"][0]["id"] == entry["id"]
    assert line["rev"]


def test_cli_follow_rejects_rev(capsys):
    assert main(["poll", "--follow", "--rev", "abc"]) == EXIT_USAGE
    assert "does not take --rev" in capsys.readouterr().err


def test_a_post_does_not_end_an_ask_wait(conn):
    make_ask(conn)
    first = poll_snapshot(since=None, timeout=1, kind="ask", states=["open"])

    thread = later(0.2, lambda c: make_post(c))
    started = time.monotonic()
    again = poll_snapshot(since=first["rev"], timeout=0.7, kind="ask", states=["open"])
    thread.join()
    elapsed = time.monotonic() - started
    assert elapsed >= 0.6
    assert again["rev"] == first["rev"]
    assert len(again["entries"]) == 1
