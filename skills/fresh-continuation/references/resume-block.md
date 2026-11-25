# Resume block

Print this in chat after a successful handoff write. Copy-pasteable. Never invent an identifier if the write failed.

## Detect harness first

1. `CLAUDE_CODE_SESSION_ID` set → **claude**
2. `CODEX_THREAD_ID` set → **codex**
3. Else → **cursor**

```bash
if [ -n "${CLAUDE_CODE_SESSION_ID:-}" ]; then echo claude
elif [ -n "${CODEX_THREAD_ID:-}" ]; then echo codex
else echo cursor
fi
```

## Discover Justin scripts (optional)

Only needed for **claude** / **codex** (and optional Session fact-gathering). Skip `generate-command.sh` on **cursor** — it exits 1 when both harness env vars are unset.

```bash
HANDOFF_SCRIPTS="$(ls -d "$HOME/.claude/plugins/cache/jtsternberg/handoff"/*/skills/handoff/scripts 2>/dev/null | sort -V | tail -1)"
# session info (any harness; may print nothing):
[ -n "$HANDOFF_SCRIPTS" ] && bash "$HANDOFF_SCRIPTS/session-info.sh"
# pickup command — ONLY if harness is claude or codex:
[ -n "$HANDOFF_SCRIPTS" ] && bash "$HANDOFF_SCRIPTS/generate-command.sh" "<identifier>"
```

If scripts missing, hardcode harness commands below.

## Claude Code template

```
Fresh continuation saved: <identifier>

To resume in a fresh session, run:
  /handoff:pickup-handoff <identifier>

Fallback: Read <absolute-path> and continue
Deep memory: MemPalace wing=<wing> (search if you need more than the handoff)
```

Prefer `generate-command.sh` output for the exact slash line when available.

## Codex template

```
Fresh continuation saved: <identifier>

To resume in a fresh session, run:
  $handoff:pickup-handoff <identifier>

Fallback: Read <absolute-path> and continue
Deep memory: MemPalace wing=<wing> (search if you need more than the handoff)
```

Prefer `generate-command.sh` output for the exact `$handoff:` line when available.

## Cursor / unknown template

Do **not** call `generate-command.sh`. Boot blurb ≤8 lines (Goal / Now / Next only).

```
Fresh continuation saved: <identifier>

Start a new Agent chat in this project and paste:

  Pick up handoff <identifier>.
  Read <absolute-path>, reconcile with git, brief me, then continue.
  If a detail is missing, search MemPalace wing=<wing> before guessing.

Boot blurb (optional paste):
  Goal: <one line>
  Now: <one line>
  Next: <one line>
```

## Fallback

`Fallback: paste into a new session: Read <absolute path> and continue where we left off`
