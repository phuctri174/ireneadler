//! Why the HUD stopped, written down (core/irene/lifeline.py is core's side).
//!
//! Round 13: core and the HUD closed together 17 minutes into a lecture capture and
//! left no trace anywhere. Now the HUD writes, next to core's:
//!   core/logs/hud-heartbeat.jsonl  every 30 s: uptime, working set, threads
//!   core/logs/exits.jsonl          {"who": "hud"} start and exit records: a panic, the
//!                                  app exiting, its console closed, Windows ending the
//!                                  session or suspending. A run that left no exit
//!                                  record gets one at the next start ("unknown - no exit
//!                                  record", with its last heartbeat): killed without warning.

use std::ffi::c_void;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::OnceLock;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

static STARTED: OnceLock<Instant> = OnceLock::new();
static EXITED: AtomicBool = AtomicBool::new(false);
const EVERY: Duration = Duration::from_secs(30);

fn logs() -> PathBuf {
    // hud/src-tauri -> core/logs (a local dev build, like everything here)
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..").join("..").join("core").join("logs")
}

fn now() -> String {
    // seconds since the epoch (core's records carry local ISO time; both sort the same)
    let secs = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0);
    secs.to_string()
}

fn uptime() -> u64 {
    STARTED.get().map(|t| t.elapsed().as_secs()).unwrap_or(0)
}

fn append(file: &str, record: serde_json::Value) {
    let dir = logs();
    let _ = std::fs::create_dir_all(&dir);
    if let Ok(mut f) = OpenOptions::new().create(true).append(true).open(dir.join(file)) {
        let _ = writeln!(f, "{record}");
        let _ = f.sync_all();
    }
}

/// Once per run: how it ended. The first reason wins.
pub fn exit_record(reason: &str, detail: &str) {
    if EXITED.swap(true, Ordering::SeqCst) {
        return;
    }
    append(
        "exits.jsonl",
        serde_json::json!({"at_epoch": now(), "who": "hud", "pid": std::process::id(), "event": "exit",
                           "reason": reason, "uptime_s": uptime(), "detail": detail}),
    );
    eprintln!("[irene] lifeline: exiting - {reason}");
}

// ---- Win32 ---------------------------------------------------------------------------

#[repr(C)]
#[allow(non_snake_case)]
struct ProcessMemoryCounters {
    cb: u32,
    PageFaultCount: u32,
    PeakWorkingSetSize: usize,
    WorkingSetSize: usize,
    QuotaPeakPagedPoolUsage: usize,
    QuotaPagedPoolUsage: usize,
    QuotaPeakNonPagedPoolUsage: usize,
    QuotaNonPagedPoolUsage: usize,
    PagefileUsage: usize,
    PeakPagefileUsage: usize,
}

#[repr(C)]
#[allow(non_snake_case)]
struct ThreadEntry32 {
    dwSize: u32,
    cntUsage: u32,
    th32ThreadID: u32,
    th32OwnerProcessID: u32,
    tpBasePri: i32,
    tpDeltaPri: i32,
    dwFlags: u32,
}

#[repr(C)]
#[allow(non_snake_case)]
struct WndClassW {
    style: u32,
    lpfnWndProc: Option<unsafe extern "system" fn(*mut c_void, u32, usize, isize) -> isize>,
    cbClsExtra: i32,
    cbWndExtra: i32,
    hInstance: *mut c_void,
    hIcon: *mut c_void,
    hCursor: *mut c_void,
    hbrBackground: *mut c_void,
    lpszMenuName: *const u16,
    lpszClassName: *const u16,
}

#[repr(C)]
struct Msg {
    hwnd: *mut c_void,
    message: u32,
    wparam: usize,
    lparam: isize,
    time: u32,
    pt: [i32; 2],
    private: u32,
}

