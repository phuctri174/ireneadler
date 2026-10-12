//! The cursor during her introduction: gone - Windows' own and the hand pointer's
//! ring - from the boot until the last word of her greeting (core sends
//! intro_cursor hidden/shown; the HUD invokes this).
//!
//! Windows can't hide the cursor for other apps (ShowCursor is per thread), so
//! every system cursor is swapped for a blank one (SetSystemCursor) and his own
//! scheme is put back with SPI_SETCURSORS. A cursor left blank would be a disaster,
//! so it is restored on every path: when the intro ends or is skipped, after
//! SAFETY at the latest (whatever core says), when the HUD starts (a crash during
//! an intro), and when it exits.
//!
//! While hidden his hand doesn't drive the cursor either (pointer.rs): no dwell
//! can click something he can't see.

use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::time::Duration;

static HIDDEN: AtomicBool = AtomicBool::new(false);
static GENERATION: AtomicU64 = AtomicU64::new(0);
/// The longest the cursor stays hidden, whatever happens (boot 12 s + entrance +
/// greeting is well under this).
const SAFETY: Duration = Duration::from_secs(60);

// every system cursor Windows draws (OCR_*)
const CURSORS: [u32; 16] = [
    32512, 32513, 32514, 32515, 32516, 32640, 32641, 32642, 32643, 32644, 32645, 32646, 32648, 32649, 32650, 32651,
];
const SPI_SETCURSORS: u32 = 0x0057;

#[link(name = "user32")]
extern "system" {
    fn CreateCursor(instance: isize, x_hot: i32, y_hot: i32, width: i32, height: i32, and_plane: *const u8, xor_plane: *const u8) -> isize;
    fn SetSystemCursor(cursor: isize, id: u32) -> i32;
    fn SystemParametersInfoW(action: u32, param: u32, pv: *mut core::ffi::c_void, win_ini: u32) -> i32;
}

pub fn hidden() -> bool {
    HIDDEN.load(Ordering::Relaxed)
}

fn blank() -> isize {
    // 32x32: AND plane all ones (screen kept), XOR plane all zeros (nothing drawn)
    let and_plane = [0xFFu8; 128];
    let xor_plane = [0u8; 128];
    unsafe { CreateCursor(0, 0, 0, 32, 32, and_plane.as_ptr(), xor_plane.as_ptr()) }
}

/// His cursor scheme, as Windows has it saved.
pub fn restore() {
    unsafe { SystemParametersInfoW(SPI_SETCURSORS, 0, std::ptr::null_mut(), 0) };
}

pub fn set(hide: bool) {
    if hide {
        if HIDDEN.swap(true, Ordering::Relaxed) {
            return;
        }
        for id in CURSORS {
            // SetSystemCursor takes the handle (and destroys it): a new blank each
            let cursor = blank();
            if cursor != 0 {
                unsafe { SetSystemCursor(cursor, id) };
            }
        }
        let generation = GENERATION.fetch_add(1, Ordering::Relaxed) + 1;
        eprintln!("[irene] cursor hidden for her introduction");
        std::thread::spawn(move || {
            std::thread::sleep(SAFETY);
            if GENERATION.load(Ordering::Relaxed) == generation && HIDDEN.load(Ordering::Relaxed) {
                eprintln!("[irene] cursor still hidden after {} s - restored (safety)", SAFETY.as_secs());
                set(false);
            }
        });
    } else if HIDDEN.swap(false, Ordering::Relaxed) {
        restore();
        eprintln!("[irene] cursor back");
    }
}
