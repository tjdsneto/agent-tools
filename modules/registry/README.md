# agent-registry

Cross-host agent session presence. A small CLI that tracks which AI agent sessions are running, where they are working, and what they are doing — across Cursor, Claude Code, Codex, and other hosts that share the same registry file.

Each session gets a private `registry_id` (UUID) used only by the owning process for updates, pings, and unregister. The `list` command never exposes `registry_id`; it is for coordination and visibility, not identity lookup.

## Install

From the repo root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Put the launcher on your PATH and install the Claude Code, Codex, and Cursor plugin:

```bash
plugin/install
```

After `plugin/install`, run `~/projects/agent-tools/./install.sh` if you want the `agt` shim on PATH.

The `bin/agent-registry` wrapper runs the CLI through the repo's `.venv`. `PYTHONPATH` includes `src/`.

## Data path

Live registry data is stored as JSON at:

```
~/.local/share/agent-registry/registry.json
```

Removed sessions are appended to an archive sibling (JSONL, one event per line):

```
~/.local/share/agent-registry/archive.jsonl
```

Override the live path with `AGENT_REGISTRY_PATH`; the archive is always `archive.jsonl` in the same directory:

```bash
export AGENT_REGISTRY_PATH=/tmp/my-registry.json
# archive → /tmp/archive.jsonl
agent-registry list
```

Writes are atomic and file-locked (`.lock` sibling of the live file) so concurrent agents on the same machine do not corrupt live or archive data.

## Session lifecycle

**Hooks own liveness** (Claude Code / Cursor): host hooks call `ensure` on session start, throttled `heartbeat` during the session, and `end` on session end. A sidecar under `~/.local/share/agent-registry/by-session/` holds the private `registry_id`. Agents should not manually ping for liveness when hooks are installed.

Hooks (`ensure` / `heartbeat` / `end`) are unchanged. Archiving happens inside ops (`unregister`, `replace`, `prune`), so lifecycle hooks pick it up automatically — no separate archive step in hooks.

1. **ensure** — register if needed; write/refresh sidecar (hook entrypoint; also manual fallback). Default replace archives the displaced session.
2. **heartbeat** — throttled ping via sidecar (default min interval 1200s; `AGENT_REGISTRY_HEARTBEAT_SECONDS`).
3. **end** — unregister (archives) + delete sidecar.
4. **self** — owner lookup: return full session JSON (including `registry_id`) from sidecar, for `update`.
5. **update** — change status, summary, issue, PR, branch, directory, goflow timer, or parent session.
6. **list** — show active vs stale sessions (human-readable or JSON; never includes `registry_id`).
7. **prune** — move stale sessions (no ping for >1 hour) out of the live registry into `archive.jsonl` (does not hard-delete).

Low-level verbs still available: **register**, **ping**, **unregister** (prefer ensure/heartbeat/end so the sidecar stays consistent). Unregister and replace also append to the archive.

**Statuses:** `idle`, `working`, `reviewing`, `blocked`

**Stale threshold:** 3600 seconds (1 hour) since last ping.

**Archive reasons:** `unregister`, `prune`, `replace`.

## CLI reference

All mutating commands that return a session (`register`, `update`, `ping`, `ensure`, `self`) print a JSON object to stdout, including `registry_id` where applicable. **Keep that ID private** — store it in the session process / sidecar only. Never publish it in shared output, skills, or human-facing `list` views.

### ensure / heartbeat / end

Host-hook lifecycle verbs. Prefer these over raw `register` / `ping` / `unregister` so the sidecar stays consistent.

```bash
agent-registry ensure --type claude --session-id "$SESSION_ID" --directory "$PWD"
agent-registry ensure --type claude --session-id "$SESSION_ID" --directory "$PWD" \
  --model claude-sonnet-4
agent-registry heartbeat --type claude --session-id "$SESSION_ID"
agent-registry heartbeat --type claude --session-id "$SESSION_ID" --model claude-opus-4
agent-registry end --type claude --session-id "$SESSION_ID"
```

- `ensure` — registers if needed (default replace on resume/crash); always refreshes sidecar. Optional `--parent-session`, `--model`, `--title`, `--no-replace`.
- `heartbeat` — skips if no sidecar or within throttle window; otherwise pings and updates sidecar `last_heartbeat_at`. Optional `--model` / `--title`: when either **changed**, bypasses throttle so mid-session switches/renames stick.
- `end` — unregisters (if known) and deletes sidecar; idempotent when already gone.

