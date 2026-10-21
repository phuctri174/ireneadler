# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""Openers: the short interjections her replies begin with ("Ooh!", "Hmm...", "Oh no..."),
pre-rendered in her live voice so the first thing he hears needs no synthesis.

Turbo takes half a second or more even for a one-word chunk; a reply whose first
chunk is one of these plays it straight from memory while the next chunk is
synthesised. Rendered once per engine and cached in core/assets/openers/.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

import numpy as np
import soundfile as sf

log = logging.getLogger("irene.openers")

ASSETS = Path(__file__).resolve().parents[1] / "assets" / "openers"
FORMAT = 1

# as she'd say them; the key is the words alone, so "Hmm," and "Hmm..." share one take
OPENERS = [
    "Ooh!", "Hmm...", "Oh!", "Oh no...", "Oh dear...", "Ah!", "Aha!", "Ha!", "Haha!", "Wow!",
    "Whoa!", "Yay!", "Yes!", "Right!", "Alright!", "Okay!", "Sure!", "Of course!", "Done!",
    "Got it!", "On it!", "Well...", "Oh wow!", "Ooh, nice!", "Nice!", "Perfect!", "Ta-da!",
    "Hiii!", "Hi!", "Hey!", "Hello!", "Morning!", "Good morning!", "Evening!", "Good evening!",
    "Oops!", "Uh oh...", "Yikes!", "Good one!", "Hmm, good one.", "Oh, hi!", "Welcome back!",
    "Brilliant!", "Splendid!", "Oh, sir...", "Mister Tri!", "Ooh, sir!", "Hmm, let me think.",
    # said while a slow tool runs (app.py: SLOW_TOOLS)
    "Let me look that up!", "One sec, sir - checking!", "Looking into it!", "Ooh, let me dig!",
]


# what she can say first while her real first phrase is still being synthesised,
# by the feeling it opens with - several each, so it never sounds the same twice
BY_CUE = {
    "giggle": ["Ha!", "Haha!"],
    "wink": ["Ha!", "Hmm..."],
    "surprised": ["Oh!", "Whoa!", "Wow!"],
    "excited": ["Ooh!", "Oh wow!", "Yay!"],
    "happy": ["Ooh!", "Oh!", "Aha!"],
    "love": ["Ooh!", "Oh!"],
    "proud": ["Ta-da!", "Aha!"],
    "sad": ["Oh...", "Oh no...", "Oh dear..."],
    "concerned": ["Oh no...", "Oh dear...", "Hmm..."],
    "confused": ["Hmm...", "Well..."],
    "curious": ["Hmm...", "Ooh!", "Oh!"],
    "thinking": ["Hmm...", "Hmm, let me think.", "Well..."],
    "thumbsUp": ["Done!", "Got it!", "Ta-da!"],
    "salute": ["On it!", "Got it!", "Right!"],
    "wave": ["Hi!", "Hey!", "Hello!"],
    None: ["Hmm...", "Right!", "Okay!", "Well..."],
}


# while a slow tool runs, so the wait isn't silent
WORKING = ["Let me look that up!", "One sec, sir - checking!", "Looking into it!", "Ooh, let me dig!"]
# as a quick command's call is still being written: her first word, at once
ACKS = ["On it!", "Got it!", "Okay!", "Sure!", "Right!"]


def key(text: str) -> str:
    """Words only, lower case: how a spoken chunk is matched to a pre-rendered take."""
    return re.sub(r"[^a-z' ]+", "", text.lower().replace("-", " ")).strip()


def _cache_key(voice) -> str:
    """Keyed on what the engine is actually given - so a change to his
    pronunciation map re-renders the lead-ins it touches ("Mister Tri!")."""
    spoken = [voice.spoken(t) if hasattr(voice, "spoken") else t for t in OPENERS]
    return hashlib.sha1(json.dumps({"engine": voice.name, "openers": spoken, "format": FORMAT}).encode()).hexdigest()[:12]


def load_or_render(voice) -> dict[str, np.ndarray]:
    """{key: audio} for every opener, in `voice`'s engine."""
    folder = ASSETS / voice.name
    stamp = folder / "key.txt"
    takes: dict[str, np.ndarray] = {}
    if stamp.exists() and stamp.read_text(encoding="utf-8") == _cache_key(voice):
        for text in OPENERS:
            path = folder / f"{key(text).replace(' ', '_')}.wav"
            if path.exists():
                # levelled as it loads, like all her speech (levels.py)
                from .levels import level_speech

                takes[key(text)] = level_speech(sf.read(path, dtype="float32")[0])
        if len(takes) == len({key(t) for t in OPENERS}):
            return takes
    folder.mkdir(parents=True, exist_ok=True)
    for text in OPENERS:
        audio = voice.all(text)
        takes[key(text)] = audio
        sf.write(folder / f"{key(text).replace(' ', '_')}.wav", audio, 24000, subtype="PCM_16")
    stamp.write_text(_cache_key(voice), encoding="utf-8")
    log.info("openers rendered: %d takes in %s", len(takes), voice.name)
    return takes
