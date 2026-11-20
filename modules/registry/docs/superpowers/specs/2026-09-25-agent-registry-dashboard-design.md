# Agent Registry Dashboard & Archive — Design

**Date:** 2026-09-25  
**Status:** Approved for planning  
**Repo:** `agent-registry`  
**Approach:** Shared ops core + thin local dashboard (Approach B)

## Problem

The live registry (`registry.json`) only shows current sessions. `prune` deletes stale entries, so history is lost. There is no glanceable UI for “who is alive” and “what ran earlier.” Hooks already own liveness (`ensure` / `heartbeat` / `end` + sidecar); archive and dashboard must layer on that without rewriting lifecycle.

## Goals

1. **Never delete into the void** — anything leaving the live registry is appended to a durable archive log.
2. **Live + history in one UI** — tabs: Live | Archive.
3. **CLI remains source of truth** — web UI is a read-only viewer.
4. **Hooks stay compatible** — archive writes happen inside low-level `ops.*` so `lifecycle.end` / `ensure` pick them up automatically.
5. **Borrow proven board UX** (from [claude-sessions-board](https://github.com/awesomemotive/claude-sessions-board)) without Claude-only features: attention band, project grouping, loopback-only bind, poll backoff, human age language, `doctor`/`status`.

## Non-goals (v1)

- SQLite index / full-text search (JSONL is durable; index later).
- LLM summaries, token/cost bars, transcript scraping.
- Mutating actions from the UI (no unregister/prune buttons).
- Multiple layouts/themes/wall mode.
- Sound/desktop notifications.
- launchd/systemd autostart (document as follow-up).
- Docker / remote bind by default.

## Architecture

```
Agents (Cursor / Claude / Codex)
        │
        ▼
  agent-registry CLI
        │
        ├── register / update / ping / ensure / heartbeat ──► registry.json (live, flocked)
        │
        ├── unregister / prune / replace ──► append archive.jsonl
        │         ▲
        │         └── lifecycle.end / ensure(replace) call these ops
        │
        └── dashboard ──► stdlib HTTP (localhost)
                            GET /api/live
                            GET /api/archive
                            GET /  (single HTML+JS page)
```

### Paths

| Role | Default path |
|------|----------------|
| Live | `~/.local/share/agent-registry/registry.json` |
| Archive | `~/.local/share/agent-registry/archive.jsonl` (sibling of live) |
| Sidecar | `~/.local/share/agent-registry/by-session/` (unchanged) |

`AGENT_REGISTRY_PATH` still overrides the live file; archive is always `archive.jsonl` in the same directory as the live file.

### Archive event (one JSONL line)

```json
{
  "archived_at": "2026-09-25T15:00:00+00:00",
  "reason": "unregister",
  "session": { /* full Session including registry_id */ }
}
```

`reason` ∈ `unregister` | `prune` | `replace`.

Full session (including `registry_id`) is stored on disk for forensics. Public CLI/API/dashboard views strip `registry_id` unless `archive show --full`.

## Ops choke points

Archive append happens only here (same flock as live mutate; fail the whole op if append fails):

| Op | Reason | Callers |
|----|--------|---------|
| `ops.unregister` | `unregister` | CLI unregister, `lifecycle.end` |
| `ops.register(..., replace=True)` when displacing a row | `replace` | CLI register --replace, `ensure` |
| `ops.prune(..., yes=True)` | `prune` | CLI prune --yes |

- Sidecar/`by-session/` behavior unchanged.
- `lifecycle.end` with no sidecar / already gone remains idempotent (nothing to archive).
- Dry-run prune still only previews; does not write archive.

## CLI surface

**Unchanged:** `ensure`, `heartbeat`, `end`, `self`, `register`, `update`, `ping`, `list`

**Changed:**

- `prune` / `prune --yes` — move stale sessions to archive instead of deleting.

**New:**

```text
archive list [--json] [--reason R] [--limit N]
archive show <session_id> [--full]
archive purge --older-than Nd --yes
dashboard [--port N] [--no-open] [--host HOST]
doctor
status
```

- `archive purge` — manual retention (default keep forever); rewrites JSONL atomically.
- `dashboard` — start stdlib HTTP server; open browser unless `--no-open`; default port `8765` (or next free).
- `doctor` — verify live/archive paths readable/writable, lock works, report sidecar dir.
- `status` — counts (active/stale/archived), archive path, whether dashboard port is in use if detectable.

## Dashboard (v1)

### Layout

**Tabs:** Live | Archive (choice B). Preference remembered in `localStorage`.

### Live tab

1. **Needs attention** band at top: sessions with `status == blocked` **or** stale (inspired by claude-sessions-board attention rail). Deduped by `session_id`.
2. **Active** list below: non-stale sessions that are not already shown solely as blocked-in-attention — blocked active sessions appear in the attention band only (not duplicated in Active).
3. **Group by project** (default on): derive project key from `directory` (nearest git root if cheap; else basename / known roots heuristic). Toggle in UI; remembered in `localStorage`.

Card fields (public): agent type, status, directory, summary, issue/PR/branch, humanized age since `last_ping`, `session_id`. No `registry_id`.

### Archive tab

- Newest first, default limit 100 (`/api/archive?limit=100`).
- Reason filter chips: all | unregister | prune | replace.
- Rows: `archived_at` (humanized), reason, type, directory, last status/summary.
- **Group by project** uses the same `localStorage` toggle as Live (one preference for both tabs; default on).

### Behavior

- Poll `/api/live` and `/api/archive` every **5s** while the browser tab is visible.
- **Client backoff:** pause polling when `document.hidden` is true; resume when visible again. Server-side connection-count backoff is explicitly out of v1.
- Bind **loopback only** by default (`127.0.0.1`). If `--host` / env overrides to non-loopback, print a **loud warning** (board shows paths and summaries).
- Read-only: no mutation endpoints.
- Missing/empty live or archive → empty sections, not errors. Corrupt archive on read → empty list + UI banner; next successful append creates/opens the file for writing (does not delete a corrupt file automatically — `archive purge` or manual fix).
- API/UI errors: banner; keep last good payload when possible.

### API (read-only)

| Route | Response |
|-------|----------|
| `GET /` | Single-page app (HTML/CSS/JS, self-hosted) |
| `GET /api/live` | `{ "active": [...], "stale": [...], "attention": [...] }` public views; `attention` = blocked ∪ stale (deduped) |
| `GET /api/archive?limit=&reason=` | `{ "events": [ { archived_at, reason, session: public } ] }` |

Human age formatting may be client-side from ISO timestamps.

## Retention

- Default: **keep forever**.
- Manual: `archive purge --older-than Nd --yes` drops older JSONL lines; atomic rewrite.

## Error handling

- Archive append inside live transaction; if JSONL write fails, abort live change (no split brain).
- Missing `archive.jsonl` on append → create file and append. Corrupt file on read → empty list (see Behavior). Corrupt file on append → fail the op with a clear I/O error (exit 3); do not silently truncate.
- `replace` archives displaced session before insert.
- Unknown `registry_id` on unregister → unchanged (error); no archive line.

## Testing

- Unit: unregister/prune/replace append correct reason + snapshot; dry-run prune does not append; end/ensure cover archive via ops.
- Unit: public views strip `registry_id`; `archive show --full` includes it.
- Unit: purge older-than keeps newer lines; atomicity under lock.
- Unit/integration: `/api/live` and `/api/archive` shapes; dashboard binds loopback.
- Regression: existing register/update/ping/list/lifecycle tests still pass.

## Inspired by (not copied)

[claude-sessions-board](https://github.com/awesomemotive/claude-sessions-board): attention vs working, project grouping, localhost-only + HOST warning, poll backoff when unwatched, human age language, doctor/status. Explicitly **not** adopting: SQLite FTS, LLM summaries, plan usage, multi-layout wall, notifications, Claude transcript scraping.

## Implementation order (for planning)

1. Archive store + ops choke points + prune/unregister/replace behavior + tests.
2. CLI `archive list|show|purge`.
3. Dashboard HTTP + Live/Archive tabs + attention band + project grouping.
4. `doctor` / `status`; docs + skill updates.
5. Follow-ups (out of v1 plan unless trivial): autostart, SQLite index, notifications, resume copy lines.
