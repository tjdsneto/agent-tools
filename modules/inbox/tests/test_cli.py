import io
import json
import threading
import time

from agent_inbox import db, store
from agent_inbox.cli import main
from agent_inbox.constants import EXIT_CONFLICT, EXIT_IO, EXIT_NOT_FOUND, EXIT_OK, EXIT_TIMEOUT, EXIT_USAGE

CHOICE = {"type": "choice", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}
ASKER = ["--engine", "claude", "--session-id", "s-1"]


def stdin(monkeypatch, payload):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))


def out(capsys):
    return json.loads(capsys.readouterr().out)


def test_ask_answer_get_roundtrip(inbox_db, monkeypatch, capsys):
    stdin(monkeypatch, {"title": "Which split?", "control": CHOICE})
    assert main(["ask", *ASKER]) == EXIT_OK
    eid = out(capsys)["entry"]
    assert main(["answer", eid, "--value", "b", "--comment", "thin", "--via", "web"]) == EXIT_OK
    capsys.readouterr()
    assert main(["answer", eid, "--value", "a"]) == EXIT_CONFLICT
    assert "already answered via web" in capsys.readouterr().err
    assert main(["get", eid]) == EXIT_OK
    got = out(capsys)
    assert got["answer"]["value"] == "b" and got["state"] == "answered"


def test_multi_answer_repeats_value(inbox_db, monkeypatch, capsys):
    multi = {"type": "multi", "options": [{"id": "x", "label": "X"}, {"id": "y", "label": "Y"}]}
    stdin(monkeypatch, {"title": "Which ones?", "control": multi})
    main(["ask", *ASKER])
    eid = out(capsys)["entry"]
    assert main(["answer", eid, "--value", "x", "--value", "y"]) == EXIT_OK
    assert out(capsys)["value"] == ["x", "y"]


def test_ask_without_session_is_usage_error(inbox_db, monkeypatch, capsys):
    stdin(monkeypatch, {"title": "t", "control": CHOICE})
    assert main(["ask", "--engine", "claude"]) == EXIT_USAGE
    assert "--session-id" in capsys.readouterr().err


def test_bad_flags_are_usage_not_not_found(inbox_db, capsys):
    assert main(["answer"]) == EXIT_USAGE
    assert main(["ask", "--engine", "hermes", "--session-id", "x"]) == EXIT_USAGE


def test_unknown_entry_is_not_found(inbox_db, capsys):
    assert main(["get", "ib-zzzz"]) == EXIT_NOT_FOUND


def test_store_down_is_io(monkeypatch, capsys):
    monkeypatch.setenv("AGENT_INBOX_DSN", "host=127.0.0.1 port=1 dbname=nope connect_timeout=1")
    assert main(["list"]) == EXIT_IO


def test_post_list_read_archive(inbox_db, monkeypatch, capsys):
    stdin(monkeypatch, {"title": "Nightly run done", "summary": "3 projects, 0 failures"})
    assert main(["post", "--script", "nightly"]) == EXIT_OK
    eid = out(capsys)["entry"]
    assert main(["list", "--json", "--kind", "post"]) == EXIT_OK
    assert [e["id"] for e in out(capsys)] == [eid]
    assert main(["list"]) == EXIT_OK
    assert eid in capsys.readouterr().out
    assert main(["read", eid]) == EXIT_OK and out(capsys)["state"] == "read"
    assert main(["archive", eid]) == EXIT_OK and out(capsys)["state"] == "archived"


def test_thread_commands(inbox_db, monkeypatch, capsys, tmp_path):
    stdin(monkeypatch, {"title": "Which split?", "control": CHOICE})
    main(["ask", *ASKER])
    eid = out(capsys)["entry"]
    assert main(["followup", eid, "--text", "why not C?", "--via", "telegram"]) == EXIT_OK
    capsys.readouterr()
    html = tmp_path / "r.html"
    html.write_text("<p>why</p>")
    assert main(["reply", eid, "--text", "C breaks the tray", "--html-file", str(html)]) == EXIT_OK
    capsys.readouterr()
    new = {"type": "choice", "options": [*CHOICE["options"], {"id": "c", "label": "C"}]}
    assert main(["revise", eid, "--control", json.dumps(new)]) == EXIT_OK
    capsys.readouterr()
    main(["get", eid])
    got = out(capsys)
    assert len(got["thread"]) == 2 and got["thread"][1]["html"] == "<p>why</p>"
    assert len(got["control"]["options"]) == 3


