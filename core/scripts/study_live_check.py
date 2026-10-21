r"""Study mode in the RUNNING app (start-irene.ps1 -Dev), through the dev socket only - no
OS input, no screenshot, the mic deafened:

    .venv\Scripts\python scripts\study_live_check.py [--hits N] [--gap S] [--timeline out.json]

His swings are sent the way the HUD sends them ({"type": "strike_event"}) - the HUD's
detector needs his hits capture first (ctrl+alt+shift+0) - and the rest is the real
thing:

  start      "Irene, go study the Sicilian": the study scene, the subject spoken back
  hits       each one jumps the bar (progress up, rate up), with the tier's line:
             ow (1-2), indignant (3-4), uncle (5+), and no face twice in a row
  payoff     the bar fills: what she learned, then a chess game with his colour asked
  colour     "white": she is Black, and answers 1.e4 with the Sicilian (her pinned book)

Every message core broadcasts is logged with its arrival time (--timeline), so the
whole sequence can be rendered offline as a clip.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

import websockets

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from irene import study  # noqa: E402

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name:28} {detail}", flush=True)


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

    async def settle(self, since: float, timeout: float = 30) -> None:
        """Until she has said something since `since` and is listening again."""
        said = await self.wait(lambda m: m.get("type") == "reply", timeout, since)
        if said:
            at = next(a for a, m in self.seen if m is said)
            await self.wait(lambda m: m.get("type") == "state" and m.get("value") == "listening", timeout, at)


async def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--hits", type=int, default=7)
    ap.add_argument("--gap", type=float, default=3.5)
    ap.add_argument("--subject", default="the Sicilian")
    ap.add_argument("--timeline")
    a = ap.parse_args()
    async with websockets.connect("ws://127.0.0.1:8765/ws", max_size=None) as ws:
        log = Log(ws)
        reader = asyncio.create_task(log.reader())
        await log.send({"type": "mic_deaf", "value": True})
        await log.send({"type": "debug_ui", "action": "show"})
        await asyncio.sleep(3)
        try:
            t = log.now()
            await log.send({"type": "command", "text": f"Irene, go study {a.subject}"})
            start = await log.wait(lambda m: m.get("type") == "study" and m.get("action") == "start", 15, t)
            record("study starts", start is not None, f"subject {start and start.get('subject')!r}, rate {start and start.get('rate')}")
            await log.settle(t)
            said = " ".join(m.get("speak", "") for m in log.since(t, "reply"))
            record("subject spoken back", a.subject.lower().split()[-1] in said.lower(), repr(said[:120]))
            traces = [m.get("step", "") for m in log.since(0, "hud_trace") if "study" in m.get("step", "")]
            # (the HUD reports whether a detector is shipped; it is not until the capture passes)
            print(f"      HUD: {traces[-1] if traces else '(no study trace)'}")

            hits, last_p = [], start.get("progress", 0) if start else 0
            next_swing = log.now() + a.gap
            for k in range(a.hits):
                # a steady cadence, like a person swinging - not waiting for her reply
                await asyncio.sleep(max(0.0, next_swing - log.now()))
                next_swing += a.gap
                t = log.now()
                await log.send({"type": "strike_event", "wrist": "right", "peak": 30.0, "apex": -3.0, "drop": 4.5, "endx": 0.3})
                m = await log.wait(lambda m: m.get("type") == "study" and m.get("action") in ("hit", "done"), 5, t)
                if not m or m.get("action") != "hit":
                    print(f"      swing {k + 1}: {'bar already full' if m else 'no hit'}")
                    break
                reply = await log.wait(lambda m: m.get("type") == "reply", min(8.0, a.gap), t)
                hits.append((m, reply.get("speak") if reply else ""))
                print(f"      hit {m['hits']}: {m.get('tier'):9} bar {m['progress']:.2f} rate x{m['rate'] * 90:.2f}  {hits[-1][1]!r}")
            jumps = all(h[0]["progress"] > p for h, p in zip(hits, [last_p] + [x[0]["progress"] for x in hits]))
            record("every hit jumps the bar", bool(hits) and jumps, f"{[round(h[0]['progress'], 2) for h in hits]}")
            tiers = [h[0].get("tier") for h in hits]
            want = [("ow" if n <= 2 else "indignant" if n <= 4 else "uncle") for n in range(1, len(hits) + 1)]
            record("reactions escalate", tiers == want, f"{tiers}")
            emos = [m.get("value") for m in log.since(0, "emotion") if m.get("value") not in ("neutral", None)]
            record("no face twice in a row", all(x != y for x, y in zip(emos, emos[1:])), f"{emos}")

            t = log.now()
            done = await log.wait(lambda m: m.get("type") == "study" and m.get("action") == "done", 120, 0)
            record("the bar fills", done is not None, f"at {done and 'done'}")
            end = await log.wait(lambda m: m.get("type") == "study" and m.get("action") == "end", 60, 0)
            board = await log.wait(lambda m: m.get("type") == "draw" and isinstance(m.get("value"), dict) and m["value"].get("template") == "chessboard", 20 if study.is_chess(a.subject) else 6, 0)
            finale = [m.get("speak", "") for m in log.since(0, "reply")]
            payoff = next((s for s in finale if s.startswith("Done")), "")
            record("payoff: what she learned", bool(payoff), repr(payoff[:200]))
            if len(hits) >= 8:
                record("rushed: she fumbles and says so", "Wait. No." in payoff, repr(payoff[:200]))
            if not study.is_chess(a.subject):
                # no feature covers it: she only summarises - no board, no game
                record("only a summary", board is None and "white or black" not in " ".join(finale).lower(), repr(payoff[:120]))
                return 0 if all(r[1] for r in results) else 1
            record("hands off to chess", board is not None and board["value"].get("status") == "WHITE OR BLACK?", f"board status {board and board['value'].get('status')!r}")
            await log.wait(lambda m: m.get("type") == "state" and m.get("value") == "listening", 30, log.now())
            await asyncio.sleep(1.5)

            t = log.now()
            await log.send({"type": "command", "text": "white"})
            await log.settle(t)
            await asyncio.sleep(1)
            t = log.now()
            await log.send({"type": "command", "text": "e4"})
            got = await log.wait(lambda m: m.get("type") == "draw" and isinstance(m.get("value"), dict) and len(m["value"].get("history", [])) >= 2, 30, t)
            hist = got["value"]["history"] if got else []
            name = study.defence(a.subject)
            want = study.opening_moves(name).replace("1.", "").split() if name else None
            record("she plays what she studied", want is None or hist[:2] == want, f"{hist} (want {want})")
            await log.settle(t)
            t = log.now()
            await log.send({"type": "command", "text": "stop the game"})
            await log.settle(t, 20)
        finally:
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
