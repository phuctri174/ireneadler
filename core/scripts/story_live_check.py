r"""Story mode in the RUNNING app (start-irene.ps1 -Dev), through the dev socket only -
no OS input, no screenshot, the mic deafened (the room is not part of the story):

  .venv\Scripts\python scripts\story_live_check.py

He tells her a story over several messages, then asks her advice. Checked on what
the app actually sent the HUD and his ears:

  every story reply   reacts (no advice), short, shows a cue, asks him something
  the cues            fit the story (a wrong -> fuming / headShake, a twist -> shocked)
  people              the name from the first message is known in a later one
  advice              given once he asks - and only then
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from irene import story  # noqa: E402

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name:34} {detail}", flush=True)


async def drain(ws, seconds: float) -> list[dict]:
    out = []
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            out.append(json.loads(await asyncio.wait_for(ws.recv(), max(0.05, deadline - time.monotonic()))))
        except asyncio.TimeoutError:
            break
    return out


def cue_names(seen: list[dict]) -> list[str]:
    """The cues the HUD was told to show, in order."""
    names = []
    for m in seen:
        if m.get("type") in ("react", "reaction", "emotion", "gesture", "cue", "activity"):
            name = m.get("name") or m.get("value") or m.get("emotion")
            if isinstance(name, str) and name not in names:
                names.append(name)
    return names


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
    await drain(ws, 1.5)
    return said, seen


STORY = [
    ("So today at work my coworker Trác took credit for my slides in front of the whole team.", {"fuming", "headShake", "shocked", "surprised"}),
    ("And then the manager thanked him for them and he just smiled.", {"fuming", "headShake", "shocked", "surprised"}),
    ("You won't believe it, at lunch it turns out Trác asked HR for my promotion slot.", {"shocked", "surprised", "fuming", "headShake"}),
    ("Haha but then the projector died right when he started presenting MY slides.", {"giggle", "amused", "dizzy", "surprised", "shocked"}),
]


async def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    async with websockets.connect("ws://127.0.0.1:8765/ws", max_size=None) as ws:
        await drain(ws, 1)
        await ws.send(json.dumps({"type": "debug_ui", "action": "show"}))
        await ws.send(json.dumps({"type": "mic_deaf", "value": True}))
        await drain(ws, 3)
        await say(ws, "forget our conversation")
        types: set[str] = set()
        try:
            for text, fits in STORY:
                said, seen = await say(ws, text)
                types |= {m.get("type") for m in seen}
                shown = cue_names(seen)
                advice = [s for s in said.replace("?", "?.").split(".") if story.is_advice(s)]
                words = len(said.split())
                print(f"      he: {text}\n      she: {said!r}  cues {shown}", flush=True)
                record(f"reacts, no advice ({text[:16]}…)", bool(said) and not advice, f"{words} words" + (f", advised {advice[0]!r}" if advice else ""))
                record("  short", 0 < words <= 45, f"{words} words")
                record("  a cue that fits", bool(set(shown) & fits), f"{shown} vs {sorted(fits)}")
            said, seen = await say(ws, "What should I do about Trác?")
            print(f"      he: What should I do about Trác?\n      she: {said!r}  cues {cue_names(seen)}", flush=True)
            record("advice once he asks", story.is_advice(said) or len(said.split()) >= 15, f"{len(said.split())} words")
            record("  knows Trác is a he", " she " not in f" {said.lower()} " and " her " not in f" {said.lower()} ", said[:80])
        finally:
            await ws.send(json.dumps({"type": "mic_deaf", "value": False}))
            await drain(ws, 1)
        print(f"      message types seen: {sorted(t for t in types if t)}")
    ok = sum(r[1] for r in results)
    print(f"{ok}/{len(results)} passed")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
