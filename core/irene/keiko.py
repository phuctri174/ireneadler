"""Keiko with Irene: she suits up and faces him; he strikes, she answers.

Started ONLY by his voice ("Irene, let's do keiko") - the kamae pose trigger is
retired (it fired on everyday arm movements). Ended by "stop" / "yame" / "that's
enough", or by itself when he has not struck for IDLE_END_S.

His strikes come from the HUD's recogniser (hud/src/tracking/strikeFeatures.ts,
trained by core/scripts/strike_train.py on his captures): men, kote or gyaku-dou,
with how sure it is and whether it was as clean as his good ones. Her answer is
deliberately simple and fun - not a fighting system:

  block     she gets her shinai there first
  hit       she takes it; a CLEAN one is ippon - two or three shinpan flags go up
  strike    she strikes back at him

with a line, a face, and the sounds: the kiai, the shinai's crack, the flags' whoosh
(all procedural, core/irene/sfx.py).
"""
from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODEL_TS = ROOT / "hud" / "src" / "tracking" / "strikeModel.ts"

# nothing from him for this long: keiko ends by itself
IDLE_END_S = 120.0
# and never longer than this in one go
MAX_S = 20 * 60.0

_START = re.compile(
    r"^\W*(?:(?:hey\s+)?irene\W+)?(?:(?:let'?s|let\s+us|wanna|do\s+you\s+want\s+to|want\s+to|shall\s+we|can\s+we|time\s+(?:for|to))\s+"
    r"(?:do\s+(?:some\s+)?|have\s+(?:a\s+)?|practi[cs]e\s+|go\s+)?(?:keiko|kendo\s+practi[cs]e|spar|sparring|practi[cs]e\s+kendo)"
    r"|keiko\s+time|spar\s+with\s+me|(?:start|begin)\s+keiko)\b",
    re.I,
)
_STOP = re.compile(
    # "stop" on its own ends keiko; "stop the music" is still about the music
    r"^\W*(?:(?:hey\s+)?irene\W+)?(?:(?:okay|ok|alright|right)\W+)?(?:irene\W+)?"
    r"(?:stop(?:\s+(?:now|please|keiko|there|irene|it|practice|practising|practicing))*\W*$|yame|enough|that'?s\s+enough|"
    r"let'?s\s+stop|(?:stop|end|finish)\s+(?:the\s+)?keiko|i'?m\s+done|we'?re\s+done|that'?s\s+it\s+for\s+(?:today|now))",
    re.I,
)

STRIKE_NAME = {"men": "Men", "kote": "Kote", "gyaku_dou": "Do"}

LINES: dict[str, tuple[str, ...]] = {
    "start": (
        "Keiko! Onegaishimasu!",
        "Ooh, keiko. Suiting up - onegaishimasu!",
        "Bogu on. Onegaishimasu, sir!",
    ),
    "no_model": (
        "Fair warning - I can't read your strikes yet. Record the keiko capture, control alt shift nine, and I'll learn your men.",
    ),
    "block": ("Not today!", "Blocked!", "Too slow, sir!", "Saw that coming.", "Nope!", "Ha - mine first."),
    "hit": ("Ow! Okay, that landed.", "Hey! Not bad.", "Ooh, that one touched.", "Fine, a little one."),
    "ippon": ("{strike} ari! Ippon!", "Ippon! That was clean.", "Okay, that's a proper {strike_low}. Ippon.", "{strike}! Ippon - well struck, sir."),
    "strike_back": ("{counter}!", "My turn - {counter}!", "{counter}! Hah!", "And... {counter}!"),
    "stop": ("Yame! Arigatou gozaimashita.", "Good keiko, sir. Arigatou gozaimashita!", "And bow. Arigatou gozaimashita!"),
    "timeout": ("No more strikes? I'll call that keiko. Arigatou gozaimashita!",),
}
CUES = {
    "start": ("firedUp", "excited"),
    "block": ("smug", "wink"),
    "hit": ("sheepish", "surprised"),
    "ippon": ("starryEyed", "bow", "surprised"),
    "strike_back": ("firedUp", "smug"),
    "stop": ("bow", "proud"),
    "timeout": ("bow", "shrug"),
}
# the sounds under each answer, in order (sfx.py names)
SOUNDS = {"start": ("kiai",), "block": ("thwack",), "hit": ("thwack",), "ippon": ("thwack", "flags"), "strike_back": ("kiai", "thwack")}


