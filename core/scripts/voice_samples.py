"""Render one sentence in a few adult female Kokoro voices to core/voice_samples/.

Run: .venv\\Scripts\\python scripts\\voice_samples.py
"""
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from kokoro import KPipeline

OUT = Path(__file__).resolve().parent.parent / "voice_samples"
SAMPLE_RATE = 24000
SENTENCE = (
    "Good evening, Mister Tri. I found four files in Downloads; "
    "the largest is about nine megabytes, and I've put the list on screen."
)
# lang code -> voices; American then British
VOICES = {
    "a": ["af_heart", "af_bella"],
    "b": ["bf_emma", "bf_isabella"],
}


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for lang, voices in VOICES.items():
        pipeline = KPipeline(lang_code=lang, repo_id="hexgrad/Kokoro-82M")
        for voice in voices:
            t0 = time.perf_counter()
            chunks = [audio.numpy() if hasattr(audio, "numpy") else audio for _, _, audio in pipeline(SENTENCE, voice=voice)]
            audio = np.concatenate(chunks)
            path = OUT / f"{voice}.wav"
            sf.write(path, audio, SAMPLE_RATE)
            print(f"{voice:12} {len(audio) / SAMPLE_RATE:4.1f}s audio in {time.perf_counter() - t0:4.2f}s -> {path}")


if __name__ == "__main__":
    main()