#[link(name = "kernel32")]
extern "system" {
    fn GetCurrentProcess() -> *mut c_void;
    fn K32GetProcessMemoryInfo(process: *mut c_void, counters: *mut ProcessMemoryCounters, cb: u32) -> i32;
    fn CreateToolhelp32Snapshot(flags: u32, pid: u32) -> *mut c_void;
    fn Thread32First(snapshot: *mut c_void, entry: *mut ThreadEntry32) -> i32;
    fn Thread32Next(snapshot: *mut c_void, entry: *mut ThreadEntry32) -> i32;
    fn CloseHandle(handle: *mut c_void) -> i32;
    fn SetConsoleCtrlHandler(handler: Option<unsafe extern "system" fn(u32) -> i32>, add: i32) -> i32;
    fn GetModuleHandleW(name: *const u16) -> *mut c_void;
}

#[link(name = "user32")]
extern "system" {
    fn RegisterClassW(class: *const WndClassW) -> u16;
    fn CreateWindowExW(ex: u32, class: *const u16, name: *const u16, style: u32, x: i32, y: i32, w: i32, h: i32,
                       parent: *mut c_void, menu: *mut c_void, inst: *mut c_void, param: *mut c_void) -> *mut c_void;
    fn DefWindowProcW(hwnd: *mut c_void, msg: u32, wparam: usize, lparam: isize) -> isize;
    fn GetMessageW(msg: *mut Msg, hwnd: *mut c_void, min: u32, max: u32) -> i32;
    fn TranslateMessage(msg: *const Msg) -> i32;
    fn DispatchMessageW(msg: *const Msg) -> isize;
}

fn working_set_mb() -> u64 {
    let mut c: ProcessMemoryCounters = unsafe { std::mem::zeroed() };
    c.cb = std::mem::size_of::<ProcessMemoryCounters>() as u32;
    if unsafe { K32GetProcessMemoryInfo(GetCurrentProcess(), &mut c, c.cb) } != 0 {
        (c.WorkingSetSize / (1024 * 1024)) as u64
    } else {
        0
    }
}

fn threads() -> u32 {
    const TH32CS_SNAPTHREAD: u32 = 0x4;
    let me = std::process::id();
    let snap = unsafe { CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0) };
    if snap.is_null() || snap as isize == -1 {
        return 0;
    }
    let mut e: ThreadEntry32 = unsafe { std::mem::zeroed() };
    e.dwSize = std::mem::size_of::<ThreadEntry32>() as u32;
    let mut n = 0;
    let mut ok = unsafe { Thread32First(snap, &mut e) };
    while ok != 0 {
        if e.th32OwnerProcessID == me {
            n += 1;
        }
        ok = unsafe { Thread32Next(snap, &mut e) };
    }
    unsafe { CloseHandle(snap) };
    n
}

unsafe extern "system" fn console_event(event: u32) -> i32 {
    let reason = match event {
        0 => "ctrl+c",
        1 => "ctrl+break",
        2 => "console window closed",
        5 => "log off",
        6 => "windows shutting down",
        _ => "console event",
    };
    exit_record(reason, "");
    0 // the default handling (the exit) goes on
}

unsafe extern "system" fn session_proc(hwnd: *mut c_void, msg: u32, wparam: usize, lparam: isize) -> isize {
    const WM_QUERYENDSESSION: u32 = 0x11;
    const WM_ENDSESSION: u32 = 0x16;
    const WM_POWERBROADCAST: u32 = 0x218;
    match msg {
        WM_QUERYENDSESSION => {
            eprintln!("[irene] lifeline: Windows asks to end the session");
            1
        }
        WM_ENDSESSION if wparam != 0 => {
            exit_record("windows ending the session", "");
            0
        }
        WM_POWERBROADCAST => {
            let what = match wparam {
                0x4 => "suspending",
                0x7 => "resumed (suspend)",
                0x12 => "resumed (automatic)",
                _ => "power event",
            };
            beat(what);
            DefWindowProcW(hwnd, msg, wparam, lparam)
        }
        _ => DefWindowProcW(hwnd, msg, wparam, lparam),
    }
}

