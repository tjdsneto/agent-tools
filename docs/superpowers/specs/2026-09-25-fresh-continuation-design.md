# Fresh Continuation — Design Spec

**Date:** 2026-09-25  
**Status:** Implemented — skill `fresh-continuation` (`ai/skills/shared/fresh-continuation/`)  
**Plan:** `docs/superpowers/plans/2026-09-25-fresh-continuation.md`  
**Repo:** `tjdsneto-setup` (shared skill + install via `install.sh`)  
**Related:** Justin `handoff@jtsternberg` (`/handoff:handoff`, `/handoff:pickup-handoff`); MemPalace MCP; `parked-ideas`; `end-session`; Spec `2026-09-24-chatgpt-tray-handoff-design.md` (different lane: phone ChatGPT)

## 1. Summary

A shared skill `fresh-continuation` that, when invoked, banks a **small** continuation
artifact for the *current* work, optionally files richer session detail into MemPalace,
and prints a **harness-aware resume command** so the user can open a fresh session and
continue without dumping a huge summary into the new context.

It is **complementary** to Justin’s handoff plugin: same pickup path and storage
backends, intentionally slimmer content, plus a light MemPalace write for on-demand LTM.

## 2. Goals

- Spin a clean agent session when context is fat or a fresh perspective is wanted.
- Keep the **boot artifact small** (goal + state + next steps), not a full session dump.
- Reuse Justin **pickup** (`pickup-handoff` / equivalent fallback) so resume is one path.
- Store **deeper detail** in MemPalace (searchable by project wing / topic room), not in
  the always-loaded handoff body.
- Work across **Claude Code, Cursor, and Codex** with the best available resume line each.
- Fail soft when MemPalace or Justin plugin scripts are unavailable.

## 3. Non-goals (v1)

- Replacing Justin `/handoff:handoff` for heavy multi-day / end-of-day banking.
- A full **session-memory** skill (topic graph authoring, multi-doc STM/LTM pipelines).
  That may come later; this skill only does a light MemPalace checkpoint.
- Graphiti/Zep, `claude-handoff`/`chf`, or new storage backends.
- Auto-injecting MemPalace LTM into every new session (retrieval stays on demand).
- Killing the current process (`end-session` remains separate and destructive).
- ChatGPT Remote / tray handoff (see chatgpt-tray-handoff).

## 4. Relationship to existing tools

| Tool | Role vs this skill |
|------|--------------------|
| Justin `handoff` | Full content contract; preferred for rich end-of-day handoffs. |
| Justin `pickup-handoff` | **Resume path** for Claude Code / Codex. Fresh-continuation writes a slim handoff Justin can pick up. |
| MemPalace | **LTM**: topic-scoped drawers + diary; search/traverse/kg on demand. |
| `parked-ideas` | Park a thread for later *recall by topic* — not “continue this task now.” |
| `end-session` | Kill process — never used by this skill. |
| ChatGPT tray handoff | Phone ChatGPT lane — out of scope. |

**Decision (brainstorming):** Complementary (A) + Justin-compatible slim handoff for pickup
(A) + light MemPalace (B) + shared skill with harness-aware resume (B).

## 5. Architecture

```
Current session
  → skill fresh-continuation
       │
       ├─► Slim Justin handoff (beads pending-handoff: …  OR  HANDOFF-*.md)
       │     sections: Goal, Progress, Files, What worked/didn't (brief),
       │               Next steps, Anchor, Session (+ MemPalace pointer)
       │
       ├─► MemPalace checkpoint (best-effort)
       │     diary entry (STM) + few topic drawers (LTM)
       │
       └─► Chat: harness-aware Resume block
              Claude:  /handoff:pickup-handoff <id>
              Codex:   $handoff:pickup-handoff <id>
              Cursor:  paste boot blurb + Read path / bd show <id>
```

| Piece | Location | Role |
|-------|----------|------|
| Skill | `ai/skills/shared/fresh-continuation/SKILL.md` | Judgment + workflow; user-invocable |
| Justin backends | Existing plugin references | Where/how to write handoff; pickup command generator when available |
| MemPalace MCP | Already installed | Optional LTM filing |
| Install | `install.sh` shared → `~/.claude/skills` + `~/.cursor/skills-cursor` | No installer changes beyond new skill dir |

No new CLI in v1. Mechanical steps that Justin already scripts (`generate-command.sh`,
`session-info.sh`) are invoked when the plugin is present; otherwise the skill emits the
universal fallback lines itself.

## 6. Slim handoff content contract

Same **section order and names** as Justin’s handoff so `pickup-handoff` works unchanged.
Content is deliberately shorter:

| Section | v1 budget |
|---------|-----------|
| Goal | 1–3 sentences |
| Current Progress | ≤6 bullets |
| Files Changed | paths only (or `git diff --stat` condensed); skip if none |
| What Worked | ≤3 short bullets; omit section if empty |
| What Didn't Work | ≤3 short bullets; omit if empty |
| Next Steps | 2–5 concrete ordered actions |
| Anchor | Justin shape (branch, HEAD, Written) when in a git repo |
| Session | Justin `session-info.sh` when available; else omit |
| Deep memory (extra, after Session) | Pointers only: MemPalace wing (+ rooms filed), optional transcript path already in Session |

**Soft cap:** ~40–60 lines / ~2–3k characters of body (excluding YAML/frontmatter if any).
If the model wants more detail, put it in MemPalace drawers — not in the handoff.

**Backend selection:** identical to Justin — beads when `bd` + `.beads/` present, else
`HANDOFF-<work-name>.md` with `.git/info/exclude` for `HANDOFF*.md`.

