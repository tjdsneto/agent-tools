# Agent Registry — Auto Session Summary (sketch)

**Date:** 2026-09-25  
**Status:** Implemented (v1: Ollama + empty-only + archive gate + Stop hooks)  
**Repo:** `agent-registry`  
**Depends on:** `title` + `summary` fields (landed); Stop/sessionEnd hooks

## Goal

Keep the Live board scannable when agents forget to `update --summary`. On session
stop (and optionally on a throttled heartbeat for long sessions), produce a
**one-line focus blurb** into `summary` using a cheap or local model — without
blocking the hook path or inventing titles the user already set.

## Field split (already shipped)

| Field | Owner | Auto-summary touches? |
|-------|--------|------------------------|
| `title` | Harness / user (`--name`, `/rename`, Cursor title if any) | **Never overwrite** if set |
| `summary` | Agent `update`, or auto-filler | **Write target** |
| `model` | Harness hooks | No |

Dashboard headline stays: `title → summary → basename`.

## When to run

1. **Primary:** host `Stop` / Cursor `stop` hook → fire-and-forget summarizer
   (same cadence as `extract-learnings` / heartbeat today).
2. **Optional later:** every Nth heartbeat if `summary` empty and session age > 15m
   (long-running boards).
3. **Never** on `ensure` (cold start has nothing useful yet).

Fail open: summarizer errors must not break `end` / unregister.

## Input (cheap)

Prefer small, structured context over full transcripts:

1. Existing `title`, `directory`, `branch`, `issue`, `pr.title`, agent `summary` if any
2. First user message (≤300 chars) — Claude transcript already yields this in
   `extract-learnings.read_transcript`
3. Last ~3k chars of user/assistant text (not tool dumps)
4. Cap total prompt ~4–6k chars

Skip if: no transcript path, session < ~2 messages, or `summary` was set in the
last 10 minutes by an agent (`updated_at` + non-empty summary heuristic).

## Output contract

Model must return **one line**, ≤120 chars, no quotes, no “Summary:” prefix.

Prompt sketch:

```
One line: what this agent session is working on right now.
Prefer concrete nouns (repo, PR, bug). No filler.
Context:
...
```

Write via:

```bash
agent-registry update "$RID" --summary "<line>"
# or ping-with-summary once we add it; update is fine from hooks via self → rid
```

If `title` is empty and the model line is good, **do not** auto-promote to
`title` in v1 (titles are user/harness-owned). Later: optional
`--suggest-title` only when Claude `session_title` is missing.

## Provider chain (local-first)

Mirror existing setup habits (`translate-to-english` → Ollama; `extract-learnings`
→ Gemini flash / `claude -p --model haiku`):

| Priority | Provider | Default | Notes |
|----------|----------|---------|--------|
| 1 | Ollama local | `gemma4:12b-mlx` (same as translate) | `http://127.0.0.1:11434`; timeout 20–30s |
| 2 | Gemini Flash | `gemini-2.5-flash` | reuse `GEMINI_API_KEY` from claude-tools `.env` |
| 3 | Claude CLI haiku | `claude -p --model haiku` | last resort; costlier |

Env overrides: `AGENT_REGISTRY_SUMMARY_PROVIDER=ollama|gemini|claude|off`,
`AGENT_REGISTRY_SUMMARY_MODEL=…`, `AGENT_REGISTRY_SUMMARY_TIMEOUT=25`.

Default **on** only when Ollama responds to `/api/tags`; otherwise off until
configured (avoid surprise cloud spend from hooks).

## Architecture

```
Stop / stop hook
    │
    ├─► agent-registry heartbeat (existing, sync, fast)
    │
    └─► agent-registry summarize --type … --session-id …   (new, async)
              │
              ├─ resolve sidecar → registry_id + session fields
              ├─ locate transcript (Claude path / Cursor transcript_path)
              ├─ build compact prompt
              ├─ call provider chain
              └─ ops.update(rid, summary=…)   # empty-only (never overwrite non-empty)
```

### Write policy — **decided: empty-only**

- Write `summary` only when it is currently empty / whitespace.
- Never overwrite a non-empty summary (agent `update --summary` always wins).
- `--force` on the CLI is the only escape hatch (manual / debug), not used by hooks.
- No `summary_source` schema field in v1.

### Archive path — **decided: summarize before archive**

When a session leaves live via `unregister` / `replace` / `prune`, if `summary` is
still empty, run the same summarizer **synchronously with a tight timeout** (or best-
effort) *before* `archive.append_session`, so the JSONL row carries the blurb.

Order inside ops:

```
if summary empty → try summarize (timeout budget) → then append archive → then drop live
```

If summarize fails or times out, archive anyway with empty summary (fail open).
Do **not** block prune of many sessions on N LLM calls — for prune, summarize
sequentially with a per-session budget and a global prune budget, then continue.

## CLI

```bash
agent-registry summarize --type claude --session-id "$SID" [--force]
```

- Looks up sidecar; no-op if missing
- `--force` refreshes even when summary already set
- Prints JSON `{ok, summary, provider, skipped?}`

Hook wrappers call this with stdout discarded; run in background
(`… &` or `nohup`) with a hard timeout so Stop stays snappy.

## Cursor vs Claude

| Host | Transcript | Title input |
|------|------------|-------------|
| Claude | `transcript_path` on hook stdin; reuse extract-learnings reader | `session_title` already on ensure |
| Cursor | `transcript_path` when present; else skip auto-summary | rare today — summary carries the board |

Codex: manual `ensure` only for now; same `summarize` CLI when a transcript path
is passed (`--transcript PATH`).

## Non-goals (this sketch)

- Multi-paragraph recaps / MemPalace writes
- Cost dashboards / token bars
- UI button to “regenerate summary”
- Overwriting user `title`
- Blocking session end on LLM latency

## Implementation slices

1. **`summarize` CLI + provider module** (Ollama only) + empty-only + tests
2. **Archive gate** — call summarize-if-empty inside unregister/replace/prune before append
3. **Wire Claude Stop hook** (background); empty-only
4. **Add Gemini/haiku fallbacks** behind env
5. **Cursor stop** when `transcript_path` reliable
6. **Optional:** mid-session heartbeat summarize if empty + age gate

## Open questions (remaining)

1. Background from Stop: simple `&` + timeout vs `launchctl` oneshot for v1?
2. Gemma vs a tinier Ollama model (`qwen2.5:3b`) for ≤5s Stop / archive budgets?

## Decided

| Topic | Choice |
|-------|--------|
| Write policy | **Empty-only** (never overwrite non-empty `summary`) |
| Archive | **Yes** — summarize-if-empty before append to `archive.jsonl` |
| Provider default | Ollama-first; cloud off unless configured |
| `title` | Never auto-overwrite |
