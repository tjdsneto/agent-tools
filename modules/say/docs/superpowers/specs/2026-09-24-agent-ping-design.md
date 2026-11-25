# agent-ping — Attention / Ask Modal for AI Agents (Design Spec)

**Date:** 2026-09-24  
**Status:** Superseded by [`2026-09-25-agent-say-design.md`](./2026-09-25-agent-say-design.md) (renamed to `agent-say`; read mode absorbed)  
**Repo:** was `~/projects/agent-ping` — now `~/projects/agent-say`  
**Related:** same “dumb CLI + skill” shape as `jev-browse` / `jev-decide`

## 1. Summary

Generic tool so any AI agent/skill can **call attention**, **ask a question**, or
**collect a short answer** from the human without embedding UI in each agent.

v1 is **notify-first**: a blocking CLI reads a dynamic JSON payload, shows a native
macOS modal (optional Kokoro TTS), waits for the user (or timeout), and prints a JSON
result on stdout for the calling skill.

Phase 2 (out of scope for first plan): a long-lived **channel/daemon** (“notification
center”) reusing the **same message schema**. UI fallback if Swift stalls: **Tauri**
(same pattern as goflow), keeping the CLI/JSON contract unchanged.

## 2. Goals

- One generic CLI agents prefer to call (no site-specific knowledge).
- Dynamic title, body, choice options, and optional free-text input — all from JSON.
- User choice / text returned to the calling skill via stdout JSON.
- Optional voice (Kokoro), opt-in, best-effort.
- Three wait modes: block forever, timeout, timeout + agent-supplied default.
- Skill documents when/how to call; stays domain-agnostic.

## 3. Non-goals (v1)

- Automatic CAPTCHA solving.
- Persistent notification inbox / multi-agent channel (phase 2).
- Windows/Linux.
- Always-on TTS.
- Embedding Confiança or other product flows in the CLI.

## 4. Architecture

```
skill / agent
  → JSON (title, body, options[], input?, speak?, level?)
  → agent-ping CLI (blocks)
      → SwiftUI modal (frontmost + system sound)
      → Kokoro if speak=true (best-effort)
      → user chooses / types / times out / cancels
  → stdout JSON { status, choice?, text?, elapsed_ms }
  → skill continues
```

| Piece | Role |
|-------|------|
| `bin/agent-ping` | Parse args + JSON; spawn/show UI; print result; exit codes |
| SwiftUI helper | Modal UI; focus; collect choice/text |
| Kokoro ONNX (optional) | Speak title+body when requested |
| Skill `agent-ping` | When to call; payload examples; how to interpret result |

**UI plan B:** reimplement modal shell in Tauri; **same** stdin/stdout contract.

## 5. CLI / JSON contract

### 5.1 Input (stdin or `--file`)

```json
{
  "title": "Need a moment",
  "body": "Finish the step in the other window, then pick an option.",
  "options": [
    { "id": "done", "label": "Done" },
    { "id": "retry", "label": "Try again" },
    { "id": "cancel", "label": "Cancel" }
  ],
  "input": {
    "enabled": true,
    "placeholder": "Optional note…",
    "required": false
  },
  "speak": false,
  "level": "info"
}
```

| Field | Rules |
|-------|--------|
| `title` | Required, non-empty string |
| `body` | Optional string |
| `options` | Optional array of `{id, label}`; ids unique; labels shown on buttons |
| `input` | Optional; if `enabled`, show text field; `required` blocks submit without text when no option selected (if only input, must satisfy required) |
| `speak` | Optional bool; default `false`. Also `--speak` CLI flag |
| `level` | `info` \| `warn` \| `critical` (default `info`). Affects icon/sound; `critical` forces app activation |

At least one of: non-empty `options`, `input.enabled`, or implicit single **OK** when both absent (pure notify/ack).

### 5.2 Wait flags

