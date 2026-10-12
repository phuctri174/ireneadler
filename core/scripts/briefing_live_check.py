r"""This round's features in the RUNNING app (start-irene.ps1 -Dev), through the dev
hooks only - no OS input, no screenshot:

  .venv\Scripts\python scripts\briefing_live_check.py

  briefing     "What's new today?": spoken from real readings, the panel gets the
               whole briefing (dealt in, with its paper sound), the board splits
               into sections that appear one per sentence and all stay up
  expansion    "Tell me more about the second one": that item, from the briefing
  cache        asked again: answered from the 15-minute cache, much faster
  greetings    "hi Irene" and an entrance's greeting: about now, his name in them
"""
from __future__ import annotations

import asyncio
import json
import time

import websockets

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name:28} {detail}", flush=True)


async def drain(ws, seconds: float) -> list[dict]:
    out = []
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            out.append(json.loads(await asyncio.wait_for(ws.recv(), max(0.05, deadline - time.monotonic()))))
        except asyncio.TimeoutError:
            break
    return out


async def say(ws, text: str, wait: float = 120) -> tuple[str, list[dict], float]:
    await ws.send(json.dumps({"type": "command", "text": text}))
    t0 = time.monotonic()
    seen, said = [], ""
    deadline = t0 + wait
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
    return said, seen, time.monotonic() - t0


def boards(seen: list[dict]) -> list[int]:
    """How many briefing sections each board_sync showed (a section = its amber header)."""
    out = []
    for m in seen:
        if m.get("type") != "board_sync":
            continue
        shapes = (m.get("spec") or m.get("set") or {}).get("shapes") or []
        out.append(sum(1 for s in shapes if s.get("type") == "label" and s.get("color") == "amber" and str(s.get("id", "")).endswith(".0")))
    return out


async def main() -> int:
    async with websockets.connect("ws://127.0.0.1:8765/ws", max_size=None) as ws:
        await drain(ws, 1)
        await ws.send(json.dumps({"type": "mic_deaf", "value": True}))
        await ws.send(json.dumps({"type": "debug_ui", "action": "show"}))
        await drain(ws, 3)
        try:
            said, seen, took = await say(ws, "What's new today?")
            print(f"  she said ({took:.1f} s): {said}")
            panel = [m for m in seen if m.get("type") == "panel" and m.get("value")]
            content = panel[-1]["value"] if panel else {}
            kinds = [b.get("kind") for b in content.get("blocks", [])]
            record("briefing spoken", len(said.split()) > 12 and said.rstrip().endswith("?"), f"{len(said.split())} words")
            record("briefing on the panel", {"weather", "price", "story"} <= set(kinds), f"blocks {sorted(set(kinds))}")
            counts = boards(seen)
            record("board: one section a sentence", counts[:1] == [0] and counts[-1] >= 2 and counts == sorted(counts),
                   f"sections shown per board_sync {counts}")
            cues = [m.get("value") for m in seen if m.get("type") in ("reaction", "emotion")]
            record("opens on newsDesk", "newsDesk" in cues, f"cues {cues[:6]}")

            said2, seen2, took2 = await say(ws, "Tell me more about the second one.")
            print(f"  she said ({took2:.1f} s): {said2}")
            panel2 = [m for m in seen2 if m.get("type") == "panel" and m.get("value")]
            record("expansion answered", bool(said2) and bool(panel2), f"panel subtitle {panel2[-1]['value'].get('subtitle', '') if panel2 else '-'}")

            said3, seen3, _ = await say(ws, "Anything new?")
            # the app's own measure: his words to her first sound
            ttfa = [m.get("command_to_audio_ms") for m in seen + seen3 if m.get("type") == "latency"]
            record("answers at once", bool(ttfa) and max(ttfa) < 1500, f"first audio {ttfa} ms")
            ttfa2 = [m.get("command_to_audio_ms") for m in seen2 if m.get("type") == "latency"]
            print(f"  expansion first audio: {ttfa2} ms")

            said4, seen4, _ = await say(ws, "Hi Irene")
            record("greeting: hi", "Mister Tri" in said4, repr(said4))
            await ws.send(json.dumps({"type": "play_entrance", "name": ""}))
            entrance = await drain(ws, 40)
            greets = [m.get("text") for m in entrance if m.get("type") == "transcript" and m.get("role") == "irene"]
            record("greeting: after an entrance", any("Mister Tri" in (g or "") for g in greets), repr(greets[-1:] or "-"))
        finally:
            await ws.send(json.dumps({"type": "mic_deaf", "value": False}))
            await drain(ws, 1)
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
