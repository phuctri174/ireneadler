# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""Her memory, kept honest: what she says about him, his people or his past is
said only when a memory she actually retrieved - or this conversation - says it.

The model fills gaps from its priors. Asked "what did I tell you about my sister?"
with only a brother on file, gemma invented the sister (2 of 2 runs), and a memory
that fabricates relationships is worse than none: he can't tell which recollections
are real. Prompting ("never an invented detail") did not stop it, so this is code,
like grounding.py for research answers:

  MemoryGuard.check()  each sentence of a reply, before it is spoken. In an answer
                       about the past (strict) every name, relation ("your sister"),
                       number and day in it must appear in a retrieved row or in
                       this conversation; with nothing retrieved, nothing but "I
                       don't remember" is said. In any other reply, a sentence that
                       claims something about his people or what he told her
                       ("your sister", "you mentioned...") is held to the same test.
                       A sentence that fails is never spoken.
  Source               what each kept sentence came from - so "where did you get
                       that?" is answered from the record (where_from()), never by
                       the model's guess.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from .recall import Item, _when_label, fold
from .recall import words as recall_words

log = logging.getLogger("irene.provenance")

ROOT = Path(__file__).resolve().parents[2]

# his people: a relation she names must be one a memory names
RELATIONS = (
    "sister", "brother", "sibling", "mom", "mum", "mother", "dad", "father", "parent", "wife", "husband", "girlfriend",
    "boyfriend", "partner", "fiance", "fiancee", "son", "daughter", "kid", "child", "children", "baby", "cousin", "uncle",
    "aunt", "grandma", "grandmother", "grandpa", "grandfather", "gran", "niece", "nephew", "roommate", "flatmate",
    "colleague", "coworker", "classmate", "boss", "manager", "teacher", "sensei", "coach", "friend", "neighbour",
    "neighbor", "landlord", "ex", "dog", "cat", "pet",
)
_REL = r"(?:" + "|".join(RELATIONS) + r")(?:s|es)?"
_RELATION_ANY = re.compile(rf"\b({_REL})\b", re.I)
# "your sister", "your older sister", "your friend Minh's" - but not "I'm your friend"
_YOURS = re.compile(rf"\byour\s+(?:[\w'-]+\s+){{0,2}}?({_REL})\b", re.I)
_SHE_IS = re.compile(r"\bi(?:'m|’m| am)(?:\s+\w+){0,2}\s*$", re.I)


class _Yours:
    """His people she names ("your sister"), not what she is to him ("I'm your friend")."""

    @staticmethod
    def finditer(text: str):
        return [m for m in _YOURS.finditer(text) if not _SHE_IS.search(text[: m.start()])]

    @classmethod
    def search(cls, text: str):
        found = cls.finditer(text)
        return found[0] if found else None


