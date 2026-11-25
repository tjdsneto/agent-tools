# Topic awareness — manual checks

What a test can't see. Run after any change to forking or the hook. Record the date and the result of each check at the bottom.

## Setup

- `./install.sh` from the repo root.
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
