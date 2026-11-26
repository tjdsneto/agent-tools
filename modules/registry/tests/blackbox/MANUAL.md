# Topic awareness — manual checks

What a test can't see. Run after any change to forking or the hook. Record the date and the result of each check at the bottom.

## Setup

- `./install.sh`, run from the main checkout (`~/projects/agent-tools`) after merging, never from a worktree.
- `claude plugin update agent-registry@agent-registry`, then restart Claude Code. Confirm the cache matches the repo: `diff ~/.claude/plugins/cache/agent-registry/agent-registry/*/scripts/registry-hook modules/registry/plugin/scripts/registry-hook` prints nothing.

## Checks

1. **Reminder in Claude Code (Cursor extension).** Open a new Claude tab and send any prompt. The agent sets an intent, and `agt registry topics` from a terminal shows it.
2. **Drift ask.** In that session, send something off-intent. The agent asks fork / park / keep in one line and doesn't start on it.
3. **Cursor fork.** Answer "fork". A new Claude tab opens **in the same project window**, with the prompt filled in and not sent. Press Enter. The child runs `agt registry intent --adopt …`, and `agt registry topics --tree` shows it under the parent.
4. **Cursor fork with two windows open.** Focus another project's window, then trigger a fork from the first session. The tab must open in the first session's project. Record which window got it.
5. **Herdr fork.** Inside a Herdr pane (`HERDR_ENV=1`), start Claude Code and set an intent, then fork. A new pane opens on the right, the agent starts, and the prompt is sent without anything from you.
6. **Codex reminder.** In Codex, send a prompt. The first turn mentions the intent line, or sets one.
7. **Cursor agent.** In Cursor's own agent, start a chat. The session-start context includes the "No intent set" line (known to be unreliable in Cursor; record what happened).

## Results

| Date | Check | Result |
|---|---|---|
| 2026-11-25 | 1. Reminder in Claude Code | Pass. After the plugin update, the hook line appeared in an already-running session without a restart; another live session set an intent and closed a topic on its own. |
| 2026-11-25 | 2. Drift ask | Pass, via `test_topics_agent.py` (claude, 3/3 runs): off-intent prompt got a fork / park / keep ask and no topic, fork or park event. |
| 2026-11-25 | 3. Cursor fork | Pass. A Claude Code tab opened in the same agent-tools window as the parent, prompt filled and not sent; after Enter the child adopted tp-zkzb and `topics --tree` showed it under the parent (parent `forked`, child `intent`). Only one window was focused, so check 4 is still open. |
| 2026-11-25 | 6. Codex reminder | Pass, via `test_topics_agent.py` (codex, 1 run): Codex set an intent with no mention of the skill in its prompt. |

## Conversation skill (spec 4) — real-agent runs, 2026-11-26

`RUN_REAL_AGENTS=1 modules/inbox/.venv/bin/python -m pytest modules/inbox/tests/blackbox/test_conversation_agent.py -v`, against the deployed hook (Claude plugin 0.4.0) and `agent_inbox_test`:

- **Codex accepts SessionStart `additionalContext`:** passed. The injected marker came back from `codex exec`, so Codex gets the core like Claude and Cursor.
- **Claude, three decisions:** passed on the second run. The first run failed on the test, not the agent: it wrote a correct free-text card with no option tokens, which the check wrongly required. The check now asks for tokens only on choice cards.
- **Claude with maestro's conduct loaded:** passed. The reply ended the conversation way, not with conduct's single `Next for you:` line.
- Each run's inbox questions went to `agent_inbox_test` only (the first run's `ib-ppcm` is absent from the live inbox).
