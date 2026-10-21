# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""Shiai with Irene: a bout, sanbon shobu - first to two points. Rules and dice, no model.

The whole feature (his spec, 2026-10-18 - nothing beyond it):
  - he throws men only: every strike of his is a men, no classification
  - she attacks with men or kote
  - he can dodge (step back or aside) and block (hands up, held - against her men)
  - she can dodge, parry and counter his strike
  - a 5 s countdown before the bout, then "Hajime!" shouted as a kiai
  - a 5 s pause after each point, then "Hajime!" again
  - the running score on screen
  - first to two

Started by his voice ("Irene, let's do shiai") or Ctrl+Alt+Shift+M; ended by "stop" /
"yame" (or any of his exits, modes.py), by itself when he goes quiet, or at two
points. The HUD reads, with the same tuned thresholds as study mode
(hud/src/tracking/strikeEvent.ts, strike_tuning.py):

  strike    his signed downward wrist speed over the threshold, a sharp stop
  advance   his shoulders growing (he stepped in), retreat - shrinking
  side      his shoulders' midpoint moving sideways
  block     both hands up over his head, held (hud/src/tracking/strikeKind.ts)

One swing is one strike: events of his within STRIKE_GAP_S of the strike she answered
are the same swing (live in bogu, one swing came as 2-3 events over 1.4 s - each past
the detector's own 400 ms rest, which is unchanged).

His strike: she takes it (his point: "Men ari!"), parries, dodges, or counters (her
point). Stepping in just before makes it likelier to land.

Her attack, when he hasn't struck for a few seconds: a WINDUP he can see coming, then
impact WINDOW_S later. Inside the window a step back or aside is a dodge; both hands
up against her men is a block (against her kote, hands up leave it open). Nothing, and
it lands: her point. Between a point's call and hajime nothing counts.
"""
from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

TO_WIN = 2
IDLE_END_S = 120.0
MAX_S = 15 * 60.0
# she attacks when he hasn't struck for a random spell in this range
ATTACK_AFTER_S = (4.0, 8.0)
# her windup to impact: the window he has to block or step out
WINDOW_S = 1.4
# stepped in this recently: his strike is likelier to land
ADVANCE_S = 1.5
# one swing is one strike: his events this soon after the one she answered are it
STRIKE_GAP_S = 1.5
# the beat, in config/shiai.json (read every time): the countdown before the bout, and
# the pause after a point - from the call to hajime, never before she has finished her
# line - with both back to the start lines resetAfterS into it
BEAT_CONFIG = Path(__file__).resolve().parents[2] / "config" / "shiai.json"
BEAT_DEFAULTS = {"startCountdownS": 5.0, "pauseS": 5.0, "resetAfterS": 1.5, "menRaiseAboveKamae": 1.8, "menZanshinAboveKamae": 1.1}
# his block (BlockDetector, hud/src/tracking/strikeKind.ts): the lower wrist at least
# `above` shoulder widths over the shoulders, held holdMs, a dip under graceMs forgiven
BLOCK = {"above": 0.0, "holdMs": 250, "graceMs": 120, "refractoryMs": 1000}
# his men, as a sequence (MenSequence, hud/src/tracking/strikeKind.ts; his spec,
# 2026-10-19), against HIS kamae - the median wrist height over the second before (a
# rolling reference: he moves about in a bout) - not his shoulders, which in bogu the
# pose model never sees his wrists reach: both wrists raised menRaiseAboveKamae above
# it, the cut (the strike event, its threshold and guards untouched) within 0.7 s of
# that, then zanshin - both wrists still menZanshinAboveKamae above it, held 400 ms (a
# dip under 120 ms forgiven), from the cut's end - all within 2 s. Set from a readout
# of his men vs still-kamae jitter in bogu (2026-10-19): his men rose 2.34 above kamae
# and its cut ended 1.62 above; of 39 jitter cuts the highest rose 1.49 (most <= 1.03)
# and ended 1.01 (held 67 ms; <= 0.88 among those that held 400 ms). So 1.8 and 1.1.
# Height separates them; stillness does not (jitter in kamae holds still for seconds,
# his zanshin held steady 192 ms) - a stay-put band would have rejected his men. A spike alone
# scores nothing. The two heights are his to nudge in config/shiai.json. Study mode
# keeps the plain strike event.
MEN = {"holdMs": 400, "graceMs": 120, "kamaeMs": 1000, "kamaeLagMs": 300, "cutAfterRaiseMs": 700, "windowMs": 2000}
# her answer to his strike: weights (take it, parry, dodge, counter), and with an advance
WEIGHTS = (0.30, 0.30, 0.25, 0.15)
WEIGHTS_ADVANCED = (0.50, 0.20, 0.15, 0.15)
# where she cuts, and how often - his strikes are all men
TARGETS = ("men", "kote")
TARGET_WEIGHTS = (0.6, 0.4)
NAME = {"men": "Men", "kote": "Kote"}

_START = re.compile(
    r"^\W*(?:(?:hey\s+)?irene\W+)?(?:(?:let'?s|let\s+us|wanna|do\s+you\s+want\s+to|want\s+to|shall\s+we|can\s+we|time\s+(?:for|to))\s+"
    r"(?:do\s+(?:a\s+|some\s+)?|have\s+(?:a\s+)?|fight\s+(?:a\s+)?|go\s+)?(?:shiai|kendo\s+match|kendo\s+bout|bout|"
    # "let's do kendo" - Whisper never writes "shiai" (modes.py), it always writes "kendo";
    # kendo PRACTICE is keiko's
    r"kendo(?!\s+(?:practi|lesson|class|training|drill))))\b"
    r"|^\W*(?:(?:hey\s+)?irene\W+)?(?:shiai\s+time|(?:start|begin)\s+(?:a\s+)?(?:shiai|kendo\s+match)|shiai\s+with\s+me|first\s+to\s+two"
    r"|(?:a\s+)?kendo\s+(?:match|bout)(?:\s+with\s+me)?\W*$)",
    re.I,
)
_STOP = re.compile(
    r"^\W*(?:(?:hey\s+)?irene\W+)?(?:(?:okay|ok|alright|right)\W+)?(?:irene\W+)?"
    r"(?:stop(?:\s+(?:now|please|shiai|there|irene|it|the\s+match))*\W*$|yame|enough|that'?s\s+enough|"
    r"let'?s\s+stop|(?:stop|end|finish)\s+(?:the\s+)?(?:shiai|match|bout)|i\s+give\s+up|i'?m\s+done|we'?re\s+done)",
    re.I,
)

LINES: dict[str, tuple[str, ...]] = {
    "start": ("Shiai! Sanbon shobu - first to two. Get ready.", "A match? Oh, you're on. Sanbon shobu. Kamae!",
              "Sanbon shobu, first to two. I won't go easy. Kamae!"),
    # after the call ("Kote ari!") - kept short: hajime comes 3-5 s after the call and
    # never cuts her off (a 5 s line held it to 8 s, live)
    # his point
    "take": ("Ow. Fine.", "...Lucky.", "Clean. Ugh.", "Okay, okay."),
    "parry": ("Parried!", "Nope - my shinai was there.", "Too slow!"),
    "dodge": ("Missed me!", "Whoosh - not even close.", "Ha, I was never there."),
    # after the call: her points
    "counter": ("Countered - mine!", "You opened up!", "Debana! Mine."),
    "landed": ("You stood still!", "Feet, sir, feet!", "Mine. You were planted."),
    # her attack, answered
    "slipped": ("Ooh, you moved. Nice footwork.", "Clean dodge! I'm impressed. A little.", "Okay - that was good. Where did you go?"),
    "blocked": ("Hey! Blocked? Rude.", "Ugh, your shinai was right there.", "Tch. Blocked. Fine."),
    "open": ("Hands up? Wrong guard!", "Up high, cut low. Classic."),
    "shobu": ("Shobu ari!",),
    "won": ("I win! Arigatou gozaimashita - and you're buying.", "Two points. Bow to the champion.", "That's two. Undefeated. Obviously."),
    "lost": ("...Fine. You win. Rematch, right now.", "You won. I let you. Probably.", "Two points to you. I'm not sulking. I'm not."),
    "stop": ("Yame! We'll call it there - {you} to {her}.", "Match stopped at {you} - {her}. Arigatou gozaimashita."),
    "timeout": ("No more strikes? I'll call it - {you} to {her}. Arigatou gozaimashita!",),
}
CUES = {
    "start": ("firedUp", "excited"),
    "take": ("refFlag", "bonked", "sheepish"),
    "parry": ("smug", "focused"),
    "dodge": ("smug", "wink"),
    "counter": ("firedUp", "triumphant"),
    "landed": ("refFlag", "triumphant", "smug"),
    "slipped": ("surprised", "outplayed"),
    "blocked": ("indignant", "sulking"),
    "won": ("triumphant", "excitedBounce"),
    "lost": ("sulking", "outplayed"),
    "hajime": ("hajimeCall",),
    "stop": ("bow",),
    "timeout": ("bow", "shrug"),
}
SOUNDS = {"start": ("kiai",), "take": ("thwack", "flags"), "parry": ("thwack",), "dodge": (), "counter": ("kiai", "thwack"),
          "landed": ("thwack", "flags"), "slipped": (), "blocked": ("thwack",), "windup": ("kiai",)}
# the HUD's keiko action for his strike answered without a point
HUD = {"parry": "block", "dodge": "dodge"}


def beat(path: Path = BEAT_CONFIG) -> dict[str, float]:
    """The countdown before the bout, the pause after a point (call to hajime) and when
    the reset shows inside it, seconds - config/shiai.json over BEAT_DEFAULTS."""
    out = dict(BEAT_DEFAULTS)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        for key in out:
            if isinstance(raw.get(key), (int, float)) and not isinstance(raw.get(key), bool):
                out[key] = float(raw[key])
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    out["startCountdownS"] = min(30.0, max(0.0, out["startCountdownS"]))
    out["pauseS"] = min(15.0, max(1.0, out["pauseS"]))
    out["resetAfterS"] = min(out["pauseS"], max(0.0, out["resetAfterS"]))
    out["menRaiseAboveKamae"] = min(4.0, max(0.3, out["menRaiseAboveKamae"]))
    out["menZanshinAboveKamae"] = min(out["menRaiseAboveKamae"], max(0.0, out["menZanshinAboveKamae"]))
    return out


def men_tuning(strikes: dict, path: Path = BEAT_CONFIG) -> dict:
    """The HUD's men-sequence config: his two heights from config/shiai.json (read
    fresh), the strike event's own visibility floor."""
    b = beat(path)
    return {**MEN, "raiseAboveKamae": b["menRaiseAboveKamae"], "finishAboveKamae": b["menZanshinAboveKamae"], "minVis": strikes["minVis"]}


