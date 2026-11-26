# Conversation skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One `conversation` skill owns how agents talk to Tiago (intent and topics, decision cards two at a time, the single reply ending, density), injected at session start on Claude, Cursor and Codex, overriding upstream maestro's conduct without editing it.

**Architecture:** The skill lives in `skills/conversation/` with a small `CORE.md` that the registry hook injects at session start through a new in-process registry command, `agt registry session-context`. The full `SKILL.md` is loaded on demand. The per-turn hook line gains an open-question count and names the new skill. The inbox's Topics page gains per-topic anchors so a link can open one branch. A `check-maestro` script fingerprints the upstream conduct sections the skill overrides. The global instruction files in tjdsneto-setup lose their density sections and gain one pointer line.

**Tech Stack:** Python 3 (registry, inbox, scripts), bash (registry hook, install.sh), pytest (unit and black-box), Postgres-backed inbox web app, Claude Code / Codex / Cursor hooks.

**Spec:** `docs/superpowers/specs/2026-11-26-conversation-skill-design.md`. Read it before any task.

**Ground rules for every task:**
- Work in the worktree `.worktrees/conversation-skill` on branch `tn/feat/conversation-skill`. Never in the main checkout: the inbox and registry are deployed from it.
- Tabs or spaces: match the file you edit. Python here uses 4 spaces.
- Tests never touch the live registry (`~/.local/share/agent-registry` or wherever `AGENT_REGISTRY_PATH` points by default), the live `agent_inbox` database, ports 8797/8798, or LaunchAgents. Registry black-box tests use the `box` fixture; inbox tests use `agent_inbox_test`.
- Registry tests: `cd modules/registry && .venv/bin/python -m pytest -q`. Inbox tests: `cd modules/inbox && .venv/bin/python -m pytest -q`. If a worktree lacks `.venv`, symlink the main checkout's: `ln -s ~/projects/agent-tools/modules/<m>/.venv modules/<m>/.venv`.
- One commit per task, message ending with `Co-Authored-By: <the model that did the work> <noreply@anthropic.com>`.

---

### Task 1: The skill files (controller writes these; prose is judgment work)

**Files:**
- Create: `skills/conversation/CORE.md`
- Create: `skills/conversation/SKILL.md`
- Create: `skills/conversation/references/known-ground.md`
- Delete: `skills/topic-awareness/` (its text moves into `SKILL.md`)

- [ ] **Step 1: Write `CORE.md`** with exactly this content (it is what every session sees; keep it under ~900 words):

````markdown
# Conversation (core)

How you talk to Tiago, in every session on every engine. This text is injected at session start. The full skill, `conversation`, has the details: load it before you fork, park, orchestrate other agents, or ask through the inbox.

This overrides any other skill's rules for how a message ends, how Tiago is asked a decision, or where decisions are kept. For example, maestro's `conduct` skill: its `Next for you:` single-action line and its `/tmp/maestro/` ledger are replaced by this; its orchestration rules still apply.

Subagents skip this: they don't talk to Tiago. A run with no human in the chat (a script's `claude -p`) skips the cards and the ending, and asks only through `agt inbox ask --script <name>` (agent-inbox, "Unattended agents").

## Intent and topic

Each prompt starts with a hook line: `Intent: … · Topic: … · N open questions.`

- Set the intent once, as soon as the first prompt shows what the session is for: `agt registry intent "<the outcome>"`. A forked session adopts first: `agt registry intent --adopt tp-…`.
- When the main line moves to a new step, open it as a topic; when it is finished, close it. Silently: `agt registry topic "<step>"`, `agt registry topic --done`.
- Drift check, only when the subject changes (not for the next step, a bug found on the way, or a retry). An on-intent side quest: ask `Side quest: <x>. Fork / park / keep here? (fork)`. Off-intent: `Off-intent: <x>. Fork as a new intent / park / keep here? (fork)`. One chat line, never through the inbox, then end the turn. A bare ok or go means fork. Load the full skill to fork or park.

## Density

