---
name: agent-registry
description: >-
  Maintain this AI session in the cross-host agent presence registry. Hooks own
  ensure/heartbeat/end; agents list before claiming work and update on focus
  change. Use self to get registry_id. CLI: agt registry.
---

# agent-registry — session presence

CLI: **`agt registry`**. Legacy PATH shim `agent-registry` still works (binary under
`~/projects/agent-tools/modules/registry/bin/agent-registry`).

Store: `~/.local/share/agent-registry/registry.json` (override: `AGENT_REGISTRY_PATH`).
Archive sibling: `archive.jsonl` in the same directory (unregister / replace / prune append here).

Do not invent a parallel presence store. Do not put `registry_id` into shared artifacts
that other agents would treat as list output.

## Ownership split

- **Hooks (Claude Code, Codex, Cursor):** `ensure` on session start, throttled `heartbeat`,
  `end` on session end. Agents should not manually ping for liveness when hooks are installed.
  Archiving happens inside ops when unregister/replace/prune run.
- **Agents (this skill):** `update` on focus change; `list` before claiming an issue/PR;
  children still pass `--parent-session` when hooks cannot (Claude subagents in v1).
- **Humans:** `agt registry dashboard` for Live | Archive UI; `archive list|show|purge`
  and `prune` for cleanup/retention.

## Manual fallback

If this host's hook is not installed:

```bash
agt registry ensure --type <host> --session-id "$SESSION_ID" --directory "$PWD"
agt registry ensure --type <host> --session-id "$SESSION_ID" --directory "$PWD" \
  --model <slug>
agt registry heartbeat --type <host> --session-id "$SESSION_ID"
agt registry heartbeat --type <host> --session-id "$SESSION_ID" --model <slug>
agt registry end --type <host> --session-id "$SESSION_ID"
```

Prefer `ensure`/`heartbeat`/`end` over raw `register`/`ping`/`unregister` so the sidecar
stays consistent. Pass `--model` when known (hooks do this from harness payloads). A
**changed** model on heartbeat bypasses the throttle. Pass `--title` when the harness
provides a session display name.

Hooks also fire `agt registry summarize` (empty-only) on Stop / before end so the
board and archive get a one-line focus blurb when Ollama is available.

## Get registry_id (`self`)

After hooks run `ensure`, this session no longer sees `registry_id` in chat. Look it up
from the sidecar before `update`:

```bash
RID=$(agt registry self --type cursor --session-id "$SESSION_ID" | python3 -c 'import sys,json; print(json.load(sys.stdin)["registry_id"])')
```

Exit 2 means no sidecar / unknown entry — run `ensure` (fallback) or wait for hooks.

Keep `RID` / `registry_id` **private to this session**. `list` never exposes it.

Child sessions (subagents, spawned hosts) pass the parent’s public `session_id`:

```bash
agt registry ensure --type cursor --session-id "$CHILD_ID" --directory "$PWD" \
  --parent-session "$PARENT_SESSION_ID"
```

## List (before claiming work)

```bash
agt registry list
# or
agt registry list --json
```

Treat another **Active** session on the same issue/PR as a coordination signal — do not
silently collide unless the human says otherwise. Stale entries (>60m since last ping)
appear separately; orphans still show their `parent_session_id`.

## Poll (a reader that should stay current)

```bash
agt registry poll                         # one JSON line, current list, then exit
agt registry poll --rev 4                 # wait until revision passes 4, or 20s
agt registry poll --follow                # a line now, and another when the list changes
```

The line is `{"rev", "active", "stale"}`. Same public rows as `list --json` (no
`registry_id`). Pass the `rev` you just got as `--rev` on the next call so a loop
waits for a change instead of spinning. `--timeout` is seconds, default 20; on
timeout the current list is printed anyway. `--follow` stays open until the pipe
closes. A repeated revision is a heartbeat and prints nothing.

## Poll (a reader that should stay current)

```bash
agt registry poll                         # one JSON line, current list, then exit
agt registry poll --rev 4                 # wait until revision passes 4, or 20s
agt registry poll --follow                # a line now, and another when the list changes
```

The line is `{"rev", "active", "stale"}`. Same public rows as `list --json` (no
`registry_id`). Pass the `rev` you just got as `--rev` on the next call so a loop
waits for a change instead of spinning. `--timeout` is seconds, default 20; on
timeout the current list is printed anyway. `--follow` stays open until the pipe
closes. A repeated revision is a heartbeat and prints nothing.

## Update (focus change)

Patch work fields; refreshes `last_ping` and `updated_at`.

```bash
agt registry update "$RID" --summary "Implementing auth fix"
agt registry update "$RID" --issue "bd-42" --branch tn/auth-fix
agt registry update "$RID" --pr-title "Fix token refresh" --pr-url "https://github.com/org/repo/pull/123"
agt registry update "$RID" --goflow-timer "$TIMER_ID"
agt registry update "$RID" --model claude-opus-4
agt registry update "$RID" --title "auth-refactor"
agt registry update "$RID" --summary "Implementing token refresh"
```

Hooks own turn status: `working` when a prompt starts, `idle` when the turn stops.
Use `--status reviewing` or `--status blocked` only when that is the real focus state.
Do not set `--status working` or `--status idle` yourself — the hooks already do.

Status values: `idle`, `working`, `reviewing`, `blocked`.

- **title** — session display name (Claude from hooks; Cursor from composer `name` in
  `state.vscdb` on ensure / heartbeat / live sync, since Cursor hooks omit it; or set
  via update). Renames on heartbeat bypass the throttle like model changes.
- **summary** — short focus line (agent-written / auto-summarize; never a stand-in for title).
- **model** — active LLM slug (hooks usually set it).

## Archive (human cleanup)

`prune` moves stale sessions out of the live registry into `archive.jsonl` (does not
hard-delete). Unregister and replace also archive. For a glanceable UI:

```bash
agt registry dashboard
```

CLI history / retention:

```bash
agt registry prune              # dry-run preview
agt registry prune --yes        # archive stale into archive.jsonl
agt registry archive list
agt registry archive show <session_id>
agt registry archive purge --older-than 30d --yes
```

Do not put product-specific flows in this skill — only the presence protocol.
