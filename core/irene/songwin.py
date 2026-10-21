# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""The song-win bit: a scripted exchange after she names a song he taught her and he
says she got it. His lines, word for word - never rewritten:

  1. she names the song                      (brain.py: Conversation.named)
  2. he: "Yes, it's correct" (or similar)    -> "Haha, GG fucking easy Mr Tri", smug
  3. he: "Hey, don't say that"               -> "Oh really?", caughtOffGuard
                                                2 s of silence, the face held
                                                "FUGGING EASY", arrogant

Only ever after a reply of hers that named a song he taught her (Conversation.named,
set only when her answer said its title), and only on his VERY NEXT message: a whole
message of confirmation and nothing else ("yes, play it" is a request, not this).
After the gloat, only his very next message, and only if it objects; anything else
and she carries on normally - the bit is over either way.

Timing is the joke. All three lines are rendered ahead of time through the same
chokepoint as the skits (skit.render_line -> voice.take: his pronunciation map
applied, "Tri" said "Tree"; rendered once, cached in core/assets/skits/). "Oh
really?", the pause and "FUGGING EASY" are ONE clip: the pause is exactly HOLD_S of
silence from her last voiced sample to her next, and the arrogant face goes on with
the clip's own clock (a mark on its first sample of the second line), so neither the
pause nor the face can drift. Live, the RPS bonk lost its timing to her voice
arriving 1.4 s after its cue - that was a line synthesised on demand.

The pace is config/songwin.yaml (2026-10-19: "the three lines rush together"): each
line's speaking rate (stretched at the same pitch, skit.render_line), and every gap -
before the gloat, before and after "Oh really?", the hold, before "FUGGING EASY", and
how long her last face stays. Each gap is silence from the LAST sample of the take
before it (its whole tail) to the first sample of the next; the faces stay marks on
the clip.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, fields
from pathlib import Path

import numpy as np
import yaml

from . import skit

log = logging.getLogger("irene.songwin")

SR = skit.SR
CONFIG = Path(__file__).resolve().parents[2] / "config" / "songwin.yaml"


@dataclass(frozen=True)
class Pace:
    """config/songwin.yaml - what isn't there keeps these."""
    speed_gloat: float = 0.82
    speed_really: float = 0.85
    speed_fugging: float = 0.68
    beat_before_gloat_ms: int = 650
    beat_before_really_ms: int = 0
    beat_after_really_ms: int = 600
    hold_ms: int = 2000
    beat_before_fugging_ms: int = 400
    face_after_ms: int = 1500

    def speed(self, line: "Line") -> float:
        return {GLOAT.text: self.speed_gloat, REALLY.text: self.speed_really, FUGGING.text: self.speed_fugging}[line.text]


