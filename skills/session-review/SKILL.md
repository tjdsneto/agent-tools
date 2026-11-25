---
name: session-review
description: Analyse a Claude Code session transcript for tool usage and context injection events. Surfaces redundant reads, excessive tool calls, and bloated context injections. Works on the current session or any archived session.
user-invocable: true
argument-hint: "[--timeline] [session-id-or-keyword]"
---

# Session Review

Analyse a transcript to spot excessive tool calls, redundant reads, and context injection bloat.

## Script

```
agt sessions review <transcript.jsonl>
agt sessions review <transcript.jsonl> --timeline
```

## Current session

The current transcript path is always available in the `system-reminder` context injected at the top of each turn:

```
The transcript for this session is stored at: /Users/tjdsneto/.claude/projects/.../<session-id>.jsonl
```

Extract that path and run:

```bash
agt sessions review <transcript-path>
```

## Past session

Use `list-sessions` to find the path by date or title keyword:

```bash
agt sessions list | grep <keyword>
```

Then pass the `.jsonl` path to the script.

## Interpreting output

After running the script, read the output and:

1. **WARNINGS** — surface each one with a one-line suggestion:
   - "Read `.claude/settings.json` called 3x — assign its content to a variable on first read"
   - "Hook `rename-claude-sessions` exited 1 — check the script for errors"

2. **TOOL USAGE** — if Bash dominates (>50% of calls), check BASH COMMANDS for repeated patterns that could be collapsed into a single invocation.

3. **READ FILES** — any ⚠ file is a candidate for caching in a variable instead of re-reading.

4. **CONTEXT INJECTIONS** — high `hook_success` counts are normal; high `task_reminder` counts (>5) mean TodoWrite/TaskUpdate are firing frequently.

Do not attempt to fix inefficiencies automatically — only report and suggest.