| Flag | Behavior |
|------|----------|
| (default) | `--timeout 180` |
| `--wait` | Block indefinitely until user acts or Ctrl+C |
| `--timeout N` | Seconds; on expiry → `status: "timeout"` unless `--default` |
| `--default <id>` | On timeout, synthesize `status: "ok"` with `choice` = that option id (must exist in `options`). Invalid if there are no `options`. |

`--wait` and `--timeout` are mutually exclusive; if both passed, CLI errors.

### 5.3 Output (stdout — single JSON object)

```json
{
  "status": "ok",
  "choice": "done",
  "text": null,
  "elapsed_ms": 4200
}
```

| `status` | Meaning |
|----------|---------|
| `ok` | User confirmed (option and/or text), or timeout+default applied |
| `timeout` | Timed out with no `--default` |
| `cancelled` | Esc / close / Ctrl+C |
| `error` | Invalid input, missing helper, etc. |

- `choice`: option `id` or `null`
- `text`: trimmed string or `null`
- Diagnostics and Kokoro warnings go to **stderr** only (stdout stays machine-readable)

### 5.4 Exit codes

| Code | When |
|------|------|
| `0` | `status` is `ok` |
| `2` | `status` is `timeout` (no default) |
| `130` | `cancelled` |
| `1` | `error` |

## 6. UI (SwiftUI)

- Floating panel, always on top for the session.
- Layout: title, body, dynamic buttons (1…N), optional text field, primary affordance clear.
- On open: short system sound; bring helper to front (`critical` also activates the app).
- Esc / window close → `cancelled`.
- Submit rules: clicking an option (or OK) submits immediately with the current text field value (may be null/empty). If `input.required` is true, option/OK controls stay disabled until the field is non-empty.
- Pure notify (no options, no input): single **OK** button.

## 7. Voice (Kokoro)

- Only when `speak: true` or `--speak`.
- Synthesize title + body (concatenated with a short pause or period).
- Best-effort: missing model, ONNX error, or slow synth → warn on stderr; **modal still works**.
- Reuse prior `kokoro-onnx` approach from the visual-aids audio pipeline (no torch required).

## 8. Skill

Installed like other shared skills (`ai/skills/shared/agent-ping/SKILL.md`).

Teaches agents to:

1. Decide when a human interrupt is needed (CAPTCHA handoff, confirm destructive action, pick among options, short free-text).
2. Build the JSON payload (dynamic options/text).
3. Run `agent-ping` (blocking) and parse stdout JSON.
4. Branch on `status` / `choice` / `text`; never assume success on non-zero exit.

No product/domain content in the skill.

## 9. Project layout (proposed)

```
~/projects/agent-ping/
  README.md
  bin/agent-ping          # or thin wrapper → python/swift
  # SwiftUI app / helper target
  # optional: python shim for JSON validation + Kokoro invoke
  tests/                  # contract tests for parse + timeout/default matrix
```

Skill source of truth in `tjdsneto-setup`, linked via `install.sh`.

## 10. Error handling

- Invalid JSON / schema → exit `1`, stderr message, no modal.
- Swift helper missing / failed to launch → exit `1`, install hint.
- Kokoro failure with `speak` → stderr warning; continue modal path.
- `--default` id not in `options` → exit `1` before showing UI.

## 11. Testing (v1)

- Unit/contract: schema validation; wait-flag matrix; default-on-timeout behavior; exit codes.
- Manual: three-option ask + optional input; speak on/off; timeout path; cancel path.

## 12. Phase 2 (explicitly later)

- Daemon + inbox UI: agents enqueue pings; human processes a queue.
- Same message + response schema as v1.
- Only after v1 CLI + skill are stable.

## 13. Decisions log

| Topic | Choice |
|-------|--------|
| Overall shape | Hybrid: notify-first v1; channel later |
| Interactions | Alert + dynamic options + free text |
| Return path | Blocking CLI → stdout JSON for skill |
| Wait modes | All three: `--wait`, `--timeout N`, `--default <id>` |
| Voice | Opt-in + best-effort Kokoro |
| UI | SwiftUI first; Tauri fallback (goflow-like) |
| Name | `agent-ping` |
