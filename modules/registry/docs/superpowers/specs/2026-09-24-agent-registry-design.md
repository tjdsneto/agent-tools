# agent-registry — Cross-Host Agent Session Presence (Design Spec)

**Date:** 2026-09-24  
**Status:** Approved — ready for implementation plan  
**Repo:** new project `~/projects/agent-registry` + skill in `tjdsneto-setup`  
**Related:** same “dumb CLI + skill” shape as `agent-ping`; does **not** replace Oslo’s
delegation registry or Watts’s env-lock registry

## 1. Summary

Laptop-local **session presence registry** so every AI agent session (Claude Code,
Codex, Cursor, and others) can **coordinate** with peers and so the human can see who
is alive and what they are on.

All reads and writes go through a CLI. A shared skill (plus a short global rule) makes
agents register themselves, list before claiming work, ping while alive, update focus
fields, and unregister on wrap.

## 2. Goals

- One registry for all agent hosts — not Claude-only or Cursor-only.
- Coordination: before starting work on an issue/PR, agents list and avoid colliding
  with another **active** session on the same work unless the human says otherwise.
- Human awareness: `list` shows active and stale sessions with work context.
- Parent/child: children declare the parent by **session id**; list surfaces the tree.
- Private mutate capability: each session keeps a `registry_id` that `list` never
  exposes, so sessions cannot update each other’s entries.
- Optional GoFlow timer id on the entry when the session starts a timer.
- Stale handling: entries with `last_ping` older than 60 minutes appear under a **Stale**
  section; `prune` removes them.

## 3. Non-goals (v1)

- Replacing Oslo (`orchestration/registry.json`) or Watts (`dev-envs/registry.json`).
- Spawning, supervising, or messaging child processes (handoff of parent session id is
  the parent agent’s job at spawn time).
- Multi-machine / network sync.
- Auto-detecting `agent_type` or `session_id` from the environment (explicit flags only).
- Enforcing locks on issues/PRs (advisory awareness only).

## 4. Architecture

```
skill / agent
  → agent-registry CLI
      → flock + atomic write
      → ~/.local/share/agent-registry/registry.json
  → stdout (register/update: includes registry_id; list: never)
```

**v1.1 hooks:** Host hooks call `ensure` / `heartbeat` / `end`. A sidecar under
`~/.local/share/agent-registry/by-session/<agent_type>/<session_id>.json` stores the
private `registry_id`. The skill retains semantic `update` + coordination `list`; agents
recover `registry_id` via `self`. Amends the non-goal “auto-detect session_id” — hooks may
read host-provided `session_id` from hook stdin (CLI flags remain explicit; no env sniffing
inside the Python package).

| Piece | Role |
|-------|------|
| `~/projects/agent-registry` | Python package, tests, README |
| `bin/agent-registry` | CLI entry on PATH |
| `registry.json` | Durable store (single file) |
| Skill `agent-registry` | When/how to register, list, ping, update, unregister |
| Global rule snippet | Short must-follow protocol in Claude/Cursor/Codex instructions |

**Env override for tests:** `AGENT_REGISTRY_PATH` points at an alternate registry file.

## 5. Data model

One object per session inside a versioned wrapper:

```json
{
  "version": 1,
  "sessions": [
    {
      "registry_id": "uuid",
      "session_id": "host-session-id",
      "agent_type": "cursor",
      "directory": "/path/to/workdir",
      "parent_session_id": null,
      "status": "working",
      "summary": "short free text",
      "issue": "optional string or url",
      "pr": { "title": "…", "url": "…" },
      "branch": "optional",
      "goflow_timer_id": "optional",
      "registered_at": "ISO-8601",
      "last_ping": "ISO-8601",
      "updated_at": "ISO-8601"
    }
  ]
}
```