- The body holds at most about three things that need his judgment, most consequential first, in short prose. No recap in the body; the recap is the ending's Summary.
- Say where you might be wrong: mark which points are confident and which are shaky.
- Long output (an analysis, review, plan, comparison) goes to a file in `./tmp/`; give the link and a three-line gist.
- Altitude: lead with consequence and decision, not mechanism. Introduce fewer technical objects and explain each one; give anything outside his stack (he is a full-stack web developer) half a sentence of plain-English gloss on first use. What he already knows: `~/projects/agent-tools/skills/conversation/references/known-ground.md`. When he says "I'm familiar with X", add X there and say so in one line.
- Never cut for brevity: what failed (the actual output), what was skipped and why, what you're unsure of, what surprised you.
- A question gets an assessment, a directive gets executed. "Your call" means decide, say why in a sentence, and proceed.
- Keywords he may use: `brief` = reassert this section hard; `deep` = full reasoning in chat this time; `mechanism` = drop to flag, API or line level; `eli5` = start from the concept.

## Decisions: self-contained cards, two at a time

Every decision you ask is a card that reads correctly with no scrollback. It never says "see above".

```
F1. *Intent › Topic.* <The question?> <Why it matters, one or two sentences; spell ids out: "PR #92, which fixes …">. Answer `token` (a) or `token` (b). Recommended: `token`, because <one clause>. Next: <what you do with the answer>. <inbox link>
```

- Each decision is also an inbox question (agent-inbox `ask`), with the long form in its summary and detail: what happened, why it matters, the options, the recommendation, what happens next either way. The card in chat is the short form. When he answers in chat, record it: `agt inbox answer ib-… --value <token> --via chat`.
- At most **two** cards per reply. Merge related decisions first. Any beyond two are asked in the inbox only, and the ending says `+N more waiting under this topic: <inbox url>/topics#<topic id>`. After he answers, bring up the next waiting one.
- A decision you can make yourself is not asked: make it, say so in one line, and post it to the inbox as "decided, veto here".
- If the inbox is down, put the full card in chat, and list the extra cards' questions instead of the link.
- Answers: a lone letter maps to its token; `N: <change>` overrides item N of a card that bundles numbered recommendations. Name the mapped action as you act on it (`k → taking all 8`).

## How a reply ends

```
---
**Summary:** two or three lines: what this turn settled, what changed, where things stand.

**Next for you:**
- F1. <card>
- F2. <card>
+N more waiting under this topic: <link>

**To hand off / do later:**
- F3. <worth doing, not now: park it, queue it in Tray, or spin it out>
```

- F-numbers run continuously across both groups, so he can answer "f1 - a / f3 - do it". Within a card, option aliases are letters.
- Nothing owed: `**Next for you:** nothing`. A trivial exchange skips the ending.
- Any skill's own end-of-turn list (next steps, suggestions) is folded into this ending, never printed separately.
````

- [ ] **Step 2: Write `SKILL.md`.** Frontmatter:

```yaml
---
name: conversation
description: How to talk to Tiago, in every session. Its core (intent and topics, decision cards two at a time, the reply ending, density) is injected at session start. Load this full skill before forking or parking a thread, asking through the inbox, orchestrating other agents, or when a hook line names the conversation drift check.
---
```

