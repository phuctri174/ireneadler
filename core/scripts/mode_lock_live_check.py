r"""The mode lock, the learn/research verbs and shiai's scoreboard in the RUNNING app
(start-irene.ps1 -Dev), through the dev socket only - no OS input, no screenshot, the
mic deafened:

    .venv\Scripts\python scripts\mode_lock_live_check.py [--timeline out.json]

  chess      mid-game trash talk is answered in words; a drawing, research and another
             mode are brushed off; the board takes his move as before - and nothing
             else that repaints the display reaches the HUD
  shiai      0-0 on the scoreboard at the start; every point's score arrives before the
             line that calls it; study mode can't start mid-match; yame ends it
  study      "learn tenouchi" is study mode (a kendo term, not chess); "look up black
             holes" is brushed off while she studies; the lecture hotkey too

His swings are sent the way the HUD sends them ({"type": "strike_event"}).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

import websockets

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from irene import modes  # noqa: E402

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name:34} {detail}", flush=True)


class Log:
    def __init__(self, ws):
        self.ws = ws
        self.t0 = time.monotonic()
        self.seen: list[tuple[float, dict]] = []
        self.sent: list[tuple[float, dict]] = []

    def now(self) -> float:
        return time.monotonic() - self.t0

    async def reader(self) -> None:
        async for raw in self.ws:
            try:
                self.seen.append((self.now(), json.loads(raw)))
            except ValueError:
                pass

    async def send(self, m: dict) -> None:
        self.sent.append((self.now(), m))
        await self.ws.send(json.dumps(m))

    def since(self, t: float, kind: str | None = None) -> list[dict]:
        return [m for at, m in self.seen if at >= t and (kind is None or m.get("type") == kind)]

    async def wait(self, pred, timeout: float, since: float) -> dict | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for at, m in self.seen:
                if at >= since and pred(m):
                    return m
            await asyncio.sleep(0.05)
        return None

    async def settle(self, since: float, timeout: float = 40) -> None:
        said = await self.wait(lambda m: m.get("type") == "reply", timeout, since)
        if said:
            at = next(a for a, m in self.seen if m is said)
            await self.wait(lambda m: m.get("type") == "state" and m.get("value") == "listening", timeout, at)
        await asyncio.sleep(0.8)

    async def say(self, text: str, timeout: float = 40) -> float:
        t = self.now()
        await self.send({"type": "command", "text": text})
        await self.settle(t, timeout)
        return t


def repaints(msgs: list[dict], keep_board: bool = False) -> list[dict]:
    """What would have changed the display: a draw (but the game's own board when
    `keep_board`), the panel, a scene, a reply's display text."""
    out = []
    for m in msgs:
        kind = m.get("type")
        if kind == "draw" and keep_board and isinstance(m.get("value"), dict) and m["value"].get("template") == "chessboard":
            continue
        if kind in modes.REPAINTS and not (kind == "activity" and m.get("value") in (None, "keiko", "study")):
            out.append(m)
        elif kind == "reply" and m.get("display"):
            out.append(m)
    return out


def spoken(log: Log, t: float) -> str:
    return " ".join(m.get("speak", "") for m in log.since(t, "reply"))


def brushed(log: Log, t: float, mode: str) -> bool:
    said = spoken(log, t)
    return any(line in said for line in modes.BRUSH_OFF[mode])


async def chess_part(log: Log) -> None:
    t = await log.say("Let's play chess!")
    board = await log.wait(lambda m: m.get("type") == "draw" and isinstance(m.get("value"), dict) and m["value"].get("template") == "chessboard", 10, t)
    record("chess starts", board is not None, f"status {board and board['value'].get('status')!r}")
    await log.say("white")

    t = await log.say("You can even play Sicilian?", 60)
    said = spoken(log, t)
    record("trash talk answered in words", bool(said.strip()) and not brushed(log, t, "chess"), repr(said[:140]))
    record("  ...the board untouched", repaints(log.since(t)) == [], f"{[m.get('type') for m in repaints(log.since(t))]}")

    for ask in ("Draw me a black hole", "Research the Najdorf", "Let's do shiai", "Show me the panel"):
        t = await log.say(ask)
        bad = repaints(log.since(t))
        started = log.since(t, "shiai")
        record(f"brushed off: {ask}", brushed(log, t, "chess") and not bad and not started, f"{spoken(log, t)!r} {[m.get('type') for m in bad]}")

    t = log.now()
    await log.send({"type": "command", "text": "e4"})
    moved = await log.wait(lambda m: m.get("type") == "draw" and isinstance(m.get("value"), dict) and len(m["value"].get("history", [])) >= 2, 40, t)
    record("the game's own move still plays", moved is not None, f"{moved and moved['value'].get('history')}")
    await log.settle(t)
    await log.say("stop the game", 25)


