# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""What Irene may show while she talks: the cue vocabulary, from config/cues.json.

Four kinds, one flat namespace:
  expression  the face alone - eyes that change while she speaks
  gesture     LED hand poses with a matching face (the HUD's led/poses.ts)
  scene       a short activity loop (chess, kendo), played once
  prop        what a running tool shows (a magnifier, a clock) - picked by the
              tool, never offered to the model

A new cue is its art in the HUD plus one registry entry; everything here, the
model's catalogue included, follows from the registry.
"""
from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from pathlib import Path

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "cues.json"


def _load() -> list[dict]:
    cues = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))["cues"]
    names = [c["name"] for c in cues]
    if len(names) != len(set(names)):
        raise RuntimeError(f"duplicate cue names in {REGISTRY_PATH}")
    return cues


CUES: list[dict] = _load()
BY_NAME: dict[str, dict] = {c["name"]: c for c in CUES}


def _of(kind: str) -> tuple[str, ...]:
    return tuple(c["name"] for c in CUES if c["kind"] == kind)


GESTURES: tuple[str, ...] = _of("gesture")
EXPRESSIONS: tuple[str, ...] = _of("expression")
SCENES: tuple[str, ...] = _of("scene")
PROPS: tuple[str, ...] = _of("prop")
# what the model may write; props are the tools' own
ALL: tuple[str, ...] = tuple(c["name"] for c in CUES if c["kind"] != "prop")

# models write names loosely ("Thumbs up", "heart-hands"); match on letters only
_KEY = {re.sub(r"[^a-z]", "", name.lower()): name for name in ALL}


@dataclass(frozen=True)
class React:
    name: str
    kind: str  # "gesture" | "expression" | "scene" | "prop"
    # he asked for this action himself: it plays even if it played last time
    asked: bool = False
    # cues that fit this moment equally (his joke: giggle or wink): if this one just
    # played, another of these plays instead of something unrelated
    family: tuple[str, ...] = ()

    @property
    def speed(self) -> float:
        """Speaking rate for a sentence cued with this."""
        return float(BY_NAME.get(self.name, {}).get("speed", 1.0))

    @property
    def sfx(self) -> str | None:
        """The little sound (sfx.py) under a sentence cued with this, if any."""
        return BY_NAME.get(self.name, {}).get("sfx")


def resolve(raw: str | None) -> React | None:
    """A model-written name -> a known cue, or None. Never raises."""
    if not raw:
        return None
    name = _KEY.get(re.sub(r"[^a-z]", "", raw.lower()))
    if name is None:
        return None
    return React(name, BY_NAME[name]["kind"])


def prop(name: str | None) -> React | None:
    """A tool's prop by exact name (tools declare it; the model never does)."""
    entry = BY_NAME.get(name or "")
    return React(entry["name"], "prop") if entry and entry["kind"] == "prop" else None


def catalogue() -> str:
    """The model's view of the pool: one compact line per cue, grouped by kind."""
    lines = []
    for kind, title in (("expression", "face"), ("gesture", "hands"), ("scene", "scenes")):
        lines.append(f"{title}:")
        lines += [f"- {c['name']} - {c['when']}" for c in CUES if c["kind"] == kind and c.get("when")]
    return "\n".join(lines)


# "show me a kendo strike", "wave at me", "play me a chess move": he asks her to DO
# one of her actions. gemma picks a nearby feeling instead (thinking for a chess
# move) often enough that the action he named is enforced for that turn.
_ACT_ALIASES: dict[str, str] = {c["name"]: c["act"] for c in CUES if c.get("act")}
_ACT_REQUEST = re.compile(
    r"^\W*(irene\W+)?(please\W+)?(go on\W+)?(wave|salute|yawn|facepalm|shrug|cross|kiai|strike|flinch|cover|peer|peek|measure|size|raise|call|lights|roll)\b"
    r"|\b(do|show|play|make|give|perform|put|let'?s see|let me see|let'?s hear|can you|could you|will you)\b",
    re.I,
)


def act_out(text: str) -> str | None:
    """The action he is asking her to perform, if the message is such a request."""
    if not _ACT_REQUEST.search(text):
        return None
    for name, alias in _ACT_ALIASES.items():
        if re.search(rf"\b({alias})\b", text, re.I):
            return name
    return None


# Every reply shows at least one cue. When the model gives none, one is picked from
# what she says: the topic first (chess talk gets the chess scene), then the mood of
# the words; never the cue that just played. Checked in order; first match wins.
_FALLBACK: tuple[tuple[re.Pattern, tuple[str, ...]], ...] = tuple(
    (re.compile(pattern, re.I), names)
    for pattern, names in (
        (r"\bchess|checkmate|\bgambit\b", ("chess", "thinking")),
        (r"\bkendo|sword|shinai|\bdojo\b", ("kendo", "salute")),
        (r"\b(tired|sleepy|late night|bed ?time|exhausted)\b", ("yawn", "concerned")),
        (r"\b(sorry|oh no|oh dear|oops|unfortunately|sadly|failed|couldn'?t|can'?t|error|broke)\b", ("concerned", "sad", "facepalm")),
        (r"\b(haha|lol|joke|funny|pun|silly|cheeky)\b|\bha!", ("giggle", "wink")),
        (r"\b(let'?s (go|do this)|fired up|pumped|bring it( on)?|come at me|hajime|game on|keiko time)\b", ("firedUp", "excited")),
        (r"\b(wow|whoa|amazing|incredible|astonishing|stunning|gorgeous|dream)\b", ("starryEyed", "surprised", "excitedBounce")),
        (r"\b(yay|great|awesome|congrat\w*|brilliant|perfect|wonderful|fantastic|love)\b|!.*!", ("excitedBounce", "excited", "happy", "proud")),
        (r"\b(done|got it|on it|ready|opened|paused|skipped|set|saved)\b", ("thumbsUp", "salute")),
        (r"\b(hi|hello|hey|morning|evening|welcome)\b", ("wave", "happy")),
        (r"\b(hmm|let me think|maybe|perhaps|not sure|depends|guess|wonder)\b", ("headTilt", "thinking", "shrug")),
        (r"\?", ("headTilt", "curious", "thinking")),
    )
)
_TOPICS = 3  # the first entries above are topics, the rest moods
# nothing in the words to go on: still something he can SEE - mostly cues that move
# her body (a tilt, a bounce, a sign), not a face that barely changes
_ANYTIME = ("headTilt", "peace", "excitedBounce", "wink", "happy", "proud")


def fallback(text: str, avoid: str | tuple[str, ...] | None = None, rng=None) -> React:
    """A cue that fits `text`, for a reply the model left without one - never `avoid`
    (the cue that just played, or several), so no two replies in a row look the same."""
    rng = rng or random
    avoid = (avoid,) if isinstance(avoid, str) else tuple(avoid or ())
    for k, (pattern, names) in enumerate(_FALLBACK):
        if pattern.search(text or ""):
            fits = [n for n in names if n in BY_NAME and n not in avoid]
            if fits:
                # a topic has its own cue (chess talk -> the chess scene); a mood varies
                name = fits[0] if k < _TOPICS else rng.choice(fits)
                return React(name, BY_NAME[name]["kind"])
    name = rng.choice([n for n in _ANYTIME if n in BY_NAME and n not in avoid])
    return React(name, BY_NAME[name]["kind"])


def of_family(family: tuple[str, ...], avoid: str | tuple[str, ...] | None = None) -> React | None:
    """The first of `family` not in `avoid` (a name, or every cue the last reply
    showed - the first of them, its opening, avoided hardest), carrying the family
    along - for a moment that calls for one of a few cues (sentiment.MOOD_CUES)."""
    names = [n for n in family if n in BY_NAME]
    shown = (avoid,) if isinstance(avoid, str) else tuple(avoid or ())
    name = next((n for n in names if n not in shown), None)
    if name is None:
        name = next((n for n in names if not shown or n != shown[0]), None)
    return React(name, BY_NAME[name]["kind"], family=tuple(names)) if name else None
