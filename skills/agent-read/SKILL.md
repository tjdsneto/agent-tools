---
name: agent-read
description: Read text or a file aloud to the human via Kokoro (blocking by default). Use when the human should hear a summary, notes, or PR body without an ask modal — not for interrupts/choices (use agt say / agent-say).
---

# agent-read — speak prepared text

Kokoro read-aloud for agents. Hand text or a file to the human as spoken audio; print a JSON result on stdout. **Not** an interrupt/ask modal — that is `agt say`.

CLI: **`agt read`**. Legacy PATH shim `agent-read` still works.

## When to use

- Human should **hear** content (summary, notes, PR body) without a modal
- Blocking listen until finish/stop, or `--background` then `agt read stop`

## How

Exactly **one** text source: `--text`, `--file`, or stdin. Diagnostics → stderr; stdout → one JSON object.

```bash
agt read --title "Smoke" --text "Hello from agent read."
agt read --title "Notes" --file /path/to/notes.md
printf '%s' "Short summary." | agt read --title "Summary"

agt read --background --title "Long listen" --file /path/to/notes.md
agt read stop
```

Useful flags: `--title`, `--voice`, `--speed`, `--background`, subcommand `stop`.

## Result

Parse stdout JSON (`status`, `mode`, `title`, `chars`, `voice`, `elapsed_ms`) and the exit code:

| Exit | `status` |
|------|----------|
| `0` | `ok` |
| `130` | `stopped` |
| `1` | `error` |

Do not assume success on non-zero. Requires macOS + Kokoro ONNX (`$KOKORO_HOME`).
