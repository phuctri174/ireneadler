r"""Kokoro (af_bella) on the six expressive lines, two ways, as the baseline:

  kokoro           as she spoke before: every sentence at 1.0, nothing under it
  kokoro_quickwins her current path: the line's cue sets the speed (config/cues.json)
                   and its sound effect is mixed under the first words

Writes core/voice_samples/expressive/<variant>/<id>.wav and timing.json (time to
first audio per line, VRAM). Run from core/: .venv\Scripts\python scripts\expressive\kokoro.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

HERE = Path(__file__).parent
CORE = HERE.parents[1]
sys.path.insert(0, str(CORE))

import irene  # noqa: E402,F401
from irene import sfx  # noqa: E402
from irene.react import resolve  # noqa: E402
from irene.tts import SAMPLE_RATE, VOICE, mix_under, unshout  # noqa: E402

OUT = CORE / "voice_samples" / "expressive"
LINES = json.loads((HERE / "lines.json").read_text(encoding="utf-8"))["lines"]


def main() -> None:
    from kokoro import KPipeline

    torch.cuda.reset_peak_memory_stats()
    base = torch.cuda.memory_allocated()
    pipe = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M")
    for _ in pipe("Ready.", voice=VOICE):
        pass
    for variant in ("kokoro", "kokoro_quickwins"):
        folder = OUT / variant
        folder.mkdir(parents=True, exist_ok=True)
        timing = {}
        for line in LINES:
            cue = resolve(line["cue"]) if variant.endswith("quickwins") and line["cue"] else None
            speed = cue.speed if cue else 1.0
            chunks = []
            t0 = time.perf_counter()
            first = None
            # sentence by sentence, as the live stream does
            for sentence in [s for s in __import__("re").split(r"(?<=[.!?…])\s+", line["text"]) if s]:
                for _, _, audio in pipe(unshout(sentence), voice=VOICE, speed=speed):
                    if first is None:
                        first = time.perf_counter() - t0
                    chunks.append(np.asarray(audio, np.float32))
            audio = np.concatenate(chunks)
            if cue and cue.sfx:
                audio = mix_under(audio, sfx.render(cue.sfx, np.random.default_rng(3)))
            sf.write(folder / f"{line['id']}.wav", audio, SAMPLE_RATE, subtype="PCM_16")
            timing[line["id"]] = {"ttfa_ms": round(first * 1000), "seconds": round(len(audio) / SAMPLE_RATE, 2)}
        vram = (torch.cuda.max_memory_allocated() - base) / 2**20
        (folder / "timing.json").write_text(json.dumps({"model": variant, "vram_mb": round(vram), "lines": timing}, indent=1), encoding="utf-8")
        print(variant, json.dumps(timing))


if __name__ == "__main__":
    main()
