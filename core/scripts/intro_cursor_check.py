r"""His cursor during her introduction, checked in the RUNNING app (start-irene.ps1
-Dev): gone from the boot until her greeting's last word, back after. Read-only -
the cursor's own image (GetCursorInfo, drawn into an off-screen bitmap), never a
screenshot, never any input.

  .venv\Scripts\python scripts\intro_cursor_check.py
"""
from __future__ import annotations

import asyncio
import ctypes
import ctypes.wintypes as wt
import json
import time

import websockets

user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32


class CURSORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("flags", wt.DWORD), ("hCursor", wt.HANDLE), ("pt", wt.POINT)]


def cursor_pixels() -> int:
    """How many pixels the current cursor draws (0: invisible)."""
    info = CURSORINFO(cbSize=ctypes.sizeof(CURSORINFO))
    if not user32.GetCursorInfo(ctypes.byref(info)) or not info.flags & 1 or not info.hCursor:
        return 0
    size = 64
    screen = user32.GetDC(None)
    dc = gdi32.CreateCompatibleDC(screen)
    bmp = gdi32.CreateCompatibleBitmap(screen, size, size)
    gdi32.SelectObject(dc, bmp)
    lit = 0
    for background in (0x00FFFFFF, 0x00000000):
        brush = gdi32.CreateSolidBrush(background)
        user32.FillRect(dc, ctypes.byref(wt.RECT(0, 0, size, size)), brush)
        gdi32.DeleteObject(brush)
        user32.DrawIconEx(dc, 0, 0, info.hCursor, 0, 0, 0, None, 3)
        lit = max(lit, sum(1 for y in range(0, size, 2) for x in range(0, size, 2) if gdi32.GetPixel(dc, x, y) != background))
    gdi32.DeleteDC(dc)
    gdi32.DeleteObject(bmp)
    user32.ReleaseDC(None, screen)
    return lit


async def main() -> int:
    samples: list[tuple[float, int, str]] = []
    async with websockets.connect("ws://127.0.0.1:8765/ws", max_size=None) as ws:
        await ws.send(json.dumps({"type": "mic_deaf", "value": True}))
        before = cursor_pixels()
        await ws.send(json.dumps({"type": "debug_ui", "action": "show"}))
        await ws.send(json.dumps({"type": "play_entrance", "name": ""}))
        t0 = time.monotonic()
        greeted_at = None
        try:
            while time.monotonic() - t0 < 50:
                try:
                    m = json.loads(await asyncio.wait_for(ws.recv(), 0.5))
                except asyncio.TimeoutError:
                    m = {}
                if m.get("type") == "intro_cursor":
                    samples.append((time.monotonic() - t0, cursor_pixels(), f"intro_cursor hidden={m['hidden']}"))
                    if not m["hidden"]:
                        greeted_at = time.monotonic()
                elif int((time.monotonic() - t0) * 2) % 6 == 0:
                    samples.append((time.monotonic() - t0, cursor_pixels(), m.get("type", "")))
                if greeted_at and time.monotonic() - greeted_at > 2:
                    break
        finally:
            await ws.send(json.dumps({"type": "mic_deaf", "value": False}))
    after = cursor_pixels()
    print(f"before the summon: {before} cursor pixels")
    hidden = [s for s in samples if 1.0 < s[0] and (greeted_at is None or s[0] < greeted_at - t0 - 0.2)]
    for at, px, what in samples:
        print(f"  {at:5.1f} s  {px:4d} px  {what}")
    print(f"after her greeting: {after} cursor pixels")
    ok = before > 0 and hidden and all(px == 0 for _, px, _ in hidden) and after > 0 and greeted_at is not None
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
