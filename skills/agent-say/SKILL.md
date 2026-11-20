---
name: agent-say
description: Use when an agent needs the human's attention (ask modal), a choice among options, short free-text, or to read text aloud via Kokoro. Runs `agt say` and continues from the JSON result on stdout.
---

# agent-say — ask the human / read aloud

CLI: **`agt say`**. Legacy PATH shim `agent-say` still works.

## Ask (default) — interrupt / choose / short answer

When:

- CAPTCHA / external UI handoff ("tell me when done")
- Confirm before irreversible action
- Pick among options the agent cannot decide alone
- Short free-text answer

How:

1. Build JSON (`title`, `body`, `options[]`, optional `input`, `speak`, `level`).
2. Run blocking:

```bash
printf '%s' "$JSON" | agt say --timeout 180
# or --wait / --default <id> / --speak
```

3. Parse **stdout** JSON: `status`, `choice`, `text`, `elapsed_ms`.
4. Branch on exit: `0` ok, `2` timeout, `130` cancelled, `1` error.

Optional `--speak` / `"speak": true` is best-effort (Kokoro, else macOS `say`). Portuguese text auto-uses `pf_dora`; ask for Alex/Santa → set `AGENT_SAY_VOICE_PT=pm_alex` or `pm_santa`.

## Read — speak prepared text (Kokoro required)

When the human should **hear** content (summary, notes, PR body) without a modal.

Prefer dedicated **`agt read`** for listen-only. Via say, exactly one of stdin / `--text` / `--file`:

```bash
agt say read --text "$TEXT"
agt say read --file path.md --title "Notes"
printf '%s' "$TEXT" | agt say read --title "…"
```

Stdout: `{status, mode, title, chars, voice, elapsed_ms}`. Exit `0` ok, `1` error (no Kokoro / empty text). Hard-fail — no `say` fallback.

Do not put product-specific flows in this skill — only the ask/read protocol.
