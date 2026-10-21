# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""The key terms of a research answer, for the board while she says it.

As each grounded sentence plays, its key terms appear on the board one at a time
(her face in the corner). A term is taken only from a sentence the grounder
passed, and only if it also appears in the fetched text that supported that
sentence - so nothing on the board is invented, and nothing she only guessed.

Lexical and cheap, like grounding: names and other capitalised terms first
("All Japan Kendo Federation"), then hyphenated or foreign words ("gyaku-dō"),
then numbers with what they count ("8 dan", "10 years"), then long words. Never
a word of the question itself - the board's title already says what it's about.
"""
from __future__ import annotations

import re
import unicodedata

from .grounding import FILLER, strip_citations

# below her face in the corner the board is the full 128 columns: ~30 characters
MAX_CHARS = 30
TITLE_CHARS = 22
# what she says that is not a term, even capitalised
_NOT_TERMS = {"i", "it", "its", "the", "a", "an", "and", "but", "so", "sir", "mister", "tri", "irene", "yes", "no", "oh", "ooh", "well", "okay", "hmm", "ha", "wow", "right"}
_CAPS = re.compile(r"\b[A-Z][\w'’\-ōūāēī]*(?:\s+(?:of|the|de|du|la|von|van|and)?\s*[A-Z][\w'’\-ōūāēī]*)*")
_HYPHEN = re.compile(r"\b[\w’']*[a-zōūāēī]-[\wōūāēī]+\b|\b\w*[ōūāēī]\w*\b", re.I)
_NUMBER = re.compile(
    r"\b\d[\d,.]*(?:st|nd|rd|th)?\s*(?:%|percent|dan|kyu|years?|months?|days?|hours?|minutes?|km|kilometres?|kilometers?|metres?|meters?|m|kg|cm|mm|°c|degrees?|million|billion|thousand|people|players|games|points|moves)\b",
    re.I,
)
_WORD = re.compile(r"\b[a-z][a-z'-]{6,}\b")


def fold(text: str) -> str:
    """Lower case, no accents or macrons, hyphens and runs of space as one space."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return re.sub(r"[\s\-‐–—_/]+", " ", re.sub(r"[’']", "'", text)).strip()


def _plain(text: str) -> str:
    """Folded, and punctuation as space: for matching a term inside a page."""
    return " " + re.sub(r"\s+", " ", re.sub(r"[^\w' ]", " ", fold(text))).strip() + " "


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9']+", fold(text)))


def short_topic(question: str) -> str:
    """The board's title from the research question: "what is gyaku-do in kendo?"
    -> "gyaku-do in kendo"."""
    q = re.sub(r"[?.!]+$", "", (question or "").strip())
    lead = r"(?:please|can you|could you|hey irene|irene|research|look up|find out|tell me about|explain|what(?: is| are| was| were)?|who(?: is| was)?|how(?: does| do| did| is| are)?|why(?: is| are| does| do)?|when(?: is| was| did)?|where(?: is| are)?|the|a|an)"
    q = re.sub(rf"^(?:{lead}[,\s]+)+", "", q, flags=re.I).strip()
    if len(q) > TITLE_CHARS:
        q = q[:TITLE_CHARS].rsplit(" ", 1)[0]
    return q


def key_terms(sentence: str, support: str, question: str = "", taken: set[str] | None = None, limit: int = 2) -> list[str]:
    """Up to `limit` key terms of `sentence` that `support` (the fetched text behind
    it) also has, not already `taken` (folded forms; updated) and not just the
    question's own words."""
    taken = taken if taken is not None else set()
    text = re.sub(r"<[^>]+>|\[(?:laugh|sigh|gasp|chuckle)\]", " ", strip_citations(sentence))
    source = _plain(support)
    asked = _words(question)
    found: list[tuple[int, int, str]] = []  # (priority, position, term)

    def consider(term: str, priority: int, at: int) -> None:
        term = term.strip(" ,.;:!?\"'()")
        if not term or len(term) > MAX_CHARS:
            return
        key = fold(term)
        words = key.split()
        if not words or all(w in _NOT_TERMS or w in FILLER for w in words):
            return
        if set(words) <= asked:
            return
        if key in taken or _plain(term) not in source:
            return
        found.append((priority, at, term))

    for m in _CAPS.finditer(text):
        term = m.group(0)
        words = term.split()
        # a capital that only starts the sentence is not a name
        if m.start() == 0 or text[: m.start()].rstrip().endswith((".", "!", "?")):
            if words[0].lower() in _NOT_TERMS:
                words = words[1:]
                term = " ".join(words)
            if len(words) == 1:
                # one capitalised word opening the sentence may be a name ("Shodan
                # is...") or just an opening ("Promotion..."): after the sure ones
                if len(term) >= 5:
                    consider(term, 2, m.start())
                continue
        consider(term, 0, m.start())
    for m in _HYPHEN.finditer(text):
        consider(m.group(0), 1, m.start())
    for m in _NUMBER.finditer(text):
        consider(m.group(0), 2, m.start())
    # plain long words ("experience", "ranking") are not key terms: names, foreign
    # words and numbers with what they count are

    out: list[str] = []
    for _, _, term in sorted(found):
        key = fold(term)
        # not a piece of one already picked ("Kendo" inside "All Japan Kendo Federation")
        if any(key in fold(o) or fold(o) in key for o in out):
            continue
        out.append(term)
        taken.add(key)
        if len(out) >= limit:
            break
    return out
