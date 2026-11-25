# Slim handoff contract

Compatible with Justin `handoff` / `pickup-handoff`. Same section **names and order**.
**Deep memory** is an extension after Session (not in Justin's core contract); pickup still works.
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

Write `HANDOFF-<work-name>.md` or `HANDOFF.md`. Reuse an existing matching file. After write, ensure local exclude:

```bash
git rev-parse --git-dir >/dev/null 2>&1 && {
  ex="$(git rev-parse --git-dir)/info/exclude"
  mkdir -p "$(dirname "$ex")"
  grep -qxF 'HANDOFF*.md' "$ex" 2>/dev/null || echo 'HANDOFF*.md' >> "$ex"
}
```

Open with Justin-style pickup banner when you can generate a command; otherwise:

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
