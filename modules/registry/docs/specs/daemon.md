# Registry daemon

> **Scope:** `src/agent_registry/daemon.py`, `client.py`, `usage.py`, the daemon and dashboard commands in `cli.py`, and `static/dashboard.html`.
> **Baseline:** main @ a2b7d8b

Loopback daemon, CLI client, live usage, and board session actions. Each line below states what the code does and ends with the function that does it.

## Ownership

- The daemon is the only production opener of `registry.json`, `archive.jsonl`, the lock, and `by-session/`. The CLI never opens them; it forwards every command. — `agent_registry.daemon.dispatch`
- Tests of `ops`, `lifecycle`, `archive`, and `store` may still open the same files in-process. Nothing in `ops` or `store` forbids it. — `agent_registry.store.transact`

## CLI path

- Every CLI command except `daemon` and `dashboard` builds an `(op, params)` pair and sends it with `agent_registry.client.call`. The daemon runs it with `agent_registry.daemon.dispatch`. — `agent_registry.cli.main`
- `client.call` starts a detached `daemon run` when the port refuses the connection, waits for a healthy answer, then POSTs the command. A port that answers but is not this service is exit 3, and a live `daemon.pid` on a different port is exit 1. — `agent_registry.client.ensure_daemon`
- Port order: the live daemon's `daemon.port`, then the explicit argument, then `AGENT_REGISTRY_DAEMON_PORT`, then 8765. — `agent_registry.client._resolve_port`
- `dispatch` returns `(exit_code, data, error)`. Params that `_prepare_command` rejects (a missing key, or a non-string where it checks) and an unknown op are exit 1. Not every op type-checks its params. — `agent_registry.daemon.dispatch`
- An exception raised inside an op that `do_POST` does not map to a specific code, such as an `AttributeError` from a mistyped `end` `agent_type`, is exit 3, and the traceback is printed on the daemon's stderr. — `agent_registry.daemon.DaemonHandler.do_POST`
- `daemon run` on a port already held by this service exits 0 and leaves the first daemon in place. — `agent_registry.daemon.run_foreground`

## Dashboard

- `agent-registry dashboard` calls `client.ensure_daemon`, prints `http://127.0.0.1:<port>/`, opens it with `webbrowser.open` unless `--no-open` (which skips only the open, not the print), and binds no server of its own. A non-loopback `--host` is exit 1. — `agent_registry.cli._dashboard`
- The daemon serves `/api/health`, `/api/live`, `/api/archive`, and `POST /api/command`. `/api/health` answers `{"ok": true, "service": "agent-registry"}`. — `agent_registry.daemon.DaemonHandler.do_GET`
- `/api/live` returns `active`, `stale`, and `attention` with usage attached to each row. A corrupt registry returns empty lists with `corrupt: true`. — `agent_registry.daemon.DaemonHandler._serve_live`
- `/api/archive` takes `reason` and `limit`; a bad `limit` is HTTP 400. — `agent_registry.dashboard.DashboardHandler._serve_archive`
- The board stays on Loading until the first live and archive fetch settles, then shows the page. A failed fetch still leaves the page, with the error banner. It polls every 1.5 seconds while the tab is visible. — `poll`, `reveal`
- The left sidebar lists All, then each project on the registry rows. A project's name is its `project` field. The badge is how many of that project's sessions have a process open. Choosing one filters Live, Stopped, and Archive to that project. The choice is kept in `localStorage` under `agent-registry.project`. — `renderProjects`
- Live is a session whose `pid` `ps` could sample, so the row has `cpu_percent`, or a Cursor chat selected in a Cursor window that is open. A Cursor chat has no process of its own. An open chat that was never registered is registered on this read, with the workspace directory and the composer name when Cursor has one. — `usage.open_cursor_chats`, `DaemonHandler._include_open_cursor_chats`, `processOpen`
- Multi-root Cursor windows: the title ends with ` (Workspace)`; strip that when matching. `workspace.json` may use a `workspace` URI to a `.code-workspace` file instead of `folder` — resolve that to the file's parent directory. — `usage._window_project_name`, `usage._workspace_directory`
- On the same live read, every registered Cursor row gets its `title` filled or refreshed from Cursor's composer `name` in `state.vscdb` when that name is present and differs from the stored title. That name is the harness display title, not `summary`. Lookup order: `composerHeaders`, then `cursorDiskKV` `composerData:<id>` when the header row is missing. — `usage.cursor_composer_names`, `DaemonHandler._sync_cursor_titles`
- Claude rows with an empty `title` are backfilled from the session jsonl: latest `custom-title`/`customTitle`, else latest `ai-title`/`aiTitle`. Cap how many scans run per live poll; prefer rows with a `pid`. — `usage.claude_session_title`, `DaemonHandler._sync_claude_titles`
- Those sessions are on the Stopped tab. — `renderStopped`
- The circle is amber for a live idle session, green for working, blue for reviewing, and red for blocked. Stopped is a gray circle. Archive is an empty ring. The word on a live idle session is idle. — `dotStatus`
- Dragging the sidebar edge sets its width, kept in `localStorage` under `agent-registry.sidebarWidth`, between 160 and 520. A double-click returns it to 220. — `setupSidebarResize`
- The selected project's heading shows its directory. When every session directory sits inside the shortest one, that path is shown. Otherwise each directory is shown. — `dirsFor`
- The loading screen and the bottom of the sidebar show `APP_VERSION`, the same string as `agent_registry.__version__`.