def block_tuning(strikes: dict) -> dict:
    """The HUD's block config, with the strike event's own guards (minVis, maxPeak)."""
    return {**BLOCK, "minVis": strikes["minVis"], "maxPeak": strikes["maxPeak"]}


def command(text: str, active: bool) -> str | None:
    """His words as shiai: "start", "stop" (only while it's on), or None."""
    said = (text or "").strip()
    if active and _STOP.search(said):
        return "stop"
    if _START.search(said):
        return "start"
    return None


@dataclass
class Answer:
    """What she does: the HUD's keiko action (and its details), her line, its face,
    the sounds - and for a point, its call and the reset that follows."""

    action: str | None
    line: str
    cue: str | None
    sounds: tuple[str, ...] = ()
    flags: int | None = None
    over: bool = False
    # the score as it stands after this answer (you, her) - on the board before she says it
    score: tuple[int, int] | None = None
    target: str | None = None
    # a point: the call across the top ("KOTE ARI") and whose it is
    call: str | None = None
    who: str | None = None
    # her attack: how it ended (impact), how long it takes (windup, ms)
    result: str | None = None
    ms: int | None = None
    # HUD keiko messages to send before this one (her cut landing, before the call)
    before: list[dict] = field(default_factory=list)
    # a point that does not end the bout: then the pause, the reset ("NIHONME" /
    # "SHOBU") and hajime (Shiai.hajime) - app.Core runs the beat
    reset: str | None = None

    def hud(self) -> dict | None:
        """The HUD's keiko message for this answer, or None."""
        if self.action in (None, "start", "end"):
            return None
        m: dict = {"type": "keiko", "action": self.action}
        for key in ("flags", "target", "call", "who", "result", "ms"):
            if getattr(self, key) is not None:
                m[key] = getattr(self, key)
        return m


