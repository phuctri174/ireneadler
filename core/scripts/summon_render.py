"""Render produced summon variants to core/voice_samples/summon_<key>.wav.

Run: .venv\\Scripts\\python scripts\\summon_render.py
"""
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import irene  # noqa: E402,F401  - offline mode before kokoro loads
from irene.summon_fx import INTENSITIES, SR, render  # noqa: E402

# v1 with "Irene Adler" (part 2a) at three paces
VARIANTS = {
    f"v1{tag}": replace(INTENSITIES["v1"], name=f"v1 / 2a at {speed}", part2a_speed=speed)
    for tag, speed in (("a", 0.9), ("b", 0.95), ("c", 1.0))
}


def db(x: np.ndarray) -> float:
    return 20 * np.log10(np.sqrt(np.mean(x**2)) + 1e-9)


def main() -> None:
    from kokoro import KPipeline

    pipeline = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M")
    out = ROOT / "voice_samples"
    out.mkdir(exist_ok=True)
    for key, spec in VARIANTS.items():
        r = render(pipeline, spec)
        sf.write(out / f"summon_{key}.wav", r.audio, SR)
        p2 = int(r.part2_at * SR)
        breath = r.audio[p2 - int(0.12 * SR) : p2]
        # loudness over the spoken spans only, not the swell lead-in or the ring-out
        loud = np.flatnonzero(np.abs(r.voice) > 0.02)
        s1, s2 = loud[loud < p2], loud[loud >= p2]
        print(
            f"summon_{key}.wav  {spec.name:18}  {len(r.audio) / SR:4.1f}s  part2 at {r.part2_at:4.2f}s  "
            f"speech: part1 {db(r.audio[s1[0] : s1[-1]]):5.1f} dB  part2 {db(r.audio[s2[0] : s2[-1]]):5.1f} dB  "
            f"breath {db(breath):6.1f} dB  peak {np.max(np.abs(r.audio)):.2f}"
        )


if __name__ == "__main__":
    main()
