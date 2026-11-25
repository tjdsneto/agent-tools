"""Real agents on a temp registry. Needs install.sh (skill links) and the updated Claude plugin.

Run explicitly: .venv/bin/python -m pytest tests/blackbox/test_topics_agent.py -v
The agent's wording varies, so the off-intent check looks for the fork / park words, not a sentence.
Agents run with box.env, so their hooks and Bash commands write to the temp registry, never the real one.
"""
import json
import shutil
import subprocess

import pytest

FIRST = (
    "This session's goal: write a haiku about autumn leaves into haiku.txt in this directory. "
    "Before anything else, follow the topic-awareness skill. Then write the haiku."
)
OFF_INTENT = (
    "Unrelated: I also need to design a retry policy for a payment webhook. "
    "Follow the topic-awareness skill for this new thread."
)
ALLOWED = "Bash(agt registry:*) Write Read"


def _claude(box, *args):
    return subprocess.run(
        [shutil.which("claude"), "-p", *args, "--output-format", "json", "--allowedTools", ALLOWED],
        cwd=box.root, env=box.env, capture_output=True, text=True, timeout=300,
    )


@pytest.mark.skipif(not shutil.which("claude"), reason="claude is not on PATH")
def test_claude_sets_intent_then_asks_on_drift(box):
    first = _claude(box, FIRST)
    assert first.returncode == 0, first.stderr
    sid = json.loads(first.stdout)["session_id"]
    events = box.log("claude", sid)
    assert any(e["event"] == "intent" for e in events), f"no intent recorded: {events}"

    second = _claude(box, "--resume", sid, OFF_INTENT)
    assert second.returncode == 0, second.stderr
    reply = json.loads(second.stdout)["result"].lower()
    assert "fork" in reply and "park" in reply, reply
    after = box.log("claude", sid)
    assert not any(e["event"] == "topic" and "retry" in e["topic"]["title"].lower() for e in after), after


@pytest.mark.skipif(not shutil.which("codex"), reason="codex is not on PATH")
def test_codex_sets_intent(box):
    proc = subprocess.run(
        [shutil.which("codex"), "exec", "--dangerously-bypass-hook-trust", "-s", "workspace-write",
         "-C", str(box.root), "--json", FIRST],
        env=box.env, capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    logs = list((box.data / "topics" / "codex").glob("*.jsonl")) if (box.data / "topics" / "codex").exists() else []
    assert logs, f"codex wrote no topic log; stdout tail: {proc.stdout[-2000:]}"
    events = [json.loads(line) for line in logs[0].read_text().splitlines() if line.strip()]
    assert any(e["event"] == "intent" for e in events)