| Field | Visibility | Notes |
|-------|------------|--------|
| `registry_id` | **Private** — returned only by mutate commands that the owner runs | UUID; required for `update` / `ping` / `unregister` |
| `session_id` | Public | Host’s session id; parent-link target |
| `agent_type` | Public | Explicit string, e.g. `cursor`, `claude`, `codex` |
| `directory` | Public | Working directory / worktree |
| `parent_session_id` | Public | Optional; child’s pointer to parent `session_id` |
| `status` | Public | `idle` \| `working` \| `reviewing` \| `blocked` |
| `summary` | Public | Short free text |
| `issue` | Public | Optional string/url |
| `pr` | Public | Optional `{ title, url }` |
| `branch` | Public | Optional |
| `goflow_timer_id` | Public | Optional GoFlow entry id |
| `registered_at` | Public | Set on register |
| `last_ping` | Public | Set on register; refreshed by `ping` and successful `update` |
| `updated_at` | Public | Last successful mutate |

**Stale rule:** `now - last_ping > 60 minutes` → stale. `list` does not hide stale
entries; it separates **Active** and **Stale** sections.

**Parent/child:** Children self-register with `--parent-session <parent session_id>`.
Parents do not create or mutate child entries. List annotates or groups children when
`parent_session_id` matches a listed `session_id`; orphans still show with the parent
session id noted.

## 6. CLI contract

All interaction with the registry is via this CLI.

| Command | Purpose |
|---------|---------|
| `register --type <t> --session-id <s> --directory <d> [--parent-session <s>] [--replace]` | Create entry; print JSON including `registry_id`. Default: error if `session_id` already exists. `--replace` overwrites that session’s entry (crash recovery). |
| `update <registry_id> [flags…]` | Patch work fields (`--status`, `--summary`, `--issue`, `--pr-title`, `--pr-url`, `--branch`, `--goflow-timer`, `--directory`, clear flags as needed). Refreshes `last_ping` and `updated_at`. |
| `ping <registry_id>` | Refresh `last_ping` only. |
| `unregister <registry_id>` | Remove own entry. |
| `list [--json]` | Human table or JSON. **Never** includes `registry_id`. Active then Stale. |
| `prune [--dry-run] [--yes]` | Without `--yes`: preview stale removals. With `--yes`: delete stale. |

**Exit codes:** `0` success; `1` usage/validation; `2` not found / auth (bad registry id);
`3` I/O / corrupt file (fail closed — do not wipe a non-parseable non-empty file).

**Concurrency:** exclusive flock around read-modify-write; write via temp file + atomic
replace.

## 7. Skill & global rule

### Skill (`ai/skills/shared/agent-registry/SKILL.md`)

Documents:

1. **Register** at session start with explicit `--type`, `--session-id`, `--directory`;
   add `--parent-session` when spawned as a child; keep `registry_id` private to the
   session.
2. **List** before claiming an issue/PR; treat another active session on the same work
   as a coordination signal.
3. **Update** when status/focus/PR title/timer/branch changes.
4. **Ping** periodically (guidance: every ~20–30 minutes, under the 60m stale threshold).
5. **Unregister** on session wrap; rely on stale + `prune` if forgotten.

### Global rule

Short must-follow blurb in Claude / Cursor / Codex instruction surfaces: use
`agent-registry` for presence; never invent another store; never put `registry_id` into
shared artifacts that other agents would treat as list output.

## 8. Trust model

- `registry_id` is a capability token. Possession allows mutate/unregister.
- `list` (human and `--json`) must not emit `registry_id`.
- Knowing `session_id` is enough for parent linking and awareness, not for mutation.
- `prune` is unauthenticated cleanup of stale rows (any caller with CLI access).

## 9. Testing

- Unit: stale classification; list redaction (no `registry_id`); duplicate `session_id`
  behavior; `--replace`.
- Integration: `AGENT_REGISTRY_PATH` tempfile — register → update → list → ping →
  prune → unregister.

## 10. Open decisions for the plan (not blocking design)

- Exact human `list` column layout / grouping of children.
- Whether `update` with no field flags is an error or a no-op ping alias (prefer error;
  use `ping` for heartbeat-only).
- Install path: symlink from `tjdsneto-setup` `install.sh` vs document PATH to
  `~/projects/agent-registry/bin`.
