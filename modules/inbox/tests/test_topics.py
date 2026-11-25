import stat
import time

import pytest

from agent_inbox import topics
from agent_inbox.errors import ValidationError
from agent_inbox.topics import registry as real_registry

PATH = [{"id": "tp-root", "title": "Ship it", "kind": "intent"}, {"id": "tp-plan", "title": "Plan", "kind": "topic"}]


def fake_agt(tmp_path, monkeypatch, body):
    """A stand-in `agt` that writes its args to calls.txt, one per line, then runs body."""
    script = tmp_path / "agt"
    script.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{tmp_path}/calls.txt"\n{body}\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("AGENT_INBOX_AGT", str(script))
    return tmp_path / "calls.txt"


def test_registry_returns_parsed_json_and_passes_the_args(tmp_path, monkeypatch):
    calls = fake_agt(tmp_path, monkeypatch, "echo '[1, 2]'")
    assert real_registry("topic-path", "--topic=tp-a") == [1, 2]
    assert calls.read_text().splitlines() == ["registry", "topic-path", "--topic=tp-a"]


def test_registry_reports_an_unknown_topic(tmp_path, monkeypatch):
    fake_agt(tmp_path, monkeypatch, "echo 'agent-registry: topic not found: tp-x' >&2; exit 2")
    assert real_registry("topic-path", "--topic=tp-x") is topics.NOT_FOUND


@pytest.mark.parametrize("body", [
    "echo boom >&2; exit 1",
    "echo 'not json'",
    "echo 'usage: agent-registry ...' >&2; exit 2",  # argparse also exits 2; that is not "not found"
])
def test_registry_failures_are_none_with_a_warning(tmp_path, monkeypatch, capsys, body):
    fake_agt(tmp_path, monkeypatch, body)
    assert real_registry("topic-path", "--topic=tp-x") is None
    assert "continuing without the topic link" in capsys.readouterr().err


def test_a_missing_registry_is_none(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AGENT_INBOX_AGT", str(tmp_path / "no-such-agt"))
    assert real_registry("topic-path") is None
    assert "continuing without the topic link" in capsys.readouterr().err


def test_a_slow_registry_times_out(tmp_path, monkeypatch):
    fake_agt(tmp_path, monkeypatch, "exec sleep 5")
    monkeypatch.setattr(topics, "TIMEOUT_SEC", 0.3)
    start = time.monotonic()
    assert real_registry("topic-path") is None
    assert time.monotonic() - start < 2


def test_path_for_a_session_and_a_named_topic(fake_registry):
    fake_registry.replies["topic-path"] = PATH
    assert topics.path_for(engine="claude", session_id="s-1", topic=None) == PATH
    assert topics.path_for(engine="claude", session_id="s-1", topic="tp-plan") == PATH
    assert topics.path_for(engine=None, session_id=None, topic=None) is None
    assert fake_registry.calls == [
        ["topic-path", "--type=claude", "--session-id=s-1"],
        ["topic-path", "--topic=tp-plan"],
    ]


def test_path_for_an_unknown_topic_is_a_validation_error(fake_registry):
    fake_registry.replies["topic-path"] = topics.NOT_FOUND
    with pytest.raises(ValidationError, match="unknown topic tp-nope"):
        topics.path_for(engine=None, session_id=None, topic="tp-nope")


@pytest.mark.parametrize("reply", [None, [], {"id": "tp-a"}, [{"title": "no id"}], ["tp-a"]])
def test_path_for_drops_a_malformed_path(fake_registry, reply):
    fake_registry.replies["topic-path"] = reply
    assert topics.path_for(engine="claude", session_id="s-1", topic=None) is None


def test_path_for_normalises_nodes(fake_registry):
    fake_registry.replies["topic-path"] = [{"id": "tp-a", "title": 7, "kind": "weird", "extra": 1}]
    assert topics.path_for(engine="claude", session_id="s-1", topic=None) == [{"id": "tp-a", "title": None, "kind": "topic"}]


def test_note_names_the_last_topic_and_the_asker(fake_registry):
    topics.note("answered", "ib-1", PATH, engine="claude", session_id="s-1", value=["a", "b"], via="web", title=None)
    assert fake_registry.notes() == [[
        "answered", "--topic=tp-plan", "--entry=ib-1", "--value=a, b", "--via=web", "--type=claude", "--session-id=s-1",
    ]]


def test_note_without_a_path_does_nothing_and_without_an_asker_sends_none(fake_registry):
    topics.note("asked", "ib-1", None, title="Q")
    topics.note("asked", "ib-1", [], title="Q")
    assert fake_registry.calls == []
    topics.note("posted", "ib-2", PATH, title="R")
    assert fake_registry.notes() == [["posted", "--topic=tp-plan", "--entry=ib-2", "--title=R"]]


def test_non_utf8_output_from_agt_is_none_and_never_raises(tmp_path, monkeypatch, capsys):
    fake_agt(tmp_path, monkeypatch, r"printf '\377\376'; printf '\377\376' >&2; exit 1")
    assert real_registry("topic-path") is None
    assert "continuing without the topic link" in capsys.readouterr().err
    fake_agt(tmp_path, monkeypatch, r"printf '\377\376'")
    assert real_registry("topic-path") is None
