r"""The who_is_stronger skit in the RUNNING app (start-irene.ps1 -Dev), through the dev
hooks only: no OS input, no screenshot, the mic deaf, his turns the dev "heard" hook.

  .venv\Scripts\python scripts\who_is_stronger_live.py [--loud]

Muted by default (her lines, the boot and the summon song silent; every visual runs
on the same timeline). Checks: her intro's domain expansion plays and ends before
her first line; every line exactly as written, in order; the last line fires her
domain again - visor in, lifted 0.42 s later, carrying the 3 s hold; the take
completes.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time

import websockets

LINES = ["What's up, Mister Tri?", "If Jarvis used at 100% its power, he might give me some trouble.", "Nah. I'd win."]
SAID = ["Hey Irene", "Who's stronger, you or Jarvis?", "Damn, so would you lose?"]


async def main(loud: bool) -> int:
    ok = True
    async with websockets.connect("ws://127.0.0.1:8765/ws", max_size=None) as ws:
        seen: list[tuple[float, dict]] = []
        done = asyncio.Event()
        started = asyncio.Event()
        waits = 0

        async def reader():
            nonlocal waits
            async for raw in ws:
                m = json.loads(raw)
                seen.append((time.monotonic(), m))
                if m.get("type") == "skit" and m.get("phase") == "waiting":
                    said = SAID[min(waits, len(SAID) - 1)]
                    waits += 1
                    await asyncio.sleep(1.2)  # "he" talks (then 2.5 s of quiet ends his turn)
                    await ws.send(json.dumps({"type": "skit", "action": "heard", "seconds": 1.2, "said": said}))
                if m.get("type") == "skit" and m.get("phase") == "start":
                    started.set()
                # starting a take aborts one still running: ITS end comes first - only
                # an end after this take's start is this take's (one counted early once
                # un-muted the room mid-take)
                if m.get("type") == "skit" and m.get("phase") in ("end", "error") and started.is_set():
                    done.set()

        task = asyncio.create_task(reader())
        await ws.send(json.dumps({"type": "mic_deaf", "value": True}))
        if not loud:
            await ws.send(json.dumps({"type": "mute", "value": True}))
        try:
            await ws.send(json.dumps({"type": "skit", "action": "start", "name": "who_is_stronger"}))
            await asyncio.wait_for(done.wait(), 120)
            await asyncio.sleep(4.5)  # the last domain's hold and fade
        finally:
            if not loud:
                await ws.send(json.dumps({"type": "mute", "value": False}))
            await ws.send(json.dumps({"type": "mic_deaf", "value": False}))
            task.cancel()

    t0 = seen[0][0]
    said = [m["text"] for _, m in seen if m.get("type") == "transcript" and m.get("role") == "irene"]
    summons = [(t - t0, m) for t, m in seen if m.get("type") == "summon"]
    begun = next(i for i, (_, m) in enumerate(seen) if m.get("type") == "skit" and m.get("phase") == "start")
    end = next((m for _, m in seen[begun:] if m.get("type") == "skit" and m.get("phase") in ("end", "error")), {})
    for t, m in summons:
        print(f"  +{t:6.2f} s  summon {m.get('phase'):6} {('hold ' + str(m.get('hold_ms'))) if m.get('hold_ms') else ''} {m.get('bubble') or ''}")

    def check(name: str, good: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and good
        print(f"{'PASS' if good else 'FAIL'}  {name:44} {detail}")

    check("her lines, exactly and in order", [s for s in said if s in LINES] == LINES, f"{said}")
    intro = [m["phase"] for _, m in summons if not m.get("skit")]
    check("her intro's domain expansion played to its end", intro[:3] == ["start", "part2", "end"], f"{intro}")
    final = [(t, m) for t, m in summons if m.get("skit")]
    check("the last line fires the domain: start, then part2", [m["phase"] for _, m in final] == ["start", "part2"], f"{[m['phase'] for _, m in final]}")
    if len(final) == 2:
        gap = final[1][0] - final[0][0]
        check("part2 0.42 s after the visor", abs(gap - 0.42) < 0.12, f"{gap:.2f} s")
        check("it carries the 3 s hold, no bubble", all(m.get("hold_ms") == 3000 and not m.get("bubble") for _, m in final))
        line_at = next((t - t0 for t, m in seen if m.get("type") == "transcript" and m.get("text") == LINES[2]), None)
        check("fired with the last line, not before", line_at is not None and 0 <= final[0][0] - line_at < 1.0, f"line at +{line_at:.2f} s, visor at +{final[0][0]:.2f} s" if line_at else "")
    check("the take completed", bool(end.get("completed")), f"{end}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main("--loud" in sys.argv)))
