# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""A work he taught her, answered: its card on the board, and nothing said about it
that he did not say.

When a message quotes something he taught her ("that song is Blue by yung kai, the
one that goes...", recall.Store.told), her answer is two or three sentences - the
title and artist as he gave them, anything else he told her, her own feel for it -
and two things hold it to his words:

  card      the board shows the work as she speaks: its kind, the title and artist,
            and a small abstract picture of the moods his own words carry (waves,
            a night sky, a heart, a sun). Never album art. The title and artist on
            it are words that are BOTH in his statement and in what she says - so
            the card can't show a name he never gave, nor one she didn't speak.
  unknown() a sentence of hers claiming a fact about the work - a year, an album,
            a chart, a label, sales, a genre, where the artist is from, another
            artist - that his statement doesn't hold is never spoken. Live
            2026-10-19 she credited a song to the wrong artist with a made-up
            "big hit in 1958".

Not a topic template: one card for any song, film or book he teaches, its picture
chosen from his words.
"""
from __future__ import annotations

import logging
import re
import zlib
from dataclasses import dataclass

from . import drawing
from .compose import NAME, NOT_A_NAME, caps, wrap2
from .drawing import _circle, _dot, _label, _line, _rect, _sprite

log = logging.getLogger("irene.taught")

_KINDS = r"songs?|tracks?|tunes?|albums?|films?|movies?|shows?|series|books?|novels?|poems?|plays?|paintings?|games?|anime"
# "that song is Blue by yung kai...", "the song that goes ... is called Blue by yung kai"
_IS_BY = re.compile(rf"\b(?P<kind>{_KINDS})\b.{{0,80}}?\b(?:is|'s|was)\s+(?:called |named |titled )?(?P<title>[^,.;!?]{{1,60}}?),?\s+by\s+(?P<rest>.+)", re.I | re.S)
# "Blue is a song by yung kai..."
_A_KIND_BY = re.compile(rf"(?P<title>[^,.;!?]{{1,60}}?)\s+is\s+(?:a |the )?(?P<kind>{_KINDS})\s+by\s+(?P<rest>.+)", re.I | re.S)
# "...it's called Blue" (no artist given)
_CALLED = re.compile(rf"(?:\b(?P<kind>{_KINDS})\b.{{0,80}}?)?\b(?:called|named|titled)\s+(?P<title>[^,.;!?]{{1,60}}?)(?=\s*(?:[,.;!?]|$|,? the one\b))", re.I | re.S)
_LEAD = re.compile(r"^\W*(?:that|this|the|it|it's|its|a)\s+", re.I)


def fold(text: str) -> list[str]:
    """Words, lower case, no punctuation: how his words and hers are compared."""
    return re.findall(r"[\w']+", (text or "").lower().replace("’", "'"))


def _within(words: list[str], said: list[str]) -> bool:
    n = len(words)
    return n > 0 and any(said[k : k + n] == words for k in range(len(said) - n + 1))


@dataclass
class Named:
    kind: str
    title: str
    # the words after "by" in his statement: the artist, then (when he sang straight
    # on) the lyrics - where the name ends is read from what she says (artist())
    after: list[str]


def named(fact: str) -> Named | None:
    """The work his statement names: its kind, title and what follows "by"."""
    fact = " ".join((fact or "").split())
    for pattern in (_IS_BY, _A_KIND_BY):
        m = pattern.search(fact)
        if m:
            title = _LEAD.sub("", m.group("title")).strip(" \"'“”")
            if title and len(title.split()) <= 8:
                return Named(_kind(m.group("kind")), title, m.group("rest").split())
    m = _CALLED.search(fact)
    if m and m.group("title").strip(" \"'“”"):
        return Named(_kind(m.group("kind") or "song"), m.group("title").strip(" \"'“”"), [])
    return None


def _kind(word: str) -> str:
    word = word.lower()
    return {"movie": "film", "movies": "film", "tune": "song", "track": "song"}.get(word, word.rstrip("s") if word not in ("series",) else word)


def artist(n: Named, said: str) -> str:
    """The artist as he gave it, as far as she said it too: the longest run of the
    words after his "by" (up to five) that her sentence holds - "" if none."""
    spoken = fold(said)
    after = [w for w in (re.sub(r"[^\w'’-]", "", w) for w in n.after) if w]
    for k in range(min(5, len(after)), 0, -1):
        if _within(fold(" ".join(after[:k])), spoken):
            return " ".join(after[:k])
    return ""


def says_title(n: Named, said: str) -> bool:
    return _within(fold(n.title), fold(said))


def names(n: Named, said: str) -> bool:
    """`said` names this work as an answer: its title with the artist, or the title
    quoted - not just the word ("a blue mood" is not "Blue")."""
    if not says_title(n, said):
        return False
    quoted = any(fold(m.group(1)) == fold(n.title) for m in _QUOTED.finditer(said))
    return quoted or bool(artist(n, said))


# ---- nothing about it that he didn't say ---------------------------------------------------------

# what would be a fact about the work or its artist, not a feeling about it
_FACT = re.compile(
    r"\b(?:1[0-9]\d\d|20\d\d)s?\b|'\d0s\b|\b(?:nineteen|twenty)[- ]\w+\b|\b(?:fifties|sixties|seventies|eighties|nineties)\b"
    # (not "it really hits", "every single time", "moonlight streams": feelings)
    r"|\b(?:albums?|EPs?|(?:a|the|his|her|their|lead|debut) single|singles|labels?|records|recorded|recording|charts?|charted|charting"
    r"|billboard|number one|no\. ?1|top (?:ten|\d+)|(?:a |big |huge |massive )hits?|releas\w*|came out|debut\w*|sold|sales"
    r"|million|billion|platinum|grammys?|awards?|viral"
    r"|tiktok|spotify|youtube|anime|edits?|used in|paired with|trending|memes?|featur\w+|feat\.?|covers?|covered|remix\w*|soundtracks?|produc\w+|written by|wrote|composed|composer"
    r"|band|duo|label|genre|indie|pop|rock|r&b|hip[- ]hop|rap|k-?pop|v-?pop|jazz|folk|edm|country|acoustic|lo-?fi"
    r"|korean|japanese|chinese|vietnamese|american|british|indonesian|filipino|thai|australian|canadian)\b"
    # who the artist is: "he sings", "her voice", "their debut"
    r"|\b(?:he|she|they) (?:sings?|sang|wrote|released|made|recorded|is from|was born)\b"
    r"|\b(?:his|their) (?:voice|vocals|music|songs?|fans|career|style)\b",
    re.I,
)
# "by Frankie Avalon": a name after "by" that is not his
_BY = re.compile(r"\bby\s+([A-Z][\w'’-]*)(?:\s+([\w'’-]+))?")
_QUOTED = re.compile(r"[“\"]([^”\"]{2,60})[”\"]")


def unknown(sentence: str, known: str) -> str | None:
    """What in `sentence` claims a fact about the work that `known` (his statements)
    doesn't hold, or None: such a sentence is never spoken."""
    have = set(fold(known))
    folded = " " + " ".join(fold(known)) + " "
    for m in _FACT.finditer(sentence):
        if f" {' '.join(fold(m.group(0)))} " not in folded:
            return m.group(0)
    for m in _BY.finditer(sentence):
        first = m.group(1).lower().replace("’", "'")
        # (Whisper's "Yongkai", her "Yong Kai": the same name)
        if first not in have and (first + (m.group(2) or "").lower()) not in have:
            return f"by {m.group(1)}"
    for m in _QUOTED.finditer(sentence):
        if not set(fold(m.group(1))) <= have:
            return f"“{m.group(1)}”"
    return None


def guess(sentence: str, his: str) -> str | None:
    """Naming a song he never taught her: a title she quotes, or a name he never said
    ("a Connie Francis classic") - a guess, or None."""
    have = set(fold(his))
    m = _QUOTED.search(sentence)
    if m:
        return f"“{m.group(1)}”"
    for m in NAME.finditer(sentence):
        # ("I’ve", "Tri’s": a contraction or possessive of a word that is no name - live, "I’ve" was one)
        words = [w for w in (re.sub(r"['’](?:s|ve|ll|m|d|re|t)$", "", w.strip(".,'’-")) for w in m.group(1).split()) if w and w not in NOT_A_NAME]
        if len(m.group(1).split()) == 1 and not sentence[: m.start()].strip(" \"'“‘(-…"):
            continue  # "Teach me?": a capital that only starts the sentence
        if words and not set(fold(" ".join(words))) <= have:
            return m.group(1)
    return None


# a message still about the work she just named: "what else do you know about it?",
# "who sings that one?", "when did it come out?"
_ABOUT = re.compile(r"\b(?:it|its|it's|that one|this one|the one|that song|this song|the song|the title|the artist|the singer"
                    r"|who sings|who sang|who made|the album|the lyrics|released?|came out|more about)\b", re.I)


def follows_up(text: str, title: str) -> bool:
    """His message is about the work she just named (its title, or "it", "that song")."""
    return _ABOUT.search(text or "") is not None or says_title(Named("", title, []), text or "")


def known(items) -> str:
    """His statements this answer may draw on (recall.Recalled.items, source him)."""
    return " ".join(i.text for i in items if getattr(i, "source", "") == "him")


# ---- the card ----------------------------------------------------------------------------------

# the moods his words carry, each a small abstract figure (never a cover)
_MOODS = (
    ("water", re.compile(r"\b(?:waves?|ocean\w*|seas?|rain\w*|rivers?|tides?|tears?|water|shores?|beach|blue|swim\w*)\b", re.I)),
    ("night", re.compile(r"\b(?:moon\w*|night\w*|stars?|starry|sky|skies|midnight|dark\w*|dreams?)\b", re.I)),
    ("love", re.compile(r"\b(?:love\w*|hearts?|kiss\w*|hold\w*|darling|baby|fell for)\b", re.I)),
    ("sun", re.compile(r"\b(?:sun\w*|summer|fire|burn\w*|golden|morning|bright)\b", re.I)),
)
# the picture's square, and the words beside it
AX, AY, AS = 6, 20, 44
TX, TW = 56, 68


def moods(text: str) -> list[str]:
    return [name for name, pattern in _MOODS if pattern.search(text or "")]


def _art(pen: drawing.Pen, el: drawing.Element, found: list[str], seed: int) -> None:
    pen.add(el, _rect(AX, AY, AS, AS, "accent"))
    x0, y0, x1, y1 = AX + 2, AY + 2, AX + AS - 3, AY + AS - 3
    if "water" in found:
        # three swells across the bottom, each a step out of phase
        for k, base in enumerate((y1 - 12, y1 - 7, y1 - 2)):
            pts = [(x, base + (2 if (x // 4 + k) % 4 in (1, 2) else 0) - (1 if (x // 4 + k) % 4 == 3 else 0)) for x in range(x0, x1 + 1, 4)]
            for (ax, ay), (bx, by) in zip(pts, pts[1:]):
                pen.add(el, _line(ax, ay, bx, by, "cyan" if k != 1 else "accent"))
    if "night" in found:
        pen.add(el, _circle(x1 - 9, y0 + 8, 5, "amber", fill=True))
        for k in range(7):
            h = zlib.crc32(f"{seed}:{k}".encode())
            pen.add(el, _dot(x0 + 2 + h % (AS - 20), y0 + 2 + (h >> 8) % 16, 0, "white"))
    if "sun" in found and "night" not in found:
        cx, cy = x0 + AS // 2 - 2, y0 + 12
        pen.add(el, _circle(cx, cy, 5, "amber", fill=True))
        for dx, dy in ((0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1)):
            pen.add(el, _line(cx + dx * 8, cy + dy * 8, cx + dx * 10, cy + dy * 10, "amber"))
    if "love" in found and len(found) == 1:
        # love alone: the heart is the picture, with a soft ring round it
        cx, cy = AX + AS // 2, AY + AS // 2
        pen.add(el, _sprite(cx - 9, cy - 9, "heart", 2))
        pen.add(el, _circle(cx, cy, 16, "accent"))
    elif "love" in found:
        pen.add(el, _sprite(x0 + 2, y0 + 3 if "night" in found else y0 + 14, "heart", 1))
    if not found:
        # nothing his words picture: sound, rippling out
        cx, cy = AX + AS // 2, AY + AS // 2
        for r in (4, 9, 14, 19):
            pen.add(el, _circle(cx, cy, r, "accent" if r % 2 else "cyan"))


class CardBoard:
    """The card of a work he taught her, as he hears her answer: up with the first
    sentence that names it - the picture, the title, the artist as far as that
    sentence gives it."""

    kind = "card"

    def __init__(self, n: Named, fact: str):
        self.n = n
        self.fact = fact
        self.started = False
        self.shown = False
        self.said: list[str] = []
        self._seed = zlib.crc32(n.title.lower().encode())

    def _drawn(self, by: str) -> drawing.Drawn:
        pen = drawing.Pen("card", "")
        el = pen.element(self.n.title)
        _art(pen, el, moods(self.fact), self._seed)
        pen.add(el, _label(TX, AY, caps(self.n.kind, TW), "amber"))
        title = caps(self.n.title, 10_000)
        y = AY + 9
        if len(title) * 8 - 1 <= TW:
            pen.add(el, {**_label(TX, y, title, "white"), "size": 2})
            y += 13
        else:
            for line in wrap2(self.n.title, TW):
                pen.add(el, _label(TX, y, line, "white"))
                y += 7
            y += 2
        pen.add(el, _line(TX, y, TX + TW - 2, y, "accent"))
        if by:
            pen.add(el, _label(TX, y + 4, caps(by, TW), "cyan"))
        drawn = pen.drawn
        for s in drawn.shapes():
            drawing._clamp(s)
        return drawn

    def _message(self, by: str) -> dict:
        shapes = self._drawn(by).shapes()
        self.shown = True
        if not self.started:
            self.started = True
            return {"type": "board_sync", "spec": {"shapes": shapes}}
        return {"type": "board_sync", "set": {"shapes": shapes}}

    def step(self, sentence: str, terms=()) -> dict | None:
        self.said.append(sentence)
        if self.shown or not says_title(self.n, sentence):
            return None
        by = artist(self.n, sentence)
        log.info("card up: %r by %r", self.n.title, by)
        return self._message(by)

    def snapshot(self) -> dict | None:
        return None  # nothing until she names it

    def finish(self) -> dict | None:
        if self.shown:
            return None
        # she never named it in one sentence: the title alone, and the artist if she said it anywhere
        return self._message(artist(self.n, " ".join(self.said)))


# ---- filing what he says ---------------------------------------------------------------
#
# Live 2026-10-19 he told her the song several times - "No, it's Blue by Yongkai" among
# them - and nothing was filed: only "<work> is <title> by <artist>" was recognised,
# and what wasn't went by in silence. Now:
#   - a correction (or an answer) right after she answered a song question is teaching,
#     whatever its shape: "no, it's Blue by Yongkai", "wrong - Blue, yung kai",
#     "it's called Blue, by yung kai", "Blue by yung kai"
#   - so is an explicit statement anywhere: "remember that one is Blue by yung kai",
#     "that song is Blue by yung kai, the one that goes..."
# and she says, every time, what happened: filed (title, artist), or NOT filed and why.
# What is stored is his words; when they carry no lyrics, his own lyrics from the song
# question before are kept with them, so the lyrics find it later.

# what leads a correction: "no", "wrong", "you're wrong", "actually", "Irene,"...
_FILLER = re.compile(
    r"^\W*(?:(?:no+|nope|nah|wrong|not quite|incorrect|you'?re wrong|that'?s wrong|that'?s not it|not that one|actually|well"
    r"|hey|irene|haha|ok(?:ay)?|so|listen|sorry|oh)\b[\W_]*)+", re.I)
# what leads a statement of the title
_LEAD = re.compile(
    # ("remember that one is..." - the "that" of "that one" is not "remember that")
    r"^(?:(?:remember|note|for the record|just so you know)[\s,:]+(?:that\s+(?!(?:one|song|track|tune)\b))?)?"
    r"(?:(?:that|this|the) (?:one|song|track|tune)(?: (?:you (?:heard|guessed|said|named)|i (?:sang|asked about|meant)))?"
    r"(?: is| was|'s)|it'?s|it is|it was|that'?s|that is|the (?:song|answer|title|name) is|its name is)?\s*"
    r"(?P<called>(?:called|named|titled)\b)?\s*",
    re.I,
)
# a statement naming it: "it's...", "that's...", "the song is...", "called..."
_NAMING = re.compile(r"^(?:it'?s|it is|it was|that'?s|that is|the (?:song|answer|title|name) is|(?:it'?s )?called|its name is)\b", re.I)
_REMEMBER = re.compile(r"^\W*(?:remember|note|for the record|just so you know)\b", re.I)
# where the title ends and the artist starts: ", by" / " by " / ", " / " - "
# (live 2026-10-19, in his real app: "It's blue from Yung Kai" - "from" was not read,
# and nothing was filed)
_SPLIT = re.compile(r"^(?P<title>.+?)\s*(?:,?\s+(?:by|from|sung by|performed by)\s+|,\s+|\s+[-–—]+\s+)(?P<rest>.+)$", re.I)
# "play it", "search for it", "open youtube": a request after her answer, not a naming
_REQUEST = re.compile(r"^\W*(?:(?:hey|irene|ok(?:ay)?|so|now)\W+)*(?:play|search|find|open|look|show|put|skip|stop|pause|tell|give|draw|can|could|would|will|please)\b", re.I)
# a title is a name, not a sentence about the song
_NOT_TITLE = re.compile(r"\b(?:not|another|listen|again|asked|mean|meant|wrong|song|lyrics|play|search|find|youtube|know|think|guess)\b", re.I)
# words that start lyrics, or a frame - the artist's name ends before them
_ARTIST_END = {"i", "i'll", "i'm", "i've", "you", "we", "the", "and", "my", "your", "she", "he", "it", "it's", "that", "when",
               "oh", "one", "goes", "with", "from", "who", "which",
               # ...and words he says to HER after it ("It's blue from Yongkai Irene. You should know that")
               "irene", "okay", "ok", "alright", "sir", "mister", "right", "yeah", "please"}
# what he tacks on the end: "...okay?", ", right?", ", Irene" - Whisper writes "okay?" as
# a question (live 2026-10-19: four of his corrections, all "...okay?", none filed)
_TAIL = re.compile(r"(?:[\s,.!?-]+(?:okay|ok|alright|all right|right|yeah|yes|you know|got it|sir|irene|mister tri|please))+\W*$", re.I)
# a real question: "is it Blue by yung kai?", "who sings it?"
_QUESTION = re.compile(r"^(?:who|what|which|whose|when|where|why|how|is|was|are|were|do|does|did|can|could|would|will|have|has)\b", re.I)
# "the song with the name Blue from Dung Kai" (live) - the name follows
_NAMED_AS = re.compile(r"^(?:the|a) (?:song|one|track|tune)\s+(?:with the (?:name|title)|called|named|titled)\s+", re.I)
# a correction with no title in it, said so: "no", "wrong", "that's not it"
_NEG = re.compile(r"^\W*(?:no+|nope|nah|wrong|not quite|incorrect|you'?re wrong|that'?s wrong|that'?s not it|not that one)\b", re.I)
_NOT_ARTIST = {"me", "you", "him", "her", "us", "them", "myself", "the", "a", "now", "far", "then"}


@dataclass
class Claim:
    title: str
    artist: str
    # what follows the artist (lyrics he sang on with, or "the one that goes ...")
    rest: str


def claim(text: str) -> Claim | None:
    """The title (and artist) his words state, whatever their shape - or None."""
    body = _TAIL.sub("", _FILLER.sub("", (text or "").strip()))
    lead = _LEAD.match(body)
    called = bool(lead and lead.group("called"))
    body = body[lead.end():] if lead else body
    named_as = _NAMED_AS.match(body)
    if named_as:
        body, called = body[named_as.end():], True
    body = body.strip(" \"'“”‘’.!:;?")
    if not body:
        return None
    m = _SPLIT.match(body)
    if m:
        # ("Blue is by yung kai": the title is "Blue")
        title = re.sub(r"\s+(?:is|was)$", "", m.group("title").strip(" \"'“”‘’,."), flags=re.I)
        words = m.group("rest").split()
        artist: list[str] = []
        for w in words:
            bare = re.sub(r"[^\w'’-]", "", w).lower().replace("’", "'")
            if not bare or bare in _ARTIST_END or len(artist) == 4:
                break
            artist.append(re.sub(r"[^\w'’-]", "", w))
            if re.search(r"[,.;!?]$", w):
                break
        rest = " ".join(words[len(artist):]).strip(" ,.;-–—")
        rest = re.sub(r"^(?:the one|that one|it)?\s*(?:that )?goes\s*", "", rest, flags=re.I).strip()
        if title and len(title.split()) <= 6 and not _NOT_TITLE.search(title) and artist and artist[0].lower() not in _NOT_ARTIST:
            return Claim(title, " ".join(artist), rest)
    if called:
        # "it's called Blue" - no artist given
        title = re.split(r"[,.;!?]|\s+the one\b", body, maxsplit=1)[0].strip(" \"'“”")
        if title and len(title.split()) <= 6 and not _NOT_TITLE.search(title):
            return Claim(title, "", body[len(title):].strip(" ,.;"))
    return None


@dataclass
class Teach:
    said: str
    title: str
    artist: str
    # his lyrics this is about: in his words now, or in his song question just before
    lyrics: str
    correction: bool

    @property
    def text(self) -> str:
        """What is stored: his words - with his own lyrics from before when these have none."""
        if self.lyrics and self.lyrics not in self.said:
            return f"{self.said.strip().rstrip('.')} - the one that goes {self.lyrics}"
        return self.said.strip()

    @property
    def about(self) -> str:
        return f"taught: {self.title} | {self.artist}"


@dataclass
class NotFiled:
    said: str
    why: str


def teaching(text: str, song_lyrics: str | None, asks: bool) -> Teach | NotFiled | None:
    """Whether his message tells her about a work - and so is filed. `song_lyrics`: his
    lyrics when her last reply answered his song question (None otherwise): then any
    statement of a title is a correction, whatever its shape. `asks`: it's a question."""
    from .recall import teaches

    if not (text or "").strip():
        return None
    from .songwin import confirms

    if confirms(text):
        return None  # "yes, it's correct": her answer stands, nothing new
    c = claim(text)
    # a "?" is not a question when it is only his "...okay?" - a real one asks ("is it
    # Blue by yung kai?") and is never filed
    plain = _TAIL.sub("", _FILLER.sub("", text.strip()))
    if _QUESTION.match(plain) or (asks and c is None and plain.rstrip().endswith("?")):
        return None
    explicit = teaches(text) or _REMEMBER.match(text) is not None
    # ("no, it's Blue by Yongkai" with no song question just before: still a statement of a work)
    if c is not None and (song_lyrics is not None or explicit or (c.artist and _FILLER.match(text or "") is not None)):
        lyrics = c.rest if len(c.rest.split()) >= 4 else (song_lyrics or "")
        return Teach(text, c.title, c.artist, lyrics, correction=song_lyrics is not None)
    named_rest = _NAMING.match(plain)
    if song_lyrics is not None and len(text.split()) <= 12 and not _REQUEST.match(plain) and (
            _NEG.match(text) or (named_rest is not None and plain[named_rest.end():].strip(" .,!?"))):
        # "no, that's wrong", or a naming he said that can't be read as a title: never a
        # silent pass to the model - she says nothing was filed
        return NotFiled(text, "no title")
    if explicit and teaches(text):
        return NotFiled(text, "no title I could read")
    return None


def confirm_line(t: Teach | NotFiled, filed: "object | None") -> tuple[str, str]:
    """What she says, and her cue, after filing (or not): said every time."""
    if isinstance(t, NotFiled):
        return "I haven't filed anything - what's it called, and who's it by?", "oops"
    if filed is None or not getattr(filed, "ok", False):
        return "I couldn't file that - the memory write failed.", "concerned"
    what = f"“{t.title}” by {t.artist}" if t.artist else f"“{t.title}”"
    line = f"Fixed - filed {what}." if t.correction or getattr(filed, "replaced", None) else f"Filed: {what}."
    if getattr(filed, "store", "his") != "his":
        line += " That went to the test memory."
    return line, "takeNotes"


def named_item(item) -> Named | None:
    """The work one of his taught facts names: from how it was filed, else his words."""
    about = getattr(item, "about", "") or ""
    if about.startswith("taught: "):
        title, _, artist = about[len("taught: "):].partition(" | ")
        return Named("song", title.strip(), artist.split())
    return named(getattr(item, "text", "") or "")


def card_for(recalled) -> CardBoard | None:
    """The card for an answer that found what he taught (recall.Store.told)."""
    if getattr(recalled, "skipped", "") != "world knowledge":
        return None
    for item in getattr(recalled, "items", []):
        n = named_item(item) if item.source == "him" else None
        if n is not None:
            return CardBoard(n, item.text)
    return None
