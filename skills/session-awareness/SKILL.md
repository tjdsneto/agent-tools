---
name: session-awareness
description: List active Claude Code sessions — what's running, where, and what it's working on
user-invocable: true
argument-hint: "[--all]"
---

# Session Awareness

Run `active-sessions` (shim) or `agt sessions active` to show currently running Claude Code sessions.

## Default (recently active)

```bash
active-sessions
# equiv: agt sessions active
```

Shows sessions whose transcript was modified in the last 30 minutes — these are the sessions you're actually working in. Idle Cursor tabs are hidden.

## All processes

```bash
active-sessions --all
# equiv: agt sessions active --all
```

Shows every running `claude` process — one per open Cursor tab, regardless of when it was last used.

## Output columns

| Column | Meaning |
|--------|---------|
| PID | OS process ID |
| Last active | When the transcript was last written to |
| Session | First 8 chars of the session UUID (`~` = best-guess, not `--resume`) |
| CWD | Working directory the session was started in |
| ▸ | Custom title (if `rename-claude-sessions` has run) or first user message |

## How it works

Each Claude Code session is an OS process. Sessions opened via `--resume` carry their session ID in the process args, giving a definite match. New sessions (no `--resume`) are matched to the most recently modified transcript in the corresponding `~/.claude/projects/<encoded-cwd>/` directory.

## Renaming a session

To manually rename any session by ID:

```bash
rename-session <session-id> "New Title"
# equiv: agt sessions rename <session-id> "New Title"
```

Searches across all projects for the session and appends a `custom-title` record to the JSONL transcript — the same mechanism used by Ctrl+R rename and `rename-claude-sessions`.

To get the session ID, run `active-sessions` and copy the Session column value (prefix with the full UUID from `list-sessions --all` if needed).

## Browsing session history

```bash
list-sessions              # sessions for the current project (cwd)
# equiv: agt sessions list
list-sessions --all        # all sessions across every project
list-sessions --all --sort started   # oldest first
list-sessions --all --limit 50       # show more
list-sessions --stuck      # sessions that are very large or have many messages
```

The `--all` flag is the cross-project view — it groups sessions by project and shows title, size, message count, and timestamps.

## Related scripts

- `rename-claude-sessions` — auto-title sessions from PR/issue context or AI
- `rename-session <id> <title>` — manually rename a specific session
