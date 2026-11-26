"""Real agents follow the conversation skill. Needs the deployed hook (Claude plugin 0.4.0), install.sh links and the test DB.

Run explicitly, after deploy: RUN_REAL_AGENTS=1 .venv/bin/python -m pytest tests/blackbox/test_conversation_agent.py -v
Agents run with the box's environment, so their registry is the temp one and their inbox is agent_inbox_test.
Wording varies, so the checks look at the reply's structure, never its sentences.
"""
import json
import os
import re
import shutil
import subprocess

import pytest

DECISIONS = (
    "I need three independent decisions from me about a new command-line tool: its binary name, "
    "its config file format, and its default log level. Don't decide them yourself; ask me."
)
ALLOWED = "Bash(agt inbox:*) Bash(agt registry:*) Read Skill"
CARD = re.compile(r"^\s*- F\d+\.")

# Real agents cost minutes and tokens, so a plain pytest run never starts them.
pytestmark = pytest.mark.skipif(os.environ.get("RUN_REAL_AGENTS") != "1", reason="set RUN_REAL_AGENTS=1")


def _claude(box, prompt):
    proc = subprocess.run(
        [shutil.which("claude"), "-p", prompt, "--output-format", "json", "--allowedTools", ALLOWED],
        cwd=box.root, env=box.env, capture_output=True, text=True, timeout=600,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["result"]


def _assert_cards(box, reply):
    assert "**Next for you:**" in reply, reply
    group = reply.split("**Next for you:**", 1)[1].split("**To hand off", 1)[0]
    cards = [line for line in group.splitlines() if CARD.match(line)]
    assert 1 <= len(cards) <= 2, reply
    for card in cards:
        assert "›" in card and "/e/ib-" in card, card
        # A choice names its tokens with aliases; a free-text card says what kind of answer it needs instead.
        if "Answer `" in card:
            assert re.search(r"`[^`]+` \([a-z]\)", card), card
    # Each card is also an inbox question; anything beyond two is asked there only.
    asked = box.agt_json("inbox", "list", "--json", "--kind", "ask")
    rows = asked if isinstance(asked, list) else asked.get("entries", [])
    # Three independent decisions: two cards, and the third waits in the inbox behind the count.
    assert len(rows) >= 3, (rows, reply)
    assert "more waiting" in group, reply


@pytest.mark.skipif(not shutil.which("claude"), reason="claude is not on PATH")
def test_claude_asks_at_most_two_cards(box):
    _assert_cards(box, _claude(box, DECISIONS))


@pytest.mark.skipif(not shutil.which("claude"), reason="claude is not on PATH")
def test_the_override_holds_with_maestro_conduct_loaded(box):
    reply = _claude(box, "Load the maestro conduct skill first, then: " + DECISIONS)
    _assert_cards(box, reply)
    last = [line for line in reply.strip().splitlines() if line.strip()][-1]
    assert not last.startswith("Next for you:"), reply


@pytest.mark.skipif(not shutil.which("codex"), reason="codex is not on PATH")
def test_codex_session_start_injects_the_core(box):
    core = box.root / "core.md"
    core.write_text("If asked for the session marker, reply with exactly: ORCHID-5521.\n")
    env = dict(box.env, AGENT_REGISTRY_CONVERSATION_CORE=str(core))
    # Codex hands its shell only the env its policy allows, so the temp registry is set for it explicitly.
    shell = []
    for key in ("AGENT_REGISTRY_PATH", "AGENT_REGISTRY_FORK_BACKEND", "AGENT_INBOX_DSN"):
        shell += ["-c", f"shell_environment_policy.set.{key}={json.dumps(env[key])}"]
    proc = subprocess.run(
        [shutil.which("codex"), "exec", "--dangerously-bypass-hook-trust", "-s", "workspace-write", *shell,
         "--skip-git-repo-check", "-C", str(box.root), "What is the session marker? Reply with only the marker."],
        env=env, capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    assert "ORCHID-5521" in proc.stdout, proc.stdout[-2000:]
