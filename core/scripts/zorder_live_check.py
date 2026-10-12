r"""Her z-order in the RUNNING app (start-irene.ps1 -Dev): she is an ordinary window
except from a summon until another window is activated, or while pinned.

  .venv\Scripts\python scripts\zorder_live_check.py

Opens Notepad, File Explorer and a new window of his Chrome (his profile,
about:blank) over her, activates each (SetForegroundWindow - a window-manager call,
never input), and reads where everything stands in Windows' own z-order. Then
summons her through the dev hook and checks she is back on top, and checks the
pin. Closes only the windows it opened (WM_CLOSE to those windows).
"""
from __future__ import annotations

import asyncio
import ctypes
import json
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

import websockets
import yaml
from pathlib import Path as _Path
import sys as _sys

_sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
from tools.localconfig import personal  # noqa: E402

user32 = ctypes.windll.user32
user32.GetWindow.restype = wintypes.HWND
user32.GetTopWindow.restype = wintypes.HWND
user32.GetForegroundWindow.restype = wintypes.HWND
GW_HWNDNEXT, GWL_EXSTYLE, WS_EX_TOPMOST, WM_CLOSE = 2, -20, 0x8, 0x10
ROOT = Path(__file__).resolve().parents[2]
results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name:44} {detail}", flush=True)


def windows() -> list[tuple[int, str, int]]:
    """Every visible top-level window, front to back: (hwnd, title, pid)."""
    out = []
    hwnd = user32.GetTopWindow(None)
    while hwnd:
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            out.append((int(hwnd), buf.value, pid.value))
        hwnd = user32.GetWindow(hwnd, GW_HWNDNEXT)
    return out


def topmost(hwnd: int) -> bool:
    return bool(user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST)


def find(title_part: str, exclude: set[int] = frozenset(), wait: float = 10.0) -> int | None:
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        for hwnd, title, _ in windows():
            if title_part.lower() in title.lower() and hwnd not in exclude:
                return hwnd
        time.sleep(0.25)
    return None


def irene() -> tuple[int | None, int | None]:
    main = next((h for h, t, _ in windows() if t == "Irene"), None)
    panel = next((h for h, t, _ in windows() if t == "Irene - panel"), None)
    return main, panel


def above(a: int, b: int) -> bool:
    order = [h for h, _, _ in windows()]
    return a in order and b in order and order.index(a) < order.index(b)


def front_of_both(hwnd: int) -> bool:
    """`hwnd` in front of BOTH her windows in Windows' z-order, and neither topmost."""
    main_w, panel_w = irene()
    return bool(main_w) and above(hwnd, main_w) and not topmost(main_w) and (not panel_w or (above(hwnd, panel_w) and not topmost(panel_w)))


async def skit_until(ws, waits_wanted: int, seen: list, timeout: float = 90.0) -> bool:
    """Read messages until the skit is waiting for him the `waits_wanted`-th time
    (or ended: waits_wanted 0). Collected into `seen`."""
    deadline = time.monotonic() + timeout
    waits = sum(1 for m in seen if m.get("type") == "skit" and m.get("phase") == "waiting")
    while time.monotonic() < deadline:
        try:
            m = json.loads(await asyncio.wait_for(ws.recv(), 1))
        except asyncio.TimeoutError:
            continue
        seen.append(m)
        if m.get("type") == "skit" and m.get("phase") == "waiting":
            waits += 1
            if waits == waits_wanted:
                return True
        if m.get("type") == "skit" and m.get("phase") == "end":
            return waits_wanted == 0
    return False


def activate(hwnd: int) -> bool:
    # window-manager calls only - as if he had clicked it; no input is sent. Windows
    # lets only the foreground thread hand the foreground on, so for this one call
    # we share its input queue (AttachThreadInput), the documented way round it
    kernel32 = ctypes.windll.kernel32
    fg = user32.GetForegroundWindow()
    theirs = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    ours = kernel32.GetCurrentThreadId()
    attached = bool(theirs) and theirs != ours and user32.AttachThreadInput(ours, theirs, True)
    try:
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(ours, theirs, False)
    time.sleep(0.8)
    return int(user32.GetForegroundWindow() or 0) == hwnd


async def dev(ws, action: str, wait: float = 2.5) -> None:
    await ws.send(json.dumps({"type": "debug_ui", "action": action}))
    await asyncio.sleep(wait)


