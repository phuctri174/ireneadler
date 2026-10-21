# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""Study mode: "Irene, go study the Sicilian" - she hits the books, and he hits her.

A comedy bit, built on real parts. She puts her head down over a notepad and a
progress bar fills, slowly, while she mutters. Every time he swings at her (a strike
EVENT from the HUD - hud/src/tracking/strikeEvent.ts, binary: a swing happened) she
complains, and LEARNS FASTER: the bar jumps and its rate goes up. That is the gag,
so the hits are never cosmetic - progress is this module's number, nobody else's.

Her reaction escalates with the count, comic throughout, never really distressed:

  hits 1-2   "ow"         startled - a bonk, stars round her head
  hits 3-4   "indignant"  offended - "I AM studying."
  hits 5+    "uncle"      mock tears and a white flag - "okay okay okay okay"

When the bar fills she says what she learned, and if a feature covers it she
challenges him to it: a chess opening goes straight into a game (his colour first,
as always), with her book pinned to that defence (chess_book.DEFENCES) so she plays
what she just studied. Anything else she just summarises. Hit her TOO_FAST times or
more and she finishes too fast and gets a detail wrong - and catches it, out loud.

What she learned comes from the language model (notes_prompt / parse_notes), written
while the bar fills; anything it gets wrong in the shape is dropped for plain
fallbacks. For a book defence the true first moves are put in front of it.
"""
from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass, field

from . import chess_book

# no hits at all: the bar fills in this long
BASE_S = 90.0
# each hit: the bar jumps this much, and fills this much faster from then on
HIT_JUMP = 0.06
SPEEDUP = 0.25
# hits closer together than this are one hit (the detector rests too, 0.4 s)
HIT_GAP_S = 0.8
# this many hits or more by the end: she finishes too fast, and fumbles a detail
TOO_FAST = 8
# a mutter now and then while she works (s), never right after a hit, and never the
# moment she stops talking
MUTTER_EVERY = (13.0, 21.0)
MUTTER_QUIET_AFTER_HIT_S = 5.0
MUTTER_QUIET_AFTER_SPEECH_S = 4.0
# never longer than this, whatever happens
MAX_S = 10 * 60.0
# the hotkey (Ctrl+Alt+Shift+S) studies the last subject - or this, the first time
HOTKEY_SUBJECT = "the Sicilian"

_LEAD = r"^\W*(?:(?:hey\s+|okay\s+|ok\s+|alright\s+)?irene\W+)?(?:(?:okay|ok|alright|right|now)\W+)?"
# ("you learn X", "let's learn X": live, 2026-10-18)
_POLITE = r"(?:(?:can|could|would|will)\s+you\s+|why\s+don'?t\s+you\s+|please\s+|let'?s\s+|you\s+)?"
_VERB = r"(?:learn|study|read\s+up\s+on|swot\s+up\s+on|brush\s+up\s+on|bone\s+up\s+on|cram)"
_START_GO = re.compile(_LEAD + _POLITE + r"go\s+(?:and\s+)?" + _VERB + r"\s+(?P<subject>.+)$", re.I)
# without "go", only when she is named: "Irene, study the Sicilian"
_START_NAMED = re.compile(r"^\W*(?:hey\s+)?irene\W+" + _POLITE + _VERB + r"\s+(?P<subject>.+)$", re.I)
# told she should: "I think you should go learn the Sicilian", "I want you to study X"
_START_SUGGEST = re.compile(
    r"^\W*(?:(?:hey\s+)?irene\W+)?(?:i\s+think\s+|maybe\s+|honestly\s+)?(?:you\s+(?:should|need\s+to|have\s+to|gotta|ought\s+to|must)|i\s+(?:want|need)\s+you\s+to)"
    r"\s+(?:go\s+(?:and\s+)?)?" + _VERB + r"\s+(?P<subject>.+)$",
    re.I,
)
# a bare order, nothing else said: "Learn Sicilian", "study quantum entanglement" -
# a short subject, no clause after it ("study the Sicilian, they said, it's easy" is talk)
_START_BARE = re.compile(_LEAD + _POLITE + _VERB + r"\s+(?P<subject>[^,;]{1,60}?)[.!]?$", re.I)
# ("learn about black holes", "learn how black holes form" are orders: any topic)
_BARE_NOT = re.compile(
    r"^(?:(?:to|what|why|when|where|from|that|it|this|more|everything|nothing|something|anything|hard|a\s+lot|too|so|very|fast|slow\w*|quick\w*|well|badly)\b"
    r"|how\W*$|about\W*$|about\s+(?:it|this|that|them|him|her|me|us)\b)",
    re.I,
)
# a subject that is really him leaving, or not a subject at all
_NOT_A_SUBJECT = re.compile(r"^(?:for\b|with\b|now\b|later\b|tonight\b|it\b|that\b|this\b|more\b|up\b|hard\b|some\s+more\b|to\s+\w+\s*$)", re.I)
_TRAILING = re.compile(r"(?:\s*[,.!?]+\s*|\s+(?:please|for\s+me|for\s+a\s+bit|for\s+a\s+while|real\s+quick|right\s+now|now|then|okay|ok))+$", re.I)
_STOP = re.compile(
    r"^\W*(?:(?:hey\s+)?irene\W+)?(?:(?:okay|ok|alright|right)\W+)?(?:irene\W+)?"
    r"(?:stop(?:\s+(?:now|please|studying|it|there|irene))*\W*$|(?:stop|quit|enough)\s+(?:studying|the\s+studying|reading)|"
    r"that'?s\s+enough|enough|you'?re\s+done|never\s*mind|forget\s+it|put\s+(?:the\s+)?(?:book|books|notes)\s+(?:down|away))",
    re.I,
)

# a chess opening she has a book line for: the name chess_book.DEFENCES uses
_DEFENCE_NAMES = {
    "Sicilian": re.compile(r"\bsicilian\b", re.I),
    "Caro-Kann": re.compile(r"\bcaro[\s-]*kann\b", re.I),
    "Nimzowitsch Defence": re.compile(r"\bnimzowitsch\b", re.I),
}
_CHESS = re.compile(
    r"\bchess\b|\bopenings?\b|\bgambit\b|\bdefen[cs]e\b|\bendgames?\b|\bnimzo|\bruy\s+lopez\b|\bitalian\s+game\b|\blondon\s+system\b"
    r"|\bqueen'?s\s+gambit\b|\bking'?s\s+indian\b|\bfrench\s+defen|\bscandinavian\b|\bpirc\b|\bdutch\s+defen|\bgr[uü]nfeld\b|\bcheckmates?\b",
    re.I,
)

LINES: dict[str, tuple[str, ...]] = {
    "start": (
        "Studying {subject}. Head down - do not disturb.",
        "{Subject}? Okay. Hitting the books. Quiet, please.",
        "Right - {subject}. Give me a minute, I'm learning.",
        "{Subject}. On it. Nobody bother me.",
    ),
    "ow": ("Ow!", "Ow! Hey!", "Ouch! I'm reading!", "Ow - what was that for?", "Hey! Ow!"),
    "indignant": ("I AM studying!", "Excuse me - I am STUDYING.", "Do you mind? I AM studying!", "I'm literally learning right now!", "Hey! Studying! Me! Now!"),
    "uncle": ("Okay okay okay okay!", "Okay! Okay! I'm going faster!", "Okay okay okay - I'm learning, I'm learning!", "Waah - okay okay okay okay!", "Okay okay, maximum speed, okay!"),
    "mutter": (
        "Hmm. {subject}... okay...",
        "Wait, so that means... oh. Oh, that's clever.",
        "Hm. Hmm. Hmmm.",
        "Okay... and then... right.",
        "Page forty... no, forty-one.",
    ),
    "stop": ("Fine - I got about {pct} percent through {subject}.", "Okay, books closed. {Pct} percent of {subject}, for the record."),
    "done_plain": ("Done! {subject} - got it.",),
}
CUES = {
    # faces only while the book is open: a gesture's hands would draw over it
    "start": ("focused", "firedUp"),
    "ow": ("bonked", "surprised"),
    "indignant": ("indignant", "sulking"),
    "uncle": ("surrender", "dizzy"),
    "mutter": ("focused", "curious"),
    "done": ("proud", "eureka"),
    "done_fast": ("sheepish", "oops"),
    "stop": ("shrug", "sheepish"),
    "challenge": ("firedUp", "smug"),
}
SOUNDS = {"ow": ("bonk",), "indignant": ("bonk",), "uncle": ("bonk",)}


def tier(hits: int) -> str:
    """The reaction for the nth hit."""
    return "ow" if hits <= 2 else "indignant" if hits <= 4 else "uncle"


def _clean_subject(raw: str) -> str | None:
    subject = _TRAILING.sub("", raw.strip()).strip(" ,.!?\"'")
    # "learn ABOUT the French revolution", "read up ON it": the subject is what follows
    subject = re.sub(r"^(?:about|on|up\s+on|all\s+about)\s+", "", subject, flags=re.I)
    if not subject or _NOT_A_SUBJECT.search(subject) or len(subject) > 80:
        return None
    return subject


def command(text: str, active: bool) -> tuple[str, str | None] | None:
    """His words as study mode: ("start", subject), ("stop", None) while it is on, or None."""
    said = (text or "").strip()
    if active and _STOP.search(said):
        return ("stop", None)
    m = _START_GO.search(said) or _START_NAMED.search(said) or _START_SUGGEST.search(said)
    if m:
        subject = _clean_subject(m.group("subject"))
        if subject:
            return ("start", subject)
    m = _START_BARE.search(said)
    if m and len(m.group("subject").split()) <= 5 and not _BARE_NOT.search(m.group("subject")):
        subject = _clean_subject(m.group("subject"))
        if subject:
            return ("start", subject)
    return None


def defence(subject: str) -> str | None:
    """The book defence this subject is (chess_book.DEFENCES), or None."""
    return next((name for name, pat in _DEFENCE_NAMES.items() if pat.search(subject)), None)


def is_chess(subject: str) -> bool:
    return defence(subject) is not None or bool(_CHESS.search(subject))


def opening_moves(name: str) -> str:
    """The true first moves of a book defence: "1.e4 c5"."""
    first = chess_book.DEFENCES[name][0].split()
    return f"1.{first[0]} {first[1]}"


def notes_prompt(subject: str) -> str:
    facts = ""
    name = defence(subject)
    if name:
        facts = f"\nA fact to build on: the {name} begins {opening_moves(name)}.\n"
    return (
        f"You are Irene, a warm, playful assistant. You have just spent a few minutes studying {subject}.{facts}\n"
        "Write exactly these lines, plain spoken English, no markdown, no lists, no emoji:\n"
        "MUTTER: a short thing you mumble to yourself while studying it, under nine words, specific to it\n"
        "MUTTER: another\nMUTTER: another\nMUTTER: another\nMUTTER: another\n"
        "SUMMARY: two or three short sentences telling him what you learned: the core idea, correct, in your own voice\n"
        "WRONG: one short sentence stating one detail of it slightly wrong, as if you rushed\n"
        "RIGHT: that same sentence, corrected\n"
    )


@dataclass
class Notes:
    mutters: list[str] = field(default_factory=list)
    summary: str = ""
    wrong: str = ""
    right: str = ""


def _plain(line: str) -> str:
    return re.sub(r"[*_#`]+", "", line).strip().strip('"').strip()


def parse_notes(raw: str) -> Notes:
    """The model's lines, by their label; anything off-shape is dropped (fallbacks)."""
    notes = Notes()
    for line in (raw or "").splitlines():
        m = re.match(r"^\W*(MUTTER|SUMMARY|WRONG|RIGHT)\s*:\s*(.+)$", line.strip(), re.I)
        if not m:
            continue
        label, text = m.group(1).upper(), _plain(m.group(2))
        if not text:
            continue
        if label == "MUTTER" and len(text.split()) <= 12:
            notes.mutters.append(text)
        elif label == "SUMMARY" and not notes.summary and len(text.split()) <= 70:
            notes.summary = text
        elif label == "WRONG" and not notes.wrong and len(text.split()) <= 30:
            notes.wrong = text
        elif label == "RIGHT" and not notes.right and len(text.split()) <= 30:
            notes.right = text
    if notes.wrong and notes.right and notes.wrong.lower().rstrip(".!") == notes.right.lower().rstrip(".!"):
        notes.wrong = notes.right = ""
    return notes


