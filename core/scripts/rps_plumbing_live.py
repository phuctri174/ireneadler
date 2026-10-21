r"""Rock-paper-scissors plumbing in the RUNNING app (start-irene.ps1 -Dev), dev socket
only, mic deafened - no hand needed, none used:

  .venv\Scripts\python scripts\rps_plumbing_live.py

  no model     "rock paper scissors" with no rps_model.json: she says she can't read
               throws yet, and game mode never turns on
  capture      "train rock paper scissors": game mode ON in the HUD (hud_trace), her
               count, the shoot instant reaches the HUD and its frame window comes back
               (game_frames - empty with no hand in view), she asks again
  exit         "exit game": game mode OFF in the HUD, gestures back
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
    print(f"{'PASS' if ok else 'FAIL'}  {name:36} {detail}", flush=True)


async def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    seen: list[dict] = []
    async with websockets.connect("ws://127.0.0.1:8765/ws", max_size=None) as ws:
        async def reader():
            async for raw in ws:
                try:
                    seen.append(json.loads(raw))
                except ValueError:
                    pass

        task = asyncio.create_task(reader())
        send = lambda m: ws.send(json.dumps(m))  # noqa: E731

        async def until(pred, wait):
            deadline = time.monotonic() + wait
            while time.monotonic() < deadline:
                if any(pred(m) for m in seen):
                    return True
                await asyncio.sleep(0.2)
            return False

        await send({"type": "debug_ui", "action": "show"})
        await send({"type": "mic_deaf", "value": True})
        await asyncio.sleep(2)
        try:
            start = len(seen)
            await send({"type": "command", "text": "Let's play rock paper scissors!"})
            await until(lambda m: m.get("type") == "state" and m.get("value") == "listening", 40)
            said = " ".join(m.get("text", "") for m in seen[start:] if m.get("type") == "transcript" and m.get("role") == "irene")
            record("no model: she says so", "train" in said.lower(), said[:90])
            record("no model: game mode stays off", not any(m.get("type") == "game_mode" for m in seen[start:]), "")

            start = len(seen)
            await send({"type": "command", "text": "Train rock paper scissors."})
            ok = await until(lambda m: m.get("type") == "game_mode" and m.get("on"), 30)
            record("capture: game mode ON sent", ok, "")
            ok = await until(lambda m: m.get("type") == "game_shoot", 60)
            record("capture: shoot instant sent to HUD", ok, next((m.get("id") for m in seen[start:] if m.get("type") == "game_shoot"), ""))
            ok = await until(lambda m: m.get("type") == "transcript" and m.get("role") == "irene" and ("didn't see" in m.get("text", "") or "missed" in m.get("text", "").lower()), 30)
            record("capture: no hand -> she asks again", ok, "")
            await asyncio.sleep(1)
            start = len(seen)
            await send({"type": "command", "text": "exit game"})
            ok = await until(lambda m: m.get("type") == "game_mode" and m.get("on") is False, 30)
            record("exit: game mode OFF sent", ok, "")
            await asyncio.sleep(3)
        finally:
            await send({"type": "mic_deaf", "value": False})
            await asyncio.sleep(1)
            task.cancel()
    ok = sum(r[1] for r in results)
    print(f"{ok}/{len(results)} passed")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
