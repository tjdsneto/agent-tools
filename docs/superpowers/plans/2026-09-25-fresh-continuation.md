# Fresh Continuation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship shared skill `fresh-continuation` that writes a slim Justin-compatible handoff, optionally checkpoints MemPalace, and prints a harness-aware resume command for a fresh session.

**Architecture:** Markdown skill + three reference files under `ai/skills/shared/fresh-continuation/`. No new CLI. Handoff storage reuses Justin beads/file backends and `pickup-handoff`. MemPalace is best-effort via MCP. `install.sh` already symlinks shared skills.

**Tech Stack:** Agent skills (YAML frontmatter + markdown), Justin `handoff@jtsternberg` plugin scripts when present, MemPalace MCP, `bd`, git, `install.sh`.

**Spec:** `docs/superpowers/specs/2026-09-25-fresh-continuation-design.md`

---

## File map

| Path | Responsibility |
|------|----------------|
| `ai/skills/shared/fresh-continuation/SKILL.md` | Triggers, workflow steps, budgets, fail-soft rules |
| `ai/skills/shared/fresh-continuation/references/slim-contract.md` | Section budgets + Deep memory template |
| `ai/skills/shared/fresh-continuation/references/mempalace-checkpoint.md` | Wing/room heuristics + checkpoint shape |
| `ai/skills/shared/fresh-continuation/references/resume-block.md` | Harness detection + chat output templates |
| `ai/skills/claude/end-session/SKILL.md` | One routing-table row for fresh-continuation |
| `docs/superpowers/specs/2026-09-25-fresh-continuation-design.md` | Mark Implemented when done |

---

### Task 1: Reference docs (contract + MemPalace + resume)

**Files:**
- Create: `ai/skills/shared/fresh-continuation/references/slim-contract.md`
- Create: `ai/skills/shared/fresh-continuation/references/mempalace-checkpoint.md`
- Create: `ai/skills/shared/fresh-continuation/references/resume-block.md`

- [ ] **Step 1: Create the references directory**

```bash
mkdir -p /Users/tjdsneto/projects/tjdsneto-setup/ai/skills/shared/fresh-continuation/references
```

- [ ] **Step 2: Write `slim-contract.md`** with this exact content:

```markdown
# Slim handoff contract

Compatible with Justin `handoff` / `pickup-handoff`. Same section **names and order**.
Keep the body small — deeper detail goes to MemPalace (see mempalace-checkpoint.md).

## Soft cap

- Target: **40–60 lines** or **~2–3k characters** of handoff body.
- If over: cut What Worked / Didn't first, then Progress bullets; never drop Goal or Next Steps.
- Do not paste transcripts, long diffs, or tool dumps into the handoff.

## Work name

1. Prefer `git branch --show-current` when it describes the work.
2. If branch is generic (`main`, `master`, `develop`, `trunk`) or a bare ticket id carrying unrelated work → short kebab-case from the session topic (e.g. `fresh-continuation-skill`).
3. Not in a git repo / no clear name → omit work-name suffix (file backend uses `HANDOFF.md`).

## Backend

```bash
command -v bd >/dev/null 2>&1 && [ -d .beads ] && echo beads || echo files
```

- **Beads:** title exactly `pending-handoff: <work-name>` (or `pending-handoff:` alone if no name). Reuse open issue with that title before create. Description = full markdown body below (no pickup banner required).
- **Files:** `HANDOFF-<work-name>.md` or `HANDOFF.md`. Reuse existing matching file. After write, ensure local exclude:

```bash
git rev-parse --git-dir >/dev/null 2>&1 && {
  ex="$(git rev-parse --git-dir)/info/exclude"
  mkdir -p "$(dirname "$ex")"
  grep -qxF 'HANDOFF*.md' "$ex" 2>/dev/null || echo 'HANDOFF*.md' >> "$ex"
}
```

File backend: open with Justin-style pickup banner when you can generate a command; otherwise:

```
> **Resuming this work?** Paste into a new session: Read <absolute-path> and continue where we left off.
```

## Sections (in order)

### Goal

1–3 sentences. What success looks like. If the ask evolved, one clause on how.

### Current Progress

≤6 bullets. Done vs in-flight. No essays.

### Files Changed

Paths only, or condensed `git diff --stat` / `git status -sb`. **Omit entire section** if nothing changed.

### What Worked

≤3 short bullets. **Omit** if empty.

### What Didn't Work

≤3 short bullets (so the next agent does not retry). **Omit** if empty.

### Next Steps

2–5 concrete ordered actions. First item should be what to do immediately after pickup.

### Anchor

Only in a git repo:

```markdown
## Anchor
- Branch: <git branch --show-current>
- HEAD: `<git rev-parse HEAD>`
- Written: <date -u +%Y-%m-%dT%H:%M:%SZ>
```

### Session

If Justin session-info is available (see resume-block.md for path discovery), run it and include `session_id` + `transcript_path`. Otherwise **omit** this section — no placeholders.

### Deep memory

Always include when MemPalace ran or was skipped (so pickup knows):

```markdown
## Deep memory
- Source: fresh-continuation
- MemPalace: wing=<wing> rooms=<comma-list>   # or: skipped (<reason>)
- Hint: search MemPalace before guessing forgotten detail; handoff is the boot artifact only.
```

## Beads create / update

Create (stdin body):

```bash
bd create "pending-handoff: <work-name>" -t task --stdin --json <<'EOF'
## Goal
...
EOF
```

Update existing:

```bash
bd show <id> --json   # read first
bd update <id> --body-file - --json <<'EOF'
<full replacement body>
EOF
```

Reuse lookup:

```bash
bd list --status open,in_progress --title-contains "pending-handoff:" --json
```
```

