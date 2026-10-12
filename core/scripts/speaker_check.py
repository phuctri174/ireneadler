r"""Only his voice is acted on: a video playing in the room never becomes a turn,
and a take of his own voice still does.

  (start-irene.ps1 -Dev running)
  .venv\Scripts\python scripts\speaker_check.py <audio file of an English video>

1. her window shown (so she listens with no wake word - the strictest case);
2. the video's audio played OUT LOUD through the default speakers for 60 s, the
   live mic hearing it - every utterance must be rejected by the speaker check;
3. one of his corpus takes replayed through the mic pipeline (dev voice_replay):
   it must pass the speaker check.
Reads core/logs/voice.log for the "speaker check" lines and any turn that started.

No OS input, no screenshot: audio out of the speakers and the dev socket only.
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import sys
import time
from pathlib import Path

import sounddevice as sd
import websockets

CORE = Path(__file__).resolve().parents[1]
LOG = CORE / "logs" / "voice.log"
PLAY_S = 60.0


def tail_from(offset: int) -> list[str]:
    with LOG.open(encoding="utf-8", errors="replace") as f:
        f.seek(offset)
        return f.read().splitlines()


async def main() -> int:
    from faster_whisper.audio import decode_audio

    clip = Path(sys.argv[1])
    audio = decode_audio(str(clip), sampling_rate=48000)
    audio = audio[int(30 * 48000): int((30 + PLAY_S) * 48000)]  # past any intro music
    # one of his held-out takes, as a saved turn the replay hook may read
    take = sorted((CORE / "voice_data" / "corpus").glob("cmd-*/take1.wav"))[0]
    turns = CORE / "voice_data" / "turns" / "_check"
    turns.mkdir(parents=True, exist_ok=True)
    shutil.copy(take, turns / "his_take.wav")

    async with websockets.connect("ws://127.0.0.1:8765/ws", max_size=None, ping_interval=None) as ws:
        await ws.send(json.dumps({"type": "debug_ui", "action": "show"}))
        await asyncio.sleep(2.0)
        start = LOG.stat().st_size
        print(f"playing {PLAY_S:.0f} s of {clip.name} out loud...")
        sd.play(audio, 48000)
        await asyncio.sleep(PLAY_S + 4.0)
        sd.stop()
        video = tail_from(start)
        mark = LOG.stat().st_size
        print(f"replaying his take {take.parent.name}/{take.name}...")
        await ws.send(json.dumps({"type": "voice_replay", "turn": "_check/his_take"}))
        await asyncio.sleep(8.0)
        him = tail_from(mark)
        await ws.send(json.dumps({"type": "debug_ui", "action": "hide"}))

    rejected = [l for l in video if "NOT his voice" in l]
    passed = [l for l in video if "speaker check" in l and ": him (" in l]
    turned = [l for l in video if "for her:" in l]
    print(f"\nvideo: {len(rejected)} utterance(s) rejected, {len(passed)} passed the speaker check, {len(turned)} became a turn")
    for l in rejected + passed:
        print("   ", l.split(" irene.voice ")[-1][:110])
    accepted = [l for l in him if "speaker check" in l and ": him (" in l]
    print(f"his take: {'accepted' if accepted else 'NOT accepted'}")
    for l in him:
        if "speaker check" in l or "for her:" in l:
            print("   ", l.split(" irene.voice ")[-1][:110])
    scores = [float(m.group(1)) for l in rejected + passed if (m := re.search(r"similarity ([-\d.]+)", l))]
    if scores:
        print(f"video similarity: max {max(scores):.2f}")
    ok = not turned and not passed and bool(accepted)
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
