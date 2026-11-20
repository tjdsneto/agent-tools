# Menu-bar manual check

Prerequisite: the registry daemon is answering on port 8765, and the menu app is installed at `~/Applications/Agent Registry.app` (or `cargo tauri dev` is running from `desktop/src-tauri` on macOS).

Build/install: from `desktop/src-tauri`, `cargo tauri build --bundles app`, then copy `target/release/bundle/macos/Agent Registry.app` to `~/Applications/`, and point `~/Library/LaunchAgents/com.tjdsneto.agent-registry.menu.plist` at that app’s `Contents/MacOS/agent-registry-menu`.

1. The menu bar shows a slate tile with three bars — green, gold, coral — and no title text (on a second display's menu bar, if the Mac has one). The Dock icon is absent. `curl -s http://127.0.0.1:8765/api/health` returns `"service":"agent-registry"`.
2. Click the tile. The page opens on Loading, then a project list on the left and that project's sessions on the right. The version `0.1.0` is at the bottom of the project list. The Dock shows that same tile.
3. Close the board window. The Dock icon is gone. The menu-bar icon remains. `/api/health` still answers.
4. Quit from the tray menu (right-click the tile). `/api/health` still answers. `~/Library/LaunchAgents/com.tjdsneto.agent-registry.plist` is still the daemon's plist.
