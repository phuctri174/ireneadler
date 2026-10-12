r"""An original cartoon voice mode: Irene's own voice (Chatterbox-Turbo cloned from
af_bella, the live voice; Kokoro if Turbo can't load) made small, bright and
bouncy by pitch + formant shift (Praat's "Change gender" via parselmouth) - a
smaller vocal tract (formants up), a higher, livelier pitch, a touch faster. Not
modelled on any character or voice actor; for jokes, reactions and summon lines
only. Renders two samples to core/voice_samples/expressive/cartoon_mode/.

Run from core/: .venv\Scripts\python scripts\expressive\cartoon.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import parselmouth
import soundfile as sf
from parselmouth.praat import call

CORE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(CORE))

import irene  # noqa: E402,F401
from irene.tts import SAMPLE_RATE  # noqa: E402

OUT = CORE / "voice_samples" / "expressive" / "cartoon_mode"
LINES = {
    "1_joke": "Why did the scarecrow win an award? Because he was outstanding in his field! [laugh]",
    "2_summon": "Surprise! Did you miss me? Ta-da!",
}
# formants x1.2 (a smaller speaker), pitch median 340 Hz with a wider range, 8% faster
FORMANT_SHIFT = 1.2
PITCH_MEDIAN_HZ = 340
PITCH_RANGE = 1.5
DURATION = 0.92


def cartoon(audio: np.ndarray) -> np.ndarray:
    snd = parselmouth.Sound(audio.astype(np.float64), sampling_frequency=SAMPLE_RATE)
    out = call(snd, "Change gender", 100, 600, FORMANT_SHIFT, PITCH_MEDIAN_HZ, PITCH_RANGE, DURATION)
    y = out.values[0].astype(np.float32)
    return y / max(1e-6, float(np.max(np.abs(y)))) * 0.9


def main() -> None:
    from irene.voice import Voice

    voice = Voice("turbo")
    OUT.mkdir(parents=True, exist_ok=True)
    for name, text in LINES.items():
        sf.write(OUT / f"{name}.wav", cartoon(voice.all(text, 1.08)), SAMPLE_RATE, subtype="PCM_16")
        print(name, "done with", voice.name)


if __name__ == "__main__":
    main()
