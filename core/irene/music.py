"""Music under a voice summon: config/summon_music.yaml.

When his wake phrase brings her up, a track plays under the boot-up and her entrance
(the Speaker's music bed, mixed beneath her voice and seen by the echo canceller like
everything she plays), drops away for the boot's held beat of silence, slams back on
the name reveal, and fades out as she greets him.

The file is his, on his disk: it is decoded once (in the background at startup) and
kept in memory as mono 24 kHz - never copied into the repo.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from math import gcd
from pathlib import Path

import numpy as np
import yaml

from .tts import SAMPLE_RATE
from tools.localconfig import personal

log = logging.getLogger("irene.music")

CONFIG = personal("summon_music.yaml")


@dataclass(frozen=True)
class Settings:
    enabled: bool
    file: Path
    start_s: float
    max_s: float
    level: float
    fade_in_s: float
    fade_out_s: float


def settings(path: Path = CONFIG) -> Settings:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    raw = raw or {}
    return Settings(
        enabled=bool(raw.get("enabled", False)),
        file=Path(str(raw.get("file", ""))),
        start_s=float(raw.get("start_s", 0.0)),
        max_s=float(raw.get("max_s", 40.0)),
        level=max(0.0, min(1.0, float(raw.get("level", 0.3)))),
        fade_in_s=max(0.0, float(raw.get("fade_in_s", 0.5))),
        fade_out_s=max(0.05, float(raw.get("fade_out_s", 4.0))),
    )


def decode(file: Path, start_s: float, max_s: float) -> np.ndarray:
    """The track from start_s, at most max_s of it, as mono float32 at her rate,
    peak-normalised (the level is applied by the bed)."""
    import soundfile as sf
    from scipy.signal import resample_poly

    with sf.SoundFile(str(file)) as f:
        rate = f.samplerate
        f.seek(min(int(start_s * rate), max(0, f.frames - 1)))
        audio = f.read(int(max_s * rate), dtype="float32", always_2d=True)
    mono = audio.mean(axis=1)
    g = gcd(SAMPLE_RATE, rate)
    out = resample_poly(mono, SAMPLE_RATE // g, rate // g).astype(np.float32)
    peak = float(np.max(np.abs(out))) if len(out) else 0.0
    return out / peak if peak > 0 else out


class Track:
    """The decoded track, loaded once in the background; None until it is ready (or
    if the file is missing - she summons without music, logged once)."""

    def __init__(self, cfg: Settings | None = None):
        self.cfg = cfg or settings()
        self.audio: np.ndarray | None = None
        self._thread: threading.Thread | None = None

    def load_in_background(self) -> None:
        if not self.cfg.enabled or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._load, name="summon-music", daemon=True)
        self._thread.start()

    def _load(self) -> None:
        try:
            if not self.cfg.file.is_file():
                log.warning("summon music: %s not found - summons play without it", self.cfg.file)
                return
            self.audio = decode(self.cfg.file, self.cfg.start_s, self.cfg.max_s)
            log.info("summon music ready: %s from %.0f s, %.1f s loaded", self.cfg.file.name, self.cfg.start_s, len(self.audio) / SAMPLE_RATE)
        except Exception:
            log.exception("summon music: could not decode %s", self.cfg.file)
