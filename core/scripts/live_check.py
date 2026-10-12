"""Drive the running app (start-irene.ps1 -Dev) through its dev hooks and log what
she said and which cue fired on every reply - no OS-level input, only the socket.

  entrances      play each entrance, ask "what are you doing?", log the answer
  conversation   a 20-turn conversation; the cue distribution at the end

Run (from core/): .venv/Scripts/python scripts/live_check.py entrances|conversation
Writes logs/live-<mode>.jsonl. No screen grabs: they catch the whole desktop.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from collections import Counter
from pathlib import Path

import websockets

URL = "ws://127.0.0.1:8765/ws"
LOGS = Path(__file__).resolve().parents[1] / "logs"
ENTRANCES = ["chess", "kendo", "energy_wave", "cards", "victorian", "domain_expansion"]
QUESTIONS = ["what are you doing?", "What were you up to?", "what are you doing, Irene?"]
CONVERSATION = [
    "hey Irene",
    "how's your day going?",
    "haha, you're funny",
    "that was a bit cringy, not gonna lie",
    "guess what, I got the job!",
    "thanks, you're the best",
    "I wonder why the sky is blue",
    "my cat died this morning",
    "I'm so tired today",
    "tell me a joke",
    "lol that's terrible",
    "what's your favourite chess opening?",
    "do you like kendo?",
    "what do you think about rainy days?",
    "good job today, Irene",
    "sure you are, Irene",
    "I passed my exam!",
    "ugh, nothing's working today",
    "what should I have for dinner?",
    "goodnight Irene",
]
CUE_TYPES = {"reaction", "emotion", "activity"}


class Link:
    def __init__(self, ws):
        self.ws = ws
        self.seen: list[tuple[float, dict]] = []
        self.changed = asyncio.Event()

    async def read(self) -> None:
        async for text in self.ws:
            self.seen.append((time.monotonic(), json.loads(text)))
            self.changed.set()

    async def send(self, message: dict) -> None:
        await self.ws.send(json.dumps(message))

    async def wait_for(self, test, since: int, timeout: float) -> int | None:
        """Index of the first message from `since` that passes `test`."""
        deadline = time.monotonic() + timeout
        while True:
            for i in range(since, len(self.seen)):
                if test(self.seen[i][1]):
                    return i
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            self.changed.clear()
            try:
                await asyncio.wait_for(self.changed.wait(), left)
            except asyncio.TimeoutError:
                return None


def cues_in(messages: list[dict]) -> list[str]:
    out = []
    for m in messages:
        if m.get("type") in CUE_TYPES and m.get("value") and m.get("value") != "neutral":
            out.append(m["value"])
    return out


async def turn(link: Link, text: str) -> dict:
    """Send one command; wait for her reply to finish; what she said and showed."""
    start = len(link.seen)
    await link.send({"type": "command", "text": text})
    got = await link.wait_for(lambda m: m.get("type") == "reply", start, 120)
    end = await link.wait_for(lambda m: m.get("type") == "state" and m.get("value") in ("listening", "error"), got or start, 60)
    window = [m for _, m in link.seen[start : (end or len(link.seen)) + 1]]
    reply = link.seen[got][1] if got is not None else {}
    return {"said": text, "speak": reply.get("speak", ""), "cues": cues_in(window)}


async def entrances(link: Link) -> list[dict]:
    rows = []
    for k, name in enumerate(ENTRANCES):
        start = len(link.seen)
        await link.send({"type": "play_entrance", "name": name})
        talk_over = name == "cards"  # one where he talks over her greeting
        if talk_over:
            await link.wait_for(lambda m: m.get("type") in ("entrance", "summon") and m.get("phase") == "start", start, 20)
            await asyncio.sleep(1.5)
        else:
            # the entrance, then her greeting, then listening
            said = await link.wait_for(lambda m: m.get("type") == "transcript" and m.get("role") == "irene", start, 30)
            greet = await link.wait_for(lambda m: m.get("type") == "transcript" and m.get("role") == "irene", (said or start) + 1, 30)
            await link.wait_for(lambda m: m.get("type") == "state" and m.get("value") == "listening", (greet or start) + 1, 30)
        row = await turn(link, QUESTIONS[k % len(QUESTIONS)])
        row["entrance"] = name
        row["talked_over_greeting"] = talk_over
        rows.append(row)
        print(f"[{name}{' (talked over)' if talk_over else ''}] {row['said']!r} -> {row['cues']} {row['speak']!r}", flush=True)
        await asyncio.sleep(1.0)
    return rows


async def conversation(link: Link) -> list[dict]:
    rows = []
    for k, text in enumerate(CONVERSATION):
        row = await turn(link, text)
        rows.append(row)
        print(f"{k + 1:2d}. {text!r} -> {row['cues']} {row['speak']!r}", flush=True)
    first = [r["cues"][0] if r["cues"] else "(none)" for r in rows]
    repeats = sum(a == b for a, b in zip(first, first[1:]))
    print("\nopening cue per reply:", Counter(first).most_common())
    print(f"replies with no cue: {first.count('(none)')}/{len(rows)}; same opening cue back to back: {repeats}")
    return rows


async def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "entrances"
    async with websockets.connect(URL, max_size=None) as ws:
        link = Link(ws)
        reader = asyncio.create_task(link.read())
        rows = await (entrances if mode == "entrances" else conversation)(link)
        reader.cancel()
    LOGS.mkdir(exist_ok=True)
    out = LOGS / f"live-{mode}.jsonl"
    out.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    print(f"\nlog: {out}")


if __name__ == "__main__":
    asyncio.run(main())
