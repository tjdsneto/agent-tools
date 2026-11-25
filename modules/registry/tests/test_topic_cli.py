import json

import pytest

from agent_registry import topics
from agent_registry.cli import main
from agent_registry.constants import EXIT_CONFLICT, EXIT_NOT_FOUND, EXIT_OK, EXIT_USAGE

WHO = ["--type", "claude", "--session-id", "s1"]


@pytest.fixture(autouse=True)
def no_session_env(monkeypatch):
    for var in ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "CURSOR_CONVERSATION_ID"):
        monkeypatch.delenv(var, raising=False)


def _run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_intent_topic_done_history(tmp_registry, capsys):
    code, out, _ = _run(capsys, "intent", "Ship it", *WHO)
    assert code == EXIT_OK
    tid = json.loads(out)["topic"]["id"]
    code, out, _ = _run(capsys, "topic", "Plan", *WHO)
    assert code == EXIT_OK and json.loads(out)["parent"] == tid
    code, out, _ = _run(capsys, "topic", "--done", *WHO)
    assert code == EXIT_OK and json.loads(out)["event"] == "done"
    code, out, _ = _run(capsys, "topics", *WHO)
    data = json.loads(out)
    assert [e["event"] for e in data["events"]] == ["intent", "topic", "done"]
    assert data["intent"]["id"] == tid
    assert data["topic"] is None


def test_exit_codes(tmp_registry, capsys):
    assert _run(capsys, "topic", "Plan", *WHO)[0] == EXIT_USAGE
    assert _run(capsys, "intent", "A", *WHO)[0] == EXIT_OK
    assert _run(capsys, "intent", "B", *WHO)[0] == EXIT_CONFLICT
    assert _run(capsys, "topic", "--done", "tp-zzzz", *WHO)[0] == EXIT_NOT_FOUND
    assert _run(capsys, "topic", *WHO)[0] == EXIT_USAGE
    assert _run(capsys, "intent", *WHO)[0] == EXIT_USAGE
    assert _run(capsys, "intent", "A", "--adopt", "tp-zzzz", *WHO)[0] == EXIT_USAGE


def test_park_with_ref(tmp_registry, capsys):
    _run(capsys, "intent", "A", *WHO)
    _run(capsys, "topic", "Side", *WHO)
    code, out, _ = _run(capsys, "topic", "--park", "--ref", "pk-1", *WHO)
    assert code == EXIT_OK
    assert json.loads(out)["ref"] == "pk-1"


def test_identity_from_env(tmp_registry, capsys, monkeypatch):
    monkeypatch.setenv("CODEX_THREAD_ID", "t-1")
    assert _run(capsys, "intent", "From env")[0] == EXIT_OK
    assert topics.state("codex", "t-1")["intent"]["title"] == "From env"


def test_no_identity_is_usage(tmp_registry, capsys):
    code, _, err = _run(capsys, "intent", "x")
    assert code == EXIT_USAGE
    assert "--type" in err


def test_session_id_needs_type(tmp_registry, capsys):
    assert _run(capsys, "intent", "x", "--session-id", "s1")[0] == EXIT_USAGE


def test_topic_context_is_a_plain_line(tmp_registry, capsys):
    code, out, _ = _run(capsys, "topic-context", *WHO)
    assert code == EXIT_OK
    assert out.startswith("No intent set for this session.")


def test_topics_other_session_open_and_tree(tmp_registry, capsys):
    _run(capsys, "intent", "A", *WHO)
    code, out, _ = _run(capsys, "topics", "--session", "s1")
    assert code == EXIT_OK and json.loads(out)["agent_type"] == "claude"
    assert _run(capsys, "topics", "--session", "nope")[0] == EXIT_NOT_FOUND
    code, out, _ = _run(capsys, "topics", "--open")
    assert [t["title"] for t in json.loads(out)["topics"]] == ["A"]
    code, out, _ = _run(capsys, "topics", "--tree")
    assert [n["title"] for n in json.loads(out)["tree"]] == ["A"]


def test_fork_reads_brief_file(tmp_registry, capsys, tmp_path):
    _run(capsys, "intent", "A", *WHO)
    brief = tmp_path / "brief.md"
    brief.write_text("# Why\nSplit off.\n")
    code, out, _ = _run(capsys, "fork", "Side", "--side", "--backend", "none", "--brief-file", str(brief), *WHO)
    assert code == EXIT_OK
    data = json.loads(out)
    assert data["launched"] is False
    assert open(data["brief"]).read() == "# Why\nSplit off.\n"
    assert f"--adopt {data['topic']['id']}" in data["prompt"]


def test_fork_needs_a_mode(tmp_registry, capsys):
    with pytest.raises(SystemExit):
        main(["fork", "Side", "--backend", "none", *WHO])
