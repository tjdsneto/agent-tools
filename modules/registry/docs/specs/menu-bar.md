# Menu-bar client

> **Scope:** `desktop/src-tauri/src/lib.rs`, `tray_arm.rs`, `rows.rs`, `daemon_client.rs`, and `desktop/src-tauri/tauri.conf.json`.
> **Baseline:** main @ 5ab75b5

macOS menu-bar client of the registry daemon. Each line below states what the code does and ends with the function that does it. The manual check is `desktop/MANUAL.md`.

## Ownership

- The app does not open `registry.json`. The board window is the daemon's own page. — `lib::open_board`
- It reads `daemon.pid` and `daemon.port` beside the registry, and appends a spawned daemon's output to `daemon.log`. — `daemon_client::ensure_daemon`, `daemon_client::spawn_and_wait`
- The Tauri config declares no windows. The board is built in code. — `lib::run`

## Menu bar

- The menu bar item is a slate rounded tile with three bars — green, gold, coral — and no title text. The tile is drawn in color, not as a template image. Hover shows the tooltip Agent Registry. — `lib::run`
- Left click opens or focuses the board. It does not open a drop-down. A second delivery of that same click is ignored. — `lib::open_app`
- The status item's own button performs that click, because its click-catching subview does not receive it. — `tray_arm::install`
- The tray menu holds one item, Quit. Left click does not open the menu. Quit calls `app.exit(0)`. — `lib::run`

## Glance

The menu bar does not render a glance. `rows.rs` still builds one.

- The glance is the `attention` rows followed by the `active` rows. The `stale` array is not read, so a session listed in both is not listed twice and there is no stale list. — `rows::glance_from_live`
- `attention_count` is the length of the `attention` array. — `rows::glance_from_live`
- A body with `corrupt: true` is an error, `registry is corrupt`. A row without a `session_id` is an error. — `rows::glance_from_live`
- A row's name is the first non-empty of `peer_name`, `title`, `session_id`. — `rows::row_from`
- Marks are `C` for claude, `X` for codex, `>` for cursor, the first letter of any other non-empty agent type, and `?` when the type is empty. — `rows::mark`
- Token total is Claude `input_tokens` + `output_tokens`, Codex `total_tokens`, and none for Cursor or any other type. A missing or non-object `tokens` value has no total. An empty object totals 0 for Claude and Codex. — `rows::token_total`
- Age is seconds since `last_ping`, never below 0. — `rows::age_seconds`
- The glance carries no `registry_id`. — `rows::row_from`

## Nesting

- A row whose `parent_session_id` names a session already in the glance has depth 1 and is indented under that parent. Its parent lists it in `children`. — `rows::glance_from_live`
- A row whose parent is not in the glance stays at depth 0 and keeps `parent_session_id`. — `rows::glance_from_live`

## Board and Dock

- A menu-bar click calls `ensure_daemon` off the UI thread, then opens or focuses a window named `board` titled `Agent Registry` at 1100x800 on the main thread (activation policy, Dock icon, show/focus, `orderFrontRegardless`). — `lib::open_board`, `lib::show_or_create_board`
- The board window loads `http://127.0.0.1:{port}/` and no other URL. — `lib::board_url`
- The Dock icon is hidden at start (activation policy Accessory), becomes visible (Regular) while the board is open, and returns to Accessory when the board's close is requested. While it is visible it is that same slate tile with three bars: green, gold, coral. — `lib::run`, `lib::show_or_create_board`, `tray_arm::set_dock_icon`
- Closing the board does not stop the tray or the daemon. — `lib::open_board`
- An exit request with no code, which Tauri raises when the last window closes, is prevented. An exit with a code, as Quit sends, is not. — `lib::keeps_tray_alive`

## Daemon

- The app starts a daemon only when the port refuses a connection. It reads `daemon.pid` and `daemon.port` beside the registry first, and a live pid on a different port than the requested one is an error. — `daemon_client::ensure_daemon`
- A live pid file's `daemon.port` wins. Otherwise the port is the explicit argument, then `AGENT_REGISTRY_DAEMON_PORT`, then 8765. Opening the board passes no argument. — `daemon_client::ensure_daemon`
- A port that answers without `"service":"agent-registry"` in `/api/health` is `Stranger` and is the error `port is not agent-registry`. A refused connection is `Refused`. — `daemon_client::classify_health`
- A refused port starts `agent-registry daemon run --port <port>` with output appended to `daemon.log`, and waits up to 5 seconds (`AGENT_REGISTRY_DAEMON_START_TIMEOUT` overrides it) for a healthy answer. — `daemon_client::spawn_and_wait`
- Quit does not stop the daemon. Nothing in the app signals it or runs `launchctl`, and nothing boots out `com.tjdsneto.agent-registry`. — `lib::run`

## Login item

- The app enables its own login item at startup when it is not already enabled. — `lib::run`
- The login item is registered through the autostart plugin as a LaunchAgent under the app name `com.tjdsneto.agent-registry.menu`, which is also the Tauri identifier. The daemon's label `com.tjdsneto.agent-registry` is not used. — `lib::autostart_plugin`
- `Info.plist` sets `LSUIElement`, so login-window restore does not start a second copy beside that LaunchAgent. — `Info.plist`
