r"""Voice works whenever she is on screen, whatever summoned her.

  (start-irene.ps1 -Dev running)   .venv\Scripts\python scripts\voice_after_summon_check.py

1. hides her, then summons her the way the hotkey does (the dev hook runs the same
   Rust summon - no key is pressed);
2. waits for the entrance and her greeting to finish (state back to listening);
3. replays his saved "What are you doing?" - NO wake word - through the live mic
   pipeline;
4. passes if she heard it and answered.

Live, this path used to leave her asleep: only a voice summon woke the listener.
No OS input, no screenshot.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time

import websockets

from summon_check import irene_window_visible

TURN = "2026-09-27/222406-abf31f"  # "What are you doing?"


async def until(ws, want, seconds):
    deadline = time.monotonic() + seconds
    seen = []
    while time.monotonic() < deadline:
        try:
            m = json.loads(await asyncio.wait_for(ws.recv(), max(0.05, deadline - time.monotonic())))
        except asyncio.TimeoutError:
            break
        seen.append(m)
        if want(m):
            return m, seen
    return None, seen


async def main() -> int:
    async with websockets.connect("ws://127.0.0.1:8765/ws") as ws:
        await ws.send(json.dumps({"type": "debug_ui", "action": "hide"}))
        await asyncio.sleep(1.5)
        print("hidden:", irene_window_visible() is False)
        await ws.send(json.dumps({"type": "debug_ui", "action": "summon"}))
        entrance, _ = await until(ws, lambda m: m.get("type") == "entrance" and m.get("phase") == "start", 10)
        print("summoned (hotkey path), window visible:", irene_window_visible(), "| entrance:", entrance and entrance.get("name"))
        # the entrance, then her greeting: wait until she is listening again
        spoke, _ = await until(ws, lambda m: m.get("type") == "transcript" and m.get("role") == "irene" and "summon" not in str(m), 15)
        done, _ = await until(ws, lambda m: m.get("type") == "state" and m.get("value") == "listening", 20)
        print("greeting done:", bool(done), "| greeting:", spoke and spoke.get("text"))
        mic, _ = await until(ws, lambda m: False, 1.0)
        await ws.send(json.dumps({"type": "voice_replay", "turn": TURN}))
        heard, seen = await until(ws, lambda m: m.get("type") == "transcript" and m.get("role") == "user", 15)
        answer, seen2 = await until(ws, lambda m: m.get("type") == "transcript" and m.get("role") == "irene", 20)
        phases = [m.get("phase") for m in seen + seen2 if m.get("type") == "voice"]
        print("mic phases seen:", sorted(set(phases)))
        print("she heard:", heard and heard.get("text"))
        print("she said:", answer and answer.get("text"))
        ok = bool(heard and answer)
        print("RESULT:", "PASS - voice works after a hotkey summon, no wake word" if ok else "FAIL")
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
