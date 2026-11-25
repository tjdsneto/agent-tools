---
name: claude-session-mngr
description: Report on Claude Code sessions touched today (running — including cmux-delegated tabs — or already closed), with per-session and daily token totals. Use when Tiago asks "what sessions are running", "how many tokens today", "session report", "what did I run today", or wants visibility into Claude Code session/token sprawl.
user-invocable: true
argument-hint: "[--json]"
---

# claude-session-mngr

Read-only report of every Claude Code session touched today. Run:

```bash
agt sessions report
```

or, for machine-readable output:

```bash
agt sessions report --json
```

The legacy `session-report` shim still works.

## What it shows

One row per session with any activity today (regardless of whether the process is still
running): session id (short), running/closed status, cmux workspace name (if it's running
inside a cmux tab — blank for plain-terminal or already-closed sessions), per-category token
counts (input / cache-write / cache-read / output), and last-active time. A totals footer
gives the daily grand total per token category plus session/running counts.

## How it works

- **"Today"** means any transcript line timestamped since local midnight — a session that
  started yesterday and continued into today still counts, but only today's tokens are summed.
- **cmux correlation** is a soft dependency: if `cmux` isn't running or the call fails, every
  session just shows with no workspace label (falls back to "plain terminal"). Never errors.
- **Includes subagent/Task-tool usage** — a session's token total includes any subagents it
  delegated to (`<session-id>/subagents/*.jsonl`), folded into the parent session's row rather
  than shown as separate rows.
- **Never mutates anything** — pure read of `~/.claude/projects/*/*.jsonl` and its `subagents/`
  transcripts, `ps`, `lsof`, and `cmux tree --all --json`.
- Sessions matched only by heuristic (no --session-id/--resume in their process — a manually-typed
  claude, not a cmux-delegated one) are shown with a ~ prefix, same convention as active-sessions.

## Related

- `session-awareness` skill (`agt sessions active`/`list`) is a separate, pre-existing
  tool with some overlap (live-process listing). Its fate (retire/keep/merge) is undecided —
  see `~/projects/agent-tools/modules/sessions/docs/superpowers/specs/2026-07-28-claude-session-mngr-design.md`.
- Implementation lives in `~/projects/agent-tools/modules/sessions/mngr-scripts/` (`_sessions.py`
  is the tested library; `session-report` is the thin CLI). Tests:
  `python3 ~/projects/agent-tools/modules/sessions/mngr-scripts/tests/test_sessions.py -v`.