_RELATION_YOURS = _Yours
# she claims what he told her, or what happened before
_PAST_CLAIM = re.compile(
    r"\byou(?:'ve| have)?\s+(?:told|mentioned|said|shared|talked about|brought up)\b|\b(?:last|that) time (?:we|you)\b"
    r"|\bwe (?:talked|spoke|chatted|discussed)\b|\bi remember (?:you|when|that)\b|\byou (?:were|went|had|did) .{0,30}\b(?:last|yesterday|ago)\b",
    re.I,
)
_HONORIFIC_END = re.compile(r"\b(?:mr|mrs|ms|dr|st|prof)\.$", re.I)
_EARLIER = re.compile(
    r"\byou(?:'ve| have)?\s+(?:told|mentioned|shared|brought up)\b|\b(?:last|that) time\b|\bwe (?:talked|spoke|chatted|discussed)\b"
    r"|\bi remember (?:you|when|that)\b|\bthe other day\b",
    re.I,
)
# she says she doesn't know: always hers to say
_REFUSAL = re.compile(
    r"\b(?:don'?t|do not|can'?t|cannot) (?:remember|recall|know|find|see)\b|\bdidn'?t (?:tell|mention|say)\b|\bnot sure\b"
    r"|\bno (?:memory|record|note|idea)\b|\bhaven'?t (?:told|mentioned|said|heard)\b|\bnever (?:told|mentioned|said)\b"
    r"|\bnothing (?:about|on|from|kept)\b|\bnot (?:something|anything) you(?:'ve| have)? (?:told|mentioned)\b"
    r"|\b(?:you'?ll|you will|you'd) have to (?:tell|fill) me\b|\bi(?:'m| am) drawing a blank\b|\bi don'?t have (?:that|anything)\b"
    # "No, you didn't! Tell me!" (live eval: asked whether he had told her)
    r"|^\W*(?:no|nope|nah)\W+you (?:didn'?t|never|haven'?t)\b|\byou (?:never|didn'?t|haven'?t) (?:told|tell|mentioned|mention|said|say)\b",
    re.I,
)
_DIGITS = re.compile(r"\d+(?:[.,:]\d+)*")
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december")
_DATES = re.compile(r"\b(" + "|".join(_WEEKDAYS + _MONTHS[:4] + _MONTHS[5:]) + r")\b", re.I)  # "may" is a verb too
# a name: a capitalised word that isn't opening its sentence (Hanoi, Trác, Le Guin)
_WORD = re.compile(r"[^\W\d_][\w'’-]*", re.U)
# capitalised and common: never a name she could have invented
_COMMON = set(
    "i i'm i'd i've i'll irene ok okay oh ooh hmm hm mm ah aha wow yes yeah yep no nope hey hi god mister mr ms mrs "
    "english vietnamese japanese french spanish chinese german today yesterday tomorrow".split()
)


