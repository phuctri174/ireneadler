# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""The strike event's tuning: a threshold he calibrates with three swings, not a model.

Study mode and shiai are modes he is in, shinai in hand, to hit her; a false positive
is a funny noise. So the HUD's detector (hud/src/tracking/strikeEvent.ts) is a
threshold on signed downward wrist speed plus a sharp stop, and this module owns
the number:

  config/strike_event.json          the knobs he nudges ("fraction", the stop, shiai's footwork)
  core/data/strike_calibration.json his last calibration: three peak speeds

threshold = fraction x the median of the three. "Irene, calibrate my strikes" runs it
again any time: the detector goes on at a low floor for a few seconds, she says "hit
me three times", and his three fastest swings are kept. Uneven swings (one under
half the fastest) are not saved - she asks again.
"""
from __future__ import annotations

import json
import re
import statistics
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "strike_event.json"
STATE = ROOT / "core" / "data" / "strike_calibration.json"

DEFAULTS = {
    "fraction": 0.6,
    "stopRatio": 0.35,
    "stopMs": 160,
    "refractoryMs": 400,
    "minVis": 0.4,
    "maxPeak": 60,
    "calibration": {"seconds": 12, "floorSpeed": 4.0, "swings": 3, "minEven": 0.5},
    "shiai": {"scaleRatio": 0.08, "lateral": 0.5, "windowMs": 500, "refractoryMs": 800, "holdMs": 200, "graceMs": 60},
}

_CALIBRATE = re.compile(
    r"^\W*(?:(?:hey\s+)?irene\W+)?(?:(?:please|can\s+you|could\s+you|let'?s)\s+)?"
    r"(?:re-?)?calibrat\w*\s+(?:my\s+|the\s+|your\s+)?(?:strikes?|hits?|swings?|men|shinai)\b",
    re.I,
)


def settings(path: Path = CONFIG) -> dict:
    """The knobs, read fresh each time (he edits them while she runs)."""
    out = json.loads(json.dumps(DEFAULTS))
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return out
    for key, value in raw.items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key].update({k: v for k, v in value.items() if not k.startswith("_")})
        else:
            out[key] = value
    return out


def calibration(path: Path = STATE) -> dict | None:
    """His last saved calibration ({"peaks": [...], "median": m, "at": ...}), or None."""
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return saved if isinstance(saved, dict) and saved.get("median") else None


def threshold(config: Path = CONFIG, state: Path = STATE) -> float | None:
    saved = calibration(state)
    return None if saved is None else round(float(settings(config)["fraction"]) * float(saved["median"]), 2)


def _strikes(at: float, s: dict) -> dict:
    return {"threshold": at, **{k: s[k] for k in ("stopRatio", "stopMs", "refractoryMs", "minVis", "maxPeak")}}


def tuning(moves: bool = False, config: Path = CONFIG, state: Path = STATE) -> dict | None:
    """The HUD's strike_events config: None until he has calibrated."""
    at = threshold(config, state)
    if at is None:
        return None
    s = settings(config)
    return {"strikes": _strikes(at, s), "moves": dict(s["shiai"]) if moves else None}


def calibration_tuning(config: Path = CONFIG) -> dict:
    """Strike events at the low floor, so every real swing reports its peak."""
    s = settings(config)
    return {"strikes": _strikes(float(s["calibration"]["floorSpeed"]), s), "moves": None}


@dataclass
class Result:
    ok: bool
    peaks: list[float]
    median: float = 0.0
    threshold: float = 0.0
    why: str = ""


def calibrate(peaks: list[float], config: Path = CONFIG) -> Result:
    """His swings' peaks from one calibration window: the fastest three, and whether
    they are even enough to set a threshold from."""
    s = settings(config)
    want = int(s["calibration"]["swings"])
    top = sorted((float(p) for p in peaks), reverse=True)[:want]
    if len(top) < want:
        return Result(False, top, why="few")
    if top[-1] < float(s["calibration"]["minEven"]) * top[0]:
        return Result(False, top, why="uneven")
    median = statistics.median(top)
    return Result(True, top, round(median, 2), round(float(s["fraction"]) * median, 2))


def save(result: Result, path: Path = STATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"peaks": [round(p, 2) for p in result.peaks], "median": result.median,
                                "at": time.strftime("%Y-%m-%dT%H:%M:%S")}), encoding="utf-8")


def command(text: str) -> str | None:
    """"Irene, calibrate my strikes": "calibrate", else None. (Whisper's "calibrate my
    stripe" is put back by modes.heard before this is asked.)"""
    return "calibrate" if _CALIBRATE.search((text or "").strip()) else None


LINES = {
    "ask": ("Hit me three times. Full speed - I'm measuring.", "Three hits, as hard as you'd really swing. Go!",
            "Calibration. Give me your three best men - go!"),
    "first": ("Before we start - I need to feel your hits. Three men, full speed, go!",),
    "done": ("Got it: {a}, {b} and {c}. I'll feel anything over {t}.", "Measured - {a}, {b}, {c}. Threshold {t}."),
    "few": ("I only felt {n}. Say calibrate my strikes and give me three.", "That was {n} - I need three. Calibrate again?"),
    "none": ("I didn't feel a thing - is your whole upper body in the picture?",),
    "uneven": ("Those weren't even - {a}, {b}, {c}. One was soft. Calibrate again, three proper ones.",),
}
CUES = {"ask": "firedUp", "first": "firedUp", "done": "measure", "few": "shrug", "none": "concerned", "uneven": "headShake"}


def line(result: Result, rng) -> tuple[str, str]:
    """What she says about a calibration, and the cue for it."""
    p = [f"{x:.0f}" for x in result.peaks] + ["0", "0", "0"]
    if result.ok:
        kind = "done"
    elif not result.peaks:
        kind = "none"
    else:
        kind = result.why
    text = rng.choice(LINES[kind]).format(a=p[0], b=p[1], c=p[2], t=f"{result.threshold:.0f}", n=len(result.peaks))
    return text, CUES[kind]
