# Agent Registry Daemon and Menu-Bar App — Design

**Date:** 2026-11-16
**Status:** Approved for planning
**Repo:** `agent-registry`
**Approach:** One local daemon owns the files. The CLI, the web board, and a macOS menu-bar app are clients.

## Problem

Session state lives in `registry.json`, `archive.jsonl`, and `by-session/` sidecars. Every CLI invocation and the dashboard server open those files themselves. A menu-bar app and the board need one reader and one writer, or each new interface becomes another implementation of stale, attention, archive, and `registry_id` stripping.

Hooks already call `ensure`, `heartbeat`, and `end`. Those command lines stay. What changes is that the command reaches a long-lived process instead of opening the files.

## Goals

1. **One owner of the files.** In production, only the daemon opens `registry.json`, `archive.jsonl`, the lock file, and `by-session/`.
2. **Same commands.** Hooks and humans keep the current CLI. Output and exit codes stay the same.
3. **One read API.** The board and the menu bar use the existing loopback HTTP reads.
4. **Menu bar on the Mac.** A login item shows who is working and opens the existing board. It does not own the daemon.

## Non-goals

- A Rust rewrite of session logic.
- The CLI writing the files when the daemon cannot start.
- A prune-all button, or any action that archives or kills a session's children along with it.
- Desktop notifications.
- A Dock icon while the board window is closed.
- Linux or Windows menu-bar apps.
- SQLite, remote bind, or a second public REST shape for writes.
- Changing hook command lines.

## Slices

Implementation is two plans, in order. This document covers both.

1. **Daemon and CLI.** The daemon serves the API and the current board. CLI commands become clients.
2. **Menu-bar app.** A Tauri client of that API. It waits until slice 1 is the only door to the files.

## Architecture

```
Hooks and humans                Menu-bar app (macOS, slice 2)
agent-registry ensure|list|…    glance panel, Open board
        │                                │
        └──────────── HTTP ──────────────┘
                         │
                         ▼
              Daemon  127.0.0.1:8765
              Python session logic (ops, lifecycle,
              archive, summarize, resolve, wake)
                         │
                         ▼
              registry.json
              archive.jsonl
              by-session/
```

The session logic stays in the Python modules that implement it today. The daemon process is the only production caller. Unit tests of those modules still call them in-process.

`resolve` and `wake` run inside the daemon. They read registry rows, so a CLI-side copy would be a second reader.

## Daemon

### Process

- Python, loopback only: `127.0.0.1` and port **8765**.
- `ThreadingHTTPServer`, so overlapping hook calls are accepted. `ops` file locks still serialize writes. Summarize and wake do their slow work outside the lock, as they do today.
- Foreground command, used by launchd and by hand: `agent-registry daemon`.
- The listening socket is the single-owner lock.
- After a successful bind, the daemon writes `<registry-dir>/daemon.pid` and `<registry-dir>/daemon.port`, and removes both on a clean shutdown. Logs go to `<registry-dir>/daemon.log`. `<registry-dir>` is the directory of the live registry file, so `AGENT_REGISTRY_PATH` keeps tests and overrides in one place.

One daemon per registry directory. If `daemon.pid` is alive, clients use `daemon.port`. A `--port` or `AGENT_REGISTRY_DAEMON_PORT` that disagrees with that live port exits 1 and does not start a second writer.

A second start that can already see our `/api/health` exits 0 and does not listen. If bind fails because the port is taken, the process checks `/api/health` once: our service exits 0, anything else exits 3.

### Address

Default port 8765. `AGENT_REGISTRY_DAEMON_PORT` or `--port` on `daemon` and `dashboard` sets the port only when no daemon is already live for this registry. A live daemon's `daemon.port` wins.

`dashboard --host` is rejected with exit 1. The daemon does not bind a non-loopback address.

There is no port scan. Today's "try 8765 through 8775" behavior goes away.

### Launchd

macOS only.

- `agent-registry daemon install` writes `~/Library/LaunchAgents/com.tjdsneto.agent-registry.plist` with `RunAtLoad` and `KeepAlive`, then bootstraps it. The program is the same `agent-registry` binary, argument `daemon`.
- A crash is restarted by `KeepAlive`.
- `agent-registry daemon stop` sends SIGTERM to `daemon.pid` and bootouts the LaunchAgent, so KeepAlive does not immediately bring it back.
- `agent-registry daemon start` bootstraps the LaunchAgent again when it is installed, otherwise spawns a detached daemon.
- `agent-registry daemon uninstall` bootouts the agent and deletes the plist.
- `daemon install` on a non-macOS machine exits 1 with a clear message. `agent-registry daemon` in the foreground still runs.

### HTTP

**Read API**, used by the board and the menu bar. Responses omit `registry_id`.

| Method | Path | Body |
|--------|------|------|
| GET | `/api/health` | `{"ok": true, "service": "agent-registry"}` |
| GET | `/api/live` | Today's `live_views` shape: `active`, `stale`, `attention`. Corrupt file: those lists empty and `"corrupt": true`. |
| GET | `/api/archive` | Today's archive shape, including `corrupt`. |
| GET | `/` | The existing `dashboard.html` board. |