def model_ready(path: Path = MODEL_TS) -> bool:
    """Has a strike recogniser passed its held-out test and shipped to the HUD?"""
    try:
        return "STRIKE_MODEL: StrikeModel | null = null" not in path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False


def command(text: str, active: bool) -> str | None:
    """His words as keiko: "start", "stop" (only while it's on), or None."""
    said = (text or "").strip()
    if active and _STOP.search(said):
        return "stop"
    if _START.search(said):
        return "start"
    return None


@dataclass
class Answer:
    """What she does: the HUD's keiko action, her line, its face, the sounds."""

    action: str  # start | end | block | hit | strike | ippon
    line: str
    cue: str | None
    sounds: tuple[str, ...] = ()
    target: str | None = None
    flags: int | None = None


@dataclass
class Keiko:
    rng: random.Random = field(default_factory=random.Random)
    active: bool = False
    started: float = 0.0
    last_strike: float = 0.0
    ippon: int = 0
    strikes: int = 0
    _last: dict[str, str] = field(default_factory=dict)

    def _line(self, kind: str, **fill) -> str:
        pool = [line for line in LINES[kind] if line != self._last.get(kind)] or list(LINES[kind])
        line = self.rng.choice(pool)
        self._last[kind] = line
        return line.format(**fill) if fill else line

    def _cue(self, kind: str) -> str:
        return self.rng.choice(CUES[kind])

    def start(self, now: float | None = None) -> Answer:
        self.active = True
        self.started = self.last_strike = now if now is not None else time.monotonic()
        self.ippon = self.strikes = 0
        line = self._line("start")
        if not model_ready():
            line = f"{line} {self._line('no_model')}"
        return Answer("start", line, self._cue("start"), SOUNDS["start"])

    def stop(self, why: str = "stop") -> Answer:
        self.active = False
        line = self._line(why)
        if self.strikes:
            line += f" You landed {self.ippon} ippon in {self.strikes} strikes." if self.ippon else f" {self.strikes} strikes, and I kept you to zero ippon!"
        return Answer("end", line, self._cue(why))

    def expired(self, now: float | None = None) -> bool:
        now = now if now is not None else time.monotonic()
        return self.active and (now - self.last_strike > IDLE_END_S or now - self.started > MAX_S)

    def strike(self, strike: str, p: float, clean: bool, now: float | None = None) -> Answer | None:
        """His strike (from the recogniser): her answer - None if it isn't one."""
        if not self.active or strike not in STRIKE_NAME:
            return None
        self.last_strike = now if now is not None else time.monotonic()
        self.strikes += 1
        roll = self.rng.random()
        target = {"men": "men", "kote": "kote", "gyaku_dou": "dou"}[strike]
        if roll < 0.35:
            return Answer("block", self._line("block"), self._cue("block"), SOUNDS["block"])
        if roll < 0.7:
            if clean:
                self.ippon += 1
                # the more certain the recogniser, the more shinpan agree
                flags = 3 if p >= 0.97 else 2
                name = STRIKE_NAME[strike]
                return Answer("ippon", self._line("ippon", strike=name, strike_low=name.lower()), self._cue("ippon"), SOUNDS["ippon"], target, flags)
            return Answer("hit", self._line("hit"), self._cue("hit"), SOUNDS["hit"], target)
        counter = self.rng.choice(("Men", "Kote", "Do"))
        return Answer("strike", self._line("strike_back", counter=counter), self._cue("strike_back"), SOUNDS["strike_back"], counter.lower())
