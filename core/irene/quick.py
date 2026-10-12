"""Quick replies: the everyday exchanges - hello, thanks, how are you, what were you
doing, okay, goodbye - answered at once from audio rendered ahead of time in her
live voice. No model call, no synthesis: the answer plays as soon as his words are
known (well under the 600 ms small-talk target, from the end of his speech).

Only a WHOLE message matches ("thanks, Irene!" does; "thanks, and set a timer" goes
to the model). Every intent has several lines, each with the cues that fit it; the
line never repeats the one before, and the cue never repeats the last reply's
(CLAUDE.md: never the same cue twice in a row).

"What are you doing?" is answered from the entrance he last summoned her in -
while it is recent (brain.ENTRANCE_RECENT_S), and otherwise left to the model.

Rendered once per engine and cached in core/assets/quick/<engine>/ (keyed on what
the engine is given, his pronunciation map included, like openers.py).
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf

from .greeting import NAME, band, with_name

from .levels import level_speech
log = logging.getLogger("irene.quick")

ASSETS = Path(__file__).resolve().parents[1] / "assets" / "quick"
FORMAT = 1


@dataclass(frozen=True)
class Intent:
    name: str
    pattern: re.Pattern
    # (line, cues that fit it), in her words
    lines: tuple[tuple[str, tuple[str, ...]], ...]
    # the hour decides which of the lines fit ("morning" lines only in the morning)
    by_band: dict = field(default_factory=dict)
    # the conversation ends with it (goodbye)
    ends: bool = False


def _p(pattern: str) -> re.Pattern:
    return re.compile(rf"^(?:{pattern})$", re.I)


_GREET = r"(?:hi|hello|hey|hiya|heya|yo|howdy|hi there|hello there|hey there|good (?:morning|afternoon|evening|day)|morning|afternoon|evening|hey hey|hello hello|hi again|hey again)"
_HOW = (
    r"(?:how are you(?: doing)?(?: today| tonight)?|how are things|how(?:'s| is) it going|how(?:'s| is) everything|how have you been|how(?:'s| is) (?:your|the) day(?: going| been)?"
    r"|how(?:'s| is) life|how do you do|what'?s up|sup|how are you feeling|you (?:good|okay|alright)|are you (?:good|okay|alright))"
)

INTENTS: tuple[Intent, ...] = (
    Intent(
        "greet_how",
        _p(rf"{_GREET} {_HOW}|{_HOW}"),
        (
            ("I'm great, thanks for asking! How about you?", ("happy", "peace")),
            ("Doing wonderfully, sir. And you?", ("happy", "excitedBounce")),
            ("Never better! What's up with you?", ("peace", "wink")),
            ("Pretty good - better now you're here. You?", ("wink", "happy")),
            (f"All good here, {NAME}! How's your day going?", ("headTilt", "happy")),
        ),
    ),
    Intent(
        "greet",
        _p(_GREET),
        (
            ("Hi, sir! What's up?", ("wave", "happy")),
            ("Hey you! What can I do for you?", ("wave", "excitedBounce")),
            (f"Hello, {NAME}!", ("wave", "happy")),
            ("Hiii! Good to hear you.", ("excitedBounce", "wave")),
            ("Oh, hi! I'm all ears.", ("headTilt", "wave")),
        ),
        by_band={
            "morning": (("Good morning, sir! Sleep well?", ("wave", "stretch")), (f"Morning, {NAME}! Ready for the day?", ("excitedBounce", "wave"))),
            "afternoon": (("Good afternoon, sir! How's the day treating you?", ("wave", "headTilt")), (f"Afternoon, {NAME}! What's the plan?", ("wave", "happy"))),
            "evening": (("Good evening, sir! Long day?", ("wave", "headTilt")), (f"Evening, {NAME}! What can I do?", ("wave", "happy"))),
        },
    ),
    Intent(
        "thanks",
        _p(r"(?:thanks|thank you|thanks a lot|thanks so much|thank you so much|thank you very much|thanks a bunch|cheers|much appreciated|appreciate it|ty|thx|thanks again|thank you again)(?: (?:so much|a lot))?"),
        (
            ("You're welcome, sir!", ("bow", "happy")),
            ("Anytime!", ("wink", "peace")),
            ("My pleasure!", ("bow", "fingerHeart")),
            (f"Happy to help, {NAME}.", ("happy", "salute")),
            ("Of course! That's what I'm here for.", ("proud", "thumbsUp")),
        ),
    ),
    Intent(
        "compliment",
        _p(r"(?:good job|great job|nice job|well done|nice work|great work|good work|you(?:'re| are) (?:the best|amazing|awesome|great|so smart|brilliant|so cool|the greatest)|i love you|love you|good girl|you rock|you did (?:great|good|well))"),
        (
            ("Aww, thank you, sir!", ("embarrassed", "heartHands")),
            ("Stop it, you'll make me blush!", ("embarrassed", "sheepish")),
            ("Hehe, I try!", ("proud", "peace")),
            ("I know, I know. But thank you!", ("proud", "wink")),
        ),
    ),
    Intent(
        "ack",
        _p(r"(?:ok|okay|okey|alright|all right|cool|nice|great|got it|gotcha|sounds good|perfect|awesome|fair enough|i see|makes sense|sure|fine|right|oh okay|oh ok|ah okay|ah i see|oh i see|oh nice|oh cool|very nice|good|good to know|noted|understood)"),
        (
            ("Great!", ("thumbsUp", "happy")),
            ("Mm-hm! Anything else, sir?", ("headTilt", "happy")),
            ("Alright! I'm here if you need me.", ("peace", "salute")),
            ("Nice!", ("happy", "satisfied")),
        ),
    ),
    Intent(
        "sorry",
        _p(r"(?:never ?mind|forget it|sorry|my bad|oops|sorry about that|no worries|don'?t worry about it)"),
        (
            ("No worries!", ("peace", "happy")),
            ("All good, sir.", ("thumbsUp", "happy")),
            ("Don't mention it!", ("wink", "shrug")),
        ),
    ),
    Intent(
        "presence",
        _p(r"(?:are you there|you there|can you hear me|are you listening|hello\?? are you there|you awake|are you awake)"),
        (
            ("Right here, sir!", ("listenClose", "wave")),
            ("I'm here! Loud and clear.", ("listenClose", "thumbsUp")),
            ("Always! What's up?", ("excitedBounce", "wave")),
        ),
    ),
    Intent(
        "back",
        _p(r"(?:i'?m back|i am back|i'?m home|back again|guess who'?s back)"),
        (
            ("Welcome back, sir!", ("wave", "excitedBounce")),
            ("Yay, you're back! I missed you.", ("excitedBounce", "heartHands")),
            (f"Welcome home, {NAME}.", ("bow", "happy")),
        ),
    ),
    Intent(
        "goodbye",
        _p(r"(?:bye|goodbye|good bye|bye bye|see you|see ya|see you later|see you soon|talk (?:to you )?later|later|that'?s all|that'?s all for now|catch you later|i'?m off|i'?m going)"),
        (
            ("Bye for now, sir!", ("wave", "bow")),
            (f"See you soon, {NAME}!", ("wave", "peace")),
            ("Okay! Call me anytime.", ("salute", "wave")),
        ),
        ends=True,
    ),
    Intent(
        "goodnight",
        _p(r"(?:good ?night|night night|nighty night|night|sweet dreams|i'?m going to (?:bed|sleep)|time for bed)"),
        (
            ("Good night, sir! Sleep well.", ("yawn", "wave")),
            (f"Night night, {NAME}. Sweet dreams!", ("heartHands", "wave")),
            ("Sleep tight! I'll be right here.", ("yawn", "bow")),
        ),
        ends=True,
    ),
)

# every way he asks it: a lead-in ("wait", "so", "Irene,"), a swear in the middle
# ("what the f** are you doing"), a tail ("there", "Irene") - live, "Wait what are
# you doing?" missed the whole match, went to the model, and lost the line's cues
_DOING_LEAD = r"(?:(?:wait|so|hey|oh|um+|uh+|okay|ok|and|irene|wow|whoa|huh|erm|hold on|hang on)\W*)*"
_DOING_SWEAR = r"(?: (?:the|in the) (?:f\W*|fuck|frick|heck|hell|world|devil)| on earth| exactly)?"
_DOING_TAIL = r"(?: just now| there| over there| right now| now| irene| sir| in there| before)*"
_DOING = _p(
    _DOING_LEAD
    + r"(?:what" + _DOING_SWEAR + r" (?:are|were|r) you (?:doing|up to|playing|practi[cs]ing)" + _DOING_TAIL
    + r"|what have you been (?:doing|up to)" + _DOING_TAIL
    + r"|what was (?:that|all that)" + _DOING_TAIL
    + r"|what were you doing before)"
)
# what she was doing, in the entrance's own words, and a cue per entrance
DOING_LINES = (
    "I was {doing}!",
    "Oh, {doing}. Want to join next time?",
)
DOING_CUES = {"chess": ("chess", "thinking"), "kendo": ("kendo", "salute"), "cards": ("wink", "proud")}

# he took kamae at her (the HUD's pose watcher): she suits up, and says so - fired
# up, a different line each time. Expressions only: hands would draw over the
# kamae scene's own arms.
KAMAE_LINES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Kamae! Oh, it's on, sir!", ("firedUp", "excited")),
    ("Ooh, keiko time! Show me that men!", ("excited", "firedUp")),
    (f"Hajime! Don't hold back, {NAME}!", ("firedUp", "excited")),
    ("Yosh! I'm fired up - come at me!", ("firedUp", "starryEyed")),
    ("Let's go! Onegaishimasu!", ("excited", "firedUp")),
    ("Ha! Chudan, ready. Your move, sir!", ("firedUp", "excited")),
    ("Kiai! Let's make the dojo shake!", ("firedUp", "starryEyed")),
    ("Oh, you want a match? Let's do this!", ("excited", "firedUp")),
)

_WAKE = re.compile(r"^(?:(?:hey|hi|ok|okay|oh)\s+)?irene\b[\s,!.?]*", re.I)
_TRAIL = re.compile(r"[\s,]+(?:irene|sir|mister tri|then|please|again|too|mate|buddy)$", re.I)


def normalise(text: str) -> str:
    """His words as matched: lower case, no punctuation, no wake phrase ("Hey Irene,
    thanks!" -> "thanks"), no trailing "Irene" or "sir"."""
    said = (text or "").strip()
    rest = _WAKE.sub("", said)
    said = rest if rest.strip() else said
    said = re.sub(r"[^\w' ?]+", " ", said.lower()).replace("?", " ")
    said = re.sub(r"\s+", " ", said).strip()
    for _ in range(3):
        said = _TRAIL.sub("", said).strip()
    return said


# greetings: his name in every line (greeting.with_name), the cached audio included
GREETING_INTENTS = ("greet", "greet_how", "back")


def _line(intent: str, text: str) -> str:
    return with_name(text) if intent in GREETING_INTENTS else text


@dataclass(frozen=True)
class Answer:
    intent: str
    text: str
    cues: tuple[str, ...]
    ends: bool
    audio: np.ndarray | None
    # a sound under the line (sfx name) - the signature entrances' answers
    sfx: str | None = None
    # the cues are the line's own (a signature entrance's answer): every one plays,
    # in order, full body - enforced in code (app.py attached_shows), never swapped
    attached: bool = False


def _all_lines(entrances: list[dict]) -> list[str]:
    lines = [_line(i.name, t) for i in INTENTS for t, _ in i.lines]
    lines += [_line(i.name, t) for i in INTENTS for band_lines in i.by_band.values() for t, _ in band_lines]
    lines += [doing_line(tpl, e) for e in entrances if e.get("doing") for tpl in DOING_LINES]
    lines += [a["line"] for e in entrances for a in e.get("doing_answers", ())]
    lines += [t for t, _ in KAMAE_LINES]
    return list(dict.fromkeys(lines))


def doing_line(template: str, entry: dict) -> str:
    """The activity alone ("unfolding my domain"), not the clause after it ("- the
    whole sky went dark, did you see it?"): whole, it read "...see it?. Want to
    join next time?" live."""
    doing = entry["doing"].split(" - ")[0].strip().rstrip(".!?,")
    return template.format(doing=doing)


def _file(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:12] + ".wav"


class QuickReplies:
    def __init__(self, entrances: list[dict] | None = None, rng: random.Random | None = None):
        self.entrances = {e["name"]: e for e in entrances or []}
        self.audio: dict[str, np.ndarray] = {}
        self.engine: str | None = None
        self.rng = rng or random.Random()
        self._last_line: dict[str, str] = {}
        # per signature entrance: its answers not used yet this round
        self._bags: dict[str, list[dict]] = {}

    def _from_bag(self, name: str, answers: list[dict], avoid: tuple[str, ...] = ()) -> dict:
        """The next of an entrance's answers: shuffled, each used once before a
        reshuffle - and never the one just said first after it. With `avoid` (the
        cues the last reply showed), the next one in the bag whose own cues don't
        include the last of them: its cues always all play, and the reply still
        never opens on the cue the one before it ended on."""
        bag = self._bags.get(name)
        if not bag:
            bag = list(answers)
            self.rng.shuffle(bag)
            if len(bag) > 1 and bag[-1]["line"] == self._last_line.get("doing"):
                bag[0], bag[-1] = bag[-1], bag[0]
            self._bags[name] = bag
        last = avoid[-1] if avoid else None
        for i in range(len(bag) - 1, -1, -1):
            if last not in bag[i]["cues"]:
                return bag.pop(i)
        return bag.pop()

    @property
    def ready(self) -> bool:
        return bool(self.audio)

    def lines(self) -> list[str]:
        return _all_lines(list(self.entrances.values()))

    def _cache_key(self, voice) -> str:
        spoken = [voice.spoken(t) if hasattr(voice, "spoken") else t for t in self.lines()]
        return hashlib.sha1(json.dumps({"engine": voice.name, "lines": spoken, "format": FORMAT}).encode()).hexdigest()[:12]

    def load_or_render(self, voice) -> None:
        """Every line in `voice`'s engine: from the cache, or rendered now (about a
        second a line on Turbo, once)."""
        folder = ASSETS / voice.name
        stamp = folder / "key.txt"
        key = self._cache_key(voice)
        audio: dict[str, np.ndarray] = {}
        cached = stamp.exists() and stamp.read_text(encoding="utf-8") == key
        folder.mkdir(parents=True, exist_ok=True)
        rendered = 0
        for text in self.lines():
            path = folder / _file(text)
            if cached and path.exists():
                # levelled as it loads (levels.py; idempotent): no re-render needed
                audio[text] = level_speech(sf.read(path, dtype="float32")[0])
                continue
            audio[text] = voice.all(text)
            sf.write(path, audio[text], 24000, subtype="PCM_16")
            rendered += 1
        stamp.write_text(key, encoding="utf-8")
        self.audio, self.engine = audio, voice.name
        log.info("quick replies ready: %d lines in %s (%d rendered now)", len(audio), voice.name, rendered)

    def kamae(self, avoid: tuple[str, ...] = ()) -> Answer:
        """Her line as she suits up: never the one she said last time."""
        fresh = [o for o in KAMAE_LINES if o[0] != self._last_line.get("kamae")] or list(KAMAE_LINES)
        line, fits = self.rng.choice(fresh)
        self._last_line["kamae"] = line
        cues = tuple(c for c in fits if c not in avoid) or ("firedUp",)
        return Answer("kamae", line, cues, False, self.audio.get(line))

    def match(self, text: str) -> str | None:
        """The intent `text` is, whole - or None."""
        said = normalise(text)
        if not said:
            return None
        if _DOING.match(said):
            return "doing"
        return next((i.name for i in INTENTS if i.pattern.match(said)), None)

    def answer(self, text: str, hour: int, entrance: str | None = None, avoid: tuple[str, ...] = ()) -> Answer | None:
        """Her quick answer to `text`, or None for the model. `entrance`: the one
        she was in, if still recent; `avoid`: the cues the last reply showed."""
        intent = self.match(text)
        if intent is None:
            return None
        if intent == "doing":
            entry = self.entrances.get(entrance or "")
            if entry is None or not entry.get("doing"):
                return None
            if entry.get("doing_answers"):
                # a signature entrance: its own lines, each with its cues and sound,
                # all of them used before any comes round again
                # - and the next one in the bag that doesn't OPEN on the cue the last
                # reply showed, so its own cues all play without repeating that one
                pick = self._from_bag(entry["name"], entry["doing_answers"], avoid=avoid)
                self._last_line[intent] = pick["line"]
                # its own cues, every one of them, in order: never filtered, never
                # swapped (Round 10: they were, and he saw almost nothing)
                return Answer(intent, pick["line"], tuple(pick["cues"]), False, self.audio.get(pick["line"]), pick.get("sfx"), attached=True)
            options = [(doing_line(t, entry), DOING_CUES.get(entry["name"], ("happy", "proud", "giggle"))) for t in DOING_LINES]
            ends = False
        else:
            spec = next(i for i in INTENTS if i.name == intent)
            options = list(spec.by_band.get(band(hour), ())) + list(spec.lines) if spec.by_band else list(spec.lines)
            if spec.by_band and self.rng.random() < 0.6:
                # most "good morning"s get a morning line back
                options = list(spec.by_band.get(band(hour), ())) or options
            ends = spec.ends
        options = [(_line(intent, t), fits) for t, fits in options]
        fresh = [o for o in options if o[0] != self._last_line.get(intent)] or options
        line, fits = self.rng.choice(fresh)
        self._last_line[intent] = line
        cues = tuple(c for c in fits if c not in avoid) or tuple(c for c in ("happy", "peace", "wink", "headTilt") if c not in avoid)
        return Answer(intent, line, cues, ends, self.audio.get(line))
