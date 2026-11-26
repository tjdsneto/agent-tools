# chatgpt-handoff packet format

Tray items have a **title** (short packet) and optional **body** (full documents).

**Title** — one string:

`Headline | Section: value | Section: value | …`

Soft cap **12000** characters on the title. Truncate with `…[truncated]`. Omit empty sections.

**Body** — attach large artifacts with `tray add "…" … --body-file path` or `--body '…'` (≤100000 characters). Do not stuff full documents into the title. Readers use `tray list --json` (`body` field).

## Sections

- `Goal:` — what success looks like
- `Context:` — minimal background
- `Done:` — already finished
- `Open:` — unresolved facts / blockers
- `Ask:` — what ChatGPT should do or decide
- `Return:` — required on **in** / hand-back (`from-chatgpt`)
- `Paths:` — optional host paths (Mac only; not phone-openable)

### Out (`to-chatgpt`)

```
Decide: Q3 rock wording | Goal: One reusable sentence | Context: Q3 draft | Done: outline OK | Open: tone | Ask: Pick tone and draft | Return: Final sentence + rationale | Paths: …
```

### In / hand-back (`from-chatgpt`)

```
Return: Q3 rock wording | Goal: One reusable sentence | Done: Chose measured tone | Return: "Shipped observability…" — measured | Ask: (none)
```
