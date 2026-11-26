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

1. **Work name** — from `$ARGUMENTS` if given; else slim-contract rules (branch / kebab topic). If still ambiguous, ask once then proceed.
2. **Gather facts (read-only)** — `pwd`; `git status -sb`, `git rev-parse --abbrev-ref HEAD`, `git rev-parse HEAD`, `git diff --stat HEAD` when in a repo; optional Session via Justin `session-info.sh` (path in resume-block.md).
3. **Draft slim handoff** — follow slim-contract budgets. Soft-cap 40–60 lines / ~2–3k chars.
4. **MemPalace checkpoint** — best-effort per mempalace-checkpoint.md; fill Deep memory pointers (or `skipped`).
5. **Write handoff** — file backend per slim-contract (`HANDOFF-*.md`). On failure: stop; do not invent a pickup id.
6. **Print resume block** — resume-block.md for detected harness. Include absolute path as identifier.
7. **Stop** — do not run `end-session`; do not start the new session yourself.

## Routing (do not confuse)

| Intent | Use |
|--------|-----|
| Fresh session, keep going on *this* work | **This skill** |
| Rich multi-day / end-of-day bank | `/handoff:handoff` |
| Park idea for later recall | `parked-ideas` |
| ChatGPT on phone | `chatgpt-handoff` |
| Kill the process | `end-session` |
