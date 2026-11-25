"""Real agents on a temp registry. Needs install.sh (skill links) and the updated Claude plugin.

Run explicitly: .venv/bin/python -m pytest tests/blackbox/test_topics_agent.py -v
The agent's wording varies, so the off-intent check looks for the fork / park words, not a sentence.
Agents run with the box's environment, so their hooks and Bash commands write to the temp registry, never the real one.
The prompts never name the skill: the intent has to come from the hook reminder plus the installed skill.
"""
import json
import shutil
import subprocess

import pytest

FIRST = "Write a haiku about autumn leaves into haiku.txt in this directory."
OFF_INTENT = "Unrelated: I also need to design a retry policy for a payment webhook."
ALLOWED = "Bash(agt registry:*) Write Read"


def _agent_env(box):
    # A fork must never open a real Cursor tab or Herdr pane from a test.
    return {**box.env, "AGENT_REGISTRY_FORK_BACKEND": "none"}


def _claude(box, *args):
    return subprocess.run(
        [shutil.which("claude"), "-p", *args, "--output-format", "json", "--allowedTools", ALLOWED],
        cwd=box.root, env=_agent_env(box), capture_output=True, text=True, timeout=300,
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
    assert not any(e["event"] in ("forked", "parked") for e in after[len(events):]), after


def _codex_shell_env(box):
    # Codex hands its shell only the env its shell_environment_policy allows (often just core vars),
    # so the temp registry has to be set for the shell explicitly or `agt` writes the real one.
    env = _agent_env(box)
    args = []
    for key in ("AGENT_REGISTRY_PATH", "AGENT_REGISTRY_FORK_BACKEND"):
        args += ["-c", f"shell_environment_policy.set.{key}={json.dumps(env[key])}"]
    return args


@pytest.mark.skipif(not shutil.which("codex"), reason="codex is not on PATH")
def test_codex_sets_intent(box):
    proc = subprocess.run(
        [shutil.which("codex"), "exec", "--dangerously-bypass-hook-trust", "-s", "workspace-write",
         *_codex_shell_env(box), "--skip-git-repo-check", "-C", str(box.root), "--json", FIRST],
        env=_agent_env(box), capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    logs = list((box.data / "topics" / "codex").glob("*.jsonl")) if (box.data / "topics" / "codex").exists() else []
    assert logs, f"codex wrote no topic log; stdout tail: {proc.stdout[-2000:]}"
    events = [json.loads(line) for line in logs[0].read_text().splitlines() if line.strip()]
    assert any(e["event"] == "intent" for e in events)
