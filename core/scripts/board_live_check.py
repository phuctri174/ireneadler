r"""The board illustrates what she says, in the RUNNING app (start-irene.ps1 -Dev),
through typed commands only - no OS input, no screenshot. For each answer: what
the HUD drew and when (its own report, "hud board ..." in core.log), next to the
sentences she said.

  .venv\Scripts\python scripts\board_live_check.py
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
CASES = [
    ("Research the Queen's Gambit opening.", "chessboard", r"reveal ply:\d"),
    ("Explain the parts of a shinai.", "shinai", r"reveal \w+"),
    ("Research the difference between Python and Rust for game development.", "compare", r"points "),
    ("Research how photosynthesis works.", "flow", r"steps "),
]


async def until_done(ws, wait: float) -> str:
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
        for command, template, synced in CASES:
            start = LOG.stat().st_size
            await ws.send(json.dumps({"type": "command", "text": command}))
            said = await until_done(ws, 180)
            await asyncio.sleep(1.5)
            with LOG.open("rb") as f:
                f.seek(start)
                lines = [l for l in f.read().decode("utf-8", "replace").splitlines() if "hud board" in l]
            drew = [l.split("hud ", 1)[1] for l in lines]
            ok = any(f"drew {template} (new)" in d for d in drew) and any(re.search(synced, d) for d in drew) and not any("REFUSED" in d for d in drew)
            ok_all &= ok
            print(f"{'PASS' if ok else 'FAIL'}  {command}")
            for d in drew:
                print("      ", d[:160])
            print("       she said:", said[:300])
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
