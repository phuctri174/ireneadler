r"""Media and files in the RUNNING app (start-irene.ps1 -Dev), typed commands only -
no OS input, no screenshot. Each step is checked on what the tool itself reported
(core.log "tool <name> -> ..."), and on what she said.

  .venv\Scripts\python scripts\media_files_live_check.py

  media   play a song in her browser, then "pause", "continue", "next song", and
          "pause" again - on the song itself (read back), not a blind media key
  files   research, "save this as a PDF in my downloads", "open that PDF you
          saved" - the file she saved opens in its default app
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from pathlib import Path

import websockets

LOG = Path(__file__).resolve().parents[1] / "logs" / "core.log"
STEPS = [
    ("Play Shape of You on YouTube.", "youtube_play", r"playing in Irene's browser: .*Shape of You"),
    ("pause the song", "media_play_pause", r"^paused: "),
    ("pause", "media_play_pause", r"^already paused"),
    ("continue", "media_play_pause", r"^playing again: "),
    ("next song", "media_next", r"^skipped to: "),
    ("pause", "media_play_pause", r"^paused: "),
    ("Research the Queen's Gambit opening.", "research", r"Research for"),
    ("Save this as a PDF in my downloads.", "save_panel_pdf", r"saved the panel as .+\.pdf in Downloads"),
    ("Open that PDF you saved.", "open_file", r"^opened .+\.pdf \(downloads\) in its default app"),
]


async def turn(ws, text: str, wait: float = 180) -> str:
    await ws.send(json.dumps({"type": "command", "text": text}))
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


async def main() -> int:
    ok_all = True
    async with websockets.connect("ws://127.0.0.1:8765/ws", max_size=None) as ws:
        await ws.send(json.dumps({"type": "debug_ui", "action": "show"}))
        await asyncio.sleep(2)
        # "files": the file steps only (no music)
        steps = STEPS[6:] if "files" in sys.argv[1:] else STEPS
        for text, tool, want in steps:
            start = LOG.stat().st_size
            said = await turn(ws, text)
            await asyncio.sleep(1.0 if tool != "youtube_play" else 4.0)
            with LOG.open("rb") as f:
                f.seek(start)
                results = re.findall(rf"tool {tool} -> (.*)", f.read().decode("utf-8", "replace"))
            ok = any(re.search(want, r) for r in results)
            ok_all &= ok
            print(f"{'PASS' if ok else 'FAIL'}  {text:42} {tool}: {(results[-1] if results else 'not called')[:110]}")
            print(f"      she said: {said[:140]}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
