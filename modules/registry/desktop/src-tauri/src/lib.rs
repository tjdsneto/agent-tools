use tauri::image::Image;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};
use tauri::{
    ActivationPolicy, AppHandle, Manager, WebviewUrl, WebviewWindowBuilder, RunEvent, WindowEvent,
};

mod daemon_client;
#[cfg(test)]
mod rows;
#[cfg(target_os = "macos")]
mod tray_arm;

/// Two click deliveries (the status button and the tray event) arrive for one
/// physical click. A second one inside this window is the same click.
const SAME_CLICK: u64 = 300;

static LAST_OPEN_MS: AtomicU64 = AtomicU64::new(0);

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

fn same_click(previous_ms: u64, now_ms: u64) -> bool {
    now_ms.saturating_sub(previous_ms) < SAME_CLICK
}

fn accept_open() -> bool {
    let now = now_ms();
    let previous = LAST_OPEN_MS.load(Ordering::SeqCst);
    if same_click(previous, now) {
        return false;
    }
    LAST_OPEN_MS.store(now, Ordering::SeqCst);
    true
}

/// Open or focus the board. One physical click is handled once.
fn open_app(app: &AppHandle) {
    if !accept_open() {
        return;
    }
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        let _ = open_board(app).await;
    });
}

/// The board is served by the daemon; the window loads that origin only.
fn board_url(port: u16) -> String {
    format!("http://127.0.0.1:{port}/")
}

/// Ensure the daemon is up, show the Dock icon, and open (or focus) the board.
/// Returns the board URL.
///
/// Daemon I/O stays off the UI thread; AppKit / window work must run on main
/// (otherwise macOS traps with "Must only be used from the main thread").
async fn open_board(app: AppHandle) -> Result<String, String> {
    let port = tauri::async_runtime::spawn_blocking(|| daemon_client::ensure_daemon(None))
        .await
        .map_err(|e| e.to_string())??;
    let url = board_url(port);

    let (tx, rx) = std::sync::mpsc::channel();
    let app_ui = app.clone();
    let url_ui = url.clone();
    app.run_on_main_thread(move || {
        let _ = tx.send(show_or_create_board(app_ui, url_ui));
    })
    .map_err(|e| e.to_string())?;
    rx.recv().map_err(|e| e.to_string())?
}

/// AppKit / Tauri window work — call only from the main thread.
fn show_or_create_board(app: AppHandle, url: String) -> Result<String, String> {
    #[cfg(target_os = "macos")]
    {
        app.set_activation_policy(ActivationPolicy::Regular)
            .map_err(|e| e.to_string())?;
        tray_arm::set_dock_icon();
    }

    if let Some(board) = app.get_webview_window("board") {
        // A closed board can linger in the manager. Reusing it leaves the
        // webview stuck on Loading; destroy and build a fresh one instead.
        let visible = board.is_visible().unwrap_or(false);
        if visible {
            board.set_focus().map_err(|e| e.to_string())?;
            #[cfg(target_os = "macos")]
            tray_arm::order_front(&board);
            return Ok(url);
        }
        let _ = board.destroy();
    }

    let external = url.parse::<tauri::Url>().map_err(|e| e.to_string())?;
    let board = WebviewWindowBuilder::new(&app, "board", WebviewUrl::External(external))
        .title("Agent Registry")
        .inner_size(1100.0, 800.0)
        .build()
        .map_err(|e| e.to_string())?;
    board.show().map_err(|e| e.to_string())?;
    board.set_focus().map_err(|e| e.to_string())?;
    #[cfg(target_os = "macos")]
    tray_arm::order_front(&board);

    // Closing the board drops the Dock icon again. It never stops the daemon or
    // the tray: the tray process owns neither.
    let handle = app.clone();
    board.on_window_event(move |event| {
        if let WindowEvent::CloseRequested { .. } = event {
            #[cfg(target_os = "macos")]
            let _ = handle.set_activation_policy(ActivationPolicy::Accessory);
            #[cfg(not(target_os = "macos"))]
            let _ = &handle;
        }
    });
    Ok(url)
}

/// An exit request with no code is Tauri noticing the last window closed. The
/// tray must outlive its windows; an explicit exit (Quit) carries a code.
fn keeps_tray_alive(code: Option<i32>) -> bool {
    code.is_none()
}

/// The login item is named after the menu's own Tauri identifier, so its
/// LaunchAgent is `com.tjdsneto.agent-registry.menu` and never the daemon's.
fn autostart_plugin() -> tauri::plugin::TauriPlugin<tauri::Wry> {
    let builder = tauri_plugin_autostart::Builder::new().app_name("com.tjdsneto.agent-registry.menu");
    #[cfg(target_os = "macos")]
    let builder = builder.macos_launcher(tauri_plugin_autostart::MacosLauncher::LaunchAgent);
    builder.build()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(autostart_plugin())
        .setup(move |app| {
            #[cfg(target_os = "macos")]
            app.set_activation_policy(ActivationPolicy::Accessory);

            // Start the menu bar at login. This registers only the menu app's own
            // login item; it never touches the daemon's LaunchAgent.
            {
                use tauri_plugin_autostart::ManagerExt;
                let autostart = app.autolaunch();
                if !autostart.is_enabled().unwrap_or(false) {
                    let _ = autostart.enable();
                }
            }

            let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&quit])?;
            let icon = Image::from_bytes(include_bytes!("../icons/tray.png"))?;
            let tray = TrayIconBuilder::with_id("registry")
                .icon(icon)
                .icon_as_template(false)
                .tooltip("Agent Registry")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| {
                    if event.id().as_ref() == "quit" {
                        app.exit(0);
                    }
                })
                .on_tray_icon_event(move |tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        open_app(tray.app_handle());
                    }
                })
                .build(app)?;
            // The status item's click catcher does not receive the click, so the
            // button itself is wired to open the board. See tray_arm.
            #[cfg(target_os = "macos")]
            tray_arm::install(&tray);
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("agent-registry menu")
        .run(|_app, event| {
            if let RunEvent::ExitRequested { code, api, .. } = event {
                if keeps_tray_alive(code) {
                    api.prevent_exit();
                }
            }
        });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn board_url_is_the_daemon_origin() {
        assert_eq!(board_url(7777), "http://127.0.0.1:7777/");
    }

    #[test]
    fn only_a_codeless_exit_request_is_kept_alive() {
        assert!(keeps_tray_alive(None));
        assert!(!keeps_tray_alive(Some(0)));
    }

    #[test]
    fn a_second_delivery_of_the_same_click_is_ignored() {
        assert!(same_click(1_000, 1_200));
        assert!(!same_click(1_000, 1_300));
    }
}