@dataclass
class Shiai:
    rng: random.Random = field(default_factory=random.Random)
    active: bool = False
    you: int = 0
    her: int = 0
    started: float = 0.0
    last_strike: float = 0.0
    last_advance: float = -1e9
    next_attack: float = 0.0
    # her attack under way: when the windup began, and where it will land
    attacking: float | None = None
    target: str = "men"
    # his hands went up against an attack that wasn't at his men
    raised: bool = False
    # when she last answered his strike: one swing is one strike (STRIKE_GAP_S)
    answered: float = -1e9
    # between a point's call and hajime: nothing counts
    paused: bool = False
    _last: dict[str, str] = field(default_factory=dict)

    def _line(self, kind: str) -> str:
        pool = [x for x in LINES[kind] if x != self._last.get(kind)] or list(LINES[kind])
        pick = self.rng.choice(pool)
        self._last[kind] = pick
        return pick.format(you=self.you, her=self.her)

    def _answer(self, kind: str) -> Answer:
        return Answer(HUD.get(kind, kind), self._line(kind), self.rng.choice(CUES[kind]), SOUNDS.get(kind, ()))

    def _rest(self, now: float) -> None:
        self.next_attack = now + self.rng.uniform(*ATTACK_AFTER_S)

    def _window(self, now: float) -> bool:
        return self.attacking is not None and self.attacking <= now <= self.attacking + WINDOW_S

    def start(self, now: float | None = None) -> Answer:
        now = time.monotonic() if now is None else now
        # paused until the countdown's hajime (Shiai.hajime): nothing counts before it
        self.active, self.you, self.her, self.attacking, self.paused = True, 0, 0, None, True
        self.started = self.last_strike = now
        self.last_advance = self.answered = -1e9
        self._rest(now)
        return Answer("start", self._line("start"), self.rng.choice(CUES["start"]), SOUNDS["start"], score=(0, 0))

    def stop(self, why: str = "stop") -> Answer:
        self.active = False
        self.attacking = None
        self.paused = False
        return Answer("end", self._line(why), self.rng.choice(CUES[why]), over=True)

    def _point(self, who: str, strike: str, how: str, now: float, say: str | None = None) -> Answer:
        """A point: called by name ("Kote ari!"), then her line (`how`'s, or `say`'s
        pool), then the score - or the end of the bout."""
        if who == "you":
            self.you += 1
        else:
            self.her += 1
        call = f"{NAME[strike]} ari!"
        a = Answer("ippon", f"{call} {self._line(say or how)}", self.rng.choice(CUES[how]), SOUNDS.get(how, ()), flags=3,
                   score=(self.you, self.her), target=strike, call=call.rstrip("!").upper(), who=who)
        self.attacking = None
        self.raised = False
        if self.you >= TO_WIN or self.her >= TO_WIN:
            self.active = False
            end = "lost" if self.you >= TO_WIN else "won"
            # what he did wrong stays said ("Hands up? I wasn't cutting your men!")
            said = f" {self._line(say)}" if say else ""
            a.line = f"{call}{said} {self._line('shobu')} {self._line(end)}"
            a.cue = self.rng.choice(CUES[end])
            a.over = True
        else:
            # nothing counts until hajime
            self.paused = True
            a.reset = "SHOBU" if self.you == self.her else "NIHONME"
        return a

    def hajime(self, now: float | None = None) -> Answer:
        """After a point's reset: "Hajime!" - and play resumes."""
        now = time.monotonic() if now is None else now
        self.paused = False
        self.last_strike = now
        self._rest(now)
        # shouted, as a kiai (app.Core._shiai_hajime): what the point is shows on screen
        return Answer("hajime", "Hajime!", self.rng.choice(CUES["hajime"]), ())

    def strike(self, now: float | None = None) -> Answer | None:
        """His strike - a men, always: her answer, or None if no bout is on, it is
        between a point and hajime, or it is the same swing she just answered."""
        if not self.active or self.paused:
            return None
        now = time.monotonic() if now is None else now
        self.last_strike = now
        if now - self.answered < STRIKE_GAP_S:
            return None  # the same swing, still coming through the detector
        self.answered = now
        advanced = now - self.last_advance <= ADVANCE_S
        pick = self.rng.choices(("take", "parry", "dodge", "counter"), WEIGHTS_ADVANCED if advanced else WEIGHTS)[0]
        if pick == "take":
            return self._point("you", "men", "take", now)
        if pick == "counter":
            return self._point("her", self.rng.choices(TARGETS, TARGET_WEIGHTS)[0], "counter", now)
        # striking into her attack beats it to the punch: her attack is gone either way
        self.attacking = None
        self._rest(now)
        return self._answer(pick)

    def move(self, kind: str, now: float | None = None) -> Answer | None:
        """His footwork and his guard: an advance sets up his next strike; inside her
        attack's window a retreat or a side step slips it, and hands up blocks a men."""
        if not self.active or self.paused:
            return None
        now = time.monotonic() if now is None else now
        if kind == "advance":
            self.last_advance = now
            return None
        if not self._window(now):
            return None  # hands up, a step back, with nothing coming: nothing happens
        if kind == "block":
            if self.target != "men":
                self.raised = True  # her kote is still coming - and now it's open
                return None
            self.attacking = None
            self._rest(now)
            a = self._answer("blocked")
            a.action, a.result, a.target = "impact", "blocked", "men"
            return a
        if kind in ("retreat", "side"):
            target = self.target
            self.attacking = None
            self._rest(now)
            a = self._answer("slipped")
            a.action, a.result, a.target = "impact", "dodged", target
            return a
        return None

    def tick(self, now: float | None = None) -> Answer | None:
        """Called a few times a second: her attack when he has gone still, its landing
        when he didn't answer it, and the bout's end when he has wandered off."""
        if not self.active:
            return None
        now = time.monotonic() if now is None else now
        if now - self.last_strike > IDLE_END_S or now - self.started > MAX_S:
            return self.stop("timeout")
        if self.paused:
            return None
        if self.attacking is not None:
            if now - self.attacking > WINDOW_S:
                target = self.target
                # his hands up against a kote or a do: she says what that left open
                a = self._point("her", target, "landed", now, say="open" if self.raised and target != "men" else None)
                a.before = [{"type": "keiko", "action": "impact", "target": target, "result": "hit"}]
                return a
            return None
        if now >= self.next_attack:
            self.attacking = now
            self.raised = False
            self.target = self.rng.choices(TARGETS, TARGET_WEIGHTS)[0]
            return Answer("windup", "", None, SOUNDS["windup"], target=self.target, ms=int(WINDOW_S * 1000))
        return None
