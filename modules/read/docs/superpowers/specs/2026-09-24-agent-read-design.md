# agent-read — Kokoro Read-Aloud for AI Agents (Design Spec)

**Date:** 2026-09-24  
**Status:** Superseded by [`2026-09-25-agent-say-design.md`](../../../../say/docs/superpowers/specs/2026-09-25-agent-say-design.md) — no separate `agent-read` project; use `agent-say read`  
**Repo:** cancelled (`~/projects/agent-read` never created)  
**Related:** TTS needs live under `agent-say` (`$KOKORO_HOME`, default `~/.local/share/kokoro-onnx`)

## 1. Summary

Generic tool so any AI agent/skill can **hand text (or a file) to the human as spoken audio** via Kokoro TTS, without embedding speech logic in each agent.

v1 is a **blocking-by-default CLI**: load text from stdin, `--text`, or `--file`; synthesize with Kokoro; play through a small Swift helper with **play / pause / stop**; print a JSON result on stdout. Optional `--background` starts playback and returns immediately; `agent-read stop` ends a background job.

This is **not** an interrupt/ask modal — that remains `agent-ping`. agent-read is for *listening* to content the agent wants the human to hear.

## 2. Goals

- One generic CLI agents prefer to call (no site-specific knowledge).
- First-class text **and** file inputs (plus stdin).
- Blocking default so the agent knows when the reading finished or was stopped; opt-in background for long listens while work continues.
- Minimal transport controls: play, pause, stop (real pause via AVFoundation — not raw `afplay`).
- Hard-fail if Kokoro is missing or synth fails (unlike agent-ping’s best-effort speak).
- Skill documents when/how to call; stays domain-agnostic.

## 3. Non-goals (v1)

- Chunked chapter/skip navigation.
- Persistent audio library / saved WAV catalog (temp WAV only).
- Windows/Linux.
- Extracting a shared Kokoro package from agent-ping (copy/adapt speak logic for now).
- Q&A / options / timeouts (use `agent-ping`).
- Automatic summarization inside the CLI (agent prepares the text).

## 4. Architecture

```
skill / agent
  → text (stdin | --text) OR file (--file)
  → agent-read CLI
      → validate + load text
      → Kokoro ONNX ($KOKORO_HOME) → WAV (temp)
      → Swift helper (play / pause / stop)
      → wait until done (default) OR return immediately (--background)
  → stdout JSON { status, mode, title?, chars, voice, elapsed_ms, ... }
  → skill continues
```

| Piece | Role |
|-------|------|
| `bin/agent-read` | Parse args; load text; synth; orchestrate player; print result; exit codes |
| Swift helper (`agent-read-ui`) | Playback UI; AVFoundation pause/stop; exit codes for finished vs stopped |
| Kokoro ONNX | Required for success; same home layout as agent-ping |
| Skill `agent-read` | When to call; how to pass text/file; how to interpret result |
| `agent-read stop` | End background playback via pid/job record |

## 5. CLI / JSON contract

### 5.1 Text sources

Exactly **one** of:

| Source | Invocation |
|--------|------------|
| Stdin | `printf '%s' "$TEXT" \| agent-read [flags]` |
| File | `agent-read --file path.md` |
| Inline | `agent-read --text '…'` |

If zero or more than one source is provided → `status: "error"`, exit `1`.

Empty text after load/trim → error.

### 5.2 Flags

| Flag | Behavior |
|------|----------|
| `--title <str>` | Shown in player; included in result JSON |
| `--voice <id>` | Kokoro voice; default `$AGENT_READ_VOICE` or `am_michael` |
| `--speed <float>` | Synth speed; default `1.0` |
| `--background` | Start player and return immediately with `mode: "background"` |
| `stop` (subcommand) | Stop background job; idempotent if nothing playing |

`$KOKORO_HOME` defaults to `~/.local/share/kokoro-onnx` (same as agent-ping).  
`$AGENT_READ_UI` may override the Swift helper path (parallel to `$AGENT_PING_UI`).

### 5.3 Output (stdout — single JSON object)

```json
{
  "status": "ok",
  "mode": "foreground",
  "title": "PR #2464 summary",
  "chars": 1842,
  "voice": "am_michael",
  "elapsed_ms": 42000
}
```

| `status` | Meaning |
|----------|---------|
| `ok` | Playback finished naturally, or background job started successfully, or `stop` found nothing playing |
| `stopped` | User hit Stop / window close / Ctrl+C in foreground, or `agent-read stop` ended an active background job |
| `error` | Invalid args, empty text, Kokoro missing/failed, player missing/failed |

