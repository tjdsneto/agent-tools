# agent-say — Ask Modal + Read-Aloud for AI Agents (Design Spec)

**Date:** 2026-09-25  
**Status:** Approved — ready for implementation  
**Repo:** `~/projects/agent-say` (renamed from `agent-ping`) + skill in `tjdsneto-setup`  
**Supersedes:** `2026-09-24-agent-ping-design.md`, `2026-09-24-agent-read-design.md`  
**Formerly:** `agent-ping` (modal ask); absorbs planned `agent-read` (TTS) without a separate project

## 1. Summary

One CLI so agents can either:

1. **Ask** — interrupt the human with a native macOS modal (choices / short text), optional best-effort speech.
2. **Read** — speak prepared text aloud via Kokoro (blocking, hard-fail if TTS unavailable).

Default invocation remains the ask path (JSON on stdin). Read is an explicit subcommand. Pause/stop player UI and background jobs are deferred.

## 2. Goals

- Full rename from `agent-ping` → `agent-say` (repo, package, binaries, env, skills, docs).
- Preserve ask/modal behavior and JSON contract (field names unchanged; binary/env renamed).
- Add `agent-say read` covering the core agent-read need: text/file/stdin → Kokoro → play → JSON result.
- Portuguese auto-detect + Dora default (existing speak behavior) for both ask `--speak` and read.
- Single skill documenting ask + read.

## 3. Non-goals (this pass)

- Swift play/pause/stop player UI (later).
- `--background` / `agent-say stop` (later).
- Daemon / notification inbox (phase 2).
- Standalone `agent-read` project or skill.
- Windows/Linux.

## 4. Architecture

```
skill / agent
  ├─ ask:  JSON → agent-say → SwiftUI modal (+ optional Kokoro) → {status, choice?, text?, elapsed_ms}
  └─ read: text/file/stdin → agent-say read → Kokoro (required) → afplay → {status, mode, title?, chars, voice, elapsed_ms}
```

| Piece | Role |
|-------|------|
| `bin/agent-say` | Ask (default) + `read` subcommand |
| `bin/agent-say-ui` | Modal helper (renamed from `agent-ping-ui`) |
| Kokoro ONNX | Ask: best-effort when `speak`; Read: required |
| Skill `agent-say` | When to ask vs read; payloads; result branching |

## 5. Rename map

| Old | New |
|-----|-----|
| `~/projects/agent-ping` | `~/projects/agent-say` |
| GitHub `tjdsneto/agent-ping` | `tjdsneto/agent-say` |
| Package `agent_ping` | `agent_say` |
| `bin/agent-ping` | `bin/agent-say` |
| `bin/agent-ping-ui` | `bin/agent-say-ui` |
| Swift product/target `AgentPingUI` / `agent-ping-ui` | `AgentSayUI` / `agent-say-ui` |
| `AGENT_PING_*` | `AGENT_SAY_*` |
| Skill `agent-ping` | `agent-say` |

Compat shims for old names: **not** required in this pass (YAGNI). Callers update to `agent-say`.

## 6. Ask mode (default)

Same contract as former agent-ping:

- Input: JSON stdin or `--file`; flags `--wait` / `--timeout` / `--default` / `--speak`
- Output: `{status, choice, text, elapsed_ms}`
- Exit: `0` ok, `2` timeout, `130` cancelled, `1` error
- Speak: best-effort; PT → `pt-br` + `pf_dora` (override `AGENT_SAY_VOICE_PT` / `AGENT_SAY_LANG`)

## 7. Read mode (`agent-say read`)

### 7.1 Sources (exactly one)

| Source | Invocation |
|--------|------------|
| Stdin | `printf '%s' "$TEXT" \| agent-say read [flags]` |
| File | `agent-say read --file path.md` |
| Inline | `agent-say read --text '…'` |

Zero or multiple sources → error. Empty after trim → error.

### 7.2 Flags

| Flag | Behavior |
|------|----------|
| `--title <str>` | Included in result JSON (no player chrome yet) |
| `--voice <id>` | Kokoro voice; else lang-aware defaults (`am_michael` / `pf_dora`) |
| `--speed <float>` | Synth speed; default `1.0` |

### 7.3 Output

```json
{
  "status": "ok",
  "mode": "foreground",
  "title": null,
  "chars": 42,
  "voice": "pf_dora",
  "elapsed_ms": 3800
}
```

| `status` | Meaning |
|----------|---------|
| `ok` | Playback finished |
| `error` | Bad args, empty text, Kokoro missing/failed, play failed |

Exit: `0` ok, `1` error. (Future: `130` stopped when player UI exists.)

### 7.4 Behavior

- Kokoro **required** — no macOS `say` fallback (unlike ask `--speak`).
- Playback via `afplay` for now (same as ask speak path).
- Lang/voice: reuse ask speak detection unless `--voice` / `AGENT_SAY_LANG` forces.

## 8. Environment

| Variable | Purpose |
|----------|---------|
| `AGENT_SAY_UI` | Path to `agent-say-ui` |
| `KOKORO_HOME` | Kokoro ONNX dir (unchanged) |
| `AGENT_SAY_VOICE` | English Kokoro voice (default `am_michael`) |
| `AGENT_SAY_VOICE_PT` | Portuguese voice (default `pf_dora`) |
| `AGENT_SAY_LANG` | Force `pt-br` / `en-us` |
| `AGENT_SAY_SAY_VOICE_PT` | Ask-mode `say` fallback voice (default `Luciana`) |

## 9. Skill

`ai/skills/shared/agent-say/SKILL.md` — when to ask vs read; CLI paths; JSON shapes; exit branching. Relink Cursor/Claude skill dirs.

## 10. Docs migration

- This file is the live design.
- Old ping + read specs: header **Status: Superseded by 2026-09-25-agent-say-design.md**.
- Old plans: note superseded; new plan `2026-09-25-agent-say.md`.

## 11. Deferred

- Swift playback UI (play/pause/stop).
- `--background` and `agent-say stop`.
- Notification-center daemon (phase 2).

## 12. Decisions log

| Topic | Choice |
|-------|--------|
| Rename scope | Full (A): repo, package, bins, env, skills, docs |
| agent-read | Fold into agent-say; no separate project |
| This pass | Rename + keep ask + add blocking `read` (A+B) |
| CLI shape | Default = ask; `read` subcommand |
| Read TTS | Hard-fail Kokoro; `afplay` for now |
| Old name shims | None |