**Command API**, used by the CLI. One endpoint, not a public resource-per-command API.

`POST /api/command`

```json
{ "op": "ensure", "params": {} }
```

Response is HTTP 200 when the daemon handled the operation, including usage and not-found failures:

```json
{ "exit_code": 0, "data": {}, "error": null }
```

`exit_code` uses today's codes: 0 success, 1 usage, 2 not found, 3 I/O or corrupt. `data` is the structured result: the session object, the list split, the archive events, the status payload, or the resolve/wake result. `error` is the message the CLI prints to stderr today, without the `agent-registry: ` prefix. The CLI turns `data` into the stdout it prints today, including human formatting for `list`, `archive list`, and `status`.

Owner results (`ensure`, `self`, `update`, `ping`, `register`, and `archive show --full`) still include `registry_id`. Loopback is the trust boundary. The files are already readable by this user.

`summarize` stays fail-open: the daemon returns exit 0 when Ollama is down, and an empty summary stays empty.

## CLI

Every current command that reads or writes registry state goes through `POST /api/command`: register, update, ping, unregister, list, prune, ensure, heartbeat, end, self, summarize, archive, resolve, wake, and the data behind status and doctor.

`dashboard` ensures the daemon is up, then opens `http://127.0.0.1:<port>/` unless `--no-open` is set. It does not serve HTTP itself.

Doctor:

- The CLI checks that the registry parent directory is writable.
- The daemon reports lock, archive path, and sidecar directory.
- The CLI checks `/api/health`.
- Exit 0 only when every check passed. Otherwise exit 3.

### Start if down

Used by every CLI command that needs the daemon, and by the menu-bar app.

1. If `daemon.pid` is alive, use `daemon.port`. A requested port that differs exits 1.
2. `GET /api/health` on that port.
3. If the connection is accepted and the body is not our health document, exit 3. Do not spawn a daemon. Do not open the registry files.
4. If the connection is refused, the CLI re-execs itself as `agent-registry daemon` in a new session, inheriting `AGENT_REGISTRY_PATH` and the port. Stdout and stderr append to `daemon.log`.
5. Poll `/api/health` every 100ms until it returns `service: agent-registry`, or until the timeout. The timeout is 5 seconds. `AGENT_REGISTRY_DAEMON_START_TIMEOUT` overrides it, including in tests. The success path returns as soon as health answers.
6. If health arrives, retry the original command once.
7. If health never arrives, exit 3 with a clear message. Do not open the registry files.

## Session facts

Every public session keeps the identity it has today: `session_id`, `agent_type`, `title`, `peer_name`, `directory`, `parent_session_id`, `status`, `summary`, and `pid` when the harness recorded one. `registry_id` stays off public reads.

The board and the menu-bar panel start each row with a mark for the engine: Claude, Codex, or Cursor. The row also shows the session name (`peer_name`), the title, the session id, and the directory.

`pid` is the harness process id. Claude records one. Codex and Cursor do not, and those rows leave it blank. The link between sessions is `parent_session_id`. The registry does not infer a parent from OS process parentage.

### CPU, memory, and tokens

The daemon fills these when it builds `/api/live`. It does not write them back into `registry.json`.

- `cpu_percent` and `memory_bytes` come from `ps` for a live `pid`. No pid, or a dead pid, means the fields are omitted.
- `tokens` is omitted when that engine has no reader.
- Claude: sum `message.usage` across the session transcript. Each request's `input_tokens`, `output_tokens`, `cache_read_input_tokens`, and `cache_creation_input_tokens` are consumption, so they add. The transcript parse is cached for 5 seconds per session.
- Codex: the latest `payload.info.total_token_usage` on the rollout (`input_tokens`, `output_tokens`, `cached_input_tokens`, `cache_write_input_tokens`, `total_tokens`). Same 5 second cache.
- Cursor: no token reader in v1. The row hides the number.

The board poll picks up a new snapshot on its existing 5 second cycle. The number on the row is Claude's summed input plus output, or Codex's `total_tokens`.

### Parent and child sessions

`parent_session_id` is the parent's public `session_id`. `ensure` and `register` still set it from `--parent-session`.

The board and the menu-bar panel keep today's nesting. A child is indented under its parent when that parent is in the same list. A child whose parent is absent stays visible and shows the parent id. CLI `list` keeps its current parent-then-child order.

Archive and Kill act on that one session. Children stay in the live registry and become orphans if their parent leaves.

### Row actions

Actions live on the board row. The menu-bar panel shows the facts and **Open board**. It does not archive, kill, or send.

The board passes `session_id`. The daemon looks up `registry_id` itself. Responses still omit `registry_id`.

| Action | When it shows | What it does |
|--------|----------------|--------------|
| Archive | Every engine | `unregister` for that session. The row leaves the live list and is appended to the archive. |
| Kill | `pid` is alive | SIGTERM that pid only, then `unregister`. Codex and Cursor have no pid, so they have no Kill button. |
| Send | Claude, Codex, and Cursor | `wake` with the message the user types. Claude nudges a live session. Codex queues into a live thread and resumes a dead one. Cursor starts a headless resume. |