async def shiai_part(log: Log) -> None:
    t = await log.say("Irene, let's do shiai", 60)
    start = await log.wait(lambda m: m.get("type") == "shiai" and m.get("action") == "start", 5, t)
    zero = await log.wait(lambda m: m.get("type") == "shiai" and m.get("action") == "score", 30, t)
    record("shiai starts at 0-0", start is not None and zero is not None and (zero["you"], zero["her"]) == (0, 0), f"{zero}")

    t = await log.say("Learn tenouchi")
    record("study can't start mid-match", brushed(log, t, "shiai") and not log.since(t, "study"), repr(spoken(log, t)))

    # strikes until the bout is over: each point's score before the line calling it
    order_ok, points = True, []
    for k in range(24):
        if log.since(t, "shiai") and any(m.get("action") == "end" for m in log.since(t, "shiai")):
            break
        mark = log.now()
        await log.send({"type": "strike_event", "wrist": "right", "peak": 30.0, "apex": -3.0, "drop": 4.5, "endx": 0.3})
        await log.wait(lambda m: m.get("type") == "reply" and m.get("speak"), 10, mark)
        await log.wait(lambda m: m.get("type") == "state" and m.get("value") == "listening", 15, mark)
        await asyncio.sleep(1.0)
    # every score message (her attacks score too, between his strikes) against the
    # moment she next starts speaking - the reply message only comes once she is done
    for i, (at, m) in enumerate(log.seen):
        if m.get("type") == "shiai" and m.get("action") == "score":
            spoke = next((a for a, n in log.seen[i + 1:] if n.get("type") == "state" and n.get("value") == "speaking"), None)
            points.append((m["you"], m["her"], spoke))
            order_ok = order_ok and spoke is not None and spoke >= at
            print(f"      score {m['you']}-{m['her']} on the board {((spoke or at) - at) * 1000:.0f} ms before she starts saying it")
    record("each score is up before she says it", bool(points) and order_ok, f"{len(points)} points")
    ended = any(m.get("action") == "end" for m in log.since(0, "shiai"))
    if not ended:
        await log.say("yame")
    record("the bout ends", any(m.get("action") == "end" for m in log.since(0, "shiai")), "")


async def study_part(log: Log) -> None:
    t = await log.say("learn tenouchi", 60)
    start = await log.wait(lambda m: m.get("type") == "study" and m.get("action") == "start", 5, t)
    record("'learn tenouchi' is study mode", start is not None and "tenouchi" in (start or {}).get("subject", ""), f"subject {start and start.get('subject')!r}")
    t = await log.say("look up black holes")
    record("research brushed off mid-study", brushed(log, t, "study") and not repaints(log.since(t)), repr(spoken(log, t)))
    t = log.now()
    await log.send({"type": "lecture", "action": "toggle"})
    await log.settle(t)
    record("lecture hotkey brushed off mid-study", brushed(log, t, "study"), repr(spoken(log, t)))
    await log.say("stop studying", 25)


async def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeline")
    a = ap.parse_args()
    async with websockets.connect("ws://127.0.0.1:8765/ws", max_size=None) as ws:
        log = Log(ws)
        reader = asyncio.create_task(log.reader())
        await log.send({"type": "mic_deaf", "value": True})
        await log.send({"type": "debug_ui", "action": "show"})
        await asyncio.sleep(3)
        try:
            await chess_part(log)
            await shiai_part(log)
            await study_part(log)
        finally:
            await log.send({"type": "lecture", "action": "stop"})
            await log.send({"type": "mic_deaf", "value": False})
            await asyncio.sleep(1)
            reader.cancel()
            if a.timeline:
                with open(a.timeline, "w", encoding="utf-8") as f:
                    json.dump({"seen": log.seen, "sent": log.sent}, f)
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