def _known_words() -> set[str]:
    """Words she may always say: his name and the others she is taught to pronounce
    (his file, else the example a fresh checkout has)."""
    out: set[str] = set()
    for name in ("pronunciation.yaml", "pronunciation.example.yaml"):
        try:
            raw = yaml.safe_load((ROOT / "config" / name).read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        out |= {fold(str(k)) for k in raw if isinstance(k, str)}
    return out


_KNOWN = _known_words()


def _norm(word: str) -> str:
    return fold(word).strip("'’-").removesuffix("'s").removesuffix("’s")


def _singular(word: str) -> str:
    w = fold(word)
    for end in ("es", "s"):
        if w.endswith(end) and w[: -len(end)] in RELATIONS:
            return w[: -len(end)]
    return w


def names(sentence: str) -> list[str]:
    """The capitalised words in `sentence` that aren't opening it: names, places,
    titles - each folded ("Trác" is "trac")."""
    out = []
    for m in _WORD.finditer(sentence):
        word = m.group(0)
        if not word[0].isupper():
            continue
        before = sentence[: m.start()].rstrip()
        if not before or before[-1] in ".!?:;\"“'‘—–-(…":
            continue  # a sentence (or a quote) opens with it
        n = _norm(word)
        if n and n not in _COMMON and n not in _KNOWN and n not in _WEEKDAYS and n not in _MONTHS:
            out.append(n)
    return out


# how her sentences open: never a name, whatever follows ("Right, sorry.", "Sure.")
_OPENERS = set(
    "right sorry sure so well yes yeah yep no nope okay ok oh ooh hmm hm mm ah aha wow hey hi then and but also maybe "
    "probably actually honestly exactly definitely totally great good nice cool fine true there here that this it it's "
    "its that's there's here's what which who when where why how nothing something everything anyway alright again "
    "absolutely indeed perfect done noted got gotcha lol haha".split()
)
# a word opening the sentence the way a name does: "Quang, then.", "Linh.", "Hà is..."
_LEADING_NAME = re.compile(r"^\W*([^\W\d_][\w'’-]*)(?=\s*[,.!?…]|\s+(?:is|was|'s|’s)\b)", re.U)


def leading_name(sentence: str) -> str:
    """The sentence's first word, folded, when it stands like a name ("Quang, then.")."""
    m = _LEADING_NAME.match(sentence or "")
    if not m or not m.group(1)[0].isupper():
        return ""
    n = _norm(m.group(1))
    if n in _OPENERS or n in _COMMON or n in _KNOWN or n in _STOPWORDS or n in _WEEKDAYS or n in _MONTHS:
        return ""
    return n


def refuses(sentence: str) -> bool:
    # gemma writes "don’t" as often as "don't"
    return bool(_REFUSAL.search((sentence or "").replace("’", "'")))


@dataclass
class Source:
    """What one sentence she said came from."""

    said: str
    item: Item | None = None  # the memory it came from
    session: str = ""  # or his words earlier in this conversation


@dataclass
class Evidence:
    """Everything she may draw on: the rows retrieved for this message and this
    conversation so far - as a bag of folded words, and each piece for provenance."""

    items: list[Item] = field(default_factory=list)
    session: list[str] = field(default_factory=list)
    now: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self._item_words = [self._words(f"{i.about} {i.text}") for i in self.items]
        self._session_words = [self._words(s) for s in self.session]
        # when each memory was kept may be said back ("on Monday", "the 12th") - but
        # it is no evidence for anything else: "your birthday is Tuesday, October 8th"
        # was once made of an unrelated memory's date and its "8 days ago"
        self._item_dates = [self._words(self._dated(i)) for i in self.items]
        # what she has, dates of memories aside (see dated())
        self.words = set().union(*self._item_words, *self._session_words) if (self.items or self.session) else set()

    def dated(self, sentence: str, word: str) -> bool:
        """`word` (a day, a month, a day of the month) is when a memory the sentence
        is about was kept: "you told me about Trác on Monday" may say the Monday;
        "your birthday is Tuesday, October 6th" may not borrow an unrelated memory's
        date (live eval, twice)."""
        mine = self._words(sentence) - _STOPWORDS - set(_WEEKDAYS) - set(_MONTHS) - set(_DIGITS.findall(sentence))
        return any(word in dates and mine & words for dates, words in zip(self._item_dates, self._item_words))

    def _dated(self, item: Item) -> str:
        then = datetime.fromtimestamp(item.at)
        return f"{then.strftime('%A %B')} {then.day}"

    @staticmethod
    def _words(text: str) -> set[str]:
        out = {_singular(_norm(w)) for w in _WORD.findall(text)}
        return out | set(_DIGITS.findall(text))

    def empty(self) -> bool:
        return not self.items and not self.session

    def best(self, sentence: str, enough: int = 2) -> Source | None:
        """The row (or his message) this sentence shares most with - a name counts
        twice - or None when it shares less than `enough`."""
        # days and months are when, not what: they never make a sentence about a memory
        mine = self._words(sentence) - _STOPWORDS - set(_WEEKDAYS) - set(_MONTHS)
        # any capitalised word, opening the sentence or not ("Takahashi, sir.")
        named = {_norm(w) for w in _WORD.findall(sentence) if w[0].isupper()} - _STOPWORDS - _COMMON - set(_WEEKDAYS) - set(_MONTHS)
        if enough == 2 and len(mine) <= 2:
            enough = 1  # "It covered eigenvalues on Monday.": one word of substance, and it's there

        def score(w: set[str]) -> int:
            return len(mine & w) + len(named & w)

        top = max(((score(w), k) for k, w in enumerate(self._item_words)), default=(0, -1))
        if top[0] >= enough:
            return Source(sentence, self.items[top[1]])
        top = max(((score(w), k) for k, w in enumerate(self._session_words)), default=(0, -1))
        if top[0] >= enough:
            return Source(sentence, session=self.session[top[1]])
        return None


_STOPWORDS = set(
    "a an the and or but if of to in on at for with about from by as is are was were be been am i me my you your we our "
    "he she it they them this that these those what which who when where why how do did does have has had not no yes so "
    "just than then there here said told say mentioned really very".split()
)


class MemoryGuard:
    """Checks each sentence of one reply against what she has to go on."""

    def __init__(self, evidence: Evidence, strict: bool, asked: str = "") -> None:
        self.evidence = evidence
        # an answer about the past: everything in it is checked; otherwise only her
        # claims about his people and what he told her
        self.strict = strict
        # his message: its numbers and days may be repeated back ("on Monday") - its
        # names and relations may not ("my sister" in the question is not a sister on file)
        self._asked = Evidence._words(asked) if asked else set()
        # what his question is about, in words of substance ("birthday"; nothing at all
        # for "what did we talk about last week?" - then any memory is about it)
        self._topic = {_singular(w) for w in recall_words(asked)} - set(_WEEKDAYS) - set(_MONTHS) - {"week", "month", "day", "ago", "recently", "lately"}
        self.dropped: list[str] = []
        self.sources: list[Source] = []

    def missing(self, sentence: str) -> list[str]:
        """What `sentence` asserts that nothing she has says."""
        have = self.evidence.words
        if self.strict:
            relations = [_singular(m.group(1)) for m in _RELATION_ANY.finditer(sentence)]
            wanted = relations + names(sentence) + [n for n in [leading_name(sentence)] if n]
            dates = [*(_DIGITS.findall(sentence)), *(fold(m.group(1)) for m in _DATES.finditer(sentence))]
            gone = [w for w in wanted if w not in have]
            gone += [d for d in dates if d not in have and d not in self._asked and not self.evidence.dated(sentence, d)]
            return gone
        relations = [_singular(m.group(1)) for m in _RELATION_YOURS.finditer(sentence)]
        claims = bool(relations) or bool(_PAST_CLAIM.search(sentence))
        if not claims:
            return []
        wanted = relations + names(sentence)
        # outside a question about the past, his message counts: he just told her
        return [w for w in wanted if w not in have and w not in self._asked]

    def _about_question(self, source: Source) -> bool:
        if not self._topic:
            return True
        if source.item is not None:
            return bool(self._topic & Evidence._words(f"{source.item.about} {source.item.text}"))
        return bool(self._topic & Evidence._words(source.session))

    def unsupported(self, args: dict) -> list[str]:
        """In an answer about the past, what a tool call's arguments carry that no
        memory does (live eval: "when is my cousin's wedding?" -> get_time until
        2026-11-23, a date nothing on file names)."""
        if not self.strict:
            return []
        values = " ".join(str(v) for v in args.values() if isinstance(v, (str, int, float)))
        return self.missing(values) if values.strip() else []

    def early_ok(self, clause: str) -> bool:
        """Whether her first clause may play before its sentence is complete: never in
        an answer about the past, nor a clause about his people - the rest of the
        sentence decides whether any of it is said."""
        return not self.strict and not _RELATION_YOURS.search(clause) and not _PAST_CLAIM.search(clause)

    def check(self, sentence: str) -> str | None:
        """The sentence, or None when she would be making it up."""
        said = (sentence or "").strip()
        # the patterns are written with a straight apostrophe; gemma uses both
        text = said.replace("’", "'")
        if not text or refuses(text):
            return said
        if self.strict and _HONORIFIC_END.search(text):
            # "It's Mr." - a name cut in two at its title's full stop (live: "It's Mr."
            # then the made-up name as a sentence of its own): the half is never said
            return self._drop(said, "a name cut off after its title")
        if self.strict and self.evidence.empty():
            # nothing retrieved, nothing said this session: there is nothing to tell -
            # a short "Hmm." may stay, a claim may not
            if len(_WORD.findall(text)) >= 4:
                return self._drop(said, "nothing retrieved")
            return said
        if not self.strict and self.evidence.empty() and _EARLIER.search(text):
            # "you mentioned... last time" with no earlier time on record ("you said"
            # alone may be about the message he just sent)
            return self._drop(said, "claims a past with nothing kept")
        gone = self.missing(text)
        if gone:
            return self._drop(said, f"not in any memory: {', '.join(dict.fromkeys(gone))}")
        # what it came from: a claim about him by its closest row; any other sentence
        # only when it plainly draws on one (a name in common, or three words)
        claim = self.strict or _RELATION_YOURS.search(text) or _PAST_CLAIM.search(text)
        source = self.evidence.best(said, 2 if claim else 3)
        if self.strict and source is None and len(_WORD.findall(text)) >= 5:
            # an answer about the past that shares nothing with any memory is a guess
            # ("Was it about her cats, or the new job?"), however few names it has
            return self._drop(said, "shares nothing with any memory")
        if self.strict and source is not None and not self._about_question(source):
            # true, but about something else: asked for his birthday, she recited the
            # knife-sharpening memory (live eval) - an answer that isn't one
            return self._drop(said, "its memory isn't about what he asked")
        if source is not None:
            self.sources.append(source)
        return said

    def filter(self, text: str) -> str:
        """`text` (what she shows) without its lines and sentences that fail check()."""
        out = []
        for line in (text or "").split("\n"):
            kept = [s for s in re.split(r"(?<=[.!?…])\s+", line) if not s.strip() or self.check(s) is not None]
            if any(s.strip() for s in kept) or not line.strip():
                out.append(" ".join(kept))
        return "\n".join(out)

    def _drop(self, text: str, why: str) -> None:
        log.info("memory guard: dropped %r (%s)", text[:90], why)
        self.dropped.append(text)
        return None


# ---- "where did you get that?" ---------------------------------------------------------

_ASKS_SOURCE = re.compile(
    r"\b(?:where|how) did you (?:get|hear|learn|find|pick up) (?:that|this)\b|\bhow do you know (?:that|this|about)\b"
    r"|\b(?:which|what) memory\b|\bwhere(?:'s| is| does) (?:that|this) (?:from|come from|coming from)\b|\bwho told you (?:that|this)\b"
    r"|\bwhat(?:'s| is) (?:that|this) based on\b|\bwhat'?s your source\b|\bsource for (?:that|this)\b"
    r"|\bwhen did i (?:tell|say|mention) (?:you )?(?:that|this)\b|\bdid i (?:really |actually )?(?:tell|say|mention) (?:you )?(?:that|this)\b",
    re.I,
)


def asks_source(text: str) -> bool:
    return bool(_ASKS_SOURCE.search(text or ""))


@dataclass
class LastAnswer:
    """What the reply before this one was built on, kept for 'where's that from?'."""

    strict: bool = False
    sources: list[Source] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    # the question it answered: a correction right after a question about his past is
    # held to that question ("No, that's not what I asked" -> "Mr. <a made-up name>, then.", live)
    asked: str = ""


def where_from(last: LastAnswer | None, now: float | None = None) -> str:
    """Her answer to 'where did you get that?', from the record of her last reply."""
    now = now or time.time()
    if last is None:
        return "That wasn't from anything you told me - it's just what I know in general."
    seen, parts = set(), []
    for s in last.sources:
        if s.item is not None and s.item.id not in seen:
            seen.add(s.item.id)
            parts.append(_describe(s.item, now))
        elif s.item is None and s.session and s.session not in seen:
            seen.add(s.session)
            parts.append(f'You said it earlier today: "{_clip(s.session, 120)}".')
    if parts:
        return " ".join(parts[:2])
    if last.strict:
        return "Nothing - I had no memory of that, which is why I didn't answer it."
    return "That wasn't from anything you told me - it's just what I know in general."


def _describe(item: Item, now: float) -> str:
    when = _when_label(item.at, now)
    if item.kind == "fact":
        return f'From what you told me on {when}: "{_clip(item.text, 140)}".'
    if item.kind == "turn":
        his = re.search(r'He said: "([^"]+)"', item.text)
        return f'From our talk on {when} - you asked "{_clip(his.group(1), 100)}".' if his else f"From our talk on {when}."
    if item.kind == "research":
        return f'From what I looked up on {when}: "{_clip(item.about, 100)}".'
    return f"From the lecture I listened to on {when}: {_clip(item.about, 100)}."


def _clip(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + "..."


# her line when every sentence of a recall answer was made up
DONT_REMEMBER = (
    "I don't remember you telling me about that.",
    "Hmm, that's not something you've told me - I don't have it.",
    "I don't have anything on that, honestly. Fill me in?",
)
_last_fallback = ""


def dont_remember() -> str:
    global _last_fallback
    import random

    options = [line for line in DONT_REMEMBER if line != _last_fallback]
    _last_fallback = random.choice(options)
    return _last_fallback