## Menu-bar app (slice 2)

Tauri 2 app in `desktop/`. macOS only.

- Login item of its own. It does not replace `com.tjdsneto.agent-registry`.
- Starts at login. Quitting the app leaves the daemon running.
- No Dock icon while the board window is closed. Opening the board window switches the app to a regular activation policy so the Dock icon shows. Closing that window returns to accessory policy, and the menu-bar icon is the only presence.
- The status item opens a small panel. The panel `GET`s `/api/live`.
- Attention rows first: blocked or stale, taken from `attention`. The header is `N need attention` and is hidden at 0.
- Active rows after that, from `active`. A blocked session appears only in attention, matching `live_views`. The panel does not render the `stale` array, so a stale row is not shown twice.
- Rows nest children under their parent, the same way the board does.
- Each row starts with the engine mark, then name, title, status, project, summary, directory, token total when present, CPU and memory when a pid is alive, and age since `last_ping`.
- One action: **Open board**. It opens a window whose webview loads `http://127.0.0.1:<port>/`. Archive, Kill, and Send stay on the board.
- The panel polls `/api/live` every 5 seconds while the panel is visible, and stops when it closes. The board page keeps its own poll.
- If the daemon is down, the app uses the same start-if-down rule, then loads. If that fails, the panel shows the failure. It does not read the JSON files.
- No `registry_id`. No notifications. No prune-all control.

## Failure rules

| Situation | Result |
|-----------|--------|
| Daemon down, then healthy within 5 seconds | Command or panel proceeds |
| Daemon still down after the timeout | Exit 3, or an error in the panel. Files are untouched |
| Port held by a non-registry process | Exit 3. Do not spawn. Files are untouched |
| Two daemons start together | One binds. The other exits 0 when health is already ours |
| Corrupt `registry.json` | Writes fail with exit 3 and do not repair the file. `/api/live` returns empty lists and `corrupt: true` |
| Ollama down during summarize | Exit 0, summary unchanged |
| Menu-bar app quits | Daemon keeps running |
| Daemon crash under launchd | KeepAlive starts it again |
| `daemon stop` | SIGTERM, then launchd bootout so it stays stopped until `daemon start` or the next login |

## Testing

Ops, archive, lifecycle, and model tests stay in-process and do not start a daemon.

Slice 1 adds automated tests:

- `/api/health` returns the service name.
- `/api/live` and `/api/archive` match today's shapes and contain no `registry_id`.
- A corrupt registry yields `corrupt: true` on the live read and does not get rewritten by a failed update.
- `main()` roundtrip for ensure, list, and end through the daemon, using the test's `AGENT_REGISTRY_PATH` and a free `AGENT_REGISTRY_DAEMON_PORT`.
- A command issued with nothing listening starts the daemon and succeeds.
- A second daemon process exits without binding a second socket.
- A stranger on the port makes the command exit 3, and the registry file's contents are unchanged.
- `dashboard --no-open` leaves the existing daemon as the only listener.
- The start timeout used on the failure path is the test override, not a 5 second sleep.
- A session registered with `--parent-session` keeps that `parent_session_id` on the public read. Archive of the parent leaves the child in the live list.

Existing `main()` tests keep calling `main()`. They get a daemon via start-if-down on the temp registry and temp port. They do not gain a direct-file fallback.

Slice 2 is a manual script, not an automated UI test:

1. Install the daemon and the app as login items. Log in. The menu-bar icon is present and the daemon answers `/api/health`.
2. With one blocked session and one working session, the panel shows the blocked session under attention and the working session under active.
3. Open board shows the Live and Archive page, and the Dock icon appears.
4. Close the board. The Dock icon is gone. The menu-bar icon remains. `/api/health` still answers.
5. Quit the menu-bar app. `/api/health` still answers.
6. A child session is indented under its parent in the panel and on the board. After the parent is archived, the child remains and shows the parent id.

### Black box

`pytest tests/blackbox` starts a real Claude session and spends tokens. Default `pytest` does not collect that directory, so a unit run stays hermetic.

The test sets `AGENT_REGISTRY_PATH` to a temp registry and starts the daemon on a free port, then runs `claude -p` with a one-line prompt. Hooks register the session into that registry. The test waits until `/api/live` shows the session id and directory, then until the Claude token snapshot has `output_tokens` greater than 0. A headless browser loads the board and sees the Claude mark, that session id, and the token number. The Claude process is then stopped. The test fails if `claude` is not logged in. It does not skip.

## Defaults this design locks

- Public reads omit `registry_id`. Owner command results still include it.
- The glance uses `live_views`. CLI `list` keeps `list_split`.
- Production wait for a daemon to become healthy is 5 seconds.
- The board UI stays `agent_registry/static/dashboard.html`, served by the daemon.
- Parent and child stay a `parent_session_id` link. Archive and Kill do not cascade.
- CPU, memory, and tokens are computed for the read API and are not stored in `registry.json`.
- The real-token check is `pytest tests/blackbox`, not the default unit run.
