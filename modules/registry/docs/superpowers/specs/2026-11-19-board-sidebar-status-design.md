# Board sidebar-first nav + status vocabulary

**Date:** 2026-11-19  
**Status:** Approved design (pending implementation plan)  
**Issue:** https://github.com/tjdsneto/agent-tools/issues/2  
**Deferred:** https://github.com/tjdsneto/agent-tools/issues/3  
**Surface:** `modules/registry` board (`dashboard.html` + live/archive APIs as needed)

## Problem

The board mixes two concepts under colliding words:

1. **Lifecycle** — is the session still reachable? (tabs used `Live` / `Stopped` / `Archive`; a band said `Running`)
2. **Turn status** — what is the agent doing? (row labels `idle` / `working` / `reviewing` / `blocked`)

The sidebar also flattens every project key, so ephemeral worktree leaves (e.g. `.wt-addr-*`) crowd out real projects. Selection is single-project or All, with no canvas group-by.

## Goals

- One word → one meaning across tabs, band headers, and row labels.
- Sidebar is always the primary filter; canvas options depend on that selection.
- Worktrees nest under parent projects when a heuristic can tell; orphans get a bottom bucket.
- Flexible listing modes in the canvas (not the sidebar).

## Non-goals (this pass)

Tracked on issue #3:

- Cursor token usage on the board
- Cursor CPU / memory
- Showing PID on rows
- Silent handling of broken-pipe on board close
- Auditing / tightening false-Open detection

## Model: two axes

| Axis | Answers | Where it appears |
|------|---------|------------------|
| Lifecycle | Is the session reachable / retained? | Tabs **only when a project is selected** |
| Turn status | What is the agent doing on this turn? | Row label / dot only — never a tab name |

### Lifecycle vocabulary

| Old | New | Meaning |
|-----|-----|---------|
| Live / Running | **Open** | Process sample (`cpu_percent`) or Cursor chat open in a window (`cursor_open`) |
| Stopped / No process | **Closed** | Still in the live registry, not open |
| Archive | **Archive** | Archived events (`archive.jsonl`) |

### Turn status vocabulary

Unchanged hook-owned values: `idle`, `working`, `reviewing`, `blocked`. Displayed on the row only.

## Navigation

### Sidebar (project-shaped, always)

1. Top sticky: **All Open**
2. Main projects (not worktree leaves)
3. Under each main project: nested **worktree** children when the heuristic matches and a parent can be inferred
4. Bottom bucket: **Other worktrees** for heuristic matches with no parent

Selecting a row filters the canvas. There is no “All Closed” / “All Archive” sidebar item in this pass.

### Lifecycle tabs (canvas)

- **All Open selected:** no Open/Closed/Archive tabs. Canvas shows open sessions only.
- **A project selected:** tabs **Open / Closed / Archive** appear, scoped to that project.

Flow always starts from the sidebar selection.

### Canvas group-by

| Sidebar selection | Group-by options |
|-------------------|------------------|
| All Open | `Latest activity` \| `By project` \| `By turn status` |
| One project | `Latest activity` \| `By turn status` (no by-project) |

Defaults:

- All Open → `Latest activity`
- Project → lifecycle tab `Open`, group-by `Latest activity`

Remember last group-by per sidebar context (All Open vs project) in `localStorage`.

## Worktree heuristic

Strong signals (not guarantees):

- Project key / leaf directory name starts with `.wt`
- Path contains `/.worktrees/` or a `/.wt-` segment

Parent inference: directory parent of the worktree leaf when the path shape matches. Name encoding (e.g. `.wt-addr-lindris-frontend-2687`) may help labels but is secondary to path parent.

Do not treat the heuristic as complete coverage of every git worktree practice.

## Implementation notes (guidance, not a plan)

- Primary UI file: registry board static dashboard (current `dashboard.html`).
- Prefer renaming user-visible strings and restructuring render of sidebar / tabs / bands over inventing parallel status fields.
- `project_key()` today returns the worktree leaf when `.git` exists there — nesting is a **board presentation** concern unless a later change teaches `project_key` about parents.
- Badge counts on sidebar projects should reflect **Open** sessions under that project (including nested worktrees when shown under the parent).

## Acceptance

- No user-visible `Live`, `Stopped`, or `Running` labels remain on the board.
- All Open never shows Closed/Archive tabs; a project selection does.
- Group-by options match the tables above; defaults and persistence behave as specified.
- Worktree leaves that match the heuristic nest under a parent or land in Other worktrees — they are not peers of main projects in the default sidebar list.