**Work naming:** Justin’s rules (branch when descriptive; else kebab-case from the work).

**Marker:** Prefer title/work prefix that stays Justin-compatible (`pending-handoff: …`).
Optionally mention `fresh-continuation` inside the body (e.g. under Deep memory) so humans
can tell *why* it was written — do **not** invent a new title prefix that breaks session-start
hooks.

## 7. MemPalace light checkpoint

Best-effort; never block the handoff or resume block if MCP is unavailable.

1. Infer **wing** from project (cwd / repo slug → existing wing if obvious, else a
   sensible `wing_<slug>`; do not invent dozens of wings — prefer existing taxonomy).
2. Call `mempalace_checkpoint` (or equivalent discrete calls) with:
   - **Diary** (STM): one AAAK-ish or plain short entry — what this session was about,
     outcome so far, next step. Agent name e.g. `fresh-continuation` or harness name.
   - **Items** (LTM drawers): 1–5 verbatim-ish chunks, each with a **room** among
     existing rooms when possible (`decisions`, `problems`, `technical`, `planning`,
     `architecture`, …). Content = decisions, blockers, key commands/errors — not the
     whole transcript.
3. Record wing + room list in the handoff **Deep memory** pointer section.
4. Remind the pickup agent (in Next Steps or Deep memory): search MemPalace before
   guessing forgotten detail.

Do **not** dump the entire conversation into drawers.

## 8. Resume block (chat output)

Every successful run ends with a copy-pasteable block. Detect harness in order:

1. `CLAUDE_CODE_SESSION_ID` set → Claude Code  
2. `CODEX_THREAD_ID` set → Codex  
3. Else → Cursor / unknown  

**Claude Code**

```
Fresh continuation saved: <beads id | absolute HANDOFF path>

To resume in a fresh session, run:
  /handoff:pickup-handoff <identifier>

Fallback: <bd show … | Read … and continue>
Deep memory: MemPalace wing=<…> (search if you need more than the handoff)
```

If Justin’s `generate-command.sh` is findable under the installed plugin, use its output
for the exact slash form; otherwise hardcode `/handoff:pickup-handoff <id>`.

**Codex** — same, with `$handoff:pickup-handoff <identifier>`.

**Cursor / unknown**

```
Fresh continuation saved: <identifier>

Start a new Agent chat in this project and paste:

  Pick up handoff <identifier>.
  Read/show it (bd show <id> OR Read <path>), reconcile with git, brief me, then continue.
  If a detail is missing, search MemPalace wing=<…> before guessing.

Boot blurb (optional paste):
  Goal: …
  Now: …
  Next: …
```

The boot blurb is a **≤8-line** extract of Goal / Now / Next — not the full handoff —
so Cursor users who paste into a new chat stay lean; the handoff file/issue remains the
source of truth when they follow the pickup instructions.

## 9. Skill surface

```
ai/skills/shared/fresh-continuation/
  SKILL.md                 # workflow, triggers, budgets, harness resume
  references/
    slim-contract.md       # section budgets + Deep memory pointer template
    mempalace-checkpoint.md # wing/room heuristics, checkpoint shape
    resume-block.md        # harness detection + output templates
```

Frontmatter:

- `name: fresh-continuation`
- `description:` third person, WHAT + WHEN (fresh session, continue work, context full, …)
- `user-invocable: true`
- `argument-hint:` optional note / work-name override

Triggers: `/fresh-continuation`, “fresh continuation”, “continue in a fresh session”,
“spin up a clean session with context”, “hand off to a fresh session” (when the intent is
*immediate clean continue*, not ChatGPT phone or park).

Cross-links in related skills (one-line each, v1 or follow-up):

- `end-session` — already points at handoff for wrap-up; add fresh-continuation for
  “context full, keep going in a new session.”
- Justin handoff remains the rich path; this skill does not unregister it.

## 10. Error handling

| Condition | Behavior |
|-----------|----------|
| Not in git | Write file backend without Anchor; still print resume |
| No beads | File backend |
| MemPalace MCP missing / fails | Skip checkpoint; note “no MemPalace write” in chat; still succeed |
| Cannot resolve session id | Omit Session section |
| Ambiguous work name | Ask once, or default from branch / short topic |
| Handoff write fails | Stop; do not claim success or invent a pickup id |

## 11. Testing / verification

- Dry-run in a beads repo: produces/updates `pending-handoff: …`, resume shows `/handoff:…`
  or `$handoff:…` as appropriate.
- Dry-run without beads: `HANDOFF-*.md` + exclude entry; Cursor-style resume block when
  Claude/Codex env vars absent.
- MemPalace unavailable: skill still completes with handoff + resume.
- Size: sample handoff body under soft cap; agent instructed to trim if over.
- Install: `./install.sh` links skill into Claude + Cursor skill dirs.

## 12. Future (out of v1)

- Dedicated `session-memory` skill: multi-topic STM/LTM filing, graph hygiene, recall
  protocol; `fresh-continuation` would call it instead of inline checkpoint.
- MemPalace closets as first-class summary pointers when the product matures.
- Optional `chf` / transcript digest for crashed sessions where the model never ran
  fresh-continuation.
- Hook nudge after compaction (Justin already nudges full handoff; could add a lighter
  fresh-continuation nudge — evaluate later).

## 13. Open decisions (resolved in brainstorming)

| Decision | Choice |
|----------|--------|
| vs Justin handoff | Complementary |
| Boot / pickup | Slim Justin-compatible handoff + Justin pickup |
| MemPalace | Light checkpoint (B) |
| Harnesses | Shared skill; harness-aware resume (B) |
| Soft size | ~40–60 lines / ~2–3k chars |
| Kill session | No |
