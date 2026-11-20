//! The menu-bar click catcher Tauri installs is a subview of the status
//! button, and that subview does not receive the click. The button does.
//! Point the button's action at the board.

use std::sync::OnceLock;

use objc2::rc::Retained;
use objc2::runtime::{AnyObject, NSObject};
use objc2::{define_class, msg_send, sel, AllocAnyThread, MainThreadMarker};
use objc2_app_kit::{NSApplication, NSImage, NSView, NSWindow};
use objc2_foundation::NSData;
use tauri::tray::TrayIcon;
use tauri::{AppHandle, WebviewWindow};

struct TrayClickState {
    app: AppHandle,
}

static TRAY_CLICK: OnceLock<TrayClickState> = OnceLock::new();

define_class!(
    #[unsafe(super(NSObject))]
    #[name = "AgentRegistryTrayClick"]
    struct TrayClick;

    impl TrayClick {
        #[unsafe(method(clicked:))]
        fn clicked(&self, _sender: Option<&AnyObject>) {
            open_from_button();
        }
    }
);

fn proxy() -> &'static Retained<TrayClick> {
    static PROXY: OnceLock<Retained<TrayClick>> = OnceLock::new();
    PROXY.get_or_init(|| {
        let allocated = TrayClick::alloc().set_ivars(());
        unsafe { msg_send![super(allocated), init] }
    })
}

fn open_from_button() {
    let Some(state) = TRAY_CLICK.get() else {
        return;
    };
    super::open_app(&state.app);
}

/// Remember the tray and aim its status button at the board.
pub fn install(tray: &TrayIcon) {
    let app = tray.app_handle().clone();
    let _ = TRAY_CLICK.set(TrayClickState { app: app.clone() });
    arm();
    let _ = app.run_on_main_thread(arm);
}

/// The Dock icon while the board is open. A slate tile with three bars: green, gold, coral.
pub fn set_dock_icon() {
    let Some(mtm) = MainThreadMarker::new() else {
        return;
    };
    let data = NSData::with_bytes(include_bytes!("../icons/dock.png"));
    let Some(image) = NSImage::initWithData(NSImage::alloc(), &data) else {
        return;
    };
    unsafe {
        NSApplication::sharedApplication(mtm).setApplicationIconImage(Some(&image));
    }
}

/// Bring an accessory-app window in front. `show` alone leaves it hidden.
pub fn order_front(window: &WebviewWindow) {
    let Ok(ptr) = window.ns_window() else {
        return;
    };
    if ptr.is_null() {
        return;
    }
    let win = ptr as *mut AnyObject;
    unsafe {
        let _: () = msg_send![win, orderFrontRegardless];
    }
}

fn arm() {
    let Some(mtm) = MainThreadMarker::new() else {
        return;
    };
    let windows = NSApplication::sharedApplication(mtm).windows();
    let mut wired = false;
    for i in 0..windows.count() {
        let window = windows.objectAtIndex(i);
        if let Some(content) = window.contentView() {
            if wire_targets(&content) {
                wired = true;
            }
        }
    }
    if wired {
        return;
    }
    // The click catcher was not in the hierarchy yet. A short status-item
    // window is still the button that receives the click.
    for i in 0..windows.count() {
        let window = windows.objectAtIndex(i);
        if !is_status_window(&window) {
            continue;
        }
        let Some(content) = window.contentView() else {
            continue;
        };
        let subs = content.subviews();
        for j in 0..subs.count() {
            wire_button(&subs.objectAtIndex(j));
        }
    }
}

fn is_status_window(window: &NSWindow) -> bool {
    let frame = window.frame();
    frame.size.height > 0.0
        && frame.size.height <= 40.0
        && frame.size.width >= 8.0
        && frame.size.width <= 220.0
}

/// Size the click catcher to the button and aim the button at the board.
/// Returns whether a catcher was found.
fn wire_targets(view: &NSView) -> bool {
    let mut found = false;
    if view.class().name().to_bytes() == b"TaoTrayTarget" {
        if let Some(button) = unsafe { view.superview() } {
            let bounds = button.bounds();
            if bounds.size.width > 1.0 && bounds.size.height > 1.0 {
                view.setFrame(bounds);
            }
            wire_button(&button);
            found = true;
        }
    }
    let subs = view.subviews();
    for i in 0..subs.count() {
        if wire_targets(&subs.objectAtIndex(i)) {
            found = true;
        }
    }
    found
}

fn wire_button(button: &NSView) {
    let target: &AnyObject = unsafe { &*Retained::as_ptr(proxy()).cast() };
    let action = sel!(clicked:);
    unsafe {
        let _: () = msg_send![button, setTarget: Some(target)];
        let _: () = msg_send![button, setAction: Some(action)];
    }
}
