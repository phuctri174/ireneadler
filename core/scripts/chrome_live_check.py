r"""Round 7: what he looks at opens in HIS Chrome - checked in the RUNNING app
(start-irene.ps1 -Dev). No OS input, no screenshot:

  .venv\Scripts\python scripts\chrome_live_check.py

Commands go over the socket with "real_launch" (tools/sandbox.py): a test script
may open pages in his Chrome and pause the song it put on - never press a key.
Checked with read-only queries: Windows' window titles (his Chrome's tabs), and
Windows' media session (what plays, and whether it is paused).

  "Play Shape of You on YouTube."   a Chrome window titled ...Shape of You... YouTube;
                                    his media session playing it
  "pause"                           the session paused (through Windows' API)
  "open chess.com"                  a Chrome window titled ...Chess.com...
"""
from __future__ import annotations

import asyncio
import ctypes
import ctypes.wintypes as wt
import json
import re
import sys
import time
from pathlib import Path

import websockets

LOG = Path(__file__).resolve().parents[1] / "logs" / "core.log"


def chrome_titles() -> list[str]:
    """Titles of visible top-level windows that are Chrome's (read-only Win32)."""
    user32 = ctypes.windll.user32
    titles: list[str] = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def each(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if buf.value.endswith("Google Chrome"):
                    titles.append(buf.value)
        return True

    user32.EnumWindows(each, 0)
    return titles


async def media_state() -> list[tuple[str, int, str]]:
    from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager

    manager = await Manager.request_async()
    out = []
    for s in manager.get_sessions():
        props = await s.try_get_media_properties_async()
        out.append((s.source_app_user_model_id, int(s.get_playback_info().playback_status), props.title))
    return out


async def turn(ws, text: str, wait: float = 60) -> str:
    await ws.send(json.dumps({"type": "command", "text": text, "real_launch": True}))
    said, spoke = "", False
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        try:
            m = json.loads(await asyncio.wait_for(ws.recv(), 1))
        except asyncio.TimeoutError:
            continue
        if m.get("type") == "reply":
            said = m.get("speak", "") or said
        if m.get("type") == "state":
            spoke = spoke or m.get("value") == "speaking"
            if m.get("value") == "listening" and spoke and said:
                break
    return said


def tool_result(start: int, tool: str) -> str:
    with LOG.open("rb") as f:
        f.seek(start)
        found = re.findall(rf"tool {tool} -> (.*)", f.read().decode("utf-8", "replace"))
    return found[-1] if found else "not called"


async def main() -> int:
    ok_all = True

    def record(ok: bool, what: str, detail: str) -> None:
        nonlocal ok_all
        ok_all &= ok
        print(f"{'PASS' if ok else 'FAIL'}  {what:44} {detail[:150]}", flush=True)

    async with websockets.connect("ws://127.0.0.1:8765/ws", max_size=None) as ws:
        start = LOG.stat().st_size
        said = await turn(ws, "Play Shape of You on YouTube.")
        await asyncio.sleep(8)
        titles = chrome_titles()
        yt = [t for t in titles if "YouTube" in t and "Shape of You" in t]
        record(bool(yt), "YouTube opens in his Chrome", f"{tool_result(start, 'youtube_play')} | windows {yt or titles[:3]}")
        sessions = await media_state()
        playing = [s for s in sessions if "chrome" in s[0].lower() and "Shape of You" in (s[2] or "")]
        record(any(s[1] == 4 for s in playing), "  ...and it is playing (his media session)", f"{sessions} | she said {said[:60]!r}")

        start = LOG.stat().st_size
        said = await turn(ws, "pause")
        await asyncio.sleep(1)
        sessions = await media_state()
        paused = [s for s in sessions if "chrome" in s[0].lower() and "Shape of You" in (s[2] or "")]
        record(any(s[1] == 5 for s in paused), "pause pauses it (Windows' API, no key)", f"{tool_result(start, 'media_play_pause')} | she said {said[:60]!r}")

        start = LOG.stat().st_size
        said = await turn(ws, "open chess.com")
        await asyncio.sleep(6)
        titles = chrome_titles()
        chess = [t for t in titles if "chess" in t.lower()]
        record(bool(chess), "chess.com opens in his Chrome", f"{tool_result(start, 'open_url')} | windows {chess or titles[:3]}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
