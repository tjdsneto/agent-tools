---
name: session-awareness
description: List active Claude Code sessions — what's running, where, and what it's working on. CLI via `agt sessions …`.
user-invocable: true
argument-hint: "[--all]"
---

# Session Awareness

Run **`agt sessions active`** to show currently running Claude Code sessions. Legacy shims (`active-sessions`, `list-sessions`, `rename-session`, `rename-claude-sessions`, `session-review`) still work.

## Default (recently active)

```bash
agt sessions active
```

Shows sessions whose transcript was modified in the last 30 minutes — these are the sessions you're actually working in. Idle Cursor tabs are hidden.

## All processes

```bash
agt sessions active --all
```

Shows every running `claude` process — one per open Cursor tab, regardless of when it was last used.

## Output columns

| Column | Meaning |
|--------|---------|
| PID | OS process ID |
| Last active | When the transcript was last written to |
| Session | First 8 chars of the session UUID (`~` = best-guess, not `--resume`) |
| CWD | Working directory the session was started in |
| ▸ | Custom title (if `agt sessions autorename` has run) or first user message |

## How it works

Each Claude Code session is an OS process. Sessions opened via `--resume` carry their session ID in the process args, giving a definite match. New sessions (no `--resume`) are matched to the most recently modified transcript in the corresponding `~/.claude/projects/<encoded-cwd>/` directory.

## Renaming a session

To manually rename any session by ID:

```bash
agt sessions rename <session-id> "New Title"
```

Searches across all projects for the session and appends a `custom-title` record to the JSONL transcript — the same mechanism used by Ctrl+R rename and `agt sessions autorename`.

To get the session ID, run `agt sessions active` and copy the Session column value (prefix with the full UUID from `agt sessions list --all` if needed).

## Browsing session history

```bash
agt sessions list              # sessions for the current project (cwd)
agt sessions list --all        # all sessions across every project
agt sessions list --all --sort started   # oldest first
agt sessions list --all --limit 50       # show more
agt sessions list --stuck      # sessions that are very large or have many messages
```

The `--all` flag is the cross-project view — it groups sessions by project and shows title, size, message count, and timestamps.

## Session hooks

Two Claude Code hooks feed this view; they live in `modules/sessions/` and are wired in `~/.claude/settings.json` by tjdsneto-setup's `ai/claude/scripts/install`:

- **`agt sessions context`** (`session-context`, SessionStart) — injects the session ID and transcript path into the agent's context. This is where an agent finds its own transcript.
- **`agt sessions autorename`** (`rename-claude-sessions`, Stop) — gives an untitled session a title from its GitHub URL, branch issue, branch PR, or an AI summary. Runs as `--current-only` from the hook.

Run `autorename` by hand only with `--dry-run`. With no flags (or an unknown one, it has no `--help`) it titles **every** idle untitled session across all projects, one `claude -p` call each.

```bash
echo '{"session_id":"<id>","transcript_path":"<path>"}' | agt sessions autorename --current-only --dry-run --no-ai
agt sessions autorename --dry-run     # preview the all-sessions pass
```

## Related

- `agt sessions rename <id> <title>` — manually rename a specific session
- `agt sessions report` — today's session-report table (tokens / running / closed); skill `claude-session-mngr`
- `agt sessions review <transcript.jsonl>` — tool-usage and context-injection audit of one session; skill `session-review`
- `agt sessions locate <path|branch|sha>` — which session(s) worked in a dir, branch or commit; skill `session-locate`
