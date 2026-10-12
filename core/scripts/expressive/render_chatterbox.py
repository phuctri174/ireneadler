r"""Chatterbox (Resemble AI, MIT) on the six expressive lines, cloning af_bella from
core/voice_samples/af_bella.wav so she still sounds like herself.

  chatterbox        the 0.5B model, the emotion "exaggeration" dial set per line
  chatterbox_turbo  the 350M Turbo, with its [laugh] / [sigh] / [gasp] tags

Runs in its own venv (torch cu128 for the RTX 50 series; chatterbox-tts installed
--no-deps, transformers 5.2): see scripts/expressive/README.md.
  <venv>\Scripts\python scripts\expressive\render_chatterbox.py [chatterbox|chatterbox_turbo]

Neither model streams, so time to first audio is the time to synthesise the
line's first sentence - what the live path would wait before speaking.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

HERE = Path(__file__).parent
CORE = HERE.parents[1]
OUT = CORE / "voice_samples" / "expressive"
REFERENCE = CORE / "voice_samples" / "af_bella.wav"
LINES = json.loads((HERE / "lines.json").read_text(encoding="utf-8"))["lines"]


def sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?…\]])\s+", text) if s]


def main(variant: str) -> None:
    torch.cuda.reset_peak_memory_stats()
    if variant == "chatterbox_turbo":
        from chatterbox.tts_turbo import ChatterboxTurboTTS

        model = ChatterboxTurboTTS.from_pretrained(device="cuda")
        # its loudness normalisation hands the tokenizer float64 (a crash on torch
        # 2.11): clone the voice once without it; af_bella's clip is already level
        model.prepare_conditionals(str(REFERENCE), norm_loudness=False)
        speak = lambda text, line: model.generate(text)  # noqa: E731
        field = "tagged"
    else:
        from chatterbox.tts import ChatterboxTTS

        model = ChatterboxTTS.from_pretrained(device="cuda")
        speak = lambda text, line: model.generate(text, audio_prompt_path=str(REFERENCE), exaggeration=line["exaggeration"], cfg_weight=0.4)  # noqa: E731
        field = "text"
    speak("Ready.", LINES[-1])  # warm-up: CUDA kernels, the reference embedding
    folder = OUT / variant
    folder.mkdir(parents=True, exist_ok=True)
    timing = {}
    for line in LINES:
        parts, first = [], None
        t0 = time.perf_counter()
        for s in sentences(line[field]):
            wav = speak(s, line)
            if first is None:
                torch.cuda.synchronize()
                first = time.perf_counter() - t0
            parts.append(wav.squeeze().float().cpu().numpy())
        audio = np.concatenate(parts)
        sf.write(folder / f"{line['id']}.wav", audio, model.sr, subtype="PCM_16")
        timing[line["id"]] = {"ttfa_ms": round(first * 1000), "seconds": round(len(audio) / model.sr, 2), "total_ms": round((time.perf_counter() - t0) * 1000)}
        print(line["id"], timing[line["id"]], flush=True)
    vram = torch.cuda.max_memory_allocated() / 2**20
    (folder / "timing.json").write_text(json.dumps({"model": variant, "vram_mb": round(vram), "lines": timing}, indent=1), encoding="utf-8")
    print(variant, "peak VRAM", round(vram), "MB")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "chatterbox")