## Loopback

- The daemon refuses to bind any host outside `127.0.0.1`, `localhost`, and `::1`. — `agent_registry.daemon.make_daemon`
- `POST /api/command` requires `Content-Type: application/json` and a loopback `Host`. Otherwise the envelope carries exit 1. — `agent_registry.daemon.DaemonHandler.do_POST`
- Any other POST path is 404. — `agent_registry.daemon.DaemonHandler.do_POST`
- The client opens every request through an opener with an empty proxy map, so `HTTP_PROXY`, `HTTPS_PROXY`, and `ALL_PROXY` are not honored. — `agent_registry.client._OPENER`
- The command envelope is `{"exit_code", "data", "error"}`. Exceptions map to codes: validation and unsupported transport to 1, unknown registry id and unknown session to 2, corrupt registry and I/O to 3. — `agent_registry.daemon.DaemonHandler.do_POST`

## Usage

- Usage fields are added when a view is served and are never written back to the registry. — `agent_registry.usage.attach_usage`
- CPU and memory come from `ps -o pcpu=,rss=` and are attached only when the row has a positive integer `pid` and `ps` returns a sample, so a dead pid gets neither. — `agent_registry.usage.sample_process`
- Claude: `tokens` sums `input_tokens`, `output_tokens`, `cache_read_input_tokens`, and `cache_creation_input_tokens` from each `message.usage` in `<session_id>.jsonl` under `~/.claude/projects/*/`. Other keys are ignored. A numeric value counts (a float is truncated); anything else counts as 0. No usage entry at all gives no `tokens`. — `agent_registry.usage._sum_claude` via `claude_tokens`
- Codex: `tokens` comes from `total_token_usage` in a rollout file named `rollout-<timestamp>-<session_id>.jsonl` (or `rollout-x-<session_id>.jsonl`) with the full session id. Only integer (non-bool) values for `input_tokens`, `output_tokens`, `cached_input_tokens`, `cache_write_input_tokens`, `reasoning_output_tokens`, and `total_tokens` are kept. The last object with at least one such field wins, and when a file has none, the next older matching file is tried. — `agent_registry.usage.codex_tokens`
- Cursor has no token reader, so its rows carry no `tokens`. — `agent_registry.usage.tokens_for`
- Default-home token reads are cached for 5 seconds per agent type and session id. — `agent_registry.usage._cached`

## Board session actions