def test_update_writes_the_question_text(inbox_db, monkeypatch, capsys):
    stdin(monkeypatch, {"title": "Which split?", "summary": "old", "control": CHOICE})
    main(["ask", *ASKER])
    eid = out(capsys)["entry"]
    stdin(monkeypatch, {"detail": "the prompts", "summary": "shorter"})
    assert main(["update", eid]) == EXIT_OK
    assert out(capsys)["fields"] == ["detail", "summary"]
    assert main(["get", eid]) == EXIT_OK
    got = out(capsys)
    assert got["detail"] == "the prompts" and got["summary"] == "shorter" and got["title"] == "Which split?"
    assert main(["answer", eid, "--value", "a"]) == EXIT_OK
    capsys.readouterr()
    stdin(monkeypatch, {"summary": "too late"})
    assert main(["update", eid]) == EXIT_CONFLICT


def test_withdraw_and_supersede(inbox_db, monkeypatch, capsys):
    ids = []
    for _ in range(3):
        stdin(monkeypatch, {"title": "q", "control": CHOICE})
        main(["ask", *ASKER])
        ids.append(out(capsys)["entry"])
    assert main(["withdraw", ids[0]]) == EXIT_OK
    capsys.readouterr()
    assert main(["supersede", ids[1], "--by", ids[2]]) == EXIT_OK
    assert out(capsys)["superseded_by"] == ids[2]


def test_ask_wait_returns_the_answer(inbox_db, monkeypatch, capsys):
    def answer_when_open():
        c = db.connect()
        try:
            for _ in range(50):
                rows = store.list_entries(c, states=["open"])
                if rows:
                    store.answer(c, rows[0]["id"], "a", via="web")
                    return
                time.sleep(0.1)
        finally:
            c.close()

    t = threading.Thread(target=answer_when_open)
    t.start()
    stdin(monkeypatch, {"title": "Which split?", "control": CHOICE})
    code = main(["ask", *ASKER, "--wait", "--timeout", "10"])
    t.join()
    assert code == EXIT_OK
    assert out(capsys)["value"] == "a"


def test_wait_timeout_exit_code(inbox_db, monkeypatch, capsys):
    stdin(monkeypatch, {"title": "q", "control": CHOICE})
    main(["ask", *ASKER])
    eid = out(capsys)["entry"]
    assert main(["wait", eid, "--timeout", "1"]) == EXIT_TIMEOUT
    assert out(capsys)["event"] == "timeout"


def test_ask_and_post_print_the_entry_link(inbox_db, monkeypatch, capsys):
    monkeypatch.setenv("INBOX_UI_ORIGIN", "https://inbox.example:8444/")
    stdin(monkeypatch, {"title": "t", "control": CHOICE})
    assert main(["ask", "--engine", "claude", "--session-id", "s-1"]) == EXIT_OK
    asked = out(capsys)
    assert asked["url"] == f"https://inbox.example:8444/e/{asked['entry']}"
    stdin(monkeypatch, {"title": "report"})
    assert main(["post", "--script", "nightly"]) == EXIT_OK
    posted = out(capsys)
    assert posted["url"] == f"https://inbox.example:8444/e/{posted['entry']}"


def test_the_link_falls_back_to_localhost_without_tailscale(monkeypatch):
    from agent_inbox import links
    monkeypatch.delenv("INBOX_UI_ORIGIN", raising=False)

    def no_tailscale(*args, **kwargs):
        raise OSError("no tailscale")

    monkeypatch.setattr(links.subprocess, "run", no_tailscale)
    assert links.entry_url("ib-abcd") == "http://127.0.0.1:8797/e/ib-abcd"


def test_ask_with_a_script_needs_no_session(inbox_db, monkeypatch, capsys):
    stdin(monkeypatch, {"title": "t", "control": CHOICE})
    assert main(["ask", "--script", "autopilot"]) == EXIT_OK
    eid = out(capsys)["entry"]
    assert main(["get", eid]) == EXIT_OK and out(capsys)["asker"]["script"] == "autopilot"
