"""Summon entrances: which one plays, and its clip.

The registry is config/entrances.json. The hand sign always plays domain_expansion;
every other summon picks one at random by weight, never the one that played last.
Every entrance but domain_expansion is a 4-5 s clip rendered once from its entry -
her line (in her live voice) at voice_at over its sound effects (sfx.py) - and
cached in core/assets/entrances/<name>.wav with its mouth levels; an entry that
changes gets a new key and is re-rendered on the next start. domain_expansion is
the produced summon clip (summon.py).

Each entry also carries what she was busy with, for her context after the
entrance ("What are you doing, Irene?"): `doing` in her own words, `scene` - what
the clip actually shows - and `backstory`, several lines she can draw on so the
answer differs every time.
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from . import sfx
from .summon_fx import trim
from .tts import BLOCK, SAMPLE_RATE, VOICE, block_levels

log = logging.getLogger("irene.entrances")

REGISTRY = Path(__file__).resolve().parents[2] / "config" / "entrances.json"
ASSETS = Path(__file__).resolve().parents[1] / "assets" / "entrances"
DOMAIN = "domain_expansion"
# bump when anything about how a clip is rendered changes
FORMAT = 1
# every entrance hands back to the listening face inside this: the domain
# expansion's length (5.8 s) and the tail of her line, spoken after the cut (the
# longest, victorian and kendo, measured 6.8 s on her real voice)
MAX_SECONDS = 7.0


def load_registry(path: Path = REGISTRY) -> list[dict]:
    entries = json.loads(path.read_text(encoding="utf-8"))["entrances"]
    names = [e["name"] for e in entries]
    if len(names) != len(set(names)) or DOMAIN not in names:
        raise RuntimeError(f"{path}: names must be unique and include {DOMAIN}")
    for e in entries:
        if not str(e.get("doing", "")).strip():
            raise RuntimeError(f"{path}: {e['name']} has no 'doing' line")
        if not str(e.get("scene", "")).strip() or len(e.get("backstory", [])) < 4:
            raise RuntimeError(f"{path}: {e['name']} needs a 'scene' and at least 4 'backstory' lines")
        for fx in e.get("sfx", []):
            if fx["fx"] not in sfx.EFFECTS:
                raise RuntimeError(f"{path}: {e['name']} uses unknown effect {fx['fx']!r}")
    return entries


def doing(entries: list[dict], name: str | None) -> str | None:
    """What she was doing during that entrance, in her words - for her context."""
    entry = next((e for e in entries if e["name"] == name), None) if name else None
    return entry.get("doing") if entry else None


def load_odds(path: Path = REGISTRY) -> tuple[dict[str, float], dict]:
    """The weights by name and the "picking" rules, from the registry as it is now."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    weights = {e["name"]: float(e.get("weight", 1)) for e in raw["entrances"]}
    picking = {"no_repeat": True, "may_repeat": [], **(raw.get("picking") or {})}
    return weights, picking


class Picker:
    """Weighted random choice that (by default) never repeats the previous pick.

    The weights and rules are read from config/entrances.json on every pick when
    `live` (the running app), so an edit there applies to the next summon. Each
    pick leaves `why`: its weight, the pool, the odds, what sat out."""

    def __init__(self, entries: list[dict], rng: random.Random | None = None, live: bool = False, path: Path = REGISTRY):
        self.entries = entries
        self.rng = rng or random.Random()
        self.last: str | None = None
        self.live = live
        self.path = path
        self.why = ""

    def odds(self) -> tuple[dict[str, float], dict]:
        if self.live:
            try:
                weights, picking = load_odds(self.path)
                return {e["name"]: weights.get(e["name"], float(e.get("weight", 1))) for e in self.entries}, picking
            except (OSError, ValueError, KeyError) as error:
                log.warning("entrance odds: %s unreadable (%s) - the loaded weights stand", self.path.name, error)
        return {e["name"]: float(e.get("weight", 1)) for e in self.entries}, {"no_repeat": True, "may_repeat": []}

    def pick(self) -> dict:
        weights, picking = self.odds()
        # weight 0: only ever by name (the Victorian one answers "Irene Adler")
        drawn = [e for e in self.entries if weights[e["name"]] > 0]
        rested = self.last if picking.get("no_repeat", True) and self.last not in picking.get("may_repeat", []) else None
        pool = [e for e in drawn if e["name"] != rested] or drawn
        total = sum(weights[e["name"]] for e in pool)
        choice = self.rng.choices(pool, weights=[weights[e["name"]] for e in pool])[0]
        w = weights[choice["name"]]
        self.why = (f"weight {w:g} of {total:g} in a pool of {len(pool)} (p={w / total:.0%})"
                    + (f"; {rested} sat out - it played last" if rested and len(pool) < len(drawn) else "; no repeat rule applied"))
        self.last = choice["name"]
        return choice