fn wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

fn session_window() {
    let class = wide("IreneHudLifeline");
    let title = wide("Irene HUD lifeline");
    unsafe {
        let inst = GetModuleHandleW(std::ptr::null());
        let wc = WndClassW {
            style: 0,
            lpfnWndProc: Some(session_proc),
            cbClsExtra: 0,
            cbWndExtra: 0,
            hInstance: inst,
            hIcon: std::ptr::null_mut(),
            hCursor: std::ptr::null_mut(),
            hbrBackground: std::ptr::null_mut(),
            lpszMenuName: std::ptr::null(),
            lpszClassName: class.as_ptr(),
        };
        if RegisterClassW(&wc) == 0 {
            return;
        }
        // top-level and hidden: only top-level windows are told the session is ending
        let hwnd = CreateWindowExW(0, class.as_ptr(), title.as_ptr(), 0, 0, 0, 0, 0, std::ptr::null_mut(),
                                   std::ptr::null_mut(), inst, std::ptr::null_mut());
        if hwnd.is_null() {
            return;
        }
        let mut msg: Msg = std::mem::zeroed();
        while GetMessageW(&mut msg, std::ptr::null_mut(), 0, 0) > 0 {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
    }
}

fn beat(note: &str) {
    append(
        "hud-heartbeat.jsonl",
        serde_json::json!({"at_epoch": now(), "who": "hud", "pid": std::process::id(), "uptime_s": uptime(),
                           "working_set_mb": working_set_mb(), "threads": threads(), "note": note}),
    );
}

/// The previous HUD run, if it left a start but no exit: written now as "unknown".
fn previous_run() {
    let Ok(text) = std::fs::read_to_string(logs().join("exits.jsonl")) else { return };
    let records: Vec<serde_json::Value> = text.lines().filter_map(|l| serde_json::from_str(l).ok()).collect();
    let Some(start) = records.iter().rev().find(|r| r["who"] == "hud" && r["event"] == "start") else { return };
    let pid = start["pid"].clone();
    if records.iter().any(|r| r["who"] == "hud" && r["event"] == "exit" && r["pid"] == pid) {
        return;
    }
    let beat = std::fs::read_to_string(logs().join("hud-heartbeat.jsonl"))
        .ok()
        .and_then(|t| t.lines().rev().filter_map(|l| serde_json::from_str::<serde_json::Value>(l).ok()).find(|r| r["pid"] == pid));
    append(
        "exits.jsonl",
        serde_json::json!({"at_epoch": now(), "who": "hud", "pid": pid, "event": "exit", "reason": "unknown - no exit record",
                           "detail": "terminated without warning: TerminateProcess or a process-tree kill, power loss, or a hard crash",
                           "last_heartbeat": beat, "found_at_next_start": true}),
    );
    eprintln!("[irene] lifeline: the previous HUD run left no exit record - written as unknown");
}

pub fn install() {
    let _ = STARTED.set(Instant::now());
    previous_run();
    append("exits.jsonl", serde_json::json!({"at_epoch": now(), "who": "hud", "pid": std::process::id(), "event": "start"}));
    let default_hook = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        // a panic is recorded as itself; it is an exit only if the process then dies
        // (release builds abort on panic; the next start then writes "unknown" too)
        append(
            "exits.jsonl",
            serde_json::json!({"at_epoch": now(), "who": "hud", "pid": std::process::id(), "event": "panic",
                               "uptime_s": uptime(), "detail": info.to_string()}),
        );
        default_hook(info);
    }));
    unsafe { SetConsoleCtrlHandler(Some(console_event), 1) };
    std::thread::spawn(session_window);
    std::thread::spawn(|| loop {
        beat("");
        std::thread::sleep(EVERY);
    });
}
