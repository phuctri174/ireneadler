//! His hand as a system-wide pointer: the real Windows cursor, on every monitor.
//!
//! The HUD tracks his hand (MediaPipe, in the main window) and sends each frame's
//! movement here; this moves the OS cursor RELATIVELY, like a mouse - so it crosses
//! from one monitor to the other past an edge, and his real mouse keeps working
//! (neither drives the other off). A dwell is a left click, a two-finger scroll is
//! the wheel. Everything goes through Windows itself - never per window - so it
//! works on her panel, in Chrome, in Explorer, anywhere.
//!
//! Only the camera drives it: the HUD refuses a synthetic (dev) hand, and nothing
//! in tests reaches this (core/tests/test_no_os_input.py). Ctrl+Alt+H turns it off.
//!
//! A small click-through ring window follows the cursor so he can see the dwell
//! fill before it clicks.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;

use tauri::{AppHandle, Emitter, Manager};

pub const RING_WINDOW: &str = "ring";
pub const EVENT_RING: &str = "irene://ring";
/// The ring window's size (physical px); centred on the cursor.
const RING_PX: i32 = 96;

/// Hand control on (Ctrl+Alt+H toggles). On by default.
pub static POINTER_ON: AtomicBool = AtomicBool::new(true);
/// Sub-pixel movement carried to the next frame, so slow hands still move.
static REMAINDER: Mutex<(f64, f64)> = Mutex::new((0.0, 0.0));
static RING_SHOWN: AtomicBool = AtomicBool::new(false);

#[repr(C)]
#[derive(Default, Clone, Copy)]
struct Point {
    x: i32,
    y: i32,
}

#[repr(C)]
#[derive(Clone, Copy)]
struct MouseInput {
    dx: i32,
    dy: i32,
    mouse_data: u32,
    flags: u32,
    time: u32,
    extra: usize,
}

/// INPUT with the mouse member of its union (the largest one on x64: 40 bytes).
#[repr(C)]
#[derive(Clone, Copy)]
struct Input {
    kind: u32,
    mi: MouseInput,
}

const INPUT_MOUSE: u32 = 0;
const MOUSEEVENTF_LEFTDOWN: u32 = 0x0002;
const MOUSEEVENTF_LEFTUP: u32 = 0x0004;
const MOUSEEVENTF_WHEEL: u32 = 0x0800;

#[link(name = "user32")]
extern "system" {
    fn GetCursorPos(point: *mut Point) -> i32;
    fn SetCursorPos(x: i32, y: i32) -> i32;
    fn SendInput(count: u32, inputs: *const Input, size: i32) -> u32;
}

fn send(flags: u32, data: i32) -> bool {
    let input = Input {
        kind: INPUT_MOUSE,
        mi: MouseInput { dx: 0, dy: 0, mouse_data: data as u32, flags, time: 0, extra: 0 },
    };
    unsafe { SendInput(1, &input, std::mem::size_of::<Input>() as i32) == 1 }
}

pub fn cursor() -> (i32, i32) {
    let mut p = Point::default();
    unsafe { GetCursorPos(&mut p) };
    (p.x, p.y)
}

/// The ring that follows the cursor: click-through, topmost, never focused.
pub fn create_ring(app: &AppHandle) {
    let built = tauri::WebviewWindowBuilder::new(app, RING_WINDOW, tauri::WebviewUrl::App("index.html?view=ring".into()))
        .title("Irene - pointer")
        .additional_browser_args(crate::BROWSER_ARGS)
        .decorations(false)
        .transparent(true)
        .shadow(false)
        .resizable(false)
        .skip_taskbar(true)
        .focused(false)
        .always_on_top(true)
        .visible(false)
        .inner_size(RING_PX as f64, RING_PX as f64)
        .build();
    match built {
        Ok(ring) => {
            let _ = ring.set_ignore_cursor_events(true);
            let _ = ring.set_size(tauri::PhysicalSize::new(RING_PX as u32, RING_PX as u32));
        }
        Err(error) => eprintln!("[irene] pointer ring window failed: {error}"),
    }
}

