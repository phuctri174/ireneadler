// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
//! Her z-order. Her windows (main interface and panel) are ordinary windows: he
//! clicks or opens another app and it comes in front of her, and she keeps running
//! behind it. A summon (voice, hand sign, hotkey) raises both to the top and gives
//! her focus - that is her moment in front - and the moment ANY other window is
//! activated she drops out of topmost again (the watcher below; it used to happen
//! only when something opened in his Chrome). ctrl+alt+shift+p pins her above
//! everything until pressed again (filming, demos). Click-through is untouched.

use std::sync::atomic::{AtomicBool, AtomicIsize, Ordering};
use std::time::Duration;

use tauri::{AppHandle, Emitter, Manager};

#[link(name = "user32")]
extern "system" {
    fn GetForegroundWindow() -> isize;
    fn GetAncestor(hwnd: isize, flags: u32) -> isize;
    fn SetWindowPos(hwnd: isize, after: isize, x: i32, y: i32, cx: i32, cy: i32, flags: u32) -> i32;
    fn GetWindowLongW(hwnd: isize, index: i32) -> i32;
    fn GetWindowTextW(hwnd: isize, text: *mut u16, max: i32) -> i32;
    fn GetWindow(hwnd: isize, cmd: u32) -> isize;
    fn GetAsyncKeyState(key: i32) -> i16;
    fn GetCursorPos(point: *mut Point) -> i32;
    fn WindowFromPoint(point: Point) -> isize;
    fn GetWindowThreadProcessId(hwnd: isize, pid: *mut u32) -> u32;
    fn AttachThreadInput(attach: u32, to: u32, on: i32) -> i32;
    fn SetForegroundWindow(hwnd: isize) -> i32;
    fn BringWindowToTop(hwnd: isize) -> i32;
    fn GetClassNameW(hwnd: isize, name: *mut u16, max: i32) -> i32;
}
#[link(name = "kernel32")]
extern "system" {
    fn GetCurrentThreadId() -> u32;
}
#[repr(C)]
#[derive(Clone, Copy, Default)]
struct Point {
    x: i32,
    y: i32,
}
const GW_HWNDNEXT: u32 = 2;
// the left button - READ only, to see where he clicks; nothing is ever sent
const VK_LBUTTON: i32 = 0x01;
const HWND_TOPMOST: isize = -1;
const HWND_NOTOPMOST: isize = -2;
const GWL_EXSTYLE: i32 = -20;
const WS_EX_TOPMOST: i32 = 0x8;
const GA_ROOT: u32 = 2;
const SWP_NOSIZE: u32 = 0x1;
const SWP_NOMOVE: u32 = 0x2;
const SWP_NOACTIVATE: u32 = 0x10;
const SWP_NOOWNERZORDER: u32 = 0x200;

/// Her two windows, the ones that rise and fall together.
const WINDOWS: [&str; 2] = [crate::MAIN_WINDOW, crate::DASHBOARD_WINDOW];
/// Pinned on top by hand (ctrl+alt+shift+p): nothing drops her until unpinned.
pub static PINNED: AtomicBool = AtomicBool::new(false);
/// Raised by a summon or a show, until another window is activated.
static RAISED: AtomicBool = AtomicBool::new(false);
/// The window that was in front when she was raised: if her focus didn't take, it
/// is still the foreground - that is not him activating it, so it doesn't drop her.
static RAISED_OVER: AtomicIsize = AtomicIsize::new(0);
/// Every z-order decision, to the HUD - traced into core.log ("hud panel z-order:"),
/// so a session where she stayed in front says why.
pub const EVENT_ZORDER: &str = "irene://zorder";

fn trace(app: &AppHandle, what: String) {
    eprintln!("[irene] z-order: {what}");
    let _ = app.emit(EVENT_ZORDER, what);
}

fn title(hwnd: isize) -> String {
    let mut buf = [0u16; 120];
    // SAFETY: the buffer outlives the call and its length is passed
    let n = unsafe { GetWindowTextW(hwnd, buf.as_mut_ptr(), buf.len() as i32) };
    String::from_utf16_lossy(&buf[..n.max(0) as usize])
}

/// Where her two windows stand: topmost or not, as Windows has it.
fn state(app: &AppHandle) -> String {
    WINDOWS
        .iter()
        .filter_map(|label| app.get_webview_window(label).map(|w| format!("{label} {}", if is_top(&w) { "TOPMOST" } else { "normal" })))
        .collect::<Vec<_>>()
        .join(", ")
}
const POLL: Duration = Duration::from_millis(120);

