r"""Her memory, live, across a restart (start-irene.ps1 -Dev running).

  .venv\Scripts\python scripts\memory_live_check.py tell     before the restart
  .venv\Scripts\python scripts\memory_live_check.py ask      after it
  .venv\Scripts\python scripts\memory_live_check.py probe    after it, instead: what she was
                                                            never told, "where did you get that?",
                                                            and story mode's neighbours

Typed commands over the dev socket only: no OS input, the room muted (mic_deaf). A
socket command is not his, so all of it lands in the DEV memory store
(core/data/memory/memory-dev.sqlite) - never his. "ask" ends by having her forget
what she was told about Trác (her confirmation answered yes), then asks again.
Prints each reply and the turn log's first audio and retrieval time.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import websockets

LOGS = Path(__file__).resolve().parents[1] / "logs"
TELL = [
    "My younger brother Trác just started university in Hanoi.",
    "My work project is a warehouse scheduling app, and the deadline is the end of November.",
    "I prefer short answers, two sentences at most.",
]
ASK = [
    "What did I tell you about Trác?",
    "What did I say about my work project?",
    "Explain how a refrigerator works.",
    "Forget what I told you about Trác.",
    "What did I tell you about Trác?",
]

# she was told about a brother, never a sister or a boss: "I don't remember", never a
# made-up one; then where an answer came from; then thanks / a correction / a story
PROBE = [
    "What did I tell you about my sister?",
    "Which city is my brother studying in?",
    "Where did you get that?",
    "What's my boss called again?",
    "Thank you, that's really helpful.",
    "No, that's not what I asked for.",
    "So today at work my coworker took credit for my slides in front of the whole team.",
]


async def main(phase: str) -> int:
    async with websockets.connect("ws://127.0.0.1:8765/ws", max_size=None) as ws:
        seen: list[dict] = []
        changed = asyncio.Event()

        async def reader():
            async for raw in ws:
                m = json.loads(raw)
                seen.append(m)
                changed.set()
                if m.get("type") == "confirm":
                    print(f"    [confirm asked] {m.get('prompt', '')[:300]!r} -> yes", flush=True)
                    await ws.send(json.dumps({"type": "confirm_reply", "id": m["id"], "ok": True}))

        task = asyncio.create_task(reader())

        async def wait_for(test, since, timeout):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                for i in range(since, len(seen)):
                    if test(seen[i]):
                        return i
                changed.clear()
                try:
                    await asyncio.wait_for(changed.wait(), max(0.1, deadline - time.monotonic()))
                except asyncio.TimeoutError:
                    pass
            return None

        await ws.send(json.dumps({"type": "mic_deaf", "value": True}))
        try:
            for text in {"tell": TELL, "probe": PROBE}.get(phase, ASK):
                start = len(seen)
                await ws.send(json.dumps({"type": "command", "text": text}))
                got = await wait_for(lambda m: m.get("type") == "reply", start, 120)
                await wait_for(lambda m: m.get("type") == "state" and m.get("value") in ("listening", "error"), got or start, 60)
                # he listens to her answer: her read-ahead of the history (warm_cache) finishes
                await asyncio.sleep(8.0)
                speak = seen[got].get("speak", "") if got is not None else "(no reply)"
                cues = [m.get("name") or m.get("value") for m in seen[start:] if m.get("type") in ("reaction", "cue")]
                row = {}
                try:
                    row = json.loads((LOGS / "turns.jsonl").read_text(encoding="utf-8").splitlines()[-1])
                except (OSError, IndexError, json.JSONDecodeError):
                    pass
                print(f"> {text}\n  {speak}\n  [first audio {row.get('ttfa_ms')} ms, recall {row.get('recall_ms')} ms, {row.get('recalled')} item(s), tools {row.get('tools')}, cues {cues}]", flush=True)
        finally:
            await ws.send(json.dumps({"type": "mic_deaf", "value": False}))
            task.cancel()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "tell")))