pub fn hide_ring(app: &AppHandle) {
    place_ring(app, None, 0.0, "");
}

fn place_ring(app: &AppHandle, at: Option<(i32, i32)>, dwell: f64, mode: &str) {
    let Some(ring) = app.get_webview_window(RING_WINDOW) else {
        return;
    };
    // her introduction: no ring, like no cursor (intro_cursor.rs)
    let at = if crate::intro_cursor::hidden() { None } else { at };
    match at {
        Some((x, y)) => {
            let _ = ring.set_position(tauri::PhysicalPosition::new(x - RING_PX / 2, y - RING_PX / 2));
            if !RING_SHOWN.swap(true, Ordering::Relaxed) {
                let _ = ring.show();
            }
            let _ = ring.emit(EVENT_RING, (dwell, mode.to_string()));
        }
        None => {
            if RING_SHOWN.swap(false, Ordering::Relaxed) {
                let _ = ring.hide();
            }
        }
    }
}

/// One frame of his hand. `dx`/`dy`: movement in physical px (already scaled and
/// smoothed by the HUD); `click`: a dwell fired this frame; `wheel`: wheel units
/// (120 = one notch, + is up); `active`: his hand is up and steering (else the
/// ring hides and nothing moves). Returns where the cursor is, or None when hand
/// control is off.
#[tauri::command]
pub fn hand_pointer(app: AppHandle, dx: f64, dy: f64, dwell: f64, click: bool, wheel: i32, active: bool, mode: String) -> Option<(i32, i32)> {
    // during her introduction his hand drives nothing: no click he can't see
    if !POINTER_ON.load(Ordering::Relaxed) || !active || crate::intro_cursor::hidden() {
        place_ring(&app, None, 0.0, "");
        *REMAINDER.lock().unwrap_or_else(|p| p.into_inner()) = (0.0, 0.0);
        return None;
    }
    let (x, y) = cursor();
    let (mx, my) = {
        let mut rest = REMAINDER.lock().unwrap_or_else(|p| p.into_inner());
        let fx = rest.0 + dx;
        let fy = rest.1 + dy;
        let (mx, my) = (fx.trunc(), fy.trunc());
        *rest = (fx - mx, fy - my);
        (mx as i32, my as i32)
    };
    if mx != 0 || my != 0 {
        // Windows keeps the cursor on a monitor: past an edge with a neighbour it
        // crosses, past an outer edge it stops - like a mouse
        unsafe { SetCursorPos(x + mx, y + my) };
    }
    let at = cursor();
    if click {
        let down = send(MOUSEEVENTF_LEFTDOWN, 0);
        let up = send(MOUSEEVENTF_LEFTUP, 0);
        eprintln!("[irene] hand click at ({}, {}){}", at.0, at.1, if down && up { "" } else { " - Windows refused the input" });
        let _ = app.emit("irene://hand-click", (at.0, at.1, down && up));
    }
    if wheel != 0 {
        send(MOUSEEVENTF_WHEEL, wheel);
    }
    // a click flashes the ring: he sees it fire
    place_ring(&app, Some(at), dwell, if click { "fire" } else { &mode });
    Some(at)
}

#[tauri::command]
pub fn pointer_enabled() -> bool {
    POINTER_ON.load(Ordering::Relaxed)
}

/// Ctrl+Alt+H: hand control on or off. Returns the new state.
pub fn toggle(app: &AppHandle) -> bool {
    let on = !POINTER_ON.load(Ordering::Relaxed);
    POINTER_ON.store(on, Ordering::Relaxed);
    if !on {
        place_ring(app, None, 0.0, "");
    }
    eprintln!("[irene] hand pointer {}", if on { "ON" } else { "OFF - mouse only" });
    on
}