fn foreground() -> isize {
    // SAFETY: plain Win32 queries, no pointers passed
    unsafe {
        let hwnd = GetForegroundWindow();
        if hwnd == 0 {
            0
        } else {
            GetAncestor(hwnd, GA_ROOT)
        }
    }
}

fn hwnd_of(window: &tauri::WebviewWindow) -> isize {
    window.hwnd().map(|h| h.0 as isize).unwrap_or(0)
}

/// Any of her windows (the interface, the panel, the pointer ring, the warm-ups).
fn is_hers(app: &AppHandle, hwnd: isize) -> bool {
    hwnd != 0 && app.webview_windows().values().any(|w| hwnd_of(w) == hwnd)
}

/// Her z-order is set HERE, straight through Win32 and at once - never with Tauri's
/// set_always_on_top, which is queued to the UI thread and applied later: live, a
/// drop and a raise landed out of order and left her pinned window not on top.
fn place(hwnd: isize, after: isize) {
    if hwnd != 0 {
        // SAFETY: a live top-level window; moves nothing, activates nothing
        unsafe {
            SetWindowPos(hwnd, after, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER);
        }
    }
}

/// Whether a window really is topmost, as Windows has it.
pub fn is_top(window: &tauri::WebviewWindow) -> bool {
    topmost_hwnd(hwnd_of(window))
}

fn set_top(app: &AppHandle, on: bool) {
    for label in WINDOWS {
        if let Some(window) = app.get_webview_window(label) {
            if window.is_visible().unwrap_or(false) || !on {
                place(hwnd_of(&window), if on { HWND_TOPMOST } else { HWND_NOTOPMOST });
            }
        }
    }
}

/// A summon or a show: both windows to the top. Call after the window is shown
/// and focused.
pub fn raise(app: &AppHandle) {
    set_top(app, true);
    RAISED.store(true, Ordering::Relaxed);
    take_focus(app);
    RAISED_OVER.store(foreground(), Ordering::Relaxed);
    trace(app, format!("raised to the top{} - {}", if PINNED.load(Ordering::Relaxed) { " (pinned)" } else { " until another window is activated" }, state(app)));
}

/// A summon takes his focus. Windows refuses the foreground to a process he hasn't
/// just given input (a voice summon has none): then his app stayed the active
/// window under her, and clicking it changed nothing - she never dropped. So, when
/// the plain request was refused, the documented way: share the foreground
/// thread's input queue for one SetForegroundWindow. No input is sent.
fn take_focus(app: &AppHandle) {
    let Some(main) = app.get_webview_window(crate::MAIN_WINDOW) else { return };
    let hwnd = hwnd_of(&main);
    let fg = foreground();
    if hwnd == 0 || fg == hwnd || is_hers(app, fg) {
        return;
    }
    // SAFETY: thread ids and window handles only; the attach is undone at once
    unsafe {
        let theirs = GetWindowThreadProcessId(fg, std::ptr::null_mut());
        let ours = GetCurrentThreadId();
        let attached = theirs != 0 && theirs != ours && AttachThreadInput(ours, theirs, 1) != 0;
        BringWindowToTop(hwnd);
        SetForegroundWindow(hwnd);
        if attached {
            AttachThreadInput(ours, theirs, 0);
        }
    }
    trace(app, format!("focus taken from \"{}\": {}", title(fg), if foreground() == hwnd { "she has it" } else { "Windows refused - he keeps it" }));
}

/// Whether `a` is above `b` in Windows' z-order (walking down from `a`).
fn is_above(a: isize, b: isize) -> bool {
    let mut h = a;
    for _ in 0..4000 {
        // SAFETY: a z-order walk; handles only
        h = unsafe { GetWindow(h, GW_HWNDNEXT) };
        if h == 0 {
            return false;
        }
        if h == b {
            return true;
        }
    }
    false
}

/// Any of her two windows above `w` (topmost ones are above every normal window).
fn above_any(app: &AppHandle, w: isize) -> bool {
    WINDOWS.iter().any(|label| app.get_webview_window(label).map(|win| is_above(hwnd_of(&win), w)).unwrap_or(false))
}

/// The desktop itself (wallpaper and icons): always at the bottom - she must never
/// be slotted under it, or she'd vanish behind the wallpaper.
fn is_desktop(hwnd: isize) -> bool {
    let mut buf = [0u16; 64];
    // SAFETY: the buffer outlives the call and its length is passed
    let n = unsafe { GetClassNameW(hwnd, buf.as_mut_ptr(), buf.len() as i32) };
    matches!(String::from_utf16_lossy(&buf[..n.max(0) as usize]).as_str(), "Progman" | "WorkerW")
}

fn topmost_hwnd(hwnd: isize) -> bool {
    // SAFETY: a style read
    unsafe { GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST != 0 }
}

