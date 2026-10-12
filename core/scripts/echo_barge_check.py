r"""She finishes a long answer with the live mic open: her own voice coming back
through the speakers never stops her. (Round 6: researching the Queen's Gambit,
she stopped mid-sentence and answered her own echo.)

  (start-irene.ps1 -Dev running)   .venv\Scripts\python scripts\echo_barge_check.py

1. a long research-style answer played through the dev say_reply hook;
2. a real research turn ("Research the Queen's Gambit"), typed, so the whole
   pipeline runs - research, grounding, streaming speech - with the mic live;
3. for each: every barge-in decision core.log recorded while she spoke, and
   whether she reached the end of what she was saying.

No OS input, no screenshot. The room is heard (the mic is live): a person
really talking over her may, correctly, stop her - the log says who was heard.
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

LONG = (
    "<speak><cue>excited</cue>Ooh, the Queen's Gambit! It starts with d4, d5, then c4. "
    "White offers a pawn on c4 to pull Black's pawn away from the centre. "
    "White is about to sacrifice the pawn, but Black can't really hold onto it without falling behind. "
    "So Black usually declines it, with e6 or c6. <cue>thinking</cue>The Slav is the c6 line, and it's rock solid. "
    "Accepting it is fine too, as long as Black gives the pawn back in time. "
    "It's one of the oldest openings still played at the very top, and world champions have trusted it for a century. "
    "Want the lines on the panel?</speak>"
)


def log_from(offset: int) -> list[str]:
    with LOG.open("rb") as f:
        f.seek(offset)
        return f.read().decode("utf-8", "replace").splitlines()


async def until_done(ws, wait: float) -> tuple[str, list[dict], float]:
    """Until she has spoken and is listening again: her reply text, what was sent,
    and how long she was speaking."""
    seen, said, spoke_at, spoke_s = [], "", None, 0.0
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        try:
            m = json.loads(await asyncio.wait_for(ws.recv(), 1))
        except asyncio.TimeoutError:
            continue
        seen.append(m)
        if m.get("type") == "reply":
            said = m.get("speak", "") or said
        if m.get("type") == "state":
            if m.get("value") == "speaking" and spoke_at is None:
                spoke_at = time.monotonic()
            elif m.get("value") == "listening" and spoke_at is not None:
                spoke_s = time.monotonic() - spoke_at
                break
    return said, seen, spoke_s


def report(name: str, lines: list[str], spoke_s: float) -> bool:
    barges = [l for l in lines if "barge" in l]
    stopped = [l for l in lines if "him - she stops" in l or "he spoke over her" in l or "watchdog" in l]
    # heard and acted on - not heard and then ignored ("she is busy", her echo)
    turns = [
        l for i, l in enumerate(lines)
        if "for her:" in l and not any(w in " ".join(lines[i + 1 : i + 3]) for w in ("ignored", "does not interrupt"))
    ]
    print(f"--- {name}: spoke {spoke_s:.1f} s, {len(barges)} barge line(s)")
    for l in barges:
        print("   ", l[24:220])
    for l in turns:
        print("    TURN", l[24:220])
    ok = not stopped and not turns
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {'finished her answer' if ok else 'stopped or took a turn'}")
    return ok


async def main() -> int:
    ok = True
    async with websockets.connect("ws://127.0.0.1:8765/ws", max_size=None, ping_interval=None) as ws:
        await ws.send(json.dumps({"type": "debug_ui", "action": "show"}))
        await asyncio.sleep(3)
        start = LOG.stat().st_size
        await ws.send(json.dumps({"type": "say_reply", "raw": LONG}))
        _, _, spoke = await until_done(ws, 120)
        await asyncio.sleep(1.5)
        ok &= report("long answer (say_reply)", log_from(start), spoke)

        start = LOG.stat().st_size
        await ws.send(json.dumps({"type": "command", "text": "Research the Queen's Gambit opening."}))
        said, _, spoke = await until_done(ws, 180)
        await asyncio.sleep(1.5)
        lines = log_from(start)
        ok &= report("real research turn", [l for l in lines if "for her: 'Research the Queen" not in l], spoke)
        words = len(re.findall(r"\w+", said))
        print(f"    she said ({words} words): {said[:400]}")

        # and he, really talking over her, still stops her: his saved "What are you
        # doing?" through the live pipeline while she is mid-answer
        start = LOG.stat().st_size
        await ws.send(json.dumps({"type": "say_reply", "raw": LONG}))
        await asyncio.sleep(9)
        await ws.send(json.dumps({"type": "voice_replay", "turn": HIM}))
        await until_done(ws, 60)
        await asyncio.sleep(6)
        lines = log_from(start)
        for l in lines:
            if "barge" in l or "for her:" in l:
                print("   ", l[24:220])
        stopped = any("him - she stops" in l for l in lines)
        answered = any("for her: 'What are you doing?'" in l for l in lines)
        print(f"{'PASS' if stopped and answered else 'FAIL'}  he talks over her: {'she stopped and heard him' if stopped and answered else 'missed'}")
        ok &= stopped and answered
    return 0 if ok else 1


HIM = "2026-09-27/222406-abf31f"  # "What are you doing?"


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
