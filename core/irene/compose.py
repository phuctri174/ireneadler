# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""Text for the board: her words fitted to the 128x72 matrix (4 px a character,
5 px high, capitals), the board's title from his question, and the gist of a
sentence (her keywords - the board's fallback when her drawing can't be drawn).

Round 7 composed whole pictures here from her sentences, by heuristics per kind of
picture; Round 8 has her compose them herself (drawing.py), so only the text is left.
"""
from __future__ import annotations

import re

W, H = 128, 72
ADV = 4

# capitalised names: "Ho Chi Minh City", "Iron Man", "Germany"
NAME = re.compile(r"\b([A-Z][a-zA-Z'’.-]+(?:\s+(?:of\s+|the\s+|de\s+)?[A-Z][a-zA-Z'’.-]+)*)")
NOT_A_NAME = {
    "I", "It", "Its", "The", "This", "That", "These", "Those", "There", "Then", "They", "He", "She", "We", "You", "Your", "His", "Her",
    "In", "On", "At", "By", "For", "And", "But", "Or", "So", "As", "If", "When", "While", "After", "Before", "Once", "Also", "Plus",
    "A", "An", "Sir", "Mister", "Tri", "Irene", "Okay", "Ok", "Oh", "Ooh", "Hmm", "Well", "Right", "Yes", "No", "Basically", "First",
    "Next", "Finally", "Interestingly", "Apparently", "Actually", "Honestly", "Now", "Here", "What", "Which", "Who", "Why", "How",
    "Most", "Some", "Many", "Each", "Every", "One", "Two", "Three", "Its", "Both", "With", "From", "Over", "Today", "Later", "Still",
    "Unlike", "Question", "Classic", "Good", "Great", "Laugh", "Wow", "Sure", "Alright", "Imagine", "Think", "Remember", "Picture",
    "Overall", "Instead", "Meanwhile", "However", "Because", "Since", "Though", "Although", "Even", "Just", "Only", "Maybe", "Perhaps",
    "Probably", "Essentially", "Generally", "Usually", "Typically", "Mostly", "Let", "Let's", "Think", "Look", "See", "Yeah", "Nope",
    "Exactly", "Totally", "Definitely", "Absolutely", "Fun", "Fact", "Bonus", "Anyway", "Speaking", "Other", "Another", "Such",
}
# words that say how she feels about it, never what it is
FEELING = set("amazing fascinating interesting pretty really basically important different popular classic simple beautiful incredible huge great good cool awesome wonderful tricky famous".split())
FILLER = set(
    "the a an and or but so of in on at to for with from by as is are was were be been being it its it's this that these those there "
    "they them their he she his her we you your i me my our sir mister tri irene really very quite just also then than which who what "
    "when where while about into onto over under more most some any much many such like well okay oh ooh hmm basically actually "
    "apparently interestingly honestly pretty kind sort lot lots thing things way ways one two can could would should will may might "
    "has have had does do did get gets got make makes made called known means usually often generally typically mostly roughly around "
    "nearly first next finally after before once each every both other another same own here now today still even only".split()
)
NOMINAL = re.compile(r"\b([a-z]{4,}(?:tion|sion|sis|ment|ance|ence|ure|age|ity))\b", re.I)


def caps(text: str, px: int) -> str:
    """`text` in capitals, cut to fit `px` at a word boundary."""
    text = text.replace("’", "'").replace("‘", "'").replace("“", "").replace("”", "")
    text = " ".join(re.sub(r"[^\w\s'&+/.,:%$€£°-]", "", text).split()).upper()
    room = max(1, int((px + 1) // ADV))
    if len(text) <= room:
        return text
    cut = text[:room].rsplit(" ", 1)[0] if " " in text[:room] else text[:room]
    return cut.rstrip(" ,.-:")


# what a board title can lose and still say what it is ("Introduction to Algorithm
# Analysis" -> "ALGORITHM ANALYSIS", never "INTRODUCTION TO")
_TITLE_FILLER = re.compile(r"^(?:an? |the )?(?:(?:brief |short |quick )?(?:introduction|intro|overview|basics|fundamentals|summary|review|recap)\s+(?:to|of|on)\s+)", re.I)
_SMALL_END = {"TO", "OF", "AND", "OR", "THE", "A", "AN", "IN", "ON", "FOR", "WITH", "&", "VS", "VS."}


def fit_title(text: str, px: int) -> str:
    """A board title within `px`, whole: filler first ("Introduction to"), then a
    trailing "and ..." clause, and never ending on a small word."""
    whole = caps(text, 10_000)
    if caps(text, px) == whole:
        return whole
    for candidate in (_TITLE_FILLER.sub("", text), re.split(r"\s+(?:and|&)\s+", _TITLE_FILLER.sub("", text))[0]):
        if candidate.strip() and caps(candidate, px) == caps(candidate, 10_000):
            return caps(candidate, px)
    cut = caps(_TITLE_FILLER.sub("", text) or text, px).split()
    while cut and cut[-1] in _SMALL_END:
        cut.pop()
    return " ".join(cut)


_TITLE_LEAD = re.compile(
    r"^(?:(?:please|can you|could you|hey irene|irene|research|look up|find out|tell me about|tell me|explain|describe|show me|"
    r"what(?:'s| is| are| was| were)?|who(?:'s| is| was)?|how(?: does| do| did| is| are)?|why(?: is| are| does| do)?|when(?: is| was| did)?|"
    r"where(?: is| are)?|the|a|an|key|main)[,\s]+)+",
    re.I,
)


def board_title(question: str) -> str:
    """The board's title from his question: "What are the key dates of World War 2?"
    -> "DATES OF WORLD WAR 2"; "How does photosynthesis work?" -> "PHOTOSYNTHESIS"."""
    t = re.sub(r"[?.!]+$", "", " ".join((question or "").split()))
    t = re.sub(r"\s+[-–—:]\s+.*$", "", t)  # "iPhone vs Android - what's the difference"
    t = _TITLE_LEAD.sub("", t)
    t = re.sub(r"\s+(?:work|works|happen|in chess|chess opening moves|opening moves)$", "", t, flags=re.I)
    return caps(t or question, 95)


def wrap2(text: str, px: int) -> list[str]:
    """`text` in capitals on at most two lines of `px` each."""
    room = max(1, int((px + 1) // ADV))
    words = []
    for w in caps(text, 10_000).split():
        while len(w) > room:
            words.append(w[: room - 1] + "-")
            w = w[room - 1 :]
        words.append(w)
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + (1 if cur else 0) <= room:
            cur = f"{cur} {w}" if cur else w
        else:
            if cur:
                lines.append(cur)
            cur = w[:room]
            if len(lines) == 2:
                break
    if cur and len(lines) < 2:
        lines.append(cur)
    return lines[:2]


def plain(sentence: str) -> str:
    """Her sentence without voice tags ([laugh]) or cue tags."""
    return re.sub(r"\[[^\]]*\]|<[^>]+>", " ", sentence or "")


def names_in(sentence: str) -> list[str]:
    out = []
    for m in NAME.finditer(plain(sentence)):
        name = re.sub(r"['’](?:s|re|ll|ve|d|m)\b", "", m.group(1)).strip(" .’'")
        words = name.split()
        while words and (words[0] in NOT_A_NAME or words[0].lower() in ("the", "of", "de")):
            words = words[1:]
        name = " ".join(words)
        if len(words) == 1 and m.start() == len(plain(sentence)) - len(plain(sentence).lstrip()) and re.search(r"(?:ed|ing|ly|ies|ous)$", name, re.I):
            continue  # "Described as...", "Interestingly," - a word that starts the sentence
        if name and name not in NOT_A_NAME and len(name) > 1 and not name.isdigit():
            out.append(name)
    return list(dict.fromkeys(out))


def gist(sentence: str, terms: list[str] | tuple[str, ...] = (), px: int = 96) -> str:
    """A few words that stand for the sentence: a key term, a process noun
    ("evaporation"), else its first content words."""
    sentence = plain(sentence)
    if terms:
        return caps(terms[0], px)
    m = NOMINAL.search(sentence)
    if m:
        return caps(m.group(1), px)
    names = names_in(sentence)
    if names:
        return caps(names[0], px)
    words = [w for w in re.findall(r"[A-Za-z][\w'-]+", sentence) if w.lower() not in FILLER and w.lower() not in FEELING and len(w) >= 4]
    return caps(max(words, key=len), px) if words else ""


def width(text: str) -> int:
    return max(0, len(text) * ADV - 1)