- [ ] **Step 3: Write `mempalace-checkpoint.md`** with this exact content:

```markdown
# MemPalace light checkpoint

Best-effort. Never fail the fresh-continuation run if MemPalace is missing or errors.

## When

After the slim handoff body is drafted (so Goal / Next Steps exist), before or just after writing the handoff. Record the wing/rooms in the handoff **Deep memory** section.

## Wing

1. Prefer an **existing** wing that matches the project (from `mempalace_list_wings` / status), e.g. `wing_tjdsneto_setup`, `wing_lindris_backend`.
2. Else derive from repo slug or cwd basename: `wing_<slug>` with non-alnum → `_`, lowercase.
3. Do not create a new wing per session — one wing per project.

## Rooms

Prefer existing taxonomy rooms when filing drawers:

- `decisions` — locked choices
- `problems` — blockers, bugs, failed approaches
- `technical` — commands, paths, APIs, errors worth keeping
- `planning` — remaining plan / sequencing
- `architecture` — structural notes

Use 1–5 drawer items max. Do **not** dump the transcript.

## Checkpoint call

Prefer one `mempalace_checkpoint` MCP call:

```json
{
  "items": [
    { "wing": "wing_example", "room": "decisions", "content": "…verbatim decision…" },
    { "wing": "wing_example", "room": "problems", "content": "…" }
  ],
  "diary": {
    "agent_name": "fresh-continuation",
    "entry": "session|<topic>|progress:<short>|next:<short>",
    "topic": "<work-name-or-topic>",
    "wing": "wing_example"
  }
}
```

If only discrete tools exist: `mempalace_check_duplicate` → `mempalace_add_drawer` per item, then `mempalace_diary_write`.

## Skip conditions

- MemPalace MCP not available / auth failed / tool error → skip; Deep memory says `skipped (mcp unavailable)` (or the error class).
- Nothing worth filing beyond Goal/Next already in the handoff → diary-only is fine; drawers optional.
```

- [ ] **Step 4: Write `resume-block.md`** with this exact content:

```markdown
# Resume block

Print this in chat after a successful handoff write. Copy-pasteable. Never invent an identifier if the write failed.

## Discover Justin scripts (optional)

```bash
HANDOFF_SCRIPTS="$(ls -d "$HOME/.claude/plugins/cache/jtsternberg/handoff"/*/skills/handoff/scripts 2>/dev/null | sort -V | tail -1)"
# session info:
[ -n "$HANDOFF_SCRIPTS" ] && bash "$HANDOFF_SCRIPTS/session-info.sh"
# pickup command (pass beads id or absolute HANDOFF path):
[ -n "$HANDOFF_SCRIPTS" ] && bash "$HANDOFF_SCRIPTS/generate-command.sh" "<identifier>"
```

If scripts missing, hardcode harness commands below.

## Detect harness

1. `CLAUDE_CODE_SESSION_ID` set → **claude**
2. `CODEX_THREAD_ID` set → **codex**
3. Else → **cursor**

```bash
if [ -n "${CLAUDE_CODE_SESSION_ID:-}" ]; then echo claude
elif [ -n "${CODEX_THREAD_ID:-}" ]; then echo codex
else echo cursor
fi
```

## Claude Code template

```
Fresh continuation saved: <identifier>

To resume in a fresh session, run:
  /handoff:pickup-handoff <identifier>

