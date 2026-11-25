---
name: check-usage
description: Check Claude Code usage against the account's rate-limit windows — the rolling 5-hour session window and the weekly model-family window. Use when Tiago asks about his usage, token usage, rate limit, how close he is to a limit, or says "check my usage" / "/check-usage".
user-invocable: true
---

# Check usage

Runs Claude Code's own `/usage` meta-command and reports the two numbers that matter — no
external API, no auth setup, just the CLI's own account-level usage tracking.

## What to do

1. Run `claude -p "/usage"` via Bash.
2. Run `date` to get the current local time, so you can turn the absolute reset time into
   a human-friendly countdown (e.g. "resets in 1h 20m").
3. Report back just the two headline lines, plainly:
   - Current session (the rolling 5-hour window): X% used, resets in the countdown form
     (mention the absolute time too, e.g. "in 1h 20m, at 1:19pm").
   - Current week (the model-family window, e.g. "Fable"): Y% used.
4. Only show the fuller breakdown (top skills/subagents/plugins, parallel-session stats)
   if Tiago asks for more detail — it's noisy for a quick check.

## Flagging high usage

If the 5-hour session window is at or above **85%**, say so plainly and suggest wrapping
up or being deliberate about what's queued next — don't just report the number quietly.
Below that threshold, a plain report is enough.

## Silent mode (used by the personas' `start` flows)

When invoked as a background check rather than an explicit request (e.g. from a persona's
`start` mode), run the same command but only surface the 5-hour session number if it's
≥85% — otherwise say nothing about usage at all.

## Related

- `claude-budget check` reads the same two windows for scripts (`agt budget`), and session-waker gates its wakes on them. Each `claude -p "/usage"` call leaves a small transcript in `~/.claude/projects/-/`.