- `mode`: `"foreground"` \| `"background"`
- `title`: string or `null`
- `chars`: character count of spoken text
- `voice`: voice id used
- `elapsed_ms`: wall time for the CLI invocation (for background start, time until ready/returned)
- Diagnostics → **stderr** only

### 5.4 Exit codes

| Code | When |
|------|------|
| `0` | `status` is `ok` |
| `130` | `status` is `stopped` |
| `1` | `status` is `error` |

## 6. Swift player

- Small floating panel: title (or truncated preview), **Play/Pause**, **Stop**.
- Plays WAV path passed by the CLI via AVFoundation (supports real pause).
- Natural end of audio → exit success → CLI emits `ok`.
- Stop / Esc / window close → exit stopped → CLI emits `stopped` / `130` (foreground).
- Foreground: CLI launches helper, waits for process exit, then prints JSON.
- Background: CLI launches helper, writes a job record (pid + wav path under e.g. `~/Library/Caches/agent-read/` or `/tmp/agent-read/`), prints `ok` + `mode: "background"`, exits `0`.
- `agent-read stop`: signals Quit/Stop to the recorded pid; cleans temp WAV; idempotent (nothing playing → `ok`, stderr note, exit `0`).

**WAV lifecycle:** temp file; cleaned after foreground finish/stop; background cleans on stop/finish (best-effort on next run if orphaned).

No options buttons, no free-text input, no timeout modal — transport only.

## 7. Voice (Kokoro)

- Always required for a successful read (not opt-in).
- Reuse agent-ping’s ONNX invoke pattern: `$KOKORO_HOME/venv/bin/python`, `kokoro-v1.0.onnx`, `voices-v1.0.bin`; env-driven inline script → WAV.
- Missing model/venv, ONNX error, or synth timeout → **hard error** (stderr hint, exit `1`). No `say` fallback in v1 — quality expectation is Kokoro.
- Do not extract a shared package in v1; copy/adapt from `agent-ping/agent_ping/speak.py` as needed.

## 8. Skill

Installed like other shared skills (`ai/skills/shared/agent-read/SKILL.md`), linked via `install.sh`.

Teaches agents to:

1. Decide when audio delivery helps (user asked to hear something; long summary/notes/PR body better spoken than scrolled).
2. Prepare text (agent may summarize) or pass a file path.
3. Run `agent-read` (prefer `--file` for long content; stdin/`--text` for short).
4. Use foreground when the agent should wait; `--background` when the human can keep working.
5. Parse stdout JSON; branch on `status`; never assume success on non-zero exit.
6. Use `agent-ping` for interrupts/choices — not this tool.

No product/domain content in the skill.

## 9. Project layout (proposed)

```
~/projects/agent-read/
  README.md
  bin/agent-read
  agent_read/           # Python package (cli, text load, kokoro, player runner, stop)
  ui/                   # SwiftPM helper (AVFoundation playback)
  tests/                # contract tests
  requirements.txt      # pydantic/pytest as needed; Kokoro stays in $KOKORO_HOME/venv
```

Skill source of truth in `tjdsneto-setup`, linked via `install.sh`.

## 10. Error handling

- Invalid args / dual sources / empty text → exit `1`, no player.
- Kokoro not ready or synth failure → exit `1`, install/path hint on stderr.
- Swift helper missing / failed to launch → exit `1`, build/install hint.
- Foreground Ctrl+C or Stop → `stopped` / `130`.
- Background `stop` with no job → `ok` / exit `0` (idempotent).

## 11. Testing (v1)

- Unit/contract: source selection (stdin/file/text); mutual exclusion; empty text; exit-code mapping; stop with no job.
- Mock missing `$KOKORO_HOME` → error without raising uncaught exceptions.
- Manual: short stdin read; file read; pause/resume; stop; `--background` + `agent-read stop`.

## 12. Phase 2 (explicitly later)

- Shared Kokoro helper package used by both agent-ping and agent-read.
- Chunked long-form navigation (skip section).
- Optional `--save` WAV path for re-listen without re-synth.
- Queue of readings (inbox) if multiple agents speak at once.

## 13. Decisions log

| Topic | Choice |
|-------|--------|
| Input | Both text and file (plus stdin) |
| Blocking | Default block; opt-in `--background` |
| Controls | Play / pause / stop (Swift + AVFoundation) |
| Location | New sibling repo `agent-read` + skill in setup |
| Kokoro | Required; hard-fail; no `say` fallback in v1 |
| Shared lib | Not in v1; copy/adapt from agent-ping |
| vs agent-ping | Read-aloud only; no modal Q&A |