- The board posts `session_id` and never `registry_id`. The daemon looks the row up by `session_id`, and a `registry_id` in the request is ignored. Public views drop `registry_id`. — `agent_registry.daemon._session_by_id`
- Archive unregisters only that session. It does not touch children or the parent. An unknown session is exit 2. — `agent_registry.daemon._prepare_command` (`archive_session`)
- Kill sends SIGTERM to only that session's pid, and only when `usage.sample_process` returns a sample. It then unregisters that session and no other. A missing pid, a pid with no sample, or a pid that vanishes before the signal is exit 1 and leaves the row in place. An unknown session is exit 2. — `agent_registry.daemon._prepare_command` (`kill_session`)
- Send Message is `send_session` → `transport.wake`. The board opens a modal for the message (no `prompt()`). An empty or whitespace message is exit 1 and does not call `wake`. A `wake` result other than `landed` or `already_awake` is exit 1. — `agent_registry.daemon._prepare_command` (`send_session`), `static/dashboard.html` `openSendModal`
- Open is `open_workspace`: resolve the session's directory and open it in Cursor (`cursor -r` or `open -a Cursor`). Workspace-only — does not select a chat. Missing session/directory is exit 2/1. — `agent_registry.daemon._prepare_command` (`open_workspace`)
- Claude live rows may carry `interrupt_reason` (`rate_limit` or `token_limit`) from the newest matching jsonl API error/notice. The board shows Resume when set; Resume opens the Send Message modal with a continue prefill. — `usage.claude_interrupt_reason`, `static/dashboard.html` `resumeBtnAction`
- The board shows Kill only for a positive numeric `pid`, Send Message for claude/codex/cursor, and Open when a directory is present. Engine type appears as the icon only (not repeated as a meta word). — `static/dashboard.html` `killBtn`, `sendBtn`, `openBtn`, `metaBits`
- The board sends no Send Message request for an empty modal. — `static/dashboard.html` `send-modal-submit`
- Engine marks are the Claude, OpenAI, and Cursor icons, in a span with class `engine-{type}`. An unknown type keeps its first letter. — `static/dashboard.html` `engineMark`
- The parent link stays `parent_session_id`; the board nests a row under the row whose `session_id` matches it, and marks the row an orphan when no such row is listed. — `static/dashboard.html` `buildForest`, `renderForest`

## Service lifecycle

- `daemon install` is macOS only and is exit 1 elsewhere, before any registry read or write. — `agent_registry.cli._daemon`
- `daemon install` writes `~/Library/LaunchAgents/com.tjdsneto.agent-registry.plist` and bootstraps it into `gui/<uid>`. The label is `com.tjdsneto.agent-registry`, with `RunAtLoad` and `KeepAlive` true and program arguments `daemon run`. Logs go to `daemon.log` beside the registry. — `agent_registry.client.install_launchd`
- `daemon uninstall` boots the plist out and deletes it; a missing plist is success. — `agent_registry.client.uninstall_launchd`
- `daemon start` bootstraps an installed plist, or spawns a detached daemon when none is installed. — `agent_registry.client.start_daemon`
- `daemon stop` sends SIGTERM to the pid in `daemon.pid` when that pid is alive, then boots the plist out when one is installed, so `KeepAlive` does not restart it. — `agent_registry.client.stop_daemon`
- A running daemon writes `daemon.pid` and `daemon.port` beside the registry and removes both on a clean exit. — `agent_registry.daemon.run_foreground`

## Notes outside the behavior-line rule

- The menu-bar client is `desktop/` and [menu-bar.md](menu-bar.md). It does not open `registry.json`.
- No CLI command calls `agent_registry.dashboard.run_dashboard`. — `agent_registry.cli.main`
- `DaemonHandler` subclasses `DashboardHandler` and serves its `/` and `/api/archive` routes by inheritance. — `agent_registry.daemon.DaemonHandler`
- Default `pytest` does not collect `tests/blackbox`. `pytest tests/blackbox -q` runs `test_claude_session_shows_tokens_on_the_board`. The HTML shell contains `engine-claude` and `tokens` and does not contain the token digits; those are on `/api/live`.
