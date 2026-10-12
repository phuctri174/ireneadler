"""Render pronunciation checks through the real TTS path to core/voice_samples/.

Run: .venv\\Scripts\\python scripts\\name_test.py
"""
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent))

from irene.tts import BLOCK, SAMPLE_RATE, Speaker  # noqa: E402
from tools.localconfig import personal  # noqa: E402

LINES = {
    "name_test": ("Good morning, Mister Tri.", 1.0),
    "summon_test": ("DOMAIN EXPANSION: IRENE ADLER IS COMING!!!", 1.08),
}


def main() -> None:
    speaker = Speaker(personal("pronunciation.yaml"), on_level=lambda _v: None)
    out = ROOT / "voice_samples"
    for name, (text, speed) in LINES.items():
        print(f"{name}: {speaker.prepare(text)}")
        audio = speaker.synthesize(text, speed=speed)
        sf.write(out / f"{name}.wav", audio, SAMPLE_RATE)
        blocks = audio[: len(audio) // BLOCK * BLOCK].reshape(-1, BLOCK)
        rms = np.sqrt(np.mean(np.square(blocks), axis=1))
        voiced = rms[rms > 0.01]
        print(f"  {len(audio) / SAMPLE_RATE:.1f}s  block rms p50 {np.median(voiced):.3f}  p90 {np.percentile(voiced, 90):.3f}  max {rms.max():.3f}")


if __name__ == "__main__":
    main()