Fallback: <bd show <id> | Read <absolute-path> and continue>
Deep memory: MemPalace wing=<wing> (search if you need more than the handoff)
```

Prefer `generate-command.sh` output for the exact slash line when available.

## Codex template

Same as Claude, but:

```
  $handoff:pickup-handoff <identifier>
```

## Cursor / unknown template

Boot blurb ≤8 lines (Goal / Now / Next only).

```
Fresh continuation saved: <identifier>

Start a new Agent chat in this project and paste:

  Pick up handoff <identifier>.
  Read/show it (bd show <id> OR Read <path>), reconcile with git, brief me, then continue.
  If a detail is missing, search MemPalace wing=<wing> before guessing.

Boot blurb (optional paste):
  Goal: <one line>
  Now: <one line>
  Next: <one line>
```

## Fallback lines by backend

- Beads: `Fallback: run \`bd show <issue-id>\` and continue where we left off`
- Files: `Fallback: paste into a new session: Read <absolute path> and continue where we left off`
```

- [ ] **Step 5: Commit**

```bash
cd /Users/tjdsneto/projects/tjdsneto-setup
git add ai/skills/shared/fresh-continuation/references/
git commit -m "$(cat <<'EOF'
feat(fresh-continuation): add slim-contract, MemPalace, resume references

EOF
)"
```

---

### Task 2: Main skill `SKILL.md`

**Files:**
- Create: `ai/skills/shared/fresh-continuation/SKILL.md`

- [ ] **Step 1: Write `SKILL.md`** with this exact content:

```markdown
---
name: fresh-continuation
description: >-
  Bank a slim session continuation and print a harness-aware command to resume
  in a fresh agent session. Use for fresh-continuation, continue in a fresh
  session, spin up a clean session with context, context is full but keep going,
  or hand off to a fresh session (immediate continue — not ChatGPT phone, not park).
user-invocable: true
argument-hint: "[optional work-name or note]"
---

# Fresh Continuation

Complementary to Justin `/handoff:handoff` (rich end-of-day banking). This skill is for
**immediate clean continue**: small boot artifact + optional MemPalace LTM + resume command.

Does **not** kill the process — that is `end-session`.

## References (read before writing)

1. [references/slim-contract.md](references/slim-contract.md) — sections, budgets, backends
2. [references/mempalace-checkpoint.md](references/mempalace-checkpoint.md) — light LTM
3. [references/resume-block.md](references/resume-block.md) — harness output templates

## Steps

1. **Work name** — from `$ARGUMENTS` if given; else slim-contract rules (branch / kebab topic).
2. **Gather facts (read-only)** — `pwd`; `git status -sb`, `git rev-parse --abbrev-ref HEAD`, `git rev-parse HEAD`, `git diff --stat` when in a repo; optional Session via Justin `session-info.sh` (path in resume-block.md).
3. **Draft slim handoff** — follow slim-contract budgets. Soft-cap 40–60 lines / ~2–3k chars.
4. **MemPalace checkpoint** — best-effort per mempalace-checkpoint.md; fill Deep memory pointers (or `skipped`).
5. **Write handoff** — beads or file backend per slim-contract. On failure: stop; do not invent a pickup id.
6. **Print resume block** — resume-block.md for detected harness. Include identifier (beads id or absolute path).
7. **Stop** — do not run `end-session`; do not start the new session yourself.

## Routing (do not confuse)

| Intent | Use |
|--------|-----|
| Fresh session, keep going on *this* work | **This skill** |
| Rich multi-day / end-of-day bank | `/handoff:handoff` |
| Park idea for later recall | `parked-ideas` |
| ChatGPT on phone | `chatgpt-handoff` / `phone-trays` |
| Kill the process | `end-session` |
```

- [ ] **Step 2: Commit**

```bash
cd /Users/tjdsneto/projects/tjdsneto-setup
git add ai/skills/shared/fresh-continuation/SKILL.md
git commit -m "$(cat <<'EOF'
feat(fresh-continuation): add shared skill for slim handoff resume

EOF
)"
```

---

### Task 3: Cross-link `end-session`

**Files:**
- Modify: `ai/skills/claude/end-session/SKILL.md`

- [ ] **Step 1: Add a routing-table row** in the “When NOT to use” table (after the handoff row). Change the handoff row to distinguish rich handoff vs fresh-continuation:

Replace this row:

```markdown
| "hand this off", "save context for later", "wrap up for the next agent" | resumable boot state for a fresh session | `/handoff:handoff` |
```

With these two rows:

```markdown
| "hand this off", "save context for later", "wrap up for the next agent" | rich resumable boot for later / next agent | `/handoff:handoff` |
| "fresh continuation", "continue in a fresh session", "context full keep going" | slim boot + resume cmd for immediate clean continue | `fresh-continuation` |
```

- [ ] **Step 2: Commit**

```bash
cd /Users/tjdsneto/projects/tjdsneto-setup
git add ai/skills/claude/end-session/SKILL.md
git commit -m "$(cat <<'EOF'
docs(end-session): route fresh-continuation vs Justin handoff

