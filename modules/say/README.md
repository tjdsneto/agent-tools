# agent-say

Blocking CLI for AI agents to **interrupt the human**: show a native macOS modal, collect a choice or short free-text answer, and return a JSON result on stdout. Optional Kokoro TTS reads the title and body aloud.

Agents and skills call `bin/agent-say`, block until the user responds (or a wait policy fires), then continue from the parsed result. No product logic lives in the CLI — only the interrupt protocol.

**Design spec:** [`docs/superpowers/specs/2026-09-25-agent-say-design.md`](docs/superpowers/specs/2026-09-25-agent-say-design.md)

**Skill:** [`skills/agent-say`](~/projects/agent-tools/skills/agent-say/SKILL.md) in this repo — when to call, payload shape, how to branch on the result.

## Install

```bash
cd ~/projects/agent-tools/modules/say

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Or from the monorepo root: `~/projects/agent-tools && ./install.sh` (links `agent-say` / `agt say` via shims).

Build the SwiftUI helper (prebuilt binary lives at `bin/agent-say-ui`):

```bash
cd ui
swift build -c release --product agent-say-ui
cp -f .build/release/agent-say-ui ../bin/agent-say-ui
chmod +x ../bin/agent-say-ui
```

Run via `bin/agent-say` (wrapper that uses `.venv/bin/python`).

## Usage

Request JSON on **stdin** (or `--file path/to/request.json`). **stdout** is a single JSON object; diagnostics go to **stderr**.

### Basic ask (stdin, default 180s timeout)

```bash
printf '%s' '{
  "title": "Need a moment",
  "body": "Finish the step in the other window, then pick an option.",
  "options": [
    { "id": "done", "label": "Done" },
    { "id": "retry", "label": "Try again" },
    { "id": "cancel", "label": "Cancel" }
  ]
}' | bin/agent-say
```

Example stdout:

```json
{"status": "ok", "choice": "done", "text": null, "elapsed_ms": 4200}
```

### `--timeout N`

Wait at most `N` seconds (default **180** when neither `--wait` nor `--timeout` is passed). On expiry without `--default`, `status` is `"timeout"`.

```bash
printf '%s' '{"title":"Quick check","options":[{"id":"yes","label":"Yes"}]}' \
  | bin/agent-say --timeout 30
```

### `--wait`

Block indefinitely until the user acts or the process receives Ctrl+C.

```bash
printf '%s' '{"title":"Take your time","body":"No rush.","options":[{"id":"ok","label":"OK"}]}' \
  | bin/agent-say --wait
```

`--wait` and `--timeout` are mutually exclusive.

### `--default <id>`

On timeout, synthesize `status: "ok"` with `choice` set to the given option id (must exist in `options`).

```bash
printf '%s' '{"title":"Deploy?","options":[{"id":"proceed","label":"Proceed"},{"id":"skip","label":"Skip"}]}' \
  | bin/agent-say --timeout 60 --default skip
```

### `--speak`

Read title + body aloud (best-effort). Also set `"speak": true` in JSON; the CLI flag forces speech on.

```bash
printf '%s' '{"title":"Heads up","body":"Review the diff.","speak":true,"options":[{"id":"ok","label":"OK"}]}' \
  | bin/agent-say --speak