/// One window put in front of his others, without staying there: the top of the
/// normal z-order (topmost on, then off). Her panel when she puts something new on
/// it while she is up.
pub fn front(window: &tauri::WebviewWindow) {
    let hwnd = hwnd_of(window);
    place(hwnd, HWND_TOPMOST);
    if !(PINNED.load(Ordering::Relaxed) || RAISED.load(Ordering::Relaxed)) {
        place(hwnd, HWND_NOTOPMOST);
    }
}

/// Out of topmost; whatever he activates comes in front of her. Never while pinned.
/// `behind`: the window he just activated - she goes directly under it (dropping
/// topmost alone puts a window at the TOP of the normal z-order, which lands her
/// right back over the window he chose: live, Notepad stayed behind her).
pub fn lower(app: &AppHandle, why: &str, behind: Option<isize>) {
    if PINNED.load(Ordering::Relaxed) {
        return;
    }
    let was = RAISED.swap(false, Ordering::Relaxed);
    set_top(app, false);
    // under a topmost window (the taskbar, the Start menu) she'd become topmost too;
    // under the desktop she'd be gone
    if let Some(front) = behind.filter(|&h| h != 0 && !topmost_hwnd(h) && !is_desktop(h)) {
        for label in WINDOWS {
            if let Some(window) = app.get_webview_window(label) {
                place(hwnd_of(&window), front);
            }
        }
    }
    if was {
        trace(app, format!("normal again ({why}{}) - {}", behind.map(|h| format!(": behind \"{}\"", title(h))).unwrap_or_default(), state(app)));
    }
}

fn is_top_any(app: &AppHandle) -> bool {
    WINDOWS.iter().any(|label| app.get_webview_window(label).map(|w| is_top(&w)).unwrap_or(false))
}

/// Hidden: nothing of hers is on top (the pin is kept for her next show).
pub fn hidden(app: &AppHandle) {
    RAISED.store(false, Ordering::Relaxed);
    set_top(app, false);
}

/// ctrl+alt+shift+p. Returns whether she is pinned now.
pub fn toggle_pin(app: &AppHandle) -> bool {
    let pinned = !PINNED.load(Ordering::Relaxed);
    PINNED.store(pinned, Ordering::Relaxed);
    if pinned {
        set_top(app, true);
    } else {
        RAISED.store(false, Ordering::Relaxed);
        set_top(app, false);
    }
    trace(app, format!("{} - {}", if pinned { "PINNED on top (ctrl+alt+shift+p to unpin)" } else { "unpinned - an ordinary window" }, state(app)));
    pinned
}

/// Watches the foreground: another window activated - any app, a file, his Chrome -
/// and she drops out of topmost.
pub fn watch(app: AppHandle) {
    let mut last = foreground();
    let mut was_down = false;
    loop {
        std::thread::sleep(POLL);
        // a click on any window that isn't hers - even the one already active, which
        // changes no foreground - puts that window in front of her
        // SAFETY: input STATE reads only (nothing is sent)
        let down = unsafe { GetAsyncKeyState(VK_LBUTTON) as u16 & 0x8000 != 0 };
        if down && !was_down && !PINNED.load(Ordering::Relaxed) {
            let mut at = Point::default();
            // SAFETY: a cursor read and a hit test (her click-through window is skipped)
            let target = unsafe {
                GetCursorPos(&mut at);
                GetAncestor(WindowFromPoint(at), GA_ROOT)
            };
            if target != 0 && !is_hers(&app, target) && (is_top_any(&app) || above_any(&app, target)) {
                RAISED.store(true, Ordering::Relaxed);
                lower(&app, "he clicked another window", Some(target));
            }
        }
        was_down = down;
        let now = foreground();
        if now == 0 || now == last {
            continue;
        }
        last = now;
        if is_hers(&app, now) {
            // she has the focus: the next change away from her is him moving on
            RAISED_OVER.store(0, Ordering::Relaxed);
            continue;
        }
        if PINNED.load(Ordering::Relaxed) {
            continue;
        }
        if RAISED.load(Ordering::Relaxed) && now != RAISED_OVER.load(Ordering::Relaxed) {
            lower(&app, "another window was activated", Some(now));
        } else if is_top_any(&app) || above_any(&app, now) {
            // activated, and she is still over it (topmost from elsewhere, or left at
            // the top of the normal z-order): it goes in front of her
            trace(&app, format!("\"{}\" activated with her still over it - she goes behind it ({})", title(now), state(&app)));
            RAISED.store(true, Ordering::Relaxed);
            lower(&app, "activated window under her", Some(now));
        }
    }
}
