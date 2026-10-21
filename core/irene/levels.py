# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""How loud she is: one place for every level (config/voice.yaml `output`).

Measured before this existed: her speech sat at -26..-20 dBFS RMS (median -22.8,
a 6 dB spread line to line), the entrances at -25 - too quiet at 100% Windows
volume. Now:

  level_speech  each synthesised sentence to the same loudness (speech_rms_dbfs),
                so quiet and loud lines sit together; peaks capped
  level_mix     a rendered clip (an entrance) to its own loudness
  master        the speaker's last stage, for EVERYTHING she plays (speech, cue
                sounds, entrances, the boot soundtrack): master_gain_db, then a
                soft limiter so nothing clips (limit_dbfs)
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np

from . import stt

# what counts as "her voice" when measuring loudness: samples above this
_VOICED_DBFS = -45.0


def _db_to_gain(db: float) -> float:
    return float(10 ** (db / 20))


@lru_cache(maxsize=1)
def settings() -> dict:
    out = (stt.settings().get("output") or {}) if hasattr(stt, "settings") else {}
    return {
        "master_gain_db": float(out.get("master_gain_db", 3.0)),
        "speech_rms_dbfs": float(out.get("speech_rms_dbfs", -16.0)),
        "clip_rms_dbfs": float(out.get("clip_rms_dbfs", -17.0)),
        "limit_dbfs": float(out.get("limit_dbfs", -1.0)),
    }


def _rms_voiced(x: np.ndarray) -> float:
    voiced = x[np.abs(x) > _db_to_gain(_VOICED_DBFS)]
    return float(np.sqrt(np.mean(voiced ** 2))) if len(voiced) else 0.0


def _to_rms(x: np.ndarray, target_dbfs: float, max_gain_db: float = 18.0) -> np.ndarray:
    if len(x) == 0:
        return x
    rms = _rms_voiced(x)
    if rms <= 0:
        return x
    gain = min(_db_to_gain(target_dbfs) / rms, _db_to_gain(max_gain_db))
    return soft_limit(x.astype(np.float32) * gain, settings()["limit_dbfs"])


def level_speech(x: np.ndarray) -> np.ndarray:
    """One synthesised sentence at the speech loudness, peaks capped."""
    return _to_rms(x, settings()["speech_rms_dbfs"])


def level_mix(x: np.ndarray) -> np.ndarray:
    """A rendered clip (voice and effects together) at the clip loudness."""
    return _to_rms(x, settings()["clip_rms_dbfs"])


def soft_limit(x: np.ndarray, limit_dbfs: float = -1.0) -> np.ndarray:
    """Anything above the knee bends smoothly toward the limit - never past it."""
    ceiling = _db_to_gain(limit_dbfs)
    knee = ceiling * 0.8
    a = np.abs(x)
    over = a > knee
    if not np.any(over):
        return x
    out = x.copy()
    span = ceiling - knee
    out[over] = np.sign(x[over]) * (knee + span * np.tanh((a[over] - knee) / span))
    return out


def master(out: np.ndarray) -> np.ndarray:
    """The speaker's last stage: the master gain, then the limiter."""
    s = settings()
    if s["master_gain_db"]:
        out = out * _db_to_gain(s["master_gain_db"])
    return soft_limit(out, s["limit_dbfs"])