```

Uses Kokoro ONNX when available under `KOKORO_HOME`; otherwise falls back to macOS `say`. Warnings on stderr do not block the modal.

Speech language is auto-detected from title+body: Portuguese text uses `lang=pt-br` and voice `pf_dora` (already in `voices-v1.0.bin`; no extra download). English stays on `am_michael`. Override with `AGENT_SAY_LANG` / `AGENT_SAY_VOICE_PT`.

### `agent-say read` (blocking read-aloud)

Speak prepared text via Kokoro (**required** — no `say` fallback). Exactly one of stdin, `--text`, or `--file`.

```bash
bin/agent-say read --text 'Olá, tudo bem?'
bin/agent-say read --file notes.md --title 'Notes'
printf '%s' 'Hello from the agent.' | bin/agent-say read --title 'Smoke'
```

Stdout example:

```json
{"status":"ok","mode":"foreground","title":"Smoke","chars":20,"voice":"am_michael","elapsed_ms":3200}
```

Exit `0` on success, `1` on error (missing Kokoro, empty text, bad args).

### Optional free-text input

```json
{
  "title": "Note",
  "body": "Add an optional comment.",
  "options": [{ "id": "submit", "label": "Submit" }],
  "input": {
    "enabled": true,
    "placeholder": "Optional note…",
    "required": false
  }
}
```

When `input.required` is true, option buttons stay disabled until the field is non-empty. With no `options` and no `input`, the CLI adds a single **OK** button (pure notify/ack).

### Request fields (summary)

| Field | Notes |
|-------|--------|
| `title` | Required, non-empty |
| `body` | Optional |
| `options` | `{id, label}` buttons; ids must be unique |
| `input` | Optional text field (`enabled`, `placeholder`, `required`) |
| `speak` | Optional bool; default `false` |
| `level` | `info` \| `warn` \| `critical` — icon/sound; `critical` forces app activation |

## Exit codes

| Code | When |
|------|------|
| `0` | `status` is `ok` (user confirmed, or timeout + `--default`) |
| `2` | `status` is `timeout` (no default) |
| `130` | `status` is `cancelled` (Esc, close, or Ctrl+C) |
| `1` | `status` is `error` (invalid JSON/schema, missing UI binary, etc.) |

Always parse stdout JSON and check the exit code — do not assume success on non-zero.

## Environment

| Variable | Purpose |
|----------|---------|
| `AGENT_SAY_UI` | Path to `agent-say-ui` binary (default: `bin/agent-say-ui` in repo) |
| `KOKORO_HOME` | Kokoro ONNX install dir (default: `~/.local/share/kokoro-onnx`) |
| `AGENT_SAY_VOICE` | English Kokoro voice id (default: `am_michael`) |
| `AGENT_SAY_VOICE_PT` | Portuguese Kokoro voice id (default: `pf_dora`; also `pm_alex`, `pm_santa`) |
| `AGENT_SAY_LANG` | Force lang (`pt-br` / `en-us`); skips auto-detect |
| `AGENT_SAY_SAY_VOICE_PT` | macOS `say` voice when Kokoro unavailable (default: `Luciana`) |

## Phase 2 (out of scope)

A long-lived **daemon / notification channel** (inbox queue, multiple agents) is planned for later. It will reuse the same request/response JSON schema as this CLI. v1 is notify-first: one blocking ask at a time. Playback UI (pause/stop) and `read --background` are also deferred.

## UI fallback (not implemented)

If the SwiftUI helper stalls or proves unreliable, the intended fallback is a **Tauri** modal shell (same stdin/stdout contract as goflow). That path is **not implemented** in v1 — build and use `agent-say-ui` from `ui/`.

## Manual checklist

Run these on macOS with a built `bin/agent-say-ui`. Leave unchecked until verified.

- [ ] **Options-only ask** — three buttons; choice id returned in stdout JSON
- [ ] **`input.required`** — submit disabled until text entered; then `text` populated
- [ ] **Timeout** — `--timeout 5` with no `--default` → exit `2`, `status: "timeout"`
- [ ] **Timeout + default** — `--timeout 5 --default <id>` → exit `0`, `choice` set to default id
- [ ] **Wait** — `--wait` blocks until user clicks; no premature timeout
- [ ] **Esc cancelled** — Esc or window close → exit `130`, `status: "cancelled"`
- [ ] **Speak on/off** — `--speak` / `"speak": true` reads aloud; off is silent (modal still works)
- [ ] **`level=critical`** — modal activates app / stronger attention affordance

## SwiftUI helper (`agent-say-ui`)

Low-level entry (normally invoked by the Python CLI):

```bash
agent-say-ui --request PATH --response PATH
```

Writes response JSON to `--response` when the user submits or cancels.