For a Claude session with a pid, `ensure` also saves the permission flags the process was launched with (`--permission-mode`, `--dangerously-skip-permissions`, `--allowedTools`, `--disallowedTools`, `--tools`, `--add-dir`) to `launch/claude/<session_id>.json` next to the registry. `end` keeps that file. A session that `wake` started carries `AGENT_REGISTRY_WAKE=1`, so its flags are not saved over the original ones.

**Resume permissions.** `wake` talks to a live session through SendMessage, so the session keeps its own permissions. An exited Claude session is resumed with `claude -p --resume`, which gets only the flags of the new command. Resume replays the saved launch flags. When none were saved (the session predates this, or its argv could not be read), resume uses `--dangerously-skip-permissions`; set `AGENT_REGISTRY_RESUME_BYPASS_UNKNOWN=0` in the environment of the process that runs `wake` to resume with no flags instead. Inline `--settings` permissions are not replayed; settings files still load because resume runs in the session's directory.

`model` is the active LLM slug. `title` is the session display name (Claude `session_title` from `--name` / `/rename`; Cursor composer `name` from `state.vscdb` on ensure/heartbeat/live, since Cursor hooks omit a title). A changed Cursor title bypasses the heartbeat throttle. `summary` remains the agent-written focus line (and later, optional cheap/local auto-summary) — never promoted to `title`.

### self

Owner lookup for agents that need `registry_id` after hooks ran `ensure` (no register output in chat):

```bash
agent-registry self --type cursor --session-id "$SESSION_ID"
```

Prints full session JSON including `registry_id` on success (exit 0). Exit 2 if no sidecar or the registry entry is gone.

### intent / topic / topics / fork

A session's intent (fixed) and its current topic (changes under the intent), kept in a per-session log at `topics/<type>/<session_id>.jsonl` next to the registry file. Prune and unregister never touch it. These commands run in the CLI process, not through the daemon. The session comes from `--type` and `--session-id`, or from the engine's env (`CLAUDE_CODE_SESSION_ID`, `CODEX_THREAD_ID`, `CURSOR_CONVERSATION_ID`).

```bash
agent-registry intent "Make inbox entries topic-aware"   # once per session; exit 4 if set
agent-registry intent --adopt tp-7k3q                     # a forked child binds to its topic
agent-registry topic "Decide where topic records live"    # exit 1 without an intent
agent-registry topic --done [tp-…]                        # or --park [tp-…] --ref <park id>
agent-registry topics [--session S | --open | --tree]
agent-registry fork "Retry policy" --side --brief-file brief.md [--backend cursor|herdr|none]
agent-registry topic-context                              # the hook's one-line reminder
agent-registry topic-path [--topic tp-…]                  # root-first path for the session, or from a topic; null without an intent
agent-registry topic-note asked|posted|answered|closed --topic tp-… --entry ib-… [--title|--value --via|--state] [--type T --session-id S]
```

