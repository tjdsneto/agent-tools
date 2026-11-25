import json
import subprocess
import urllib.parse

import pytest

from agent_registry import forking, topics


class FakeRun:
    """Records each command; returns canned stdout keyed by the command's first three words."""

    def __init__(self, outputs=None, codes=None):
        self.calls = []
        self.outputs = outputs or {}
        self.codes = codes or {}

    def __call__(self, cmd):
        self.calls.append(list(cmd))
        key = tuple(cmd[:3])
        return subprocess.CompletedProcess(cmd, self.codes.get(key, 0), stdout=self.outputs.get(key, ""), stderr="")


def test_cursor_backend_focuses_window_then_opens_tab(tmp_registry):
    topics.set_intent("claude", "p", "A")
    run = FakeRun()
    res = forking.fork("claude", "p", "Side", mode="side", brief_text="b", backend="cursor", directory="/proj", run=run)
    assert run.calls[0] == ["cursor", "/proj"]
    assert run.calls[1][0] == "open"
    url = run.calls[1][1]
    assert url.startswith("cursor://anthropic.claude-code/open?prompt=")
    prompt = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["prompt"][0]
    assert prompt == res["prompt"]
    assert f"agt registry intent --adopt {res['topic']['id']}" in prompt
    assert res["brief"] in prompt
    assert res["launched"] is True


def test_herdr_backend_splits_starts_and_prompts(tmp_registry):
    topics.set_intent("codex", "p", "A")
    run = FakeRun({("herdr", "pane", "split"): json.dumps({"result": {"pane": {"id": "p-9"}}})})
    res = forking.fork("codex", "p", "Side", mode="side", brief_text="b", backend="herdr", directory="/proj", run=run)
    name = f"fork-{res['topic']['id']}"
    assert run.calls[0] == [
        "herdr", "pane", "split", "--current", "--direction", "right", "--cwd", "/proj", "--no-focus",
    ]
    assert run.calls[1] == ["herdr", "agent", "start", name, "--kind", "codex", "--pane", "p-9"]
    assert run.calls[2] == ["herdr", "agent", "prompt", name, res["prompt"]]
    assert res["launched"] is True


def test_herdr_split_without_pane_id(tmp_registry):
    topics.set_intent("claude", "p", "A")
    run = FakeRun({("herdr", "pane", "split"): "{}"})
    res = forking.fork("claude", "p", "Side", mode="side", brief_text="b", backend="herdr", directory="/proj", run=run)
    assert res["launched"] is False
    assert "pane id" in res["error"]
    assert len(run.calls) == 1


def test_none_backend_runs_nothing(tmp_registry):
    topics.set_intent("claude", "p", "A")
    run = FakeRun()
    res = forking.fork("claude", "p", "Side", mode="side", brief_text="b", backend="none", directory="/proj", run=run)
    assert run.calls == []
    assert res["launched"] is False
    assert res["backend"] == "none"


def test_unknown_backend_writes_nothing(tmp_registry):
    topics.set_intent("claude", "p", "A")
    with pytest.raises(topics.TopicUsageError):
        forking.fork("claude", "p", "Side", mode="side", brief_text="b", backend="tmux", run=FakeRun())
    assert [e["event"] for e in topics.read_events("claude", "p")] == ["intent"]


def test_default_backend():
    assert forking.default_backend({"HERDR_ENV": "1"}) == "herdr"
    assert forking.default_backend({}) == "cursor"