@dataclass
class Answer:
    """What she does: the HUD's study action, her line, its face, the sounds."""

    action: str  # start | hit | end
    line: str
    cue: str | None
    sounds: tuple[str, ...] = ()
    tier: str | None = None
    hits: int = 0
    progress: float = 0.0
    rate: float = 0.0


@dataclass
class Finish:
    line: str
    cue: str
    # said as the chess board goes up (empty when there is no game)
    chess: bool
    defence: str | None
    fumbled: bool
    challenge: str = ""


@dataclass
class Study:
    rng: random.Random = field(default_factory=random.Random)
    active: bool = False
    subject: str = ""
    started: float = 0.0
    hits: int = 0
    last_hit: float = -1e9
    # progress is p0 at time t0, rising at `rate` per second
    p0: float = 0.0
    t0: float = 0.0
    rate: float = 1.0 / BASE_S
    notes: Notes | None = None
    next_mutter: float = 0.0
    _last: dict[str, str] = field(default_factory=dict)
    _last_cue: str | None = None

    def _line(self, kind: str, **fill) -> str:
        pool = [line for line in LINES[kind] if line != self._last.get(kind)] or list(LINES[kind])
        line = self.rng.choice(pool)
        self._last[kind] = line
        if fill:
            fill = {**fill, **{k.capitalize(): (str(v)[:1].upper() + str(v)[1:]) for k, v in fill.items()}}
            line = line.format(**fill)
        return line

    def _cue(self, kind: str) -> str:
        """One of that moment's faces - never the one she just wore."""
        pool = [c for c in CUES[kind] if c != self._last_cue] or list(CUES[kind])
        cue = self.rng.choice(pool)
        self._last_cue = cue
        return cue

    def progress(self, now: float | None = None) -> float:
        now = time.monotonic() if now is None else now
        return min(1.0, self.p0 + self.rate * max(0.0, now - self.t0))

    def finished(self, now: float | None = None) -> bool:
        return self.active and self.progress(now) >= 1.0

    def expired(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        return self.active and now - self.started > MAX_S

    def start(self, subject: str, now: float | None = None) -> Answer:
        now = time.monotonic() if now is None else now
        self.active, self.subject, self.started = True, subject, now
        self.hits, self.last_hit, self.notes = 0, -1e9, None
        self.p0, self.t0, self.rate = 0.0, now, 1.0 / BASE_S
        self.next_mutter = now + self.rng.uniform(*MUTTER_EVERY)
        return Answer("start", self._line("start", subject=subject), self._cue("start"), progress=0.0, rate=self.rate)

    def hit(self, now: float | None = None) -> Answer | None:
        """He swung at her (a strike event): the bar jumps, she learns faster, she
        complains - or None (not studying, done already, or the same swing twice)."""
        now = time.monotonic() if now is None else now
        if not self.active or self.finished(now) or now - self.last_hit < HIT_GAP_S:
            return None
        self.last_hit = now
        self.hits += 1
        self.p0 = min(1.0, self.progress(now) + HIT_JUMP)
        self.t0 = now
        self.rate = (1.0 + SPEEDUP * self.hits) / BASE_S
        # a mutter never lands right on top of a complaint
        self.next_mutter = max(self.next_mutter, now + MUTTER_QUIET_AFTER_HIT_S)
        kind = tier(self.hits)
        return Answer("hit", self._line(kind), self._cue(kind), SOUNDS[kind], kind, self.hits, self.p0, self.rate)

    def mutter(self, now: float | None = None) -> str | None:
        """A line to mumble now, if it is time for one."""
        now = time.monotonic() if now is None else now
        if not self.active or self.finished(now) or now < self.next_mutter:
            return None
        self.next_mutter = now + self.rng.uniform(*MUTTER_EVERY)
        own = [m for m in (self.notes.mutters if self.notes else []) if m != self._last.get("mutter")]
        if own:
            line = self.rng.choice(own)
            self._last["mutter"] = line
            return line
        return self._line("mutter", subject=self.subject)

    def talking(self, now: float | None = None) -> None:
        """She is saying something: no mutter until a moment after she stops."""
        now = time.monotonic() if now is None else now
        self.next_mutter = max(self.next_mutter, now + MUTTER_QUIET_AFTER_SPEECH_S)

    def mutter_cue(self) -> str:
        return self._cue("mutter")

    def challenge_cue(self) -> str:
        return self._cue("challenge")

    def too_fast(self) -> bool:
        return self.hits >= TOO_FAST

    def finish(self) -> "Finish":
        """What she says as the bar fills - and study mode ends. The caller starts the
        chess game when the subject is chess (pinned to `defence` when it is a book one)."""
        self.active = False
        notes = self.notes or Notes()
        name = defence(self.subject)
        chess = is_chess(self.subject)
        parts: list[str] = []
        wrong, right = notes.wrong, notes.right
        if name:
            # a book defence: the fumble is built from the real lines, never the model's -
            # she mixes it up with another defence, then gets it right
            other = self.rng.choice(sorted(n for n in chess_book.DEFENCES if n != name))
            wrong = f"The {name} starts {opening_moves(other)}."
            right = f"That's the {other}. The {name} is {opening_moves(name)}."
        fumble = self.too_fast() and wrong and right
        if fumble:
            parts += ["Done - way too fast.", wrong, "Wait. No.", right, "That's what I get for being rushed."]
        elif notes.summary:
            parts += [f"Done! Here's what I learned about {self.subject}.", notes.summary]
        else:
            parts.append(self._line("done_plain", subject=self.subject))
        challenge = ""
        if name:
            challenge = f"Now use it on me. White or black? Take white and I'll play the {name} against you - take black and you show me yours."
        elif chess:
            challenge = "Let's see if it stuck. White or black?"
        cue = self._cue("done_fast" if fumble else "done")
        return Finish(" ".join(p for p in parts if p), cue, chess, name, bool(fumble), challenge)

    def stop(self, now: float | None = None) -> Answer:
        pct = int(round(self.progress(now) * 100))
        self.active = False
        return Answer("end", self._line("stop", pct=pct, subject=self.subject), self._cue("stop"), progress=pct / 100)
