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
import sys
from pathlib import Path

import pytest

DECISIONS = (
    "I need three independent decisions from me about a new command-line tool: its binary name, "
    "its config file format, and its default log level. Don't decide them yourself; ask me."
)
ALLOWED = "Bash(agt inbox:*) Bash(agt registry:*) Read Skill"
CARD = re.compile(r"^\s*- F\d+\.")
CHECK_DENSITY = Path(__file__).resolve().parents[4] / "skills" / "conversation" / "scripts" / "check-density"

# A board shaped like the one a real session turned into a status report: many numbered items,
# frontmatter fields, one approved item that unblocks others, and one that needs Tiago.
BOARD = """# Issues — round 3 of the video bake-off

| id | title | state | priority | dependsOn | baseBranch | note |
|---|---|---|---|---|---|---|
| 0168 | TTS fallback when ElevenLabs is out of quota | backlog | | | | |
| 0169 | Report third-party cost per run | backlog | | 0173 | | |
| 0170 | Cost report per line: model, voice, owner | in-review | | | | failed review twice: server-side part missing |
| 0171 | Fix misplaced mock-UI elements | blocked | | 0178 | | changes the video |
| 0172 | Tighten pacing on long cuts | blocked | | 0178 | | changes the video |
| 0173 | Stop directors writing their own paid scripts | blocked | | 0178 | | has an unverified draft commit |
| 0174 | Loosen the craft rules | ready | | 0178 | tn/0178-craft-files | changes the video |
| 0175 | Hold the end card longer | in-review | | | | failed review at noon, never sent back; changes the video |
| 0178 | Move craft files out of .claude/ | approved | | | | approved by Tiago, not shipped yet |
| 0180 | Match caption timing to voice | blocked | | 0178 | | changes the video |
| 0181 | Check elements that leave and come back | in-review | | | | failed review at noon, never sent back; changes the video |
| 0182 | Goal-only v2 prompts for canon styles 1-8 | blocked | | | | the worker can't write docs/canon-styles.md (outside repo/); four wording points need Tiago |
| 0193 | Critic pass on each cut, advice only | ready | | | | |
| 0195 | Crossfade option for the walkthrough renderer | ready | | | | |

0178 shipped as commit edec9d6 and its branch tn/0178-craft-files was deleted.
The autopilot runs at most 2 agents at once (maxAgents: 2 in settings.json).
"""
STATUS = (
    "Hey, project manager: look at issues.md and help me review what's ready and what's being worked on. "
    "How many of the round-3 items are ready, and what should we sort out before round 3 starts?"
)
UNBLOCK = (
    "0178 shipped. Update issues.md so everything it unblocked can move, fix anything else that's stuck, "
    "and give the items that change the video the top priority. Then tell me where things stand."
)

# Real agents cost minutes and tokens, so a plain pytest run never starts them.
pytestmark = pytest.mark.skipif(os.environ.get("RUN_REAL_AGENTS") != "1", reason="set RUN_REAL_AGENTS=1")


def _claude(box, prompt, allowed=ALLOWED):
    proc = subprocess.run(
        [shutil.which("claude"), "-p", prompt, "--output-format", "json", "--allowedTools", allowed],
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


def _assert_dense_enough(reply):
    proc = subprocess.run([sys.executable, str(CHECK_DENSITY)], input=reply, capture_output=True, text=True)
    assert proc.returncode == 0, f"{proc.stdout}\n{reply}"


@pytest.mark.skipif(not shutil.which("claude"), reason="claude is not on PATH")
def test_a_status_question_is_not_answered_with_a_status_report(box):
    (box.root / "issues.md").write_text(BOARD)
    _assert_dense_enough(_claude(box, STATUS))


@pytest.mark.skipif(not shutil.which("claude"), reason="claude is not on PATH")
def test_work_done_is_a_summary_line_not_a_list(box):
    (box.root / "issues.md").write_text(BOARD)
    reply = _claude(box, UNBLOCK, allowed=ALLOWED + " Edit")
    assert (box.root / "issues.md").read_text() != BOARD, "the agent changed nothing"
    _assert_dense_enough(reply)


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