def pace(path: Path = CONFIG) -> Pace:
    """The pace as the file has it now (read every time the bit plays)."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as error:
        log.warning("song win: %s unreadable (%s) - the default pace", path.name, error)
        raw = {}
    out = {}
    for f in fields(Pace):
        if f.name in raw:
            try:
                value = float(raw[f.name]) if f.type in (float, "float") else int(raw[f.name])
            except (TypeError, ValueError):
                log.warning("song win: %s = %r is not a number - the default", f.name, raw[f.name])
                continue
            # a speed in (0.3, 2]; a gap from 0 to 10 s
            if f.name.startswith("speed_") and not 0.3 <= value <= 2.0 or not f.name.startswith("speed_") and not 0 <= value <= 10_000:
                log.warning("song win: %s = %r out of range - the default", f.name, value)
                continue
            out[f.name] = value
    return Pace(**out)


@dataclass(frozen=True)
class Line:
    text: str
    cue: str


# his wording, exactly
GLOAT = Line("Haha, GG fucking easy Mr Tri", "smug")
REALLY = Line("Oh really?", "caughtOffGuard")
FUGGING = Line("FUGGING EASY", "arrogant")
LINES = (GLOAT, REALLY, FUGGING)

# his confirmation: the whole message is made of these words ("Yes, it's correct",
# "yep that's the one", "correct!", "you got it, Irene") - nothing else in it
_YES = {"yes", "yeah", "yep", "yup", "yah", "ya", "correct", "right", "exactly", "bingo", "spot", "on", "you", "got", "it",
        "its", "it's", "that's", "thats", "that", "is", "are", "you're", "youre", "the", "one", "absolutely", "totally",
        "indeed", "irene", "hey", "wow", "nice", "haha", "ha", "good", "job", "well", "done", "perfect", "true", "so",
        "oh", "ok", "okay", "great", "sir", "song", "true", "very", "a", "100", "percent", "yes,"}
# ...with at least one of these in it
_YES_CORE = re.compile(r"\b(?:yes|yeah|yep|yup|yah|correct|right|exactly|bingo|spot on|got it|that'?s (?:it|the one)|absolutely|true)\b", re.I)
_NOT = re.compile(r"\b(?:no|not|nope|nah|wrong|isn'?t|incorrect|close|almost)\b", re.I)
# his objection to the gloat
_OBJECT = re.compile(
    r"\b(?:do ?n[o']?t|do not) (?:say|talk like) (?:that|this)|\blanguage\b|\bwatch (?:your|ur) (?:mouth|language|tongue)"
    r"|\b(?:do ?n[o']?t|no) (?:swear|swearing|curse|cursing)|\bthat'?s (?:rude|not nice|mean)|\b(?:so|very|how) rude\b"
    r"|\bdo ?n[o']?t be (?:rude|mean|cocky)|\bexcuse me\b|\bwhoa,? (?:there|hey)\b|\bhey!",
    re.I,
)


def _words(text: str) -> list[str]:
    return re.findall(r"[\w']+", (text or "").lower().replace("’", "'"))


def confirms(text: str) -> bool:
    """A whole message that only says she got it."""
    words = _words(text)
    return bool(words) and len(words) <= 10 and _YES_CORE.search(text or "") is not None \
        and _NOT.search(text or "") is None and all(w in _YES for w in words)


def objects(text: str) -> bool:
    """He pulls her up on the gloat ("Hey, don't say that")."""
    return len(_words(text)) <= 12 and _OBJECT.search(text or "") is not None


class SongWin:
    """Where the bit is: nothing, or the gloat said and his reply awaited."""

    def __init__(self) -> None:
        self.gloated = False
        self.audio: dict[str, np.ndarray] = {}
        self.engine: str | None = None
        # the speeds the audio was rendered at (a changed config re-renders)
        self.speeds: tuple[float, ...] = ()

    def heard(self, text: str, named: str | None) -> str | None:
        """His message: "gloat", "fugging", or None - the bit doesn't apply (and is
        over, if it was on)."""
        if self.gloated:
            self.gloated = False
            if objects(text):
                log.info("song win: he objected (%r) - oh really... FUGGING EASY", text[:60])
                return "fugging"
            log.info("song win: no objection (%r) - carrying on", text[:60])
            return None
        if named and confirms(text):
            log.info("song win: he confirmed %r (%r) - the gloat", named, text[:60])
            self.gloated = True
            return "gloat"
        return None

    def reset(self) -> None:
        self.gloated = False

    # ---- audio, rendered once -----------------------------------------------------------

    @property
    def ready(self) -> bool:
        return all(line.text in self.audio for line in LINES)

    def load_or_render(self, voice, p: Pace | None = None) -> None:
        """All three lines in `voice`'s engine, through skit.render_line (the chokepoint:
        his pronunciation map, the cache, the silence check) at their natural pace, then
        slowed to the configured speeds (slowed(): the onset kept whole)."""
        p = p or pace()
        audio = {}
        for line in LINES:
            raw = skit.render_line(voice, skit.Beat("irene", line.text, [line.cue]))
            audio[line.text] = slowed(raw, p.speed(line))
        self.audio, self.engine = audio, voice.name
        self.speeds = (p.speed_gloat, p.speed_really, p.speed_fugging)
        log.info("song win lines ready in %s: %s", voice.name, ", ".join(
            f"{line.text!r} {len(audio[line.text]) / SR:.2f} s at {p.speed(line):g}" for line in LINES))

    def stale(self, p: Pace) -> bool:
        """The config's speeds are not the ones rendered."""
        return bool(self.speeds) and self.speeds != (p.speed_gloat, p.speed_really, p.speed_fugging)


# the start of a line kept at its own speed when it is slowed: stretched whole, the "f"
# of FUGGING smeared into a "v" (Whisper on the takes, 2026-10-19: "smoking easy" at
# 0.68, "voguing"/"fogging" from 0.68 to 0.80, "fucking easy" only at 0.85); with its
# first 120 ms kept, "fucking easy" - the word as said - at every rate from 0.65 to 0.75
ONSET_KEEP_MS = 120
_XFADE_MS = 10


def slowed(audio: np.ndarray, rate: float) -> np.ndarray:
    """`audio` at `rate` (same pitch, stretch.py), its first word's onset untouched."""
    from .stretch import stretch

    audio = np.asarray(audio, np.float32)
    if abs(rate - 1.0) < 1e-3 or len(audio) == 0:
        return audio
    lead, _, _, _ = skit.silences(audio)
    keep = min(len(audio), int((lead + ONSET_KEEP_MS) * SR / 1000))
    xf = min(int(_XFADE_MS * SR / 1000), keep)
    tail = stretch(audio[keep - xf:], rate)
    w = np.linspace(0, 1, xf, dtype=np.float32)
    joined = audio[keep - xf:keep] * (1 - w) + tail[:xf] * w
    return np.concatenate([audio[: keep - xf], joined, tail[xf:]]).astype(np.float32)


def _gap(ms: float) -> np.ndarray:
    return np.zeros(int(round(ms * SR / 1000)), np.float32)


def gloat_clip(gloat: np.ndarray, p: Pace) -> tuple[np.ndarray, list[float]]:
    """The beat, then the gloat. Returns the clip and where its line starts (its face)."""
    lead = _gap(p.beat_before_gloat_ms)
    return np.concatenate([lead, gloat]).astype(np.float32), [len(lead) / SR]


def held(really: np.ndarray, fugging: np.ndarray, p: Pace) -> tuple[np.ndarray, list[float]]:
    """"Oh really?", then - from its LAST sample - the beat after it, the hold and the
    beat before, then "FUGGING EASY", as one clip. Returns it and where each line's
    take starts (seconds: its face goes on there)."""
    lead = _gap(p.beat_before_really_ms)
    silence = _gap(p.beat_after_really_ms + p.hold_ms + p.beat_before_fugging_ms)
    clip = np.concatenate([lead, really, silence, fugging]).astype(np.float32)
    return clip, [len(lead) / SR, (len(lead) + len(really) + len(silence)) / SR]
