use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Mutex;
use std::time::Duration;

use tauri::menu::{Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{AppHandle, Emitter, Manager, WindowEvent};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

mod lifeline;
mod intro_cursor;
mod pointer;
mod zorder;

pub(crate) const MAIN_WINDOW: &str = "main";
/// Irene herself is up (summoned, not asleep). The main WINDOW can be shown while
/// she is not: with hand control on it stays up - transparent, click-through - so
/// hand tracking runs at full rate whatever she is doing (pointer.rs).
static SHELL_UP: AtomicBool = AtomicBool::new(false);
/// Screens-off mode: everything of hers away, even the tracking window.
static DARK: AtomicBool = AtomicBool::new(false);
/// The black warm-up surfaces are up (a wake from screens-off).
static WARMUP: AtomicBool = AtomicBool::new(false);
/// The panel is held hidden while her boot plays: it stays off the second screen
/// until the HUD calls panel_burst as her name lands - then it bursts in. Each show
/// gets a new generation, so a stale safety release never touches a later boot.
static PANEL_HELD: AtomicBool = AtomicBool::new(false);
static PANEL_HOLD_GEN: AtomicU64 = AtomicU64::new(0);
/// If the HUD never releases it (a reload mid-boot), the panel comes up anyway after this.
const PANEL_HOLD_MAX: Duration = Duration::from_millis(13_000);
/// The panel's own entrance, played as it bursts in (the dashboard listens).
const EVENT_PANEL_BURST: &str = "irene://panel-burst";
/// Ctrl+Alt+Shift+O: screens-off mode (core decides, if it is enabled).
const EVENT_SCREENS_OFF: &str = "irene://screens-off";
/// Ctrl+Alt+Shift+L: lecture capture on/off (core listens to the system audio).
const EVENT_LECTURE: &str = "irene://lecture";
/// Hand control on/off (Ctrl+Alt+H): the HUD shows it and traces it to core.
const EVENT_POINTER: &str = "irene://pointer";
/// WebView2's flags, the same for every window (one browser environment): Tauri's
/// own defaults, plus no native occlusion - a window Chrome covers must keep
/// running (her hand tracking lives in the main one).
pub const BROWSER_ARGS: &str = "--disable-features=msWebOOUI,msPdfOOUI,msSmartScreenProtection,CalculateNativeWinOcclusion";

/// Her panel, on the second (portrait) monitor: what she shows, and the dashboard.
pub(crate) const DASHBOARD_WINDOW: &str = "dashboard";
const EVENT_TOGGLE_DEBUG: &str = "irene://toggle-debug";
const EVENT_TOGGLE_CALIBRATE: &str = "irene://toggle-calibrate";
const EVENT_VISIBILITY: &str = "irene://visibility";
const EVENT_SUMMON: &str = "irene://summon";
const EVENT_CYCLE_STATE: &str = "irene://cycle-state";
const EVENT_CYCLE_EMOTION: &str = "irene://cycle-emotion";
const EVENT_TOGGLE_PANEL: &str = "irene://toggle-panel";
const EVENT_CYCLE_REACTION: &str = "irene://cycle-reaction";
const EVENT_CYCLE_ACTIVITY: &str = "irene://cycle-activity";
const EVENT_CAPTURE: &str = "irene://capture";
// the window started or stopped taking the mouse (over the panel): into core.log
const EVENT_CURSOR: &str = "irene://cursor";
const EVENT_COMMAND_BAR: &str = "irene://command-bar";
const EVENT_SPEAK: &str = "irene://speak";
/// After a show: whether the window really is visible now (the HUD traces it).
const EVENT_SHOWN: &str = "irene://shown";
/// The voice corpus recorder: "start" (ctrl+alt+shift+r), "redo" (space), "stop" (escape).
const EVENT_CORPUS: &str = "irene://corpus";
/// After the panel window is shown: where it is (the HUD traces it into core.log).
const EVENT_PANEL_SHOWN: &str = "irene://panel-shown";
/// Skit mode (core/irene/skit.py): "start" (ctrl+alt+shift+k - mid-skit, start over)
/// or "abort" (ctrl+alt+shift+x). The HUD passes it to core.
const EVENT_SKIT: &str = "irene://skit";

/// Spoken on every summon. Carried on its own event so the TTS worker can consume
/// it without knowing anything about the HUD.
const SUMMON_LINE: &str = "DOMAIN EXPANSION: IRENE ADLER IS COMING!!!";

#[derive(Clone, serde::Serialize)]
struct Utterance {
    text: String,
    source: String,
    /// For a summon, what triggered it: "sign" always gets the domain expansion,
    /// "hotkey" gets a random entrance from the pool. Empty otherwise.
    by: String,
}

static CURSOR_IGNORED: AtomicBool = AtomicBool::new(true);
// Who wants the mouse. The HUD is click-through unless one of these holds:
// the command bar is open, ctrl+alt+d / the tray turned capture on, or the OS
// cursor is over the panel (polled - a click-through window gets no mouse events).
static BAR_OPEN: AtomicBool = AtomicBool::new(false);
static MANUAL_CAPTURE: AtomicBool = AtomicBool::new(false);
static OVER_PANEL: AtomicBool = AtomicBool::new(false);
/// The panel's box in CSS px inside the window (x, y, width, height); None when closed.
static PANEL_RECT: Mutex<Option<[f64; 4]>> = Mutex::new(None);
const CURSOR_POLL: Duration = Duration::from_millis(40);

/// Operator, capture and corpus keys: ctrl+alt+shift. Checked against this PC
/// (core/scripts/hotkey_probe.py) and what common apps document (hud/HOTKEYS.md):
/// bare F6-F11 stole browser and Office keys system-wide (F6 address bar, F7 caret
/// browsing, F10 menus, F11 full screen), ctrl+alt+r is held by the screenshot
/// tool, ctrl+alt+c types (c) in Word, ctrl+alt+1-3 are Docs/Word headings.
fn operator() -> Modifiers {
    Modifiers::CONTROL | Modifiers::ALT | Modifiers::SHIFT
}

fn hide_shortcut() -> Shortcut {
    Shortcut::new(Some(Modifiers::CONTROL | Modifiers::ALT), Code::Escape)
}

fn screens_off_shortcut() -> Shortcut {
    Shortcut::new(Some(operator()), Code::KeyO)
}

fn lecture_shortcut() -> Shortcut {
    Shortcut::new(Some(operator()), Code::KeyL)
}

fn pointer_shortcut() -> Shortcut {
    Shortcut::new(Some(Modifiers::CONTROL | Modifiers::ALT), Code::KeyH)
}

fn focus_shortcut() -> Shortcut {
    Shortcut::new(Some(Modifiers::CONTROL | Modifiers::ALT), Code::KeyI)
}

// The HUD is click-through and normally unfocused, so anything the operator needs
// to reach has to be a system shortcut rather than a webview keydown.
fn state_shortcut() -> Shortcut {
    Shortcut::new(Some(operator()), Code::F6)
}

fn panel_shortcut() -> Shortcut {
    Shortcut::new(Some(operator()), Code::F7)
}

fn emotion_shortcut() -> Shortcut {
    Shortcut::new(Some(operator()), Code::F8)
}

fn debug_shortcut() -> Shortcut {
    Shortcut::new(Some(operator()), Code::F9)
}

fn calibrate_shortcut() -> Shortcut {
    Shortcut::new(Some(operator()), Code::F10)
}

fn reaction_shortcut() -> Shortcut {
    Shortcut::new(Some(operator()), Code::F11)
}

// ctrl+alt+t (for "type") opens the bar. ctrl+alt+space was the spec, but it is
// the Claude desktop app's quick entry: registering it took it from Claude
// whenever Irene started first, so it is left alone.
fn command_bar_alt_shortcut() -> Shortcut {
    Shortcut::new(Some(Modifiers::CONTROL | Modifiers::ALT), Code::KeyT)
}

// Not F12: Windows reserves it for the debugger, so it can never be a global hotkey.
fn capture_shortcut() -> Shortcut {
    Shortcut::new(Some(operator()), Code::KeyC)
}

// Guided captures on the number row, one profile per key, about three minutes
// each and run separately. 1-3 are the zoom distances (the digit IS the
// distance); 4-5 are keiko, which records the upper body instead of a hand.
const CAPTURE_KEYS: [(Code, &str); 9] = [
    (Code::Digit1, "zoom_near"),
    (Code::Digit2, "zoom_mid"),
    (Code::Digit3, "zoom_far"),
    (Code::Digit4, "keiko_near"),
    (Code::Digit5, "keiko_mid"),
    // kamae in its variations, then the everyday movements that must never fire it
    (Code::Digit6, "keiko_kamae"),
    (Code::Digit7, "keiko_confusers"),
    // zoom at the distance he actually uses the panel from (a still hand latched there)
    (Code::Digit8, "zoom_panel"),
    // keiko: the three strikes at real speed and every strike-shaped movement that
    // isn't one (core/scripts/strike_train.py)
    (Code::Digit9, "keiko_strikes"),
];

fn capture_digit_shortcut(code: Code) -> Shortcut {
    Shortcut::new(Some(operator()), code)
}

// the voice corpus: ctrl+alt+shift+r starts a session (ctrl+alt+r is the
// screenshot tool's); while one runs, plain space (redo the take) and escape
// (stop) are held globally - he is reading from a metre away, the HUD is
// click-through and never has focus - and let go after
fn pin_shortcut() -> Shortcut {
    Shortcut::new(Some(operator()), Code::KeyP)
}

fn skit_shortcut() -> Shortcut {
    Shortcut::new(Some(operator()), Code::KeyK)
}

fn skit_abort_shortcut() -> Shortcut {
    Shortcut::new(Some(operator()), Code::KeyX)
}

fn corpus_shortcut() -> Shortcut {
    Shortcut::new(Some(operator()), Code::KeyR)
}

fn corpus_redo_shortcut() -> Shortcut {
    Shortcut::new(None, Code::Space)
}

fn corpus_stop_shortcut() -> Shortcut {
    Shortcut::new(None, Code::Escape)
}

#[tauri::command]
fn corpus_keys(app: AppHandle, on: bool) {
    let global = app.global_shortcut();
    for (name, shortcut) in [("space", corpus_redo_shortcut()), ("escape", corpus_stop_shortcut())] {
        let result = if on { global.register(shortcut) } else { global.unregister(shortcut) };
        match result {
            Ok(()) => eprintln!("[irene] corpus key {name} {}", if on { "held" } else { "released" }),
            Err(error) => eprintln!("[irene] corpus key {name}: {error}"),
        }
    }
}

fn activity_shortcut() -> Shortcut {
    Shortcut::new(Some(Modifiers::CONTROL | Modifiers::ALT), Code::KeyA)
}

fn cursor_shortcut() -> Shortcut {
    Shortcut::new(Some(Modifiers::CONTROL | Modifiers::ALT), Code::KeyD)
}

/// Capture the mouse exactly when something wants it; a no-op when nothing changed.
fn refresh_cursor(app: &AppHandle) {
    let wanted = BAR_OPEN.load(Ordering::Relaxed)
        || MANUAL_CAPTURE.load(Ordering::Relaxed)
        || OVER_PANEL.load(Ordering::Relaxed);
    if CURSOR_IGNORED.load(Ordering::Relaxed) == !wanted {
        return;
    }
    apply_cursor_ignore(app, !wanted);
}

fn toggle_manual_capture(app: &AppHandle) {
    MANUAL_CAPTURE.fetch_xor(true, Ordering::Relaxed);
    refresh_cursor(app);
}

/// Where the OS cursor is, in CSS px inside the main window - or None if unknown.
fn cursor_in_window(app: &AppHandle) -> Option<(f64, f64)> {
    let window = app.get_webview_window(MAIN_WINDOW)?;
    if !window.is_visible().unwrap_or(false) {
        return None;
    }
    let cursor = app.cursor_position().ok()?;
    let origin = window.inner_position().ok()?;
    let scale = window.scale_factor().ok()?;
    Some(((cursor.x - origin.x as f64) / scale, (cursor.y - origin.y as f64) / scale))
}

/// The panel is clickable (links open in his Chrome, the wheel scrolls it) only
/// while the cursor is over it; everywhere else the desktop stays clickable.
fn watch_cursor(app: AppHandle) {
    loop {
        std::thread::sleep(CURSOR_POLL);
        let rect = *PANEL_RECT.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
        let over = match (rect, cursor_in_window(&app)) {
            (Some([x, y, w, h]), Some((cx, cy))) => cx >= x && cx <= x + w && cy >= y && cy <= y + h,
            _ => false,
        };
        if OVER_PANEL.swap(over, Ordering::Relaxed) != over {
            refresh_cursor(&app);
        }
    }
}

fn apply_cursor_ignore(app: &AppHandle, ignored: bool) {
    let Some(window) = app.get_webview_window(MAIN_WINDOW) else {
        return;
    };
    match window.set_ignore_cursor_events(ignored) {
        Ok(()) => {
            CURSOR_IGNORED.store(ignored, Ordering::Relaxed);
            let _ = app.emit(EVENT_CURSOR, !ignored);
            eprintln!(
                "[irene] cursor events: {} (desktop {})",
                if ignored { "ignored" } else { "captured" },
                if ignored { "clickable" } else { "blocked" }
            );
        }
        Err(error) => eprintln!("[irene] set_ignore_cursor_events failed: {error}"),
    }
}

fn show_main(app: &AppHandle) {
    let Some(window) = app.get_webview_window(MAIN_WINDOW) else {
        return;
    };
    // from hidden to shown: her boot plays, and the panel waits for its cue
    let was_up = SHELL_UP.swap(true, Ordering::Relaxed);
    if !was_up {
        hold_panel(app);
    }
    let shown = window.show().and_then(|()| window.set_focus());
    if let Err(error) = shown {
        eprintln!("[irene] show failed: {error}");
    }
    // on top for her moment in front; the first other window he activates ends it
    zorder::raise(app);
    if let Err(error) = app.emit(EVENT_VISIBILITY, true) {
        eprintln!("[irene] visibility emit failed: {error}");
    }
    // what Windows says, not what we asked for: the summon path's step 5
    let visible = window.is_visible().unwrap_or(false);
    if let Err(error) = app.emit(EVENT_SHOWN, visible) {
        eprintln!("[irene] shown emit failed: {error}");
    }
    eprintln!("[irene] shown (visible: {visible})");
    if !PANEL_HELD.load(Ordering::Relaxed) {
        let _ = show_panel_window(app.clone());
    }
    // her windows are up now: the black warm-up surfaces can go
    hide_warmups(app);
}

/// Her introduction (boot, entrance, greeting) is on: his cursor - Windows' and the
/// hand pointer's ring - is hidden until it ends (core: intro_cursor).
#[tauri::command]
fn intro_cursor(app: AppHandle, hidden: bool) {
    intro_cursor::set(hidden);
    if hidden {
        pointer::hide_ring(&app);
    }
}

/// Hold the panel off the second screen for her boot (hidden now if it was up), with
/// a safety release in case the HUD never sends the cue.
fn hold_panel(app: &AppHandle) {
    PANEL_HELD.store(true, Ordering::Relaxed);
    let generation = PANEL_HOLD_GEN.fetch_add(1, Ordering::Relaxed) + 1;
    if let Some(panel) = app.get_webview_window(DASHBOARD_WINDOW) {
        let _ = panel.hide();
    }
    eprintln!("[irene] panel held for the boot (until her name lands)");
    let app = app.clone();
    std::thread::spawn(move || {
        std::thread::sleep(PANEL_HOLD_MAX);
        if PANEL_HOLD_GEN.load(Ordering::Relaxed) == generation && PANEL_HELD.load(Ordering::Relaxed) && SHELL_UP.load(Ordering::Relaxed) {
            eprintln!("[irene] panel hold timed out (no cue from the HUD) - showing it");
            let _ = panel_burst(app);
        }
    });
}

/// The cue: her name has landed (or the boot was skipped). The panel is released,
/// shown, and told to play its entrance. Returns where it is, for core.log.
#[tauri::command]
fn panel_burst(app: AppHandle) -> String {
    PANEL_HELD.store(false, Ordering::Relaxed);
    let report = show_panel_window(app.clone());
    if let Err(error) = app.emit_to(DASHBOARD_WINDOW, EVENT_PANEL_BURST, ()) {
        eprintln!("[irene] panel burst emit failed: {error}");
    }
    eprintln!("[irene] panel bursts in: {report}");
    report
}

/// Her panel on the second screen comes up with her - any summon, any show - and
/// whenever she puts something on it: shown and brought in front (zorder.rs: on
/// top while she is raised, otherwise just the front of the normal z-order). Live
/// it was shown but stayed behind his maximised VS Code on the MSI - visible to
/// Windows, invisible to him. Never takes his focus.
/// Returns where it is, for core.log (the HUD traces it).
#[tauri::command]
fn show_panel_window(app: AppHandle) -> String {
    let Some(panel) = app.get_webview_window(DASHBOARD_WINDOW) else {
        let report = "panel window: none (no second monitor at startup)".to_string();
        eprintln!("[irene] {report}");
        return report;
    };
    if PANEL_HELD.load(Ordering::Relaxed) {
        // her boot is playing: the panel bursts in on its cue, not before (whatever
        // she put on it is there when it does)
        return "panel window: held for the boot".to_string();
    }
    if !SHELL_UP.load(Ordering::Relaxed) {
        // the two always share visibility: the panel never comes up without her
        show_main(&app);
        return panel_report(&panel);
    }
    if let Err(error) = panel.show() {
        eprintln!("[irene] panel window show failed: {error}");
    }
    // in front of his windows on that screen - on top only while she is raised
    zorder::front(&panel);
    let report = panel_report(&panel);
    eprintln!("[irene] {report}");
    let _ = app.emit(EVENT_PANEL_SHOWN, report.clone());
    report
}

/// Where the panel window is, as Windows sees it: monitor, position, size, state.
fn panel_report(panel: &tauri::WebviewWindow) -> String {
    let monitor = panel
        .current_monitor()
        .ok()
        .flatten()
        .map(|m| format!("{:?} {}x{} at ({}, {})", m.name(), m.size().width, m.size().height, m.position().x, m.position().y))
        .unwrap_or_else(|| "no monitor".to_string());
    let at = panel.outer_position().map(|p| format!("({}, {})", p.x, p.y)).unwrap_or_default();
    let size = panel.outer_size().map(|s| format!("{}x{}", s.width, s.height)).unwrap_or_default();
    format!(
        "panel window: visible {}, topmost {}, minimized {}, at {at} size {size}, on monitor {monitor}",
        panel.is_visible().unwrap_or(false),
        zorder::is_top(panel),
        panel.is_minimized().unwrap_or(false),
    )
}

/// The second screen: her panel - what she shows him, and the dashboard around it -
/// filling the work area of the monitor that isn't the primary one (his MSI, in portrait).
/// Irene herself stays on the primary. Hidden until she is summoned; no second
/// monitor, no panel window (the content still arrives, nowhere to show it).
fn open_dashboard(app: &AppHandle) {
    let monitors = match app.available_monitors() {
        Ok(monitors) => monitors,
        Err(error) => {
            eprintln!("[irene] dashboard: available_monitors failed: {error}");
            return;
        }
    };
    let primary = app.primary_monitor().ok().flatten().map(|m| *m.position());
    let Some(second) = monitors.into_iter().find(|m| Some(*m.position()) != primary) else {
        eprintln!("[irene] dashboard: no second monitor");
        return;
    };
    let scale = second.scale_factor();
    let position = second.position().to_logical::<f64>(scale);
    let size = second.size().to_logical::<f64>(scale);
    let built = tauri::WebviewWindowBuilder::new(app, DASHBOARD_WINDOW, tauri::WebviewUrl::App("index.html?view=dashboard".into()))
        .title("Irene - panel")
        .additional_browser_args(BROWSER_ARGS)
        .decorations(false)
        // no shadow: with one, Windows keeps an invisible frame round the window and
        // its outer rect overhangs the monitor onto the G6 (as main has, in tauri.conf)
        .shadow(false)
        .resizable(false)
        .skip_taskbar(true)
        .focused(false)
        .visible(false)
        .position(position.x, position.y)
        .inner_size(size.width, size.height)
        .build();
    match built {
        // placed in physical px by fit_work_areas (the builder's is in the primary's scale)
        Ok(_) => eprintln!("[irene] panel window on {:?}", second.name()),
        Err(error) => eprintln!("[irene] dashboard window failed: {error}"),
    }
}

/// Her two windows each fill their monitor's WORK AREA - the monitor minus its
/// taskbar, as Windows reports it now - so his taskbars stay visible and clickable:
/// main on the primary (the G6), the panel on the other (the MSI). Called at
/// startup and re-checked by watch_work_areas, so a taskbar that moves, resizes or
/// auto-hides is followed. Returns whether a window had to move.
fn fit_work_areas(app: &AppHandle) -> bool {
    let monitors = app.available_monitors().unwrap_or_default();
    let primary = app.primary_monitor().ok().flatten().map(|m| *m.position());
    let mut moved = false;
    for (label, on_primary) in [(MAIN_WINDOW, true), (DASHBOARD_WINDOW, false)] {
        let Some(window) = app.get_webview_window(label) else {
            continue;
        };
        let Some(monitor) = monitors.iter().find(|m| (Some(*m.position()) == primary) == on_primary) else {
            continue;
        };
        let area = monitor.work_area();
        let (at, size) = (area.position, area.size);
        if window.outer_position().ok() == Some(at) && window.outer_size().ok() == Some(size) {
            continue;
        }
        let _ = window.set_position(at);
        let _ = window.set_size(size);
        moved = true;
        eprintln!(
            "[irene] {label} window fitted to the work area of {:?}: {}x{} at ({}, {})",
            monitor.name(), size.width, size.height, at.x, at.y
        );
    }
    moved
}

/// How often the work areas are re-read (a taskbar moved or resized).
const WORK_AREA_POLL: Duration = Duration::from_millis(1500);

fn watch_work_areas(app: AppHandle) {
    loop {
        std::thread::sleep(WORK_AREA_POLL);
        fit_work_areas(&app);
    }
}

/// Why she was hidden, into core.log through the HUD ("hidden by ...").
const EVENT_HIDDEN: &str = "irene://hidden";

fn hide_main(app: &AppHandle, why: &str) {
    let _ = app.emit(EVENT_HIDDEN, why.to_string());
    eprintln!("[irene] hide: {why}");
    // sent away mid-introduction: his cursor comes back with her going
    intro_cursor::set(false);
    let Some(window) = app.get_webview_window(MAIN_WINDOW) else {
        return;
    };
    SHELL_UP.store(false, Ordering::Relaxed);
    PANEL_HELD.store(false, Ordering::Relaxed);
    if let Err(error) = app.emit(EVENT_VISIBILITY, false) {
        eprintln!("[irene] visibility emit failed: {error}");
    }
    // with hand control on, the window stays: her interface hides (the HUD), the
    // window is transparent and click-through, and the tracking keeps running
    let hidden = if pointer::POINTER_ON.load(Ordering::Relaxed) {
        apply_cursor_ignore(app, true);
        Ok(())
    } else {
        window.hide()
    };
    zorder::hidden(app);
    if let Some(panel) = app.get_webview_window(DASHBOARD_WINDOW) {
        let _ = panel.hide();
    }
    if let Err(error) = hidden {
        eprintln!("[irene] hide failed: {error}");
    }
    eprintln!("[irene] hidden");
}

/// A summon is louder than a plain show: the main interface flares and Irene
/// announces herself. The tray's show/hide deliberately does not go through here.
/// `by` is what triggered it - "sign" for the hand sign, which always gets the
/// domain expansion, or "hotkey", which gets a random entrance.
fn summon_main(app: &AppHandle, by: &str) {
    show_main(app);
    if let Err(error) = app.emit(EVENT_SUMMON, SUMMON_LINE) {
        eprintln!("[irene] summon emit failed: {error}");
    }
    if let Err(error) = app.emit(
        EVENT_SPEAK,
        Utterance {
            text: SUMMON_LINE.to_string(),
            source: "summon".to_string(),
            by: by.to_string(),
        },
    ) {
        eprintln!("[irene] speak emit failed: {error}");
    }
    eprintln!("[irene] summon by {by}: {SUMMON_LINE}");
}

fn toggle_main(app: &AppHandle) {
    let Some(window) = app.get_webview_window(MAIN_WINDOW) else {
        return;
    };
    let _ = window;
    if SHELL_UP.load(Ordering::Relaxed) {
        hide_main(app, "the tray's Show/Hide");
    } else {
        show_main(app);
    }
}

/// The panel's box (CSS px in the window), sent by the HUD whenever it opens, moves
/// or closes (null).
#[tauri::command]
fn panel_rect(rect: Option<[f64; 4]>) {
    match rect {
        Some([x, y, w, h]) => eprintln!("[irene] panel at ({x:.0}, {y:.0}) {w:.0}x{h:.0}: clickable under the cursor"),
        None => eprintln!("[irene] panel closed: click-through everywhere"),
    }
    *PANEL_RECT.lock().unwrap_or_else(|poisoned| poisoned.into_inner()) = rect;
}

#[tauri::command]
fn summon(app: AppHandle) {
    eprintln!("[irene] summon gesture");
    std::thread::spawn(move || summon_main(&app, "sign"));
}

/// A voice wake ("Hey Irene", "Irene Adler"), heard by core: exactly what
/// ctrl+alt+i does - show the window, flare, and hand the summon back to core -
/// so she appears whether or not she was hidden. `by` is "voice" (a random
/// entrance) or "adler" (the Victorian one).
#[tauri::command]
fn summon_voice(app: AppHandle, by: String) -> Result<(), String> {
    if by != "voice" && by != "adler" {
        return Err(format!("unknown voice summon {by:?}"));
    }
    eprintln!("[irene] summon by voice ({by})");
    std::thread::spawn(move || summon_main(&app, &by));
    Ok(())
}

/// The command bar needs the keyboard and the mouse while it is open, and must
/// give both back when it closes: the HUD is click-through the rest of the time.
#[tauri::command]
fn command_bar(app: AppHandle, open: bool) {
    BAR_OPEN.store(open, Ordering::Relaxed);
    refresh_cursor(&app);
    if open {
        if let Some(window) = app.get_webview_window(MAIN_WINDOW) {
            if let Err(error) = window.set_focus() {
                eprintln!("[irene] command bar focus failed: {error}");
            }
        }
    }
}

/// Screen vision: exclude this window from screen capture while core takes a
/// screenshot, so the picture is his screen and not the HUD on top of it.
#[tauri::command]
fn capture_shield(app: AppHandle, on: bool) -> Result<(), String> {
    let window = app
        .get_webview_window(MAIN_WINDOW)
        .ok_or_else(|| "no main window".to_string())?;
    window.set_content_protected(on).map_err(|error| error.to_string())?;
    // DWM applies the affinity on its next composition; give it a frame or two
    std::thread::sleep(std::time::Duration::from_millis(if on { 60 } else { 0 }));
    Ok(())
}

/// Show without summoning (no line, no flare) - the dev test hooks use it.
#[tauri::command]
fn show(app: AppHandle) {
    std::thread::spawn(move || show_main(&app));
}

/// Screens-off mode (core/irene/app.py enter_dark): her interface, the panel, the
/// pointer ring and the tracking window all go; the camera's detection is
/// suspended by the HUD. Off again: the tracking window comes back if hand
/// control is on (the summon that ended it brings her up).
#[tauri::command]
fn dark_mode(app: AppHandle, on: bool) {
    DARK.store(on, Ordering::Relaxed);
    if on {
        hide_main(&app, "screens off");
        for label in [MAIN_WINDOW, pointer::RING_WINDOW] {
            if let Some(window) = app.get_webview_window(label) {
                let _ = window.set_always_on_top(false).and_then(|()| window.hide());
            }
        }
        eprintln!("[irene] screens-off mode: dark");
    } else if pointer::POINTER_ON.load(Ordering::Relaxed) && !SHELL_UP.load(Ordering::Relaxed) {
        if let Some(window) = app.get_webview_window(MAIN_WINDOW) {
            let _ = window.show();
        }
        eprintln!("[irene] screens-off mode: lit");
    }
}

/// Waking from screens-off: a black surface on EVERY monitor while the displays
/// come back (they report "on" before they show an image - OLED especially), so
/// her boot never plays into a dead panel. `on_at`: when Windows reported them on
/// (epoch ms), for the counter he reads. Off: the surfaces go (show_main takes
/// them down itself, after her windows are up).
#[tauri::command]
async fn warmup(app: AppHandle, on: bool, on_at: Option<f64>) {
    if !on {
        hide_warmups(&app);
        return;
    }
    // made at startup (create_warmups): building webviews here blocked the HUD for
    // 1.5 s, live, and the summon right after it timed out
    create_warmups(&app);
    let monitors = app.available_monitors().unwrap_or_default();
    for (i, monitor) in monitors.iter().enumerate() {
        let Some(window) = app.get_webview_window(&format!("warmup-{i}")) else {
            continue;
        };
        let _ = window.set_position(*monitor.position());
        let _ = window.set_size(*monitor.size());
        let _ = window.show().and_then(|()| window.set_always_on_top(true));
        let _ = window.emit("irene://warmup", serde_json::json!({ "onAt": on_at }));
    }
    WARMUP.store(true, Ordering::Relaxed);
    eprintln!("[irene] warm-up surfaces up on {} monitor(s)", monitors.len());
}

/// The black warm-up surfaces, one per monitor, made once and kept hidden until a
/// wake from screens-off needs them.
fn create_warmups(app: &AppHandle) {
    let monitors = app.available_monitors().unwrap_or_default();
    for (i, monitor) in monitors.iter().enumerate() {
        let label = format!("warmup-{i}");
        if app.get_webview_window(&label).is_some() {
            continue;
        }
        match tauri::WebviewWindowBuilder::new(app, &label, tauri::WebviewUrl::App("index.html?view=warmup".into()))
            .title("Irene - waking displays")
            .additional_browser_args(BROWSER_ARGS)
            .decorations(false)
            .resizable(false)
            .skip_taskbar(true)
            .focused(false)
            .always_on_top(true)
            .visible(false)
            .build()
        {
            Ok(window) => {
                let _ = window.set_position(*monitor.position());
                let _ = window.set_size(*monitor.size());
                let _ = window.set_ignore_cursor_events(true);
            }
            Err(error) => eprintln!("[irene] warm-up surface {i} failed: {error}"),
        }
    }
}

fn hide_warmups(app: &AppHandle) {
    if !WARMUP.swap(false, Ordering::Relaxed) {
        return;
    }
    for (label, window) in app.webview_windows() {
        if label.starts_with("warmup-") {
            let _ = window.set_always_on_top(false).and_then(|()| window.hide());
        }
    }
    eprintln!("[irene] warm-up surfaces down");
}

/// Something is opening in his Chrome: her windows drop out of topmost at once, so
/// it comes up in front - on either screen - even before Windows activates it (the
/// foreground watcher, zorder.rs, does the same for every other window). Pinned,
/// she stays on top: he asked for that.
/// Dev test hook (debug_ui "pin"): what ctrl+alt+shift+p does, without the key.
#[tauri::command]
fn toggle_pin(app: AppHandle) -> bool {
    zorder::toggle_pin(&app)
}

#[tauri::command]
fn yield_front(app: AppHandle) {
    zorder::lower(&app, "his Chrome is opening", None);
}

/// Dev test hook: run the very handler of one way to hide or show her - "tray"
/// (the tray's Show/Hide), "hotkey_hide" (ctrl+alt+esc), "hotkey_summon"
/// (ctrl+alt+i), "sleep_button" (SLEEP), "show_panel" (content for the panel),
/// "minimize_main" / "minimize_panel" (a taskbar click or Win+D),
/// "close_panel" (Alt+F4 on it). Window-manager calls only, never input.
#[tauri::command]
fn dev_visibility_path(app: AppHandle, path: String) -> Result<(), String> {
    eprintln!("[irene] dev visibility path: {path}");
    match path.as_str() {
        "tray" => std::thread::spawn(move || toggle_main(&app)),
        "hotkey_hide" => std::thread::spawn(move || hide_main(&app, "dev path: ctrl+alt+esc")),
        "hotkey_summon" => std::thread::spawn(move || summon_main(&app, "hotkey")),
        "sleep_button" => {
            sleep(app);
            return Ok(());
        }
        "show_panel" => {
            let _ = show_panel_window(app);
            return Ok(());
        }
        "minimize_main" | "minimize_panel" => {
            let label = if path == "minimize_main" { MAIN_WINDOW } else { DASHBOARD_WINDOW };
            let window = app.get_webview_window(label).ok_or("no such window")?;
            window.minimize().map_err(|e| e.to_string())?;
            return Ok(());
        }
        "close_panel" => {
            let window = app.get_webview_window(DASHBOARD_WINDOW).ok_or("no panel window")?;
            window.close().map_err(|e| e.to_string())?;
            return Ok(());
        }
        other => return Err(format!("unknown path {other:?}")),
    };
    Ok(())
}

/// Both windows as Windows sees them (dev checks): "main visible X, panel visible Y".
#[tauri::command]
fn visibility_report(app: AppHandle) -> String {
    let seen = |label: &str| {
        app.get_webview_window(label)
            .map(|w| format!("visible {} minimized {}", w.is_visible().unwrap_or(false), w.is_minimized().unwrap_or(false)))
            .unwrap_or_else(|| "none".into())
    };
    format!("her up {}; main window {}; panel window {}", SHELL_UP.load(Ordering::Relaxed), seen(MAIN_WINDOW), seen(DASHBOARD_WINDOW))
}

/// Where her two windows sit against their monitors' work areas, physical px: each
/// one's rect, the work area's, and whether it fills it exactly. The dev geometry hook traces it into core.log.
#[tauri::command]
fn geometry_report(app: AppHandle) -> String {
    let one = |label: &str| {
        let Some(window) = app.get_webview_window(label) else {
            return format!("{label}: none");
        };
        let (Ok(at), Ok(size)) = (window.outer_position(), window.outer_size()) else {
            return format!("{label}: no rect");
        };
        let Some(monitor) = window.current_monitor().ok().flatten() else {
            return format!("{label}: {}x{} at ({}, {}), no monitor", size.width, size.height, at.x, at.y);
        };
        let area = monitor.work_area();
        let (m_at, m_size) = (area.position, area.size);
        let covers = at == m_at && size == m_size;
        format!(
            "{label}: {}x{} at ({}, {}) on {:?} work area {}x{} at ({}, {}) - {}, topmost {}",
            size.width, size.height, at.x, at.y, monitor.name(), m_size.width, m_size.height, m_at.x, m_at.y,
            if covers { "fills it" } else { "does NOT fill it" },
            zorder::is_top(&window),
        )
    };
    format!("{}; {}", one(MAIN_WINDOW), one(DASHBOARD_WINDOW))
}

/// SLEEP on the main interface: the same hide as ctrl+alt+esc.
#[tauri::command]
fn sleep(app: AppHandle) {
    eprintln!("[irene] sleep");
    std::thread::spawn(move || hide_main(&app, "SLEEP"));
}

#[tauri::command]
fn greet(name: &str) -> String {
    format!("Hello, {}! You've been greeted from Rust!", name)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // how this run ends gets written down (core/logs/exits.jsonl, who "hud")
    lifeline::install();
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(|app, shortcut, event| {
                    if event.state() != ShortcutState::Pressed {
                        return;
                    }
                    let app = app.clone();
                    let shortcut = *shortcut;
                    std::thread::spawn(move || {
                        if shortcut.matches(Modifiers::CONTROL | Modifiers::ALT, Code::KeyI) {
                            summon_main(&app, "hotkey");
                        } else if shortcut.matches(operator(), Code::KeyO) {
                            let _ = app.emit(EVENT_SCREENS_OFF, ());
                        } else if shortcut.matches(operator(), Code::KeyL) {
                            let _ = app.emit(EVENT_LECTURE, ());
                        } else if shortcut.matches(Modifiers::CONTROL | Modifiers::ALT, Code::KeyH) {
                            let on = pointer::toggle(&app);
                            if !SHELL_UP.load(Ordering::Relaxed) {
                                // asleep: the window is up only for the tracking
                                if let Some(window) = app.get_webview_window(MAIN_WINDOW) {
                                    let _ = if on { window.show() } else { window.hide() };
                                }
                            }
                            let _ = app.emit(EVENT_POINTER, on);
                        } else if shortcut.matches(Modifiers::CONTROL | Modifiers::ALT, Code::KeyD)
                        {
                            toggle_manual_capture(&app);
                        } else if shortcut.matches(Modifiers::CONTROL | Modifiers::ALT, Code::KeyA)
                        {
                            if let Err(error) = app.emit(EVENT_CYCLE_ACTIVITY, ()) {
                                eprintln!("[irene] activity emit failed: {error}");
                            }
                        } else if shortcut
                            .matches(Modifiers::CONTROL | Modifiers::ALT, Code::Escape)
                        {
                            hide_main(&app, "ctrl+alt+esc");
                        } else if shortcut.matches(operator(), Code::F6) {
                            if let Err(error) = app.emit(EVENT_CYCLE_STATE, ()) {
                                eprintln!("[irene] state emit failed: {error}");
                            }
                        } else if shortcut.matches(operator(), Code::F7) {
                            if let Err(error) = app.emit(EVENT_TOGGLE_PANEL, ()) {
                                eprintln!("[irene] panel emit failed: {error}");
                            }
                        } else if shortcut.matches(operator(), Code::F8) {
                            if let Err(error) = app.emit(EVENT_CYCLE_EMOTION, ()) {
                                eprintln!("[irene] emotion emit failed: {error}");
                            }
                        } else if shortcut.matches(operator(), Code::F9) {
                            if let Err(error) = app.emit(EVENT_TOGGLE_DEBUG, ()) {
                                eprintln!("[irene] debug emit failed: {error}");
                            }
                        } else if shortcut.matches(operator(), Code::F10) {
                            if let Err(error) = app.emit(EVENT_TOGGLE_CALIBRATE, ()) {
                                eprintln!("[irene] calibrate emit failed: {error}");
                            }
                        } else if shortcut.matches(Modifiers::CONTROL | Modifiers::ALT, Code::KeyT) {
                            show_main(&app);
                            if let Err(error) = app.emit(EVENT_COMMAND_BAR, ()) {
                                eprintln!("[irene] command bar emit failed: {error}");
                            }
                        } else if shortcut.matches(operator(), Code::KeyC)
                            || CAPTURE_KEYS.iter().any(|(code, _)| shortcut.matches(operator(), *code))
                        {
                            // gesture capture (profiles in config/capture_profiles.json);
                            // it needs full tracking, which only runs while shown
                            let profile = CAPTURE_KEYS
                                .iter()
                                .find(|(code, _)| shortcut.matches(operator(), *code))
                                .map_or("summon", |(_, name)| *name);
                            show_main(&app);
                            if let Err(error) = app.emit(EVENT_CAPTURE, profile) {
                                eprintln!("[irene] capture emit failed: {error}");
                            }
                        } else if shortcut.matches(operator(), Code::KeyP) {
                            zorder::toggle_pin(&app);
                        } else if shortcut.matches(operator(), Code::KeyK) {
                            if let Err(error) = app.emit(EVENT_SKIT, "start") {
                                eprintln!("[irene] skit emit failed: {error}");
                            }
                        } else if shortcut.matches(operator(), Code::KeyX) {
                            if let Err(error) = app.emit(EVENT_SKIT, "abort") {
                                eprintln!("[irene] skit emit failed: {error}");
                            }
                        } else if shortcut.matches(operator(), Code::KeyR) {
                            show_main(&app);
                            if let Err(error) = app.emit(EVENT_CORPUS, "start") {
                                eprintln!("[irene] corpus emit failed: {error}");
                            }
                        } else if shortcut.matches(Modifiers::empty(), Code::Space) {
                            if let Err(error) = app.emit(EVENT_CORPUS, "redo") {
                                eprintln!("[irene] corpus emit failed: {error}");
                            }
                        } else if shortcut.matches(Modifiers::empty(), Code::Escape) {
                            if let Err(error) = app.emit(EVENT_CORPUS, "stop") {
                                eprintln!("[irene] corpus emit failed: {error}");
                            }
                        } else if shortcut.matches(operator(), Code::F11) {
                            if let Err(error) = app.emit(EVENT_CYCLE_REACTION, ()) {
                                eprintln!("[irene] reaction emit failed: {error}");
                            }
                        }
                    });
                })
                .build(),
        )
        .setup(|app| {
            let window = app
                .get_webview_window(MAIN_WINDOW)
                .expect("main window is declared in tauri.conf.json");

            open_dashboard(app.handle());
            fit_work_areas(app.handle());
            let areas = app.handle().clone();
            std::thread::spawn(move || watch_work_areas(areas));

            apply_cursor_ignore(&app.handle().clone(), true);
            // a HUD that died during her intro left his cursor blank: his scheme back
            intro_cursor::restore();
            let watcher = app.handle().clone();
            std::thread::spawn(move || watch_cursor(watcher));
            let zorder_app = app.handle().clone();
            std::thread::spawn(move || zorder::watch(zorder_app));
            eprintln!("[irene] starting hidden; ctrl+alt+i to summon");
            pointer::create_ring(app.handle());
            create_warmups(app.handle());
            if pointer::POINTER_ON.load(Ordering::Relaxed) {
                // hand control from the start: the window up (empty, click-through)
                // so the tracking runs; Irene herself stays asleep
                let _ = window.show();
                eprintln!("[irene] hand pointer ON (ctrl+alt+h for mouse only)");
            }

            let global = app.global_shortcut();
            for (name, shortcut) in [
                ("ctrl+alt+i", focus_shortcut()),
                ("ctrl+alt+h", pointer_shortcut()),
                ("ctrl+alt+shift+o", screens_off_shortcut()),
                ("ctrl+alt+shift+l", lecture_shortcut()),
                ("ctrl+alt+d", cursor_shortcut()),
                ("ctrl+alt+a", activity_shortcut()),
                ("ctrl+alt+escape", hide_shortcut()),
                ("ctrl+alt+shift+f6", state_shortcut()),
                ("ctrl+alt+shift+f7", panel_shortcut()),
                ("ctrl+alt+shift+f8", emotion_shortcut()),
                ("ctrl+alt+shift+f9", debug_shortcut()),
                ("ctrl+alt+shift+f10", calibrate_shortcut()),
                ("ctrl+alt+shift+f11", reaction_shortcut()),
                ("ctrl+alt+shift+c", capture_shortcut()),
                ("ctrl+alt+shift+1", capture_digit_shortcut(Code::Digit1)),
                ("ctrl+alt+shift+2", capture_digit_shortcut(Code::Digit2)),
                ("ctrl+alt+shift+3", capture_digit_shortcut(Code::Digit3)),
                ("ctrl+alt+shift+4", capture_digit_shortcut(Code::Digit4)),
                ("ctrl+alt+shift+5", capture_digit_shortcut(Code::Digit5)),
                ("ctrl+alt+shift+6", capture_digit_shortcut(Code::Digit6)),
                ("ctrl+alt+shift+7", capture_digit_shortcut(Code::Digit7)),
                ("ctrl+alt+shift+8", capture_digit_shortcut(Code::Digit8)),
                ("ctrl+alt+shift+9", capture_digit_shortcut(Code::Digit9)),
                ("ctrl+alt+t", command_bar_alt_shortcut()),
                ("ctrl+alt+shift+r", corpus_shortcut()),
                ("ctrl+alt+shift+p", pin_shortcut()),
                ("ctrl+alt+shift+k", skit_shortcut()),
                ("ctrl+alt+shift+x", skit_abort_shortcut()),
            ] {
                match global.register(shortcut) {
                    Ok(()) => eprintln!("[irene] shortcut registered: {name}"),
                    Err(error) => eprintln!("[irene] shortcut {name} failed: {error}"),
                }
            }

            let toggle = MenuItem::with_id(app, "toggle", "Show/Hide", true, None::<&str>)?;
            let cursor = MenuItem::with_id(app, "cursor", "Toggle click-through", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&toggle, &cursor, &quit])?;

            TrayIconBuilder::new()
                .icon(
                    app.default_window_icon()
                        .cloned()
                        .expect("bundle icon is declared in tauri.conf.json"),
                )
                .tooltip("Irene")
                .menu(&menu)
                .show_menu_on_left_click(true)
                .on_menu_event(|app, event| {
                    let app = app.clone();
                    let id = event.id.as_ref().to_string();
                    std::thread::spawn(move || match id.as_str() {
                        "toggle" => toggle_main(&app),
                        "cursor" => {
                            toggle_manual_capture(&app);
                        }
                        "quit" => app.exit(0),
                        _ => {}
                    });
                })
                .build(app)?;

            Ok(())
        })
        .on_window_event(|window, event| {
            let label = window.label();
            if label != MAIN_WINDOW && label != DASHBOARD_WINDOW {
                return;
            }
            match event {
                WindowEvent::CloseRequested { api, .. } => {
                    api.prevent_close();
                    eprintln!("[irene] {label}: close requested - hiding both");
                    let app = window.app_handle().clone();
                    let why = format!("{label} closed");
                    std::thread::spawn(move || hide_main(&app, &why));
                }
                WindowEvent::Resized(_) if window.is_minimized().unwrap_or(false) => {
                    // her taskbar button, Win+D: one minimized window would leave the
                    // other up - both hide instead (and the window is restored, hidden,
                    // so a later show brings it back whole)
                    eprintln!("[irene] {label}: minimized - hiding both");
                    let app = window.app_handle().clone();
                    let label = label.to_string();
                    std::thread::spawn(move || {
                        if let Some(w) = app.get_webview_window(&label) {
                            let _ = w.unminimize();
                        }
                        hide_main(&app, &format!("{label} minimized"));
                    });
                }
                _ => {}
            }
        })
        .invoke_handler(tauri::generate_handler![greet, summon, sleep, command_bar, show, capture_shield, panel_rect, corpus_keys, summon_voice, show_panel_window, pointer::hand_pointer, pointer::pointer_enabled, dev_visibility_path, visibility_report, geometry_report, panel_burst, yield_front, toggle_pin, dark_mode, warmup, intro_cursor])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|_app, event| match event {
            tauri::RunEvent::ExitRequested { code, .. } => {
                eprintln!("[irene] exit requested (code {code:?})");
            }
            tauri::RunEvent::Exit => {
                lifeline::exit_record("normal exit", "");
                intro_cursor::set(false);
                intro_cursor::restore();
            }
            _ => {}
        });
}
