"""Slower (or faster) speech at the same pitch - WSOLA, for Turbo, which has no
speed of its own. Short Hann-windowed frames of her own voice are laid down at
the new rate, each one shifted (within a few ms) to where it lines up best with
the last, so nothing smears: still her voice, just in less of a hurry. A phase
vocoder (librosa's time_stretch) sounds phasey and metallic on speech; this
doesn't.

    stretch(audio, rate)   rate < 1 slower (0.9 = 10% slower), > 1 faster
"""
from __future__ import annotations

import numpy as np

SR = 24000
FRAME_S = 0.03   # 30 ms: a few pitch periods - long enough to carry them whole
TOLERANCE_S = 0.008  # how far a frame may shift to line up with the last


def stretch(audio: np.ndarray, rate: float, sr: int = SR) -> np.ndarray:
    """`audio` played at `rate` times its speed, pitch unchanged."""
    x = np.asarray(audio, np.float32)
    if abs(rate - 1.0) < 1e-3 or len(x) == 0:
        return x
    n = int(FRAME_S * sr) // 2 * 2
    hs = n // 2  # synthesis hop: 50% overlap, Hann sums to one
    ha = hs * rate  # analysis hop
    tol = int(TOLERANCE_S * sr)
    window = np.hanning(n + 1)[:n].astype(np.float32)
    pad = n + tol
    xp = np.concatenate([np.zeros(pad, np.float32), x, np.zeros(pad + n, np.float32)])
    frames = int((len(x) / rate) / hs) + 1
    out = np.zeros(frames * hs + n, np.float32)
    norm = np.zeros_like(out)
    prev = pad  # where the last frame was read from
    for k in range(frames):
        ideal = pad + int(round(k * ha))
        if k == 0:
            at = ideal
        else:
            # the frame that would naturally follow the last one ...
            natural = xp[prev + hs : prev + hs + n]
            # ... and, near where this one should be, the best match for it
            lo = max(0, ideal - tol)
            region = xp[lo : ideal + tol + n]
            if len(region) < n or not natural.any():
                at = ideal
            else:
                score = np.correlate(region, natural, mode="valid")
                at = lo + int(np.argmax(score))
        frame = xp[at : at + n]
        if len(frame) < n:
            break
        out[k * hs : k * hs + n] += frame * window
        norm[k * hs : k * hs + n] += window
        prev = at
    out = out / np.maximum(norm, 1e-3)
    return out[: int(len(x) / rate)].astype(np.float32)