@dataclass(frozen=True)
class Clip:
    name: str
    audio: np.ndarray
    levels: np.ndarray  # mouth level per 50 ms block, from her voice only
    duration: float
    ms: int  # the HUD animation's length


# what she says about an entrance afterwards: context only, never part of the clip
CONTEXT_ONLY = ("scene", "backstory")


def key_of(entry: dict, engine: str = "kokoro", spoken: str | None = None) -> str:
    """`spoken`: the line as the engine is given it (his pronunciation map applied).
    Only when that differs from the line is it part of the key - so a map change
    re-renders the entrances whose lines it touches, and no others."""
    sound = {k: v for k, v in entry.items() if k not in CONTEXT_ONLY}
    if spoken is not None and spoken != entry.get("line"):
        sound["spoken"] = spoken
    payload = json.dumps({"entry": sound, "sr": SAMPLE_RATE, "block": BLOCK, "voice": VOICE, "engine": engine, "format": FORMAT}, sort_keys=True)
    return hashlib.sha1(payload.encode()).hexdigest()[:12]


def render(speak, entry: dict, seed: int = 11) -> tuple[np.ndarray, np.ndarray]:
    """(mix, voice stem) for one entrance; `speak(text, speed)` -> audio is the voice."""
    rng = np.random.default_rng(seed)
    said = speak(entry["line"], float(entry.get("speed", 1.0)))
    voice, _ = trim(said if len(said) else np.zeros(1, np.float32))
    at = int(float(entry.get("voice_at", 0)) * SAMPLE_RATE)
    length = max(int(entry["ms"] / 1000 * SAMPLE_RATE), at + len(voice) + int(0.12 * SAMPLE_RATE))
    for fx in entry.get("sfx", []):
        length = max(length, int(fx["at"] * SAMPLE_RATE) + int((fx.get("dur") or 0.5) * SAMPLE_RATE))
    stem = np.zeros(length, np.float32)
    stem[at : at + len(voice)] = voice
    peak = float(np.max(np.abs(voice))) or 1.0
    effects = np.zeros(length, np.float32)
    for fx in entry.get("sfx", []):
        sound = sfx.render(fx["fx"], rng, fx.get("dur")) * float(fx.get("gain", 0.4)) * peak
        start = int(fx["at"] * SAMPLE_RATE)
        end = min(length, start + len(sound))
        effects[start:end] += sound[: end - start]
    mix = stem + effects
    top = float(np.max(np.abs(mix)))
    if top > 0.98:
        mix *= 0.98 / top
    # no trailing silence past the animation: the listening face comes back on time
    end = max(int(entry["ms"] / 1000 * SAMPLE_RATE), at + len(voice) + int(0.08 * SAMPLE_RATE))
    return mix[:end], stem[:end]


def _paths(name: str) -> tuple[Path, Path]:
    return ASSETS / f"{name}.wav", ASSETS / f"{name}.json"


def load(entry: dict, engine: str = "kokoro", spoken: str | None = None) -> Clip | None:
    wav, meta = _paths(entry["name"])
    if not (wav.exists() and meta.exists()):
        return None
    info = json.loads(meta.read_text(encoding="utf-8"))
    if info.get("key") != key_of(entry, engine, spoken):
        return None
    audio, sr = sf.read(wav, dtype="float32")
    # levelled as it loads (levels.py; idempotent): no re-render needed
    from . import levels

    audio = levels.level_mix(audio)
    if sr != SAMPLE_RATE:
        return None
    return Clip(entry["name"], audio, np.asarray(info["levels"], np.float32), len(audio) / SAMPLE_RATE, int(entry["ms"]))


def load_or_render(voice, entry: dict) -> Clip:
    """`voice` is the live Voice (voice.py); a clip made by another engine re-renders."""
    spoken = voice.spoken(entry["line"]) if hasattr(voice, "spoken") else None
    clip = load(entry, voice.name, spoken)
    if clip:
        return clip
    mix, stem = render(voice.all, entry)
    # the whole clip at the clip loudness (levels.py): entrances were -25 dBFS, quiet
    from . import levels

    mix = levels.level_mix(mix)
    ASSETS.mkdir(parents=True, exist_ok=True)
    wav, meta = _paths(entry["name"])
    sf.write(wav, mix, SAMPLE_RATE, subtype="PCM_16")
    levels = block_levels(stem)
    meta.write_text(
        json.dumps(
            {
                "key": key_of(entry, voice.name, spoken),
                "engine": voice.name,
                "line": entry["line"],
                "duration": round(len(mix) / SAMPLE_RATE, 3),
                "levels": [round(float(v), 3) for v in levels],
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    log.info("entrance %s rendered: %.2fs", entry["name"], len(mix) / SAMPLE_RATE)
    return load(entry, voice.name, spoken)


def load_all(voice, entries: list[dict]) -> dict[str, Clip]:
    return {e["name"]: load_or_render(voice, e) for e in entries if e["name"] != DOMAIN}