EOF
)"
```

---

### Task 4: Install + smoke verification

**Files:** none new (installer already handles `ai/skills/shared/*`)

- [ ] **Step 1: Run installer**

```bash
cd /Users/tjdsneto/projects/tjdsneto-setup && ./install.sh
```

Expected: lines linking `fresh-continuation` (and `fresh-continuation/references`) into both `~/.claude/skills` and `~/.cursor/skills-cursor`.

- [ ] **Step 2: Verify symlinks**

```bash
readlink ~/.claude/skills/fresh-continuation/SKILL.md
readlink ~/.cursor/skills-cursor/fresh-continuation/SKILL.md
test -L ~/.claude/skills/fresh-continuation/references && echo "claude refs linked"
test -L ~/.cursor/skills-cursor/fresh-continuation/references && echo "cursor refs linked"
```

Expected: both SKILL.md links point at repo `ai/skills/shared/fresh-continuation/SKILL.md`; references dirs linked.

- [ ] **Step 3: Harness detection smoke (shell only)**

```bash
# Cursor-style when env unset
env -u CLAUDE_CODE_SESSION_ID -u CODEX_THREAD_ID bash -c 'if [ -n "${CLAUDE_CODE_SESSION_ID:-}" ]; then echo claude; elif [ -n "${CODEX_THREAD_ID:-}" ]; then echo codex; else echo cursor; fi'
# Expected: cursor

CLAUDE_CODE_SESSION_ID=test bash -c 'if [ -n "${CLAUDE_CODE_SESSION_ID:-}" ]; then echo claude; elif [ -n "${CODEX_THREAD_ID:-}" ]; then echo codex; else echo cursor; fi'
# Expected: claude
```

- [ ] **Step 4: Justin script discovery smoke**

```bash
HANDOFF_SCRIPTS="$(ls -d "$HOME/.claude/plugins/cache/jtsternberg/handoff"/*/skills/handoff/scripts 2>/dev/null | sort -V | tail -1)"
echo "$HANDOFF_SCRIPTS"
# If installed: path ends in .../skills/handoff/scripts and generate-command.sh exists
```

- [ ] **Step 5: Manual agent smoke (human or this session)** — Invoke `/fresh-continuation` (or ask the agent to run the skill) once in a disposable cwd. Confirm:
  - Handoff written (beads or `HANDOFF*.md`)
  - Body under soft cap
  - Resume block printed with correct harness line
  - MemPalace either filed or Deep memory says skipped

No commit required unless install revealed a bug (then fix `install.sh` symlink for references — already supports `references/` bundling).

---

### Task 5: Mark spec implemented

**Files:**
- Modify: `docs/superpowers/specs/2026-09-25-fresh-continuation-design.md`

- [ ] **Step 1: Update status line** at top of spec from Draft to:

```markdown
**Status:** Implemented — skill `fresh-continuation` (`ai/skills/shared/fresh-continuation/`)  
**Plan:** `docs/superpowers/plans/2026-09-25-fresh-continuation.md`
```

- [ ] **Step 2: Commit**

```bash
cd /Users/tjdsneto/projects/tjdsneto-setup
git add docs/superpowers/specs/2026-09-25-fresh-continuation-design.md
git commit -m "$(cat <<'EOF'
docs(fresh-continuation): mark design implemented

EOF
)"
```

---

## Out of scope (do not implement in this plan)

- Dedicated `session-memory` skill / topic graph pipeline
- Graphiti, `chf`, compaction hooks
- Killing the session after printing the resume block
- Changing Justin plugin source

---

## Spec coverage checklist (self-review)

| Spec section | Task |
|--------------|------|
| Slim Justin handoff + budgets | Task 1 slim-contract, Task 2 skill steps |
| MemPalace light checkpoint | Task 1 mempalace-checkpoint, Task 2 step 4 |
| Harness-aware resume | Task 1 resume-block, Task 2 step 6 |
| Shared install Claude+Cursor | Task 4 |
| end-session routing | Task 3 |
| Fail soft MemPalace / no invent id | Task 2 steps 4–5 + references |
| Non-goals (no kill, no replace Justin) | Task 2 routing table |
