---
name: session-locate
description: Attribute a path, git branch, or commit SHA to the Claude Code session(s) that actually worked there — ranked by activity, with live-vs-ended from agent-registry. Use when Tiago asks "which session worked on X", "who made this worktree/branch", "find the session for <path>", "whose session owns this orphaned worktree", or needs to trace a dir/branch/SHA back to the session that produced it. Read-only.
user-invocable: true
argument-hint: "<path|branch|sha> [--live-only] [--json] [--top N] [-C <repo-dir>]"
---

# session-locate

Trace a **path / git branch / commit SHA** back to the Claude Code session(s) that worked there, ranked by how much each did, with each session's live-vs-ended state. Read-only; never mutates anything.

```bash
agt sessions locate <path|branch|sha> [--live-only] [--json] [--top N] [-C <repo-dir>]
```

The `session-locate` shim on PATH runs the same thing.

## When to reach for it

- "Which session worked on `/…/some-worktree`?" / "who made this branch?"
- Attributing an **orphaned/removed worktree** to its author — the path need not still exist on disk; its `cwd` strings live on in old transcripts.
- Deciding whether a session is the **primary author** of a dir or just **passed through** it (ranked by line count).

## The non-obvious bit (why this tool exists)

Do **not** attribute by content-grepping a branch name or SHA across transcripts. In a repo with many worktrees, every session's routine `git log` / `git worktree list` / `git status` prints *other* branches' names and SHAs into its own transcript. Name-grep `engine-generalize` matched **137** sessions; a short SHA matches dozens. All false positives.

The reliable signal is each transcript line's own **`cwd` field** — the dir the session was actually running in. `session-locate` keys on that. (Verified: the same query by cwd returns **3** true authors vs 137 by name-grep.)

Second gotcha it handles: a transcript is filed under the session's *first* cwd, but a session can `cd` into a worktree mid-run, so the matching `cwd` lines can live in a transcript filed under some *other* dir. The tool scans **every** project dir by the `cwd` field, not just the dir whose name matches the path.

## Query resolution

- **path** → used as-is. Absolute paths that no longer exist on disk are searched literally (the orphaned-worktree case).
- **branch** → the worktree checked out on that branch (`git worktree list --porcelain`), resolved in the current dir or `-C <repo-dir>`.
- **sha** → the worktree(s) whose HEAD contains that commit. Weak key; prefer a path or branch.

## Output

Ranked table (most-active first): `session · state(live|ended) · lines · last-active · focus`. `--json` emits `{query, type, paths, sessions[]}`. `--live-only` drops ended sessions. `--top N` caps rows.

- **live** = present in `agent-registry list` active set; **ended** = in its stale set or absent. State is real-time, so a session the registry has since re-registered reads `live` even if it was ended when a path was orphaned.
- **lines** = count of transcript lines whose `cwd` was that path. High = primary author; a handful = passed through.

## Mechanics

Pure read of `~/.claude/projects/*/*.jsonl` (via `rg`) joined to `agent-registry list --json` (via `jq`) on `session_id`. Deps: `rg`, `jq`, `git`, `agent-registry` — all present. Script: `~/projects/agent-tools/modules/sessions/session-locate`.

Related: `claude-session-mngr` (today's sessions + token totals), `session-awareness` (what's running now), `session-review` (analyze one transcript). None of those attribute a path/branch → session; that's this tool's gap to fill.
