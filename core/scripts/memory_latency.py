r"""Does her long-term memory slow her down? First audio with it off and on.

  .venv\Scripts\python scripts\memory_latency.py [--items 600] [--rounds 2]

Through Core itself, like e2e_latency.py: Ollama, her real voice, the output stream -
with the speaker's gain at 0 (timed, not heard). Nothing of his memory is touched:
the memory is a temporary store seeded with about a month of made-up use (exchanges,
facts, research, lectures). Each case runs with memory off, then on, in a fresh
conversation each time, alternating, so drift hits both alike. No OS input: chat and
questions only.

Reports first audio (median, p90) per arm, the retrieval time per turn, and the
context it added.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(CORE.parent))

from tools.localconfig import personal  # noqa: E402

LOGS = CORE / "logs"

CASES = [
    "Why is the sky blue?",
    "Tell me something interesting about octopuses.",
    "What should I cook tonight?",
    "How do I get better at kendo footwork?",
    "Explain how a refrigerator works.",
    "What did I tell you about my brother?",
    "What did we talk about last week?",
    "Remind me, when is my project deadline?",
]

TOPICS = ["kendo footwork", "sourdough starter", "the Sicilian defence", "rust lifetimes", "a cheap mechanical keyboard",
          "sleep schedules", "Hanoi street food", "the French revolution", "black holes", "learning Japanese kana",
          "a budget for the trip to Da Lat", "linear algebra eigenvalues", "running shoes", "home espresso", "jazz piano voicings"]
FACTS = ["Trác is my younger brother, he just started university in Hanoi", "my work project is a warehouse scheduling app, the deadline is the end of November",
         "I prefer short answers", "I'm allergic to peanuts", "my kendo dojo trains on Tuesday and Friday nights", "my sensei is called Mr. Long",
         "I'm learning Japanese for a trip next spring", "my laptop is a ThinkPad X1", "my girlfriend's birthday is the 3rd of December"]


def seed(store, n: int) -> None:
    from irene import recall

    rng = random.Random(7)
    now = time.time()
    for k, fact in enumerate(FACTS):
        store.add("fact", fact, at=now - rng.uniform(2, 30) * 86400, session=f"s{k}")
    for k in range(n - len(FACTS)):
        topic = rng.choice(TOPICS)
        at = now - rng.uniform(1, 30) * 86400
        kind = rng.choices(["turn", "research", "lecture"], [0.85, 0.12, 0.03])[0]
        if kind == "turn":
            store.add("turn", f'He said: "question {k} about {topic}" You said: "Here is a short answer number {k} about {topic}, with a detail or two."', at=at, session=f"t{k // 6}")
        elif kind == "research":
            store.add("research", f"What the pages said about {topic}: finding {k}, with sources and a few numbers.", about=f"{topic} ({k})", at=at)
        else:
            store.add("lecture", f"A lecture on {topic}: three sections, homework {k}.", about=f"the lecture of day {k}: {topic}", at=at)
    recall.flush()


async def run(items: int, rounds: int) -> dict:
    from irene import app as app_mod, openers, recall
    from irene.brain import Conversation
    from irene.tts import Speaker

    recall.EMBEDDER.load()
    store = recall.Store(Path(tempfile.mkdtemp(prefix="irene-memlat-")) / "memory.sqlite")
    started = time.perf_counter()
    seed(store, items)
    print(f"seeded {len(store)} memories in {time.perf_counter() - started:.1f}s", flush=True)
    recall.HIS = recall.DEV = store

    core = app_mod.Core()
    core.bridge.bind(asyncio.get_running_loop())
    core.speaker = await asyncio.to_thread(Speaker, personal("pronunciation.yaml"), lambda _v: None)
    core.speaker.gain = 0.0  # timed, not heard
    voice = core.speaker.voice
    core.speaker.openers = await asyncio.to_thread(openers.load_or_render, voice)
    core.speaker.openers_engine = voice.name
    await asyncio.to_thread(core.quick.load_or_render, voice)
    await core.llm.warm()
    rows = []
    # one conversation per block, as he uses her: each turn's read-ahead of the history
    # (warm_cache) finishes before the next - he is listening to her answer. Blocks
    # alternate off/on, on/off (ABBA), so drift lands on both; a block's first turn reads
    # the whole prompt cold and is reported apart.
    for r in range(rounds):
        for arm in (("off", "on") if r % 2 == 0 else ("on", "off")):
            recall.POLICY.enabled = arm == "on"
            core.conversation = Conversation(core.llm)
            core.conversation.game = core.chess
            for k, text in enumerate(CASES):
                core.last_ttfa = None
                await core.on_command({"text": text, "via": "voice"})
                await core._turn
                rec = core.conversation._recalled
                rows.append({"arm": arm, "said": text, "round": r, "cold": k == 0, "first_audio_ms": round(core.last_ttfa) if core.last_ttfa else None,
                             "recall_ms": round(rec.ms, 1), "recalled": len(rec.items), "recall_tokens": round(len(rec.section) / 3.5)})
                x = rows[-1]
                print(f"  {arm:3} {text[:44]:44} first audio {x['first_audio_ms']} ms  recall {x['recall_ms']} ms, {x['recalled']} items (~{x['recall_tokens']} tok){'  (cold)' if k == 0 else ''}", flush=True)
                if core.conversation._warm is not None:
                    try:
                        await core.conversation._warm
                    except Exception:  # noqa: BLE001 - a failed read-ahead only costs the next prefill
                        pass
                await asyncio.sleep(0.5)
    await core.llm.close()
    recall.POLICY.enabled = True
    out = {"items": len(store), "rows": rows}
    for arm in ("off", "on"):
        ms = sorted(x["first_audio_ms"] for x in rows if x["arm"] == arm and x["first_audio_ms"] and not x["cold"])
        out[arm] = {"first_audio_p50_ms": statistics.median(ms), "first_audio_p90_ms": ms[int(0.9 * (len(ms) - 1))], "n": len(ms)}
    on = [x for x in rows if x["arm"] == "on"]
    out["recall_ms_p50"] = statistics.median(x["recall_ms"] for x in on)
    out["recall_ms_max"] = max(x["recall_ms"] for x in on)
    out["recall_tokens_max"] = max(x["recall_tokens"] for x in on)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--items", type=int, default=600)
    parser.add_argument("--rounds", type=int, default=2)
    args = parser.parse_args()
    result = asyncio.run(run(args.items, args.rounds))
    (LOGS / "memory-latency.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=1))


if __name__ == "__main__":
    main()