`fork` takes exactly one of `--side` (continues the parent's intent) or `--new-intent`, and reads the brief from `--brief-file` or stdin. It writes the brief to `briefs/<tp-id>.md` and opens a visible session in `--dir` (default: the current directory). `cursor` (the default) brings the project window forward, then opens a Claude Code tab with the prompt filled in; you press Enter. `herdr` (the default when `HERDR_ENV=1`) splits a pane and starts the agent; if a Herdr step fails, the output has `launched: false` and an `error`. `none` only prints the prompt. Set `AGENT_REGISTRY_FORK_BACKEND` to `cursor`, `herdr` or `none` to pick the default backend regardless of `HERDR_ENV` (tests use `none` so a fork never opens a real tab). A missing `cursor` or `herdr` binary is reported the same way, not raised. `list` shows each row's `intent:` and `topic:`, derived from the session's log. The rules agents follow live in the `topic-awareness` skill.

`topics` skips malformed events and reads the log with `errors="replace"`; an unreadable topics directory exits 3.

`topic-path` prints `[{id, title, kind}, …]` from the root intent down to the session's current topic (or its intent), following parent links across sessions and forks; `kind` is `intent` when some session holds that topic as its intent. A missing parent or a cycle ends the walk. An unknown `--topic` exits 2. `topic-note` is how the inbox records its activity in a topic's history: `asked` and `posted` take `--title`, `answered` takes `--value` (capped at 200 characters, on write and again on read) and `--via` (web, telegram, chat, cli), `closed` takes `--state` (withdrawn, expired, superseded). The note goes to the given session's log when that session holds the topic, otherwise to the log of the session that minted it. Notes never change a topic's status; `topics` shows them under each topic's `notes` (text fields are always str or null), and `topic --done` adds `open_questions`, the entry ids asked with no `answered` or `closed` note.

Black-box checks: `.venv/bin/python -m pytest tests/blackbox/test_topics_cli.py tests/blackbox/test_topics_hook.py` (the hook file includes a `/bin/bash` 3.2 test); with real agents, `tests/blackbox/test_topics_agent.py`; by hand, `tests/blackbox/MANUAL.md`.

### summarize

Fill an empty `summary` from session metadata (+ optional transcript) via local Ollama.
Empty-only by default. Hooks call this on Stop (background) and before `end`;
unregister / prune / replace also try before archiving.

```bash
agent-registry summarize --type claude --session-id "$SESSION_ID"
agent-registry summarize --type claude --session-id "$SESSION_ID" \
  --transcript /path/to/transcript.jsonl
agent-registry summarize --type claude --session-id "$SESSION_ID" --force
```

Env: `AGENT_REGISTRY_SUMMARY_PROVIDER=auto|ollama|off` (default `auto` = Ollama if up),
`AGENT_REGISTRY_SUMMARY_MODEL` (default `gemma4:12b-mlx`), `AGENT_REGISTRY_SUMMARY_TIMEOUT`.

### register

Register a new agent session.

```bash
agent-registry register \
  --type cursor \
  --session-id "$(uuidgen)" \
  --directory ~/projects/lindris
```

Optional flags:

- `--parent-session <session_id>` — link to a parent agent session (e.g. subagent spawned by a main session).
- `--replace` — replace an existing entry with the same `session_id` instead of failing (displaced session is archived with reason `replace`).

Example output:

```json
{
  "registry_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "session_id": "...",
  "agent_type": "cursor",
  "directory": "/Users/you/projects/lindris",
  "parent_session_id": null,
  "status": "idle",
  "summary": "",
  "issue": null,
  "pr": null,
  "branch": null,
  "goflow_timer_id": null,
  "registered_at": "2026-09-24T19:50:00+00:00",
  "last_ping": "2026-09-24T19:50:00+00:00",
  "updated_at": "2026-09-24T19:50:00+00:00"
}
```

Save `registry_id` from this output for subsequent commands.

### list

List sessions split into **Active** (pinged within the last hour) and **Stale**.

Human-readable (default):

```bash
agent-registry list
```

```
Active
cursor · abc-123 · working · fixing deploy race · branch:tn/fix-deploy · ~/projects/lindris
  cursor · def-456 · reviewing · PR:"Add canary gate" · ~/projects/lindris

Stale
  (none)
```

JSON (no `registry_id` in any session object):

```bash
agent-registry list --json
```

```json
{
  "active": [
    {
      "session_id": "abc-123",
      "agent_type": "cursor",
      "directory": "/Users/you/projects/lindris",
      "status": "working",
      "summary": "fixing deploy race",
      "branch": "tn/fix-deploy",
      ...
    }
  ],
  "stale": []
}
```

`list` never prints `registry_id` — not in human output, not in `--json`. Only owner-facing commands (`register`, `update`, `ping`, `ensure` session payload, `self`) return it.

### update

Update one or more fields on a session. Requires at least one field flag.

```bash
REGISTRY_ID="<from register>"

agent-registry update "$REGISTRY_ID" \
  --status working \
  --summary "Implementing agent-registry README"

agent-registry update "$REGISTRY_ID" \
  --issue LIN-1234 \
  --branch tn/agent-registry-readme \
  --pr-title "docs: agent-registry README" \
  --pr-url "https://github.com/org/repo/pull/42"

agent-registry update "$REGISTRY_ID" \
  --directory ~/projects/agent-tools \
  --goflow-timer timer-abc \
  --parent-session parent-session-id

agent-registry update "$REGISTRY_ID" --model claude-opus-4
```

Clear optional fields:

```bash
agent-registry update "$REGISTRY_ID" --clear-issue
agent-registry update "$REGISTRY_ID" --clear-pr
agent-registry update "$REGISTRY_ID" --clear-branch
agent-registry update "$REGISTRY_ID" --clear-goflow-timer
agent-registry update "$REGISTRY_ID" --clear-summary
agent-registry update "$REGISTRY_ID" --clear-parent-session
agent-registry update "$REGISTRY_ID" --clear-model
```

`update` also refreshes `last_ping` and prints the full session JSON (including `registry_id`).

### ping

Heartbeat — updates `last_ping` and `updated_at`. Optional `--model` / `--title` record those fields (omit to leave unchanged).

```bash
agent-registry ping "$REGISTRY_ID"
agent-registry ping "$REGISTRY_ID" --model composer-2
agent-registry ping "$REGISTRY_ID" --title "auth-refactor"
```

Use periodically (e.g. every 15–30 minutes) so the session stays in the Active section of `list`. Prefer `heartbeat` when using the sidecar/hooks model.

### unregister

Remove a session from the live registry when it exits cleanly. The session snapshot is appended to `archive.jsonl` with reason `unregister` (including `registry_id` on disk for forensics).

```bash
agent-registry unregister "$REGISTRY_ID"
```

Output:

```json
{"ok": true}
```

### prune

Move stale sessions (last ping older than 1 hour) out of the live registry into `archive.jsonl` (reason `prune`). Does **not** hard-delete history — use `archive purge` for retention.

Preview what would be archived (default when `--yes` is omitted):

```bash
agent-registry prune
# same as:
agent-registry prune --dry-run
```

```json
{
  "dry_run": true,
  "sessions": [
    {
      "session_id": "old-session",
      "agent_type": "claude",
      ...
    }
  ]
}
```

Actually archive stale sessions:

```bash
agent-registry prune --yes
```

```json
{
  "dry_run": false,
  "sessions": [...]
}
```

Prune output lists archived sessions without `registry_id`, same as `list`. Dry-run does not write archive lines.

### archive

Inspect and retain history in `archive.jsonl`. Public views strip `registry_id` unless `show --full`.

```bash
agent-registry archive list
agent-registry archive list --json --reason prune --limit 50
agent-registry archive show <session_id>
agent-registry archive show <session_id> --full   # includes registry_id
agent-registry archive purge --older-than 30d --yes
```

- `list` — newest first; optional `--reason` (`unregister` | `prune` | `replace`), `--limit` (default 100), `--json`.
- `show` — latest matching `session_id`; exit 2 if missing.
- `purge` — drop archive lines older than N days (`30` or `30d`); requires `--yes`. Default retention is forever.

### dashboard

Localhost UI with Live and Archive tabs (stdlib HTTP; no mutations).

```bash
agent-registry dashboard
agent-registry dashboard --port 8765 --no-open
agent-registry dashboard --host 0.0.0.0   # prints a loud warning
```

Binds `127.0.0.1` by default (port `8765`, or next free). Opens a browser unless `--no-open`. If you override `--host` to a non-loopback address, the CLI warns: anyone who can reach the port can read session paths and summaries.

### doctor

Health checks for live/archive paths, lock, and sidecar data dir:

```bash
agent-registry doctor
```

Exit 0 if all ok, else exit 3.

### status

Counts and paths (human or JSON):

```bash
agent-registry status
agent-registry status --json
```

```
active: 2
stale: 0
archived: 14
registry: /Users/you/.local/share/agent-registry/registry.json
archive: /Users/you/.local/share/agent-registry/archive.jsonl
```

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Usage / validation error (duplicate session, invalid status, empty update, prune without `--yes` or `--dry-run`, purge without `--yes`) |
| 2 | Unknown `registry_id` or archive `session_id` not found |
| 3 | I/O or corrupt registry/archive file |
| 4 | Conflict (`intent` when the session already has one) |

## Agent skill

For integration patterns (when to register, ping cadence, field conventions), see:

```
~/projects/agent-tools/modules/registry/plugin/skills/agent-registry/SKILL.md
```

Install hooks + skill symlink: `~/projects/agent-tools/modules/registry/plugin/install`.

## Development

```bash
source .venv/bin/activate
pytest
```