Body sections, in this order:
1. `# conversation` — one paragraph: CORE.md is the always-on part and is injected at session start; if it is not in context (an engine that couldn't inject it), read `CORE.md` in this skill's directory now. Everything below is the detail CORE points to.
2. `## Intent and topics in detail` — move verbatim from `skills/topic-awareness/SKILL.md`: the hook-line examples, "Subagents don't use this skill…", the session-identity paragraph, "Set the intent once", "Name the topic you're on" (including the `open_questions` paragraph), the drift-check table and its rules, "When the intent is done", "Look around". Change every "topic-awareness" to "conversation".
3. `## Forking and parking` — move verbatim from topic-awareness's "Then do what he chose" list (Fork with the brief example, Park, Keep here).
4. `## Asking through the inbox` — the long form of a card, adapted from maestro's ledger section shape: `summary` = what happened and why it matters, in plain language for someone who has never seen the repo; `detail` = the options as the exact tokens (with aliases), the recommendation with one sentence of why, and what happens next either way. The `control` is a `choice` whose option ids are the card's tokens. Then: the two-in-chat rule; record chat answers with `--via chat`; overflow decisions go inbox-only with the `+N more waiting` line; resolve stale questions (`agt inbox withdraw`) when the topic closes with `open_questions`.
5. `## When you orchestrate other agents` — maestro's `conduct` owns orchestration (boss/doer, work orders, fresh agent per phase, verify before relaying). Its human-facing rules are replaced by this skill. Local additions, from the spec section 6: approve before spawning; every worker brief carries the dev-env claim rule (`dev-env claim <main-dir> --who <id> --pid $$` before tests, release after); check what's running with `agt sessions` and the Topics tab; close out at wrap (close finished workers' topics, name carry-overs in the Summary).
6. `## Upstream maestro` — conduct is Justin Sternberg's plugin (`maestro@jtsternberg`) and is never edited here. `scripts/check-maestro` compares its human-facing parts with `references/maestro-baseline/`; when it fails, reread the diff, decide whether the override still holds or something is worth adopting, and refresh the baseline (`scripts/check-maestro --update`) in a commit.

- [ ] **Step 3: Write `references/known-ground.md`.** Move the "Known ground, don't over-explain" list from `~/projects/tjdsneto-setup/ai/instructions/claude/CLAUDE.md` (currently one entry: SSH day-to-day, with its "not known in depth" note) under a heading `# Known ground` and one sentence: "Tiago knows these well enough that glossing them wastes his time. Add an entry when he says he's familiar with something."

- [ ] **Step 4: Delete topic-awareness**

```bash
git rm -rq skills/topic-awareness
```

- [ ] **Step 5: Check the move dropped nothing.** For each `##` section of the old `skills/topic-awareness/SKILL.md` (`git show HEAD:skills/topic-awareness/SKILL.md`), grep its first sentence in `skills/conversation/SKILL.md` or `CORE.md`. Then read both new files end to end. `wc -w skills/conversation/CORE.md` must be ≤ 900.

- [ ] **Step 6: Commit**

```bash
git add skills/conversation && git commit -m "feat(skills): conversation skill replaces topic-awareness"
```

---

### Task 2: check-maestro and its baseline

**Files:**
- Create: `skills/conversation/scripts/check-maestro` (executable, Python 3, stdlib only)
- Create: `skills/conversation/references/maestro-baseline/the-human.md`
- Create: `skills/conversation/references/maestro-baseline/decisions-ledger.md`
- Create: `skills/conversation/tests/test_check_maestro.py`

Behaviour:
- Upstream dir: `$MAESTRO_CONDUCT_DIR`, default `~/.claude/plugins/marketplaces/jtsternberg/plugins/maestro/skills/conduct`.
- Watched parts: (1) the section of `SKILL.md` from the line `## The human` up to (not including) the next line starting with `## `; (2) the whole of `references/decisions-ledger.md`.
- `check-maestro`: compare each watched part with its baseline file. All equal → print `maestro: the parts conversation overrides are unchanged` and exit 0. Any differ → print a unified diff per changed part (baseline first) and exit 1. Upstream missing (no `SKILL.md`, or no `## The human` heading) → print `maestro: upstream conduct not found at <dir>` and exit 2.
- `check-maestro --update`: write the current watched parts to the baseline files, print what was written, exit 0 (exit 2 if upstream missing).
- Baseline dir: `references/maestro-baseline/` next to the script's parent (resolve the script path through symlinks).

- [ ] **Step 1: Write the failing tests** in `skills/conversation/tests/test_check_maestro.py`: a fixture builds a fake upstream dir in `tmp_path` (`SKILL.md` with a `## The human` section between two other sections, plus `references/decisions-ledger.md`) and a copy of the script's skill dir layout with an empty baseline dir; tests run the script with `subprocess` and `MAESTRO_CONDUCT_DIR` set:
  - `--update` then a check → exit 0;
  - edit a line inside `## The human` → exit 1 and the diff names the edited line;
  - edit a line outside `## The human` → exit 0 (only the watched part counts);
  - edit the ledger → exit 1;
  - upstream dir missing → exit 2.
- [ ] **Step 2: Run them, expect failures** (`python3 -m pytest skills/conversation/tests -q` from the repo root, using the registry venv's python if pytest isn't global: `modules/registry/.venv/bin/python -m pytest skills/conversation/tests -q`).
- [ ] **Step 3: Implement the script.**
- [ ] **Step 4: Run the tests, expect pass.**
- [ ] **Step 5: Create the real baseline**: `skills/conversation/scripts/check-maestro --update`, then `skills/conversation/scripts/check-maestro` → exit 0. Read both baseline files.
- [ ] **Step 6: Commit** (`feat(conversation): check-maestro fingerprints the conduct parts it overrides`).

---

### Task 3: Registry — `session-context`, the new hook line, the open-question count

**Files:**
- Modify: `modules/registry/src/agent_registry/topics.py` (`context_line`)
- Modify: `modules/registry/src/agent_registry/topic_cli.py` (add `session-context`)
- Create: `modules/registry/src/agent_registry/conversation.py`
- Test: `modules/registry/tests/test_topics.py`, `modules/registry/tests/test_topic_cli.py`, new `modules/registry/tests/test_conversation.py`

Behaviour:
- `context_line` ends with `If this prompt changes the subject, run the conversation drift check.` instead of `topic-awareness`.
- When the session has an intent and a current topic, and `open_questions(topic_id)` is non-empty, the line reads `Intent: X (tp-a) · Topic: Y (tp-b) · 2 open questions. If this prompt …` (`1 open question` singular). No count when zero, when there is no topic, or when counting raises (`OSError`, `ValueError`): the count is best effort and must never break the line.
- `conversation.core_text() -> str | None`: reads `$AGENT_REGISTRY_CONVERSATION_CORE` if set, else `<repo>/skills/conversation/CORE.md` where `<repo>` is `Path(__file__).resolve().parents[4]`. Returns the text stripped, or `None` when the file is missing, unreadable or not UTF-8.
- `agt registry session-context --type T --session-id S` prints `core_text()` followed by a blank line and then the `context_line`; if `core_text()` is `None`, only the `context_line`. In-process like the other topic commands (add it to `topic_cli.COMMANDS`).

- [ ] **Step 1: Failing tests.**
  - `test_topics.py::test_current_and_context_line`: update the expected suffix to `conversation drift check.`
  - New `test_context_line_counts_open_questions`: intent + topic, then `topics.add_note(...)` an `asked` note for `ib-1` and `ib-2` on the topic (use the same helper the notes tests use in `tests/test_topic_notes.py`), assert `· 2 open questions.` in the line; add an `answered` note for `ib-2`, assert `· 1 open question.`; answer `ib-1`, assert no `open question` text.
  - New `test_context_line_survives_count_failure`: monkeypatch `topics.open_questions` to raise `OSError`, assert the line is the plain `Intent: … · Topic: ….` form.
  - `test_conversation.py`: `core_text` reads the env override; returns `None` for a missing file and for invalid UTF-8 bytes; the default path resolves to `skills/conversation/CORE.md` in this repo (assert the path exists).
  - `test_topic_cli.py`: `session-context` prints the core text then a blank line then the context line; with `AGENT_REGISTRY_CONVERSATION_CORE` pointing at a missing file it prints only the context line.
- [ ] **Step 2: Run, expect failures.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Full registry suite passes** (`.venv/bin/python -m pytest -q`, black-box excluded by default if the suite is configured so; otherwise run `tests --ignore=tests/blackbox/test_topics_agent.py`).
- [ ] **Step 5: Update `modules/registry/README.md`**: "The rules agents follow live in the `topic-awareness` skill" → "the `conversation` skill"; document `session-context` next to `topic-context` in one sentence.
- [ ] **Step 6: Commit** (`feat(registry): session-context injects the conversation core; hook line counts open questions`).

---

### Task 4: The hook injects the core on all three engines

**Files:**
- Modify: `modules/registry/plugin/scripts/registry-hook`
- Modify: `modules/registry/plugin/.claude-plugin/plugin.json` (version `0.3.0` → `0.4.0`)
- Test: `modules/registry/tests/blackbox/test_topics_hook.py`

Behaviour:
- New helper `session_context()` runs `"$BIN" session-context --type "$HOST" --session-id "$SESSION_ID" 2>/dev/null || true`.
- **Claude `ensure`:** the existing `emit_ensure_context` third argument becomes `$(session_context)` instead of `$(topic_line)`.
- **Cursor `ensure`:** `CURSOR_CONTEXT=$(session_context)`, except when `HOOK_EVENT` is `subagentStart`, where `CURSOR_CONTEXT` stays empty (prints `{}`).
- **Codex `ensure`:** after a successful `ensure`, print `{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": <session_context>}}` when the text is non-empty (same JSON shape as the Claude prompt output; build it with python3 like `emit_prompt_context`).
- Every failure path still fails open: a missing `CORE.md` gives the context line alone; a failing `session-context` gives what each engine printed before this change.
- `ping` (per-turn) is unchanged except that its line now comes from the updated `topic-context`.

- [ ] **Step 1: Failing black-box tests** in `test_topics_hook.py` (the `box` fixture; add `AGENT_REGISTRY_CONVERSATION_CORE` to `box.env` pointing at a temp file containing `CORE MARKER 7f3a`):
  - Claude `ensure` additionalContext contains `CORE MARKER 7f3a` and `No intent set for this session.`;
  - Cursor `sessionStart` `additional_context` contains the marker; Cursor `subagentStart` prints `{}`;
  - Codex `ensure` prints `hookSpecificOutput.additionalContext` containing the marker;
  - with the env pointing at a missing file, Claude `ensure` still contains `No intent set` and not the marker;
  - update `test_claude_prompt_with_intent_and_topic` to expect `run the conversation drift check.`;
  - the existing macOS `/bin/bash` test still passes.
- [ ] **Step 2: Run, expect failures** (`.venv/bin/python -m pytest tests/blackbox/test_topics_hook.py -q`).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the whole black-box dir except the real-agent file, expect pass.**
- [ ] **Step 5: Bump the plugin version** to `0.4.0`.
- [ ] **Step 6: Commit** (`feat(registry-hook): inject the conversation core at session start on every engine`).

---

### Task 5: Topics page anchors

**Files:**
- Modify: `modules/inbox/src/agent_inbox/web.py` (`_tree_node`, `_SCRIPT`)
- Test: `modules/inbox/tests/test_topics_page.py`

Behaviour:
- Each `<li class="node …">` gets `id="<topic id>"` the first time that id is rendered on the page (a forked topic can appear twice; ids must stay unique). Pass a `seen: set[str]` through the recursion.
- Script, on load: if `location.hash` names an element inside `.tree`, open every `<details>` from that node up to the root (`el.closest("details")` loop), then `scrollIntoView({block: "start"})`. This must not set `dirty`: live reload keeps working. A hash that matches nothing does nothing.
- Ids are already validated topic ids (`tp-` + 4 chars from the registry alphabet); still pass them through `_esc`.

- [ ] **Step 1: Failing tests**: the page HTML contains `id="tp-…"` once per distinct topic; a tree where one id appears twice renders it once; the script text contains the hash-opening code (assert on a distinctive substring such as `location.hash`).
- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Inbox suite passes.**
- [ ] **Step 5: Visual check** with `modules/inbox/tests/visual/shots.sh` (it refuses the live ports and DB): open `/topics#<a nested topic id>` at 390 px; the screenshot shows that branch open and scrolled into view. Look at the screenshot.
- [ ] **Step 6: Commit** (`feat(inbox): Topics links can open one topic's branch`).

---

### Task 6: install.sh and agent-inbox

**Files:**
- Modify: `install.sh`
- Modify: `skills/agent-inbox/SKILL.md`

- [ ] **Step 1: install.sh.** Replace the `link_skill topic-awareness …` line with `link_skill conversation "$HOME/.claude/skills" "$HOME/.cursor/skills" "$HOME/.codex/skills"` (comment: every engine follows it). `link_skill` already bundles `references` and `scripts`. Before it, remove stale topic-awareness links only when they point into this repo:

```bash
for root in "$HOME/.claude/skills" "$HOME/.cursor/skills" "$HOME/.codex/skills"; do
  link="$root/topic-awareness/SKILL.md"
  if [ -L "$link" ] && [ "$(readlink "$link")" = "$ROOT/skills/topic-awareness/SKILL.md" ]; then
    rm -f "$link" && rmdir "$root/topic-awareness" 2>/dev/null
    echo "removed $root/topic-awareness (replaced by conversation)"
  fi
done
```

After the maestro block, warn (never fail) on upstream drift:

```bash
"$ROOT/skills/conversation/scripts/check-maestro" >/dev/null 2>&1
case $? in
  1) echo "warning: maestro's conduct changed the parts conversation overrides; run skills/conversation/scripts/check-maestro" ;;
  2) echo "warning: maestro's conduct not found; conversation's override has nothing to check" ;;
esac
```

- [ ] **Step 2: agent-inbox.** In "Ask in both places", step 2: the chat side is the decision card from the `conversation` skill (its short form, with the inbox link), not the current three-line example; keep the rule against blocking question tools. In "Write for a phone", add one sentence: the summary and detail are the card's long form (what happened, why it matters, the options, the recommendation, what happens next), per `conversation`. Nothing else changes.
- [ ] **Step 3: Run `./install.sh` in the worktree? No** — install links point at whichever checkout runs it, so it runs from the main checkout after merge (Task 9). Instead: `bash -n install.sh`.
- [ ] **Step 4: Commit** (`feat: install links the conversation skill; agent-inbox asks with its cards`).

---

### Task 7: Global instructions (tjdsneto-setup, master)

**Files** (repo `~/projects/tjdsneto-setup`, commit straight to master, never a worktree there):
- Modify: `ai/instructions/claude/CLAUDE.md`
- Modify: `ai/instructions/codex/AGENTS.md`
- Modify: `ai/instructions/cursor/user-rules.md`

- [ ] **Step 1: Record before.** `wc -w` the three files; save the counts for Task 9's measurement.
- [ ] **Step 2: Claude file.** Remove `## Response density` through the end of `### Technical altitude` (everything before `## Review before handoff`), except the paragraph that begins `**Don't claim a property you haven't tested.**`, which becomes its own section `## Don't claim untested properties`, unchanged. In place of the removed text, add:

```markdown
## How you talk to me

The `conversation` skill owns it: intent and topics, decisions (two at a time, each with its own context), how a reply ends, density and technical altitude. The agent-tools session-start hook injects its core into every session; if it is not in context, load the `conversation` skill before replying.
```

Also replace "Calibrate as we go… edit `ai/instructions/claude/CLAUDE.md`, run `./install.sh`" if any of it survived: calibration now edits `~/projects/agent-tools/skills/conversation/references/known-ground.md`.
- [ ] **Step 3: Codex and Cursor files.** Same: remove their Response density and Technical altitude text, keep the untested-claims paragraph as its own section if present (add it to Cursor's file from the Claude version if Cursor lacks it), and add the same "How you talk to me" section.
- [ ] **Step 4: Nothing dropped.** For each bullet and paragraph removed, find the rule in `skills/conversation/CORE.md` or `SKILL.md` (grep a distinctive phrase, or read). List any rule not carried over; add it to `CORE.md` (in the agent-tools worktree, amend Task 1's area with a new commit) or state why it is intentionally dropped.
- [ ] **Step 5: Read all three files end to end.**
- [ ] **Step 6: Commit in tjdsneto-setup**, one commit for the three files (`docs(instructions): how agents talk to me moves to the conversation skill`). The files are symlinked, so this is live at once: do it only after Task 9's deploy order says so (it is listed here for its content; Task 9 says when).

---

### Task 8: Real-agent checks

**Files:**
- Create: `modules/registry/tests/blackbox/test_conversation_agent.py`
- Modify: `modules/registry/tests/blackbox/MANUAL.md` (record results)

All run explicitly, like `test_topics_agent.py` (skip when the binary is missing), with the `box` env plus `AGENT_REGISTRY_FORK_BACKEND=none`, and with `AGENT_INBOX_*` pointing at the test DB or the inbox disabled (read `modules/inbox/tests/blackbox/conftest.py` for how the inbox black-box suite isolates itself, and reuse it). Never the live registry or inbox.

- [ ] **Step 1: Codex injection.** `codex exec` (same flags as `test_codex_sets_intent`) with `AGENT_REGISTRY_CONVERSATION_CORE` pointing at a file whose text includes `If asked for the session marker, reply with exactly: ORCHID-5521.`; prompt: `What is the session marker?`. Assert `ORCHID-5521` in the final message. If this fails because Codex ignores SessionStart `additionalContext`, record that in MANUAL.md, mark the test `xfail(strict=False)` with the reason, and keep Codex's pointer line in its global file (Task 7 already adds it).
- [ ] **Step 2: Claude card structure.** `claude -p` with the real `CORE.md`, prompt: `I need you to make three independent decisions with me about naming a new CLI: the binary name, the config file format, and the default log level. Don't decide them yourself; ask me.` Assert on the reply: it contains `**Next for you:**`; at most two lines matching `^- F\d+\.`; a line matching `more waiting`; each card line contains `›` and at least one backticked token followed by `(x)`. Wording varies; assert structure only.
- [ ] **Step 3: Override holds with conduct loaded.** Same as Step 2 but the prompt starts with `Load the maestro conduct skill first, then:`. Assert the same structure, and that the reply does not end with a single line starting `Next for you:` outside the `**Next for you:**` group.
- [ ] **Step 4: Run them**: `.venv/bin/python -m pytest tests/blackbox/test_conversation_agent.py -v` (needs Task 9's install for skill links; if run before deploy, point `AGENT_REGISTRY_CONVERSATION_CORE` at the worktree's `CORE.md`).
- [ ] **Step 5: Record results in MANUAL.md** with the date and actual outcomes; commit (`test(conversation): real-agent checks for injection, cards and the maestro override`).

---

### Task 9: Merge and deploy (controller, from the main checkout)

- [ ] **Step 1:** Full registry and inbox suites pass on the branch; `check-maestro` exits 0.
- [ ] **Step 2:** Merge `tn/feat/conversation-skill` into main with `--no-ff` from the main checkout. No DB migration in this work, so no backup is needed; confirm by checking that no `db.py` or `schema.sql` change is in the diff.
- [ ] **Step 3:** `./install.sh` from the main checkout. Confirm `~/.claude/skills/conversation/SKILL.md`, `~/.cursor/skills/conversation/SKILL.md` and `~/.codex/skills/conversation/SKILL.md` link into the repo and that no `topic-awareness` link remains.
- [ ] **Step 4:** Claude plugin: `claude plugin marketplace update agent-registry && claude plugin update agent-registry@agent-registry`; confirm the cache holds 0.4.0.
- [ ] **Step 5:** Restart the inbox LaunchAgent (`launchctl kickstart -k gui/$(id -u)/com.tjdsneto.agent-inbox`), check `/topics` returns 200 and contains `id="tp-`.
- [ ] **Step 6:** Now commit Task 7 in tjdsneto-setup (the global files go live the moment they're saved, so they change only after the hook injects the core).
- [ ] **Step 7:** Measure: `wc -w` of the three global files now vs Task 7 Step 1, and `wc -w skills/conversation/CORE.md`. Report the net change.
- [ ] **Step 8:** Run Task 8's real-agent checks against the deployed setup.
- [ ] **Step 9:** Hermes: `cd ~/projects/cockpit && scripts/hermes skills-sync` (preview), then `--apply`; move any orphaned `topic-awareness` imports under `~/.hermes/skills/*-imports/` to `cockpit/tmp/hermes-orphans-2026-11-26/`; pull the snapshot and commit only the conversation / topic-awareness paths, restoring the rest (cockpit#2).
- [ ] **Step 10:** Verify in a fresh real Claude session (not this one) that the session-start context contains the core's first line, and remove the worktree and branch.
