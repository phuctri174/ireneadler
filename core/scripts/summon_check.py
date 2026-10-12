r"""End to end: Irene hidden, he says "Hey Irene", her window appears.

  (start-irene.ps1 -Dev running)   .venv\Scripts\python scripts\summon_check.py [turn]

1. hides the HUD window (the dev hook does what SLEEP does) and checks Windows
   agrees it is hidden;
2. replays one of his saved "Hey Irene." voice turns through the live mic
   pipeline (the voice_replay dev hook: Silero, the endpointer, Whisper, the
   wake phrase - everything but the microphone itself);
3. watches the real window with a read-only Win32 query until it is visible;
4. prints every "summon path" step core.log recorded, so a failure says where
   the path stopped.

No OS input: nothing is pressed, clicked or typed; no screenshot is taken.
"""
from __future__ import annotations

import asyncio
import ctypes
import ctypes.wintypes as wt
import json
import sys
import time
from pathlib import Path

import websockets

LOG = Path(__file__).resolve().parents[1] / "logs" / "core.log"
DEFAULT_TURN = "2026-09-27/220107-03ec0c"  # "Hey Irene." as he said it


def irene_window_visible() -> bool | None:
    """Whether the HUD's top-level window ("Irene") is visible; None if not found."""
    user32 = ctypes.windll.user32
    found: list[bool] = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def each(hwnd, _):
        buf = ctypes.create_unicode_buffer(64)
        user32.GetWindowTextW(hwnd, buf, 64)
        if buf.value == "Irene":
            found.append(bool(user32.IsWindowVisible(hwnd)))
        return True

    user32.EnumWindows(each, 0)
    return any(found) if found else None


async def main(turn: str) -> int:
    start = LOG.stat().st_size if LOG.exists() else 0
    async with websockets.connect("ws://127.0.0.1:8765/ws") as ws:
        await ws.send(json.dumps({"type": "debug_ui", "action": "hide"}))
        for _ in range(30):
            await asyncio.sleep(0.1)
            if irene_window_visible() is False:
                break
        before = irene_window_visible()
        print(f"before: window {'not found' if before is None else 'VISIBLE' if before else 'hidden'}")
        if before is not False:
            print("could not start from hidden - is the HUD running (start-irene.ps1 -Dev)?")
            return 2
        await asyncio.sleep(1.0)
        said_at = time.perf_counter()
        await ws.send(json.dumps({"type": "voice_replay", "turn": turn}))
        shown_after = None
        while time.perf_counter() - said_at < 12:
            await asyncio.sleep(0.05)
            if irene_window_visible():
                shown_after = time.perf_counter() - said_at
                break
    await asyncio.sleep(1.5)  # the rest of the path lands in the log
    # the offset is in bytes (st_size): slice bytes, then decode
    lines = LOG.read_bytes()[start:].decode("utf-8", errors="replace").splitlines() if LOG.exists() else []
    print("core.log:")
    for line in lines:
        if "summon path" in line or "voice replay" in line or "for her" in line or "heard" in line:
            print("   ", line[:200])
    if shown_after is None:
        print("RESULT: the window did NOT appear within 12 s")
        return 1
    print(f"RESULT: the window appeared {shown_after:.2f} s after the replay started (the clip itself is ~1.6 s)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TURN)))
