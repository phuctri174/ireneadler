"""The cached summon clip: produced once by summon_fx, then played from disk.

core/assets/summon.wav    the mix
core/assets/summon.json   timing + mouth levels + the key of the spec that made it

The line never changes, so it is never synthesised live. If the spec in summon_fx
changes, the key no longer matches and the clip is re-rendered on next start.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from . import summon_fx
from .tts import BLOCK, SAMPLE_RATE, block_levels

log = logging.getLogger("irene.summon")

ASSETS = Path(__file__).resolve().parents[1] / "assets"
WAV = ASSETS / "summon.wav"
TIMING = ASSETS / "summon.json"
# the same production on Chatterbox-Turbo's voice, for comparison - not played yet
TURBO_WAV = ASSETS / "summon_turbo.wav"

# the pick: v1 ("restrained"), with "Irene Adler" at 1.0x - rendered as summon_v1c
SPEC = summon_fx.INTENSITIES["v1"]
SEED = 7
# bump when anything derived from the render (levels, timing) changes meaning
FORMAT = 3


@dataclass(frozen=True)
class Clip:
    audio: np.ndarray
    levels: np.ndarray  # mouth level per 50 ms block, from the voice stem only
    part1_at: float  # first sample of "Domain..."
    part2_at: float  # first sample of "Irene Adler"
    duration: float


def spec_key() -> str:
    payload = json.dumps({"spec": asdict(SPEC), "seed": SEED, "sr": SAMPLE_RATE, "block": BLOCK, "format": FORMAT}, sort_keys=True)
    return hashlib.sha1(payload.encode()).hexdigest()[:12]


def load() -> Clip | None:
    if not (WAV.exists() and TIMING.exists()):
        return None
    timing = json.loads(TIMING.read_text(encoding="utf-8"))
    if timing.get("key") != spec_key():
        log.info("summon cache is stale (spec changed)")
        return None
    audio, sr = sf.read(WAV, dtype="float32")
    # the domain expansion clip at the entrances' loudness (levels.py)
    from .levels import level_mix

    audio = level_mix(audio)
    if sr != SAMPLE_RATE:
        return None
    return Clip(
        audio=audio,
        levels=np.asarray(timing["levels"], np.float32),
        part1_at=timing["part1_at"],
        part2_at=timing["part2_at"],
        duration=len(audio) / SAMPLE_RATE,
    )


def render(pipeline) -> Clip:
    r = summon_fx.render(pipeline, SPEC, seed=SEED)
    levels = block_levels(r.voice)
    loud = np.flatnonzero(np.abs(r.voice) > 0.01)
    part1_at = float(loud[0] / SAMPLE_RATE) if len(loud) else SPEC.swell_seconds
    ASSETS.mkdir(exist_ok=True)
    sf.write(WAV, r.audio, SAMPLE_RATE, subtype="PCM_16")
    TIMING.write_text(
        json.dumps(
            {
                "key": spec_key(),
                "text": "DOMAIN EXPANSION: IRENE ADLER IS COMING!!!",
                "sample_rate": SAMPLE_RATE,
                "duration": round(len(r.audio) / SAMPLE_RATE, 4),
                "part1_at": round(part1_at, 4),
                "part2_at": round(r.part2_at, 4),
                "level_hz": SAMPLE_RATE // BLOCK,
                "levels": [round(float(v), 3) for v in levels],
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    log.info("summon clip rendered: %.2fs, part2 at %.2fs", len(r.audio) / SAMPLE_RATE, r.part2_at)
    return load()


def load_or_render(pipeline) -> Clip:
    """`pipeline` is a callable returning a Kokoro pipeline, only called on a cache miss
    (the live clip is Kokoro's v1c, whatever her live voice is)."""
    return load() or render(pipeline() if callable(pipeline) else pipeline)


def render_turbo(turbo) -> Path:
    """The Turbo take of the summon line, same spec and seed, to compare with v1c."""
    r = summon_fx.render(summon_fx.TurboTakes(turbo), SPEC, seed=SEED)
    sf.write(TURBO_WAV, r.audio, SAMPLE_RATE, subtype="PCM_16")
    log.info("summon clip (turbo take) rendered: %.2fs -> %s", len(r.audio) / SAMPLE_RATE, TURBO_WAV.name)
    return TURBO_WAV
