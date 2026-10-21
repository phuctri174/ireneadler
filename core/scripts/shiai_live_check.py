r"""Shiai as specified (2026-10-18), and the mode fixes, in the RUNNING app
(start-irene.ps1 -Dev) - dev socket only: no OS input, the mic deafened, the camera's
own strikes and footwork ignored (camera_events), his swings sent as the HUD sends them:

    .venv\Scripts\python scripts\shiai_live_check.py [--timeline out.json]

  bout       a full bout: the 5 s countdown, hajime, a point, the 5 s pause, hajime,
             a point, ... the result - every hajime timed
  one swing  a swing that reaches core as three strike events over 1.4 s is one answer
  his guard  a block against her men; a step back from her attack
  mode       the dashboard says "Shiai" while it runs and nothing after; a brush-off
             mid-bout says why ("...bout..."); "stop the match", then straight away
             "learn the Sicilian" - study mode starts; "Hey learn Sicilian please" too
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

import websockets

results: list[tuple[str, bool, str]] = []
STRIKE = {"type": "strike_event", "wrist": "right", "peak": 30.0, "stopMs": 60}


def record(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name:46} {detail}", flush=True)


class Log:
    def __init__(self, ws):
        self.ws, self.t0, self.seen = ws, time.monotonic(), []

    def now(self) -> float:
        return time.monotonic() - self.t0

    async def reader(self) -> None:
        async for raw in self.ws:
            try:
                self.seen.append((self.now(), json.loads(raw)))
            except ValueError:
                pass

    async def send(self, m: dict) -> None:
        await self.ws.send(json.dumps(m))

    def at(self, m: dict) -> float:
        return next(a for a, x in self.seen if x is m)

    def since(self, t: float, kind: str | None = None) -> list[dict]:
        return [m for at, m in self.seen if at >= t and (kind is None or m.get("type") == kind)]

    async def wait(self, pred, timeout: float, since: float) -> dict | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for at, m in self.seen:
                if at >= since and pred(m):
                    return m
            await asyncio.sleep(0.03)
        return None

    async def say(self, text: str, timeout: float = 40) -> float:
        t = self.now()
        await self.send({"type": "command", "text": text})
        said = await self.wait(lambda m: m.get("type") == "reply", timeout, t)
        if said:
            await self.wait(lambda m: m.get("type") == "state" and m.get("value") == "listening", timeout, self.at(said))
        await asyncio.sleep(0.5)
        return t


def keiko(action: str):
    return lambda m: m.get("type") == "keiko" and m.get("action") == action


def spoken(log: Log, t: float) -> str:
    return " ".join(m.get("speak", "") for m in log.since(t, "reply"))


def mode_shown(log: Log, t: float) -> list:
    """Every mode the dashboard was told, since t (the fast part of its push)."""
    out = []
    for m in log.since(t):
        body = m.get("value") if isinstance(m.get("value"), dict) else m
        if isinstance(body, dict) and "mode" in body and m.get("type", "").startswith("dashboard"):
            out.append(body["mode"])
    return out


async def bout(log: Log) -> None:
    t = await log.say("Irene, let's do shiai", 60)
    count = await log.wait(keiko("countdown"), 15, t)
    go = await log.wait(keiko("hajime"), 15, t)
    took = log.at(go) - log.at(count) if count and go else -1
    record("start: a 5 s countdown, then hajime", count is not None and count.get("ms") == 5000 and 4.7 <= took <= 6.0,
           f"countdown {count and count.get('ms')} ms, hajime {took:.1f} s after it")
    await asyncio.sleep(1.0)
    shown = mode_shown(log, t)
    record("the dashboard shows the mode: Shiai", "Shiai" in shown, f"{shown}")

    # a bout to its end: his strikes (dice decide), her attacks in between
    calls, hajimes, last = [], [], log.at(go)
    while not any(m.get("action") == "end" for m in log.since(t, "shiai")) and log.now() - last < 90:
        mark = log.now()
        await log.send(STRIKE)
        call = await log.wait(keiko("ippon"), 3.0, mark)
        if call is not None:
            calls.append((call.get("who"), call.get("call")))
            if any(m.get("action") == "end" for m in log.since(mark, "shiai")):
                break
            nxt = await log.wait(keiko("hajime"), 15, log.at(call))
            if nxt is not None:
                hajimes.append(log.at(nxt) - log.at(call))
                last = log.at(nxt)
        await asyncio.sleep(2.0)
    ended = any(m.get("action") == "end" for m in log.since(t, "shiai"))
    his = [c for w, c in calls if w == "you"]
    record("a full bout runs to its result", ended and len(calls) >= 2, f"points {calls}")
    record("  ...every point of his is MEN ARI", bool(his) and all(c == "MEN ARI" for c in his), f"{his}")
    record("  ...after each point a ~5 s pause, then hajime", bool(hajimes) and all(4.7 <= h <= 7.5 for h in hajimes),
           f"call -> hajime {[round(h, 1) for h in hajimes]} s")
    await asyncio.sleep(1.5)
    record("  ...the dashboard says no mode after it", mode_shown(log, t)[-1:] == [None], f"{mode_shown(log, t)}")


async def one_swing(log: Log) -> None:
    t = await log.say("Irene, let's do shiai", 60)
    await log.wait(keiko("hajime"), 15, t)
    await asyncio.sleep(0.5)
    mark = log.now()
    for gap in (0.0, 0.55, 0.85):
        await asyncio.sleep(gap)
        await log.send(STRIKE)
    await asyncio.sleep(2.0)
    answers = [m for m in log.since(mark, "keiko") if m.get("action") in ("block", "dodge", "ippon")]
    record("one swing as 3 events over 1.4 s: one answer", len(answers) == 1, f"{[m.get('action') for m in answers]}")
    if not any(m.get("action") == "ippon" for m in answers):
        # her attack, answered: a block against her men, else a step back
        for _ in range(4):
            w = await log.wait(keiko("windup"), 20, log.now())
            if w is None or any(m.get("action") == "end" for m in log.since(mark, "shiai")):
                break
            await asyncio.sleep(0.5)
            if w.get("target") == "men":
                await log.send({"type": "shiai_move", "move": "block", "height": -0.9, "rest": 1.8})
                hit = await log.wait(keiko("impact"), 3, log.at(w))
                record("her men, blocked", hit is not None and hit.get("result") == "blocked", f"{hit and hit.get('result')}")
                break
            await log.send({"type": "shiai_move", "move": "retreat"})
            hit = await log.wait(keiko("impact"), 3, log.at(w))
            record("her kote, dodged by a step back", hit is not None and hit.get("result") == "dodged", f"{hit and hit.get('result')}")
    m = log.now()
    await log.say("Draw me a cat")
    said = spoken(log, m)
    record("a brush-off mid-bout says why", "bout" in said.lower() or "shiai" in said.lower(), repr(said[:90]))


async def end_then_study(log: Log) -> None:
    if not any(m.get("action") == "end" for m in log.since(log.now() - 1e9, "shiai")[-1:]):
        await log.say("stop the match")
    t = log.now()
    await log.send({"type": "command", "text": "learn the Sicilian"})
    st = await log.wait(lambda m: m.get("type") == "study" and m.get("action") == "start", 10, t)
    record("stop the match, then 'learn the Sicilian' at once", st is not None and "sicilian" in st.get("subject", "").lower(),
           f"study {st and st.get('subject')!r}")
    await asyncio.sleep(3)
    await log.say("stop studying")
    t = log.now()
    await log.send({"type": "command", "text": "Hey learn Sicilian please"})
    st = await log.wait(lambda m: m.get("type") == "study" and m.get("action") == "start", 10, t)
    record("'Hey learn Sicilian please' starts study mode", st is not None, f"study {st and st.get('subject')!r}")
    await asyncio.sleep(3)
    await log.say("stop studying")


async def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeline")
    a = ap.parse_args()
    async with websockets.connect("ws://127.0.0.1:8765/ws", max_size=None) as ws:
        log = Log(ws)
        reader = asyncio.create_task(log.reader())
        await log.send({"type": "mic_deaf", "value": True})
        await log.send({"type": "camera_events", "value": False})
        await log.send({"type": "debug_ui", "action": "show"})
        await asyncio.sleep(2)
        try:
            await bout(log)
            await one_swing(log)
            await end_then_study(log)
        finally:
            await log.send({"type": "camera_events", "value": True})
            await log.send({"type": "mic_deaf", "value": False})
            await asyncio.sleep(1)
            reader.cancel()
            if a.timeline:
                with open(a.timeline, "w", encoding="utf-8") as f:
                    json.dump(log.seen, f)
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