async def main() -> int:
    chrome = yaml.safe_load((personal("chrome.yaml")).read_text(encoding="utf-8"))
    opened: list[int] = []
    async with websockets.connect("ws://127.0.0.1:8765/ws", max_size=None) as ws:
        await ws.send(json.dumps({"type": "mic_deaf", "value": True}))
        try:
            await dev(ws, "show")
            main_w, panel_w = irene()
            before = {h for h, _, _ in windows()}
            record("her windows are up", bool(main_w), f"main {main_w}, panel {panel_w}")
            if not main_w:
                return 1
            apps = [
                ("Notepad", ["notepad.exe"], "Notepad"),
                ("File Explorer", ["explorer.exe", str(ROOT)], "irene"),
                ("his Chrome", [chrome["chrome"], f"--profile-directory={chrome.get('profile_directory', 'Default')}", "--new-window", "about:blank"], "about:blank"),
            ]
            for name, cmd, title in apps:
                subprocess.Popen(cmd)
                hwnd = find(title, exclude=before | set(opened) | {main_w, panel_w or 0})
                if hwnd is None:
                    record(f"{name} opened", False, "no window")
                    continue
                opened.append(hwnd)
                fg = activate(hwnd)
                await asyncio.sleep(0.4)
                main_w, panel_w = irene()
                record(f"{name} in front of her", front_of_both(hwnd),
                       f"foreground {fg}, her main topmost {topmost(main_w)}, panel topmost {bool(panel_w and topmost(panel_w))}")
            # a summon: back on top, over all three
            await dev(ws, "summon", 3.0)
            main_w, panel_w = irene()
            record("summoned: on top of all three", topmost(main_w) and all(above(main_w, h) for h in opened),
                   f"main topmost {topmost(main_w)}, panel topmost {bool(panel_w and topmost(panel_w))}")
            # and he moves on: an app activated drops her again
            if opened:
                activate(opened[0])
                await asyncio.sleep(0.4)
                record("after the summon, Notepad activated: she drops", not topmost(main_w) and above(opened[0], main_w), f"main topmost {topmost(main_w)}")
            # his case: Chrome active, "Hey Irene" (the voice path - no input of hers
            # for Windows to see), then back to Chrome
            if len(opened) == 3:
                activate(opened[2])
                await ws.send(json.dumps({"type": "dev_wake"}))
                await asyncio.sleep(2.5)
                main_w, panel_w = irene()
                fg = int(user32.GetForegroundWindow() or 0)
                record("voice summon over active Chrome: on top, focused", topmost(main_w) and fg == main_w, f"main topmost {topmost(main_w)}, foreground is hers {fg == main_w}")
                activate(opened[2])
                await asyncio.sleep(0.4)
                record("...then Chrome again: in front of both", front_of_both(opened[2]))
                # let the summon's entrance and greeting finish before the pin checks
                await asyncio.sleep(18)
            # pinned: she stays above whatever he activates
            await dev(ws, "pin", 1.0)
            for hwnd in opened[1:]:
                activate(hwnd)
            await asyncio.sleep(0.4)
            record("pinned: on top whatever is activated", topmost(main_w) and all(above(main_w, h) for h in opened), f"main topmost {topmost(main_w)}")
            await dev(ws, "pin", 1.0)
            record("unpinned: an ordinary window again", not topmost(main_w), f"main topmost {topmost(main_w)}")

            # a skit: the summon raises her; while she waits through his rant, every
            # app he activates comes in front of both her windows - and after it too
            seen: list = []
            await ws.send(json.dumps({"type": "skit", "action": "start", "name": "first_dance"}))
            await skit_until(ws, 1, seen)
            await ws.send(json.dumps({"type": "skit", "action": "heard", "seconds": 1.2, "said": "Hey Irene"}))
            reached = await skit_until(ws, 2, seen)  # the intro and "What's up?" done: his rant
            main_w, panel_w = irene()
            record("skit: summoned on top", reached and topmost(main_w), f"main topmost {topmost(main_w)}, panel topmost {bool(panel_w and topmost(panel_w))}")
            for (name, _, _), hwnd in zip(apps, opened):
                activate(hwnd)
                await asyncio.sleep(0.4)
                record(f"skit, mid-take: {name} in front of her", front_of_both(hwnd))
            for waits in (3, 4, 0):
                await ws.send(json.dumps({"type": "skit", "action": "heard", "seconds": 2.0}))
                await skit_until(ws, waits, seen)
            ended = any(m.get("type") == "skit" and m.get("phase") == "end" and m.get("completed") for m in seen)
            record("skit: the take completed", ended)
            for (name, _, _), hwnd in zip(apps, opened):
                activate(hwnd)
                await asyncio.sleep(0.4)
                record(f"after the skit: {name} in front of her", front_of_both(hwnd))
        finally:
            # what it opened - and any other about:blank window its Chrome launch made
            mine = set(opened) | {h for h, t, _ in windows() if t == "about:blank - Google Chrome" and h not in before}
            for hwnd in mine:
                user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            await ws.send(json.dumps({"type": "mic_deaf", "value": False}))
    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed" + (f" - FAILED: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
