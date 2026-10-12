r"""Keiko in the RUNNING app (start-irene.ps1 -Dev), through the dev socket only - no
OS input, no screenshot, the mic deafened:

  .venv\Scripts\python scripts\keiko_live_check.py

The HUD's strike recogniser needs his captures first (ctrl+alt+shift+9), so his
strikes are sent here the way the HUD sends them ({"type": "keiko_strike"}); the
rest is the real thing:

  start      "Irene, let's do keiko": the keiko scene starts, a line, a face
  strikes    men / kote / gyaku-dou: each gets an answer (block, hit, ippon with
             flags, or a strike back) sent to the HUD, with a line
  talk       she still answers him mid-keiko, and the scene isn't replaced
  stop       "Irene, stop": keiko ends, she bows out
  no pose    a kamae from the HUD starts nothing
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


async def until_listening(ws, wait: float = 60) -> tuple[str, list[dict]]:
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
    return said, seen + await drain(ws, 0.8)


async def say(ws, text: str, wait: float = 60):
    await ws.send(json.dumps({"type": "command", "text": text}))
    return await until_listening(ws, wait)


def keiko_msgs(seen):
    return [m for m in seen if m.get("type") == "keiko"]


async def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    async with websockets.connect("ws://127.0.0.1:8765/ws", max_size=None) as ws:
        await drain(ws, 1)
        await ws.send(json.dumps({"type": "debug_ui", "action": "show"}))
        await ws.send(json.dumps({"type": "mic_deaf", "value": True}))
        await drain(ws, 3)
        try:
            await ws.send(json.dumps({"type": "kamae", "phase": "start"}))
            seen = await drain(ws, 3)
            record("no pose trigger", not keiko_msgs(seen) and not [m for m in seen if m.get("type") == "transcript"], f"{len(seen)} message(s), no keiko")

            said, seen = await say(ws, "Irene, let's do keiko")
            print(f"      she: {said!r}")
            record("start: the keiko scene", [m.get("action") for m in keiko_msgs(seen)] == ["start"], f"{keiko_msgs(seen)}")
            record("start: a line", "onegaishimasu" in said.lower(), said[:70])
            await drain(ws, 3)

            answers = []
            for k, (strike, p, clean) in enumerate([("men", 0.99, True), ("kote", 0.95, True), ("gyaku_dou", 0.8, False), ("men", 0.98, True), ("kote", 0.99, True), ("men", 0.99, True)]):
                await ws.send(json.dumps({"type": "keiko_strike", "strike": strike, "p": p, "clean": clean}))
                said, seen = await until_listening(ws, 30)
                acts = keiko_msgs(seen)
                answers.append(acts[0]["action"] if acts else None)
                print(f"      he: {strike}  ->  {acts[0] if acts else None}  she: {said!r}")
                await drain(ws, 1.5)
            record("strikes: every one answered", all(answers), f"{answers}")
            record("strikes: a mix of answers", len(set(answers)) >= 2, f"{sorted(set(a for a in answers if a))}")

            said, seen = await say(ws, "You're quick today!", wait=90)
            print(f"      he: You're quick today!  she: {said!r}")
            record("talk: she answers mid-keiko", bool(said), said[:70])

            said, seen = await say(ws, "Irene, stop")
            print(f"      he: Irene, stop  she: {said!r}")
            record("stop: keiko ends", [m.get("action") for m in keiko_msgs(seen)] == ["end"], f"{keiko_msgs(seen)}")
            record("stop: she bows out", "arigatou" in said.lower(), said[:80])

            await ws.send(json.dumps({"type": "keiko_strike", "strike": "men", "p": 0.99, "clean": True}))
            record("after: strikes ignored", not keiko_msgs(await drain(ws, 3)), "keiko is off")
        finally:
            await ws.send(json.dumps({"type": "mic_deaf", "value": False}))
            await drain(ws, 1)
    ok = sum(r[1] for r in results)
    print(f"{ok}/{len(results)} passed")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
