---
name: closing-session-sweep
description: Use when about to close, finish, or wrap up a work session and you want every loose end surfaced before stopping — uncommitted or unpushed git changes, running timers, held dev-env locks, stale agent-registry focus, unwritten handoffs, open todos, scratch files in ./tmp. Triggers include "prepare to close", "wrap up", "what's unfinished", "loose ends", and running before /end-session. Not for killing the process — that is end-session.
---

# Closing Session Sweep

## Overview

A session ends cleanly only when every loose end has an explicit decision. This skill runs in two strict phases: **scan and report** (read-only, always first), then **dispose** — for each loose end the user chooses to **tie it now**, **save it for later**, or **ignore it**. You never act during the scan, and "save for later" routes to whatever that project actually uses, not a hardwired default.

## When to Use

- "Prepare to close", "wrap up", "I'm done for now", "what's unfinished", "any loose ends", before `/end-session`, before walking away.
- As the audit step inside a persona's `wrap` mode (Karen, Pedro, etc.).

**When NOT to use:** `end-session` kills the OS process — run this sweep *before* that, never instead of it. Not for routine mid-task note-taking.

## Phase 1 — Scan and report (read-only)

Run every check below, then report what you found. **Do not act on anything in this phase.**

| Category | Check | Flag when |
|---|---|---|
| **Git state** | `git status --porcelain` | staged / modified / untracked files remain |
| | `git log @{upstream}..HEAD --oneline 2>/dev/null` (else `git log origin/$(git branch --show-current)..HEAD --oneline`) | commits exist locally but unpushed; no upstream → branch never pushed |
| **Work tracking** | `gtr list --running` | a GoFlow timer is still running |
| | current TodoWrite list | any `pending` / `in_progress` todo left |
| | footer items / ideas raised this session | surfaced but never captured anywhere |
| **Coordination locks** | `dev-env status` | a main-dir claim or queue entry is held by *this* session id |
| | `agent-registry self …` then `agent-registry status` | focus/status left stale and misleading to peers (hooks unregister on exit, but a wrong focus string lingers) |
| **Continuity + scratch** | in-flight multi-step work | task unfinished and no handoff written |
| | `ls -la ./tmp/ 2>/dev/null` | scratch / review artifacts worth keeping or cleaning |
| | `gh pr list --author @me` (as needed) | a PR you touched this session awaits your action |

### Report format — one numbered table, Suggested column

Present every loose end in a **single numbered table**, not grouped prose. The number is what the user replies with. Columns: `#` | `Loose end` | `Suggested`. Keep each loose-end cell to the specific fact (what, and the one detail that decides it); keep the suggestion to a few words naming the disposition.

```
Loose ends — your call per item (tie now / save / ignore):

| # | Loose end                                                        | Suggested              |
|---|------------------------------------------------------------------|------------------------|
| 1 | 3 uncommitted files in includes/ (the journeys refactor)         | Tie now — commit       |
| 2 | 2 local commits on tn/fix/foo not pushed                         | Tie now — push         |
| 3 | GoFlow timer "Review PR #2393" still running (1h12m)             | Tie now — offer stop   |
| 4 | dev-env claim on local-backend held by this session             | Tie now — release      |
| 5 | tmp/review-notes.md (PR review scratch)                          | Save → file as issue   |
| 6 | half-drafted idea for a batch-dial helper                        | Ignore (or park)       |

Tell me which to tie, save, or drop — or "tie 1-3, ignore rest" and I'll run it.
```

Close the report with that one-line prompt so the user can answer by number in shorthand (`tie 1-4`, `save 5`, `ignore rest`). Only then move to Phase 2.

## Phase 2 — Dispose (only on the user's per-item choice)

For each reported item the user picks one:

- **Tie now** — do it: commit, push, release the lock, write the handoff, delete the tmp file. (Timers are the exception — see mistakes.)
- **Save for later** — capture it so it survives the close. **Route per project** (below).
- **Ignore** — drop it, and say plainly that you dropped it.

### Routing "save for later" — detect the project's own mechanism first

Do **not** default to the global `parked-ideas`/`tray`. Detect what *this* repo uses, in order, and use the first that applies:

1. **Ana project** — if `.ana/` exists, append to `.ana/todo.md` in the ana-project format. Do not create a root `todo.md` or `todos.md`.
2. **Project-specific skill** — scan `.claude/skills/` and the repo's `CLAUDE.md`/`AGENTS.md` for an issue-filing, parking, or journaling skill. Use it.
3. **GitHub-backed repo** — "save" may mean file an issue: a `create-issue` skill if present, else `gh issue create`.
4. **File-based issue/todo system** — an `issues/` dir of MD files, or another backlog file the repo documents. Append there in that repo's format.
5. **Project journal** — a `JOURNAL.md` or repo journal convention. Write there.
6. **Globals, only if none of the above fit** — `parked-ideas` (idea/thread), `tray add` (actionable follow-up), `journal` skill (narrative), `handoff` / `fresh-continuation` (resume in-flight work).

Disposition → mechanism, once the project's flavor is known:

| Loose end | Save-for-later target |
|---|---|
| Unfinished thought / idea thread | project park → else `parked-ideas` |
| Actionable follow-up / bug | project issue system / `create-issue` / `gh issue create` → else `tray add` |
| Record of what happened | project journal / `journal` skill → else the running GoFlow timer note |
| In-flight work to resume next session | `handoff` skill (write) or `fresh-continuation` |

## Common Mistakes

- **Acting during the scan.** Phase 1 is read-only. The user decides every disposition.
- **Defaulting to global park/tray** when the repo has its own issue or journal system — the whole point is to detect and honor the project's mechanism.
- **Treating "wrap up" as `end-session`** and killing the process before the sweep even runs.
- **Auto-stopping the GoFlow timer as a "tie".** The global rule is never stop a timer unless explicitly asked. For a running timer, "tie now" means *offer* to stop — do not stop it yourself.
- **Leaving a coordination lock held.** A dev-env claim you don't release blocks the queue after you're gone; a stale agent-registry focus misleads peers. Surface both even when everything else is clean.
