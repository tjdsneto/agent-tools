# agent-read

Kokoro read-aloud CLI for AI agents. Hand text or a file to the human as spoken audio: synthesize with Kokoro ONNX, play through a small Swift helper (play / pause / stop), print a JSON result on stdout.

Blocking by default so the agent knows when reading finished or was stopped. Optional `--background` starts playback and returns immediately; `agent-read stop` ends a background job.

This is **not** an interrupt/ask modal — that remains `agent-ping`. agent-read is for *listening*.

**Design spec:** [`~/projects/tjdsneto-setup/docs/superpowers/specs/2026-09-24-agent-read-design.md`](~/projects/tjdsneto-setup/docs/superpowers/specs/2026-09-24-agent-read-design.md)

**Skill:** [`skills/agent-read`](~/projects/agent-tools/skills/agent-read/SKILL.md) in this repo — when to call, how to pass text/file, how to branch on the result.

## Prerequisites

- macOS
- Python 3.11+
- Swift toolchain (for the UI helper)
- Kokoro ONNX at `$KOKORO_HOME` (default `~/.local/share/kokoro-onnx`) with venv + model + voices

## Install

```bash
cd ~/projects/agent-tools/modules/read

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

./scripts/build-ui.sh
```

Or from the monorepo root: `~/projects/agent-tools && ./install.sh` (links `agent-read` / `agt read` via shims).

Run via `bin/agent-read` (wrapper that uses `.venv/bin/python`).

## Usage

Exactly **one** text source: `--text`, `--file`, or stdin. Diagnostics go to **stderr**; **stdout** is a single JSON object.

### Inline text

```bash
bin/agent-read --title "Smoke" --text "Hello from agent read."
```

### File

```bash
bin/agent-read --title "Notes" --file /path/to/notes.md
```

### Stdin

```bash
printf '%s' "Short summary." | bin/agent-read --title "Summary"
```

### Background + stop

```bash
bin/agent-read --background --title "Long listen" --file /path/to/notes.md
# …agent continues work…
bin/agent-read stop
```

### Useful flags

| Flag | Behavior |
|------|----------|
| `--title <str>` | Shown in the player; included in result JSON |
| `--voice <id>` | Kokoro voice (default `$AGENT_READ_VOICE` or `am_michael`) |
| `--speed <float>` | Synth speed; default `1.0` |
| `--background` | Start player and return immediately (`mode: "background"`) |
| `stop` | End background job; idempotent if nothing playing |

## Exit codes

| Code | When |
|------|------|
| `0` | `status` is `ok` |
| `130` | `status` is `stopped` |
| `1` | `status` is `error` |

Always parse stdout JSON and check the exit code — do not assume success on non-zero.

## JSON stdout

```json
{
  "status": "ok",
  "mode": "foreground",
  "title": "PR summary",
  "chars": 1842,
  "voice": "am_michael",
  "elapsed_ms": 42000
}
```

| Field | Notes |
|-------|--------|
| `status` | `ok` \| `stopped` \| `error` |
| `mode` | `foreground` \| `background` |
| `title` | string or `null` |
| `chars` | character count of spoken text |
| `voice` | Kokoro voice id used |
| `elapsed_ms` | wall time for this CLI invocation |

## Environment

| Variable | Purpose |
|----------|---------|
| `KOKORO_HOME` | Kokoro ONNX install dir (default `~/.local/share/kokoro-onnx`) |
| `AGENT_READ_VOICE` | Default Kokoro voice id (default `am_michael`) |
| `AGENT_READ_UI` | Path to `agent-read-ui` binary (default `bin/agent-read-ui` in repo) |
| `AGENT_READ_CACHE` | Job/cache dir for background playback (default under `~/Library/Caches/agent-read`) |

## Manual checklist

Run on macOS with Kokoro installed and a built `bin/agent-read-ui`. Leave unchecked until verified.

- [ ] **pytest** — `.venv/bin/pytest -v` passes
- [ ] **build-ui** — `./scripts/build-ui.sh` succeeds
- [ ] **Background text** — `--background --text "…"`, then `stop` (no orphaned player)
- [ ] **Background file** — `--background --file …`, then `stop`
- [ ] **Foreground** — omit `--background`; UI plays until finish or Stop
