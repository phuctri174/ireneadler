r"""This round's features, exercised in the RUNNING app (start-irene.ps1 -Dev),
through the dev hooks only - no OS input, no screenshot:

  .venv\Scripts\python scripts\live_round_check.py

  mic state    hidden -> "asleep" on her face; shown -> "listening"
  memory       a requirement and a correction, unrelated turns, then asked back
  kamae        the dev hook as the pose watcher would fire it: the scene, a
               fired-up line, and nothing added to the conversation
  research     a real research answer: key terms go to the board as she says them

(The voice paths have their own checks: summon_check.py, voice_after_summon_check.py.)
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import time

import websockets

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name:30} {detail}", flush=True)


async def drain(ws, seconds: float) -> list[dict]:
    out = []
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            out.append(json.loads(await asyncio.wait_for(ws.recv(), max(0.05, deadline - time.monotonic()))))
        except asyncio.TimeoutError:
            break
    return out


async def say(ws, text: str, wait: float = 60) -> tuple[str, list[dict]]:
    """A typed command; her words and everything sent until she is listening again."""
    await ws.send(json.dumps({"type": "command", "text": text}))
    seen, said = [], ""
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        try:
            m = json.loads(await asyncio.wait_for(ws.recv(), 1))
        except asyncio.TimeoutError:
            continue
        seen.append(m)
        if m.get("type") == "reply":
            said = m.get("speak", "")
        if m.get("type") == "state" and m.get("value") == "listening" and said:
            break
    return said, seen


async def main() -> int:
    async with websockets.connect("ws://127.0.0.1:8765/ws", max_size=None) as ws:
        await drain(ws, 1)
        # ---- mic state on her face ---------------------------------------------------
        # she starts hidden: show her first, so hiding is a real change
        await ws.send(json.dumps({"type": "debug_ui", "action": "show"}))
        await drain(ws, 3)
        await ws.send(json.dumps({"type": "debug_ui", "action": "hide"}))
        hidden = [m.get("phase") for m in await drain(ws, 3) if m.get("type") == "voice"]
        await ws.send(json.dumps({"type": "debug_ui", "action": "show"}))
        shown = [m.get("phase") for m in await drain(ws, 3) if m.get("type") == "voice"]
        record("mic: hidden -> asleep", "asleep" in hidden, f"phases {hidden}")
        record("mic: shown -> listening", "listening" in shown, f"phases {shown}")

        # ---- memory: a requirement, a correction, then asked back ---------------------
        await say(ws, "My sensei is called Tanaka.")
        await say(ws, "No wait, sorry, it's Takahashi, not Tanaka.")
        await say(ws, "I have a kendo grading on November 12th, remember that.")
        for filler in ("tell me a joke", "what's 7 times 8", "say something nice"):
            await say(ws, filler)
        said, _ = await say(ws, "What's my sensei's name?")
        record("memory: correction sticks", "takahashi" in said.lower() and "tanaka" not in said.lower(), repr(said[:90]))
        said, _ = await say(ws, "And when is my grading?")
        record("memory: requirement recalled", bool(re.search(r"12|twelfth|november", said, re.I)), repr(said[:90]))
        apology = [s for s in (said,) if re.search(r"apolog|my fault|sorry|not again", s, re.I)]
        record("memory: no spurious apology", not apology, repr(said[:60]))

        # ---- kamae through the hook -----------------------------------------------------
        await ws.send(json.dumps({"type": "debug_ui", "action": "kamae"}))
        seen = await drain(ws, 12)
        line = next((m.get("text") for m in seen if m.get("type") == "transcript" and m.get("role") == "irene"), None)
        cue = next((m.get("value") for m in seen if m.get("type") == "emotion" and m.get("value") != "neutral"), None)
        record("kamae: fired-up line and cue", bool(line) and bool(cue), f"{line!r} cue {cue}")
        await ws.send(json.dumps({"type": "debug_ui", "action": "kamae", "text": "end"}))
        await drain(ws, 2)
        said, _ = await say(ws, "What did I just tell you about my grading?")
        record("kamae: kept out of the conversation", "kamae" not in said.lower(), repr(said[:80]))

        # ---- research: the key terms board -----------------------------------------------
        said, seen = await say(ws, "Research how kendo dan grades work.", wait=150)
        # the plain terms board, or an illustrated one (Round 6: a flow for "how ...
        # work", notes beside a chessboard, points in a comparison)
        terms = [t for m in seen if m.get("type") == "board_term" for t in m.get("terms", [])] + [
            item.get("text") or item.get("key")
            for m in seen if m.get("type") == "board_sync"
            for items in (m.get("add") or {}).values() for item in items
        ]
        record("research: terms on the board", bool(terms), f"terms {terms[:6]} | said {said[:60]!r}")
    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed" + (f" - FAILED: {failed}" if failed else ""))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
