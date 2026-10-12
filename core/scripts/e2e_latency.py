r"""End to end, through Core itself: his words -> the first sound he hears.

  .venv\Scripts\python scripts\e2e_latency.py [label]

Everything real - Ollama, Chatterbox-Turbo, the cached lead-ins and quick replies,
the output stream (WASAPI) and its latency - except that the speaker's gain is 0:
the timing is exact and nothing is heard. No OS input: the commands are get_time,
set_timer (the process exits long before it would fire) and research, cancelled
the moment her first word is heard.

Adds the end-of-speech time from profile_latency.py (his saved voice turns
replayed through the endpointer) to give his last word -> her first sound.
"""
from __future__ import annotations

import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(CORE.parent))

from tools.localconfig import personal  # noqa: E402
LOGS = CORE / "logs"

CASES = [
    ("small", "Thanks, Irene!"),
    ("small", "Hey Irene, how's it going?"),
    ("small", "Good job."),
    ("small", "Okay."),
    ("command", "What's the time?"),
    ("command", "Set a timer for ten minutes for the tea."),
    ("command", "Set a timer for five minutes."),
    ("research", "Research how kendo dan grades work."),
    ("research", "Look up the latest Nintendo Switch news."),
    ("chat", "Why is the sky blue?"),
    ("chat", "Tell me a joke."),
]


async def run(label: str) -> dict:
    from irene import app as app_mod, openers
    from irene.tts import Speaker

    core = app_mod.Core()
    core.bridge.bind(asyncio.get_running_loop())
    core.speaker = await asyncio.to_thread(Speaker, personal("pronunciation.yaml"), lambda _v: None)
    core.speaker.gain = 0.0  # timed, not heard
    voice = core.speaker.voice
    core.speaker.openers = await asyncio.to_thread(openers.load_or_render, voice)
    core.speaker.openers_engine = voice.name
    print("quick replies (rendered once, then cached)...", flush=True)
    await asyncio.to_thread(core.quick.load_or_render, voice)
    await core.llm.warm()
    # a real start: she was summoned (the "what were you doing" context exists)
    core.conversation.entered(next(e for e in core.entrances if e["name"] == "chess"))
    # the speaker's own latency: the "first sound" mark fires when the sample is heard
    print(f"speaker latency {core.speaker._stream.latency * 1000:.0f} ms", flush=True)
    rows = []
    for kind, text in CASES:
        core.last_ttfa = None
        core.working_heard_at = None
        received = time.perf_counter()
        await core.on_command({"text": text, "via": "voice"})
        turn = core._turn
        if kind == "research":
            # her first word is the "let me look that up": then stop, no web needed
            while core.working_heard_at is None and not turn.done() and time.perf_counter() - received < 15:
                await asyncio.sleep(0.01)
            first = (core.working_heard_at - received) * 1000 if core.working_heard_at else None
            turn.cancel()
            core.speaker.stop()
            try:
                await turn
            except asyncio.CancelledError:
                pass
        else:
            await turn
            first = core.last_ttfa
        rows.append({"kind": kind, "said": text, "first_audio_ms": round(first) if first is not None else None})
        print(f"  {kind:8} {text[:42]:42} first sound {rows[-1]['first_audio_ms']} ms", flush=True)
        core.conversation.warm_cache()
        await asyncio.sleep(1.0)  # he listens, she reads ahead
    await core.llm.close()
    return {"rows": rows, "speaker_latency_ms": round(core.speaker._stream.latency * 1000)}


def main() -> None:
    label = sys.argv[1] if len(sys.argv) > 1 else "now"
    result = asyncio.run(run(label))
    profile = LOGS / "profile-after.json"
    known = json.loads(profile.read_text(encoding="utf-8"))["voice"] if profile.exists() else {}
    summary = {}
    for kind in ("small", "command", "research", "chat"):
        firsts = [r["first_audio_ms"] for r in result["rows"] if r["kind"] == kind and r["first_audio_ms"] is not None]
        core_ms = statistics.median(firsts) if firsts else None
        tail = known.get("new_small_talk_words_known_ms" if kind == "small" else "new_words_known_ms")
        summary[kind] = {"core_ms": core_ms, "words_known_ms": tail, "total_ms": round(core_ms + tail) if core_ms is not None and tail else None}
    result["summary"] = summary
    (LOGS / f"e2e-{label}.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
