r"""Which of Irene's global hotkeys another running app already owns, on this PC.

  .venv\Scripts\python scripts\hotkey_probe.py

Each combination is registered with RegisterHotKey and let go at once: it fails
when another app holds it globally. Nothing is pressed or sent - no OS input.
Run it with the HUD closed, or Irene's own keys show as taken.

It only sees GLOBAL registrations. Shortcuts that live inside an app (Word's
ctrl+alt+1 heading, a browser's F11) are not visible to it - hud/HOTKEYS.md lists
those from what each app documents.
"""
from __future__ import annotations

import ctypes
import sys

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
VK = {
    **{chr(c): c for c in range(ord("A"), ord("Z") + 1)},
    **{str(d): 0x30 + d for d in range(10)},
    **{f"F{n}": 0x6F + n for n in range(1, 13)},
    "SPACE": 0x20,
    "ESCAPE": 0x1B,
}


def parse(combo: str) -> tuple[int, int]:
    mods, key = 0, None
    for part in combo.upper().split("+"):
        if part == "CTRL":
            mods |= MOD_CONTROL
        elif part == "ALT":
            mods |= MOD_ALT
        elif part == "SHIFT":
            mods |= MOD_SHIFT
        elif part == "WIN":
            mods |= MOD_WIN
        else:
            key = VK[part]
    return mods, key


def free(combo: str) -> bool:
    user32 = ctypes.windll.user32
    mods, key = parse(combo)
    ok = bool(user32.RegisterHotKey(None, 0xBEEF, mods | MOD_NOREPEAT, key))
    if ok:
        user32.UnregisterHotKey(None, 0xBEEF)
    return ok


def main(combos: list[str]) -> None:
    for combo in combos:
        print(f"{combo:24} {'free' if free(combo) else 'TAKEN by another app'}")


if __name__ == "__main__":
    main(sys.argv[1:] or [
        # what Irene has used, and what she moves to
        "ctrl+alt+i", "ctrl+alt+d", "ctrl+alt+a", "ctrl+alt+escape", "ctrl+alt+c", "ctrl+alt+space", "ctrl+alt+t", "ctrl+alt+r",
        *[f"ctrl+alt+{d}" for d in range(1, 6)], *[f"f{n}" for n in range(6, 12)],
        "ctrl+alt+shift+r", "ctrl+alt+shift+c", *[f"ctrl+alt+shift+{d}" for d in range(1, 6)], *[f"ctrl+alt+shift+f{n}" for n in range(6, 12)],
    ])
