r"""Chess with Irene in the RUNNING app (start-irene.ps1 -Dev), through the dev socket
only - no OS input, no screenshot, the mic deafened:

  .venv\Scripts\python scripts\chess_live_check.py

  start        "let's play chess": the live board goes up, her line, a cue
  moves        "e4", "knight to f3": the board after his move, then after hers
  illegal      refused with the reason, the board unchanged
  talk         "are you winning?" goes to her (the model) - and the board STAYS up
  takeback     his move and hers undone, the board shows it
  resign       the game ends, the board comes down a few seconds later
"""
from __future__ import annotations

import asyncio
import json
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
    seen += await drain(ws, 1.0)
    return said, seen


def boards(seen: list[dict]) -> list[dict | None]:
    return [m.get("value") for m in seen if m.get("type") == "draw"]


def faces(seen: list[dict]) -> list[str]:
    return [m.get("value") for m in seen if m.get("type") in ("emotion", "reaction", "activity") and m.get("value") not in (None, "neutral")]


async def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    async with websockets.connect("ws://127.0.0.1:8765/ws", max_size=None) as ws:
        await drain(ws, 1)
        await ws.send(json.dumps({"type": "debug_ui", "action": "show"}))
        await ws.send(json.dumps({"type": "mic_deaf", "value": True}))
        await drain(ws, 3)
        try:
            said, seen = await say(ws, "Let's play chess!")
            b = [x for x in boards(seen) if x]
            print(f"      she: {said!r} faces {faces(seen)}")
            record("start: live board up", bool(b) and b[-1].get("template") == "chessboard" and b[-1].get("live"), f"status {b[-1].get('status') if b else None}")
            record("start: a line and a face", bool(said) and bool(faces(seen)), said[:60])
            # she asks which colour first (since the colour question): he takes white
            said, seen = await say(ws, "white")
            b = [x for x in boards(seen) if x]
            record("colour: he takes white", bool(b) and b[-1].get("status") == "YOUR MOVE", f"status {b[-1].get('status') if b else None}")

            for move in ("e4", "knight to f3"):
                said, seen = await say(ws, move)
                b = [x for x in boards(seen) if x]
                print(f"      he: {move}  she: {said!r} faces {faces(seen)}")
                record(f"{move}: his board, then hers", len(b) >= 2 and len(b[-1].get("history", [])) == len(b[0].get("history", [])) + 1, f"{[x.get('history', [])[-2:] for x in b]}")
                record(f"{move}: she announced hers", bool(said) and b and b[-1].get("status") == "YOUR MOVE", said[:70])

            plies = len(b[-1]["history"])
            said, seen = await say(ws, "queen to h7")
            print(f"      he: queen to h7  she: {said!r}")
            record("illegal: refused, why", "queen" in said.lower() and not [x for x in boards(seen) if x and len(x.get("history", [])) != plies], said[:80])

            said, seen = await say(ws, "Are you winning?", wait=90)
            b = boards(seen)
            print(f"      he: Are you winning?  she: {said!r}")
            record("talk: she answers", bool(said), said[:80])
            record("talk: the board stays up", bool(b) and all(x and x.get("template") == "chessboard" for x in b), f"{len(b)} draw message(s), none empty" if b and all(b) else f"{b}")

            said, seen = await say(ws, "take that back")
            b = [x for x in boards(seen) if x]
            print(f"      he: take that back  she: {said!r}")
            record("takeback: two plies undone", bool(b) and len(b[-1].get("history", [])) == plies - 2, f"{plies} -> {len(b[-1].get('history', [])) if b else '?'}")

            said, seen = await say(ws, "I resign")
            print(f"      he: I resign  she: {said!r} faces {faces(seen)}")
            later = await drain(ws, 8)
            record("resign: the game ends", bool(said), said[:60])
            record("resign: board down after", None in boards(later), f"{boards(later)}")
        finally:
            await ws.send(json.dumps({"type": "mic_deaf", "value": False}))
            await drain(ws, 1)
    ok = sum(r[1] for r in results)
    print(f"{ok}/{len(results)} passed")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
