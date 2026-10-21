# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""Grounding: every claim in a research answer is backed by text she actually fetched.

Each spoken sentence of a research answer is checked, as it streams, against the
readable text of the pages the research read (tools/research.py keeps it). A
sentence is a claim when it says something beyond the question's own words; it is
supported when one short window of one page holds most of its key words and every
number in it. A supported claim keeps its source and the supporting quote (for the
panel); an unsupported one is never spoken. At the end the grounder says, out
loud, when the sources were thin or disagreed.

Deliberately lexical and cheap - it runs per sentence while she talks. It can't
prove a paraphrase right, but a claim whose substance appears nowhere in the
sources (Gyaku-do as "a backward step to evade") is caught and cut.
"""
from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass

from tools.research import STOP, Research, fold

log = logging.getLogger("irene.grounding")

# a claim's words that carry no substance
FILLER = set(
    "sir mister tri irene yes yeah well okay oh ooh hmm right really actually basically just also "
    "quite pretty very much more most some any lot lots thing things kind sort way ways really "
    "called known means mean usually often generally typically mostly roughly about around nearly "
    "which there their they them then than into onto over under here where while being have has had "
    "its it's it is are was were been be so and or but not no yes one ones like get got make made "
    "say says said see seen look looks let lets want wants would could should will can may might "
    "good great nice question answer interesting fun fascinating cool lovely wow love glad happy "
    "sure honestly think guess know tell told detail details source sources panel page pages".split()
) | STOP
# where one sentence holds two claims
CLAUSE = re.compile(r",?\s+(?:though|but|although|while|whereas)\s+|;\s+|,\s+and\s+(?=\w+\s+\w+)|\s+-\s+")
CITE = re.compile(r"\s*\[(\d+(?:\s*,\s*\d+)*)\]")
NUMBER = re.compile(r"\d[\d,.]*\d|\d")
SUPPORT = 0.55        # share of a claim's key words one window must hold
WINDOW_SENTENCES = 3  # a window: this many consecutive sentences of a page


def _stem(word: str) -> str:
    # British and American spellings compare equal: metre/meter, centre/center
    if word.endswith("tres") or word.endswith("tre"):
        word = word.replace("tre", "ter")
    for suffix in ("ing", "ed", "es", "s", "e"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _words(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z]{3,}", fold(text)) if w not in FILLER}


def _overlap(key: set[str], words: set[str]) -> int:
    """Key words found in `words` - exactly, or sharing a five-letter start
    (weigh/weight, height/heights)."""
    prefixes = {w[:5] for w in words if len(w) >= 5}
    return sum(1 for k in key if k in words or (len(k) >= 5 and k[:5] in prefixes))


def _numbers(text: str) -> set[str]:
    """Numbers as digit strings: 299,792.458 and 299,792,458 compare equal."""
    return {re.sub(r"\D", "", n) for n in NUMBER.findall(text)}


def strip_citations(text: str) -> str:
    return CITE.sub("", text).strip()


@dataclass
class Claim:
    text: str
    source: int      # the research source index (1-based)
    site: str
    url: str
    quote: str       # the fetched text that supports it
    score: float


@dataclass
class _Window:
    source: int
    text: str
    words: set[str]
    numbers: set[str]


class Grounder:
    """Checks the sentences of one research answer against one research."""

    def __init__(self, research: Research) -> None:
        self.research = research
        self.subject = _words(research.question)
        self.windows: list[_Window] = []
        for s in research.sources:
            body = s.text or "\n".join(s.passages) or s.extract
            sentences = [x.strip() for x in re.split(r"(?<=[.!?])\s+|\n+", body) if x.strip()]
            for k in range(0, max(1, len(sentences)), 1):
                chunk = " ".join(sentences[k : k + WINDOW_SENTENCES])
                if chunk:
                    self.windows.append(_Window(s.index, chunk, _words(chunk), _numbers(chunk)))
        self.by_index = {s.index: s for s in research.sources}
        self.all_numbers = set().union(*(w.numbers for w in self.windows)) if self.windows else set()
        self.claims: list[Claim] = []
        self.dropped: list[str] = []
        self.chatter = 0

    def check(self, sentence: str) -> str | None:
        """The sentence to speak (citations stripped), or None to cut it. A sentence
        that fails whole keeps its supported clauses ("206 bones, though some say
        213" -> "206 bones.")."""
        whole = self._check(sentence)
        if whole is not None:
            return whole
        clauses = [c for c in CLAUSE.split(strip_citations(sentence)) if c and c.strip()]
        if len(clauses) < 2:
            return None
        self.dropped.pop()
        kept = []
        for clause in clauses:
            ok = self._check(clause.strip().rstrip(".!") + ".")
            if ok is None:
                break  # a clause stands on the ones before it; stop at the first unsupported
            kept.append(ok.rstrip("."))
        if not kept:
            self.dropped.append(strip_citations(sentence))
            return None
        return ", ".join(kept) + "."

    def _check(self, sentence: str) -> str | None:
        text = strip_citations(sentence)
        cited = {int(n) for m in CITE.finditer(sentence) for n in re.split(r"\s*,\s*", m.group(1))}
        key = _words(text) - self.subject
        numbers = _numbers(text)
        if (len(key) < 3 and not numbers) or text.rstrip().endswith("?"):
            self.chatter += 1  # "Ooh, good one!", "Want the details?" - nothing to prove
            return text
        # a number that appears nowhere in what she read is made up
        if numbers - self.all_numbers:
            log.info("unsupported number, cut: %r", text)
            self.dropped.append(text)
            return None
        best: tuple[float, _Window] | None = None
        for w in self.windows:
            found = numbers & w.numbers
            if numbers and not found:
                continue
            # a matching number is strong evidence: it counts three times
            hit = (_overlap(key, w.words) + 3 * len(found)) / max(1, len(key) + 3 * len(numbers))
            # the source she cited wins a tie
            score = hit + (0.01 if w.source in cited else 0)
            if best is None or score > best[0]:
                best = (score, w)
        if best is None or best[0] < SUPPORT or _overlap(key, best[1].words) < min(2, len(key)) - (1 if numbers else 0):
            log.info("unsupported, cut: %r (best %.2f)", text, best[0] if best else 0)
            self.dropped.append(text)
            return None
        source = self.by_index.get(best[1].source)
        self.claims.append(Claim(text, best[1].source, source.site if source else "", source.url if source else "", best[1].text[:400], round(best[0], 2)))
        return text

    def disagreement(self) -> bool:
        """Do the sources give different numbers for what a claim is about?"""
        for claim in self.claims:
            numbers = _numbers(claim.text)
            if not numbers:
                continue
            key = _words(claim.text) - self.subject
            for w in self.windows:
                if w.source == claim.source or not w.numbers or len(key & w.words) / max(1, len(key)) < 0.6:
                    continue
                unit = re.search(r"\d\s*(metres?|meters?|m\b|feet|ft|km|miles?|kg|years?|%)", claim.text, re.I)
                if unit and re.search(rf"\d\s*{re.escape(unit.group(1))}", w.text, re.I) and not numbers & w.numbers:
                    return True
        return False

    def notes(self) -> list[str]:
        """What to say out loud about the answer's footing, if anything."""
        out = []
        read = len(self.research.sources)
        facts = len(self.claims) + len(self.dropped)
        if read < 2 or (facts == 0 and read < 3):
            out.append("Honestly, sir, the sources were thin on this one - take it with a pinch of salt.")
        elif self.disagreement():
            out.append("Heads up - the sources don't quite agree on the numbers.")
        return out

    def fill(self, said: list[str], want: int, max_words: int = 60) -> list[str]:
        """Sentences from the fetched pages themselves, to make a thin answer a real
        summary: when grounding cut most of what the model said, she still says four
        to six sentences - never "the panel has the rest" in place of an answer.
        Best first (the passages research picked for the question, top source first),
        each new (not what she already said), short enough to say, and grounded by
        construction: each is a claim with its own quote."""
        if want <= 0 or not self.research.sources:
            return []
        known = [_words(t) for t in said]
        picked: list[tuple[float, str, object]] = []
        for rank, s in enumerate(self.research.sources):
            body = "\n".join(s.passages) or s.extract or s.text[:3000]
            for k, raw in enumerate(re.split(r"(?<=[.!?])\s+|\n+", body)):
                text = _speakable(raw)
                if text is None:
                    continue
                words = _words(text)
                if len(words) < 4:
                    continue
                if any(len(words & w) / len(words) >= 0.5 for w in known):
                    continue  # she already said that
                on_topic = len(words & self.subject) + (1 if self.subject & words else 0)
                score = on_topic + 1.5 / (1 + rank) + 1.0 / (1 + 0.3 * k)
                picked.append((score, text, s))
        picked.sort(key=lambda x: -x[0])
        out: list[str] = []
        used = 0
        for score, text, s in picked:
            if len(out) >= want:
                break
            words = _words(text)
            if any(len(words & w) / len(words) >= 0.5 for w in known):
                continue
            n = len(text.split())
            if used + n > max_words:
                continue
            out.append(text)
            known.append(words)
            used += n
            self.claims.append(Claim(text, s.index, s.site, s.url, text[:400], 1.0))
        if out:
            log.info("summary filled from the sources: %d sentence(s)", len(out))
        return out

    def record(self) -> list[dict]:
        return [asdict(c) for c in self.claims]


_JUNK = re.compile(r"https?://|www\.|©|\||cookie|subscribe|click|sign up|log in|retrieved|references|citation needed|\bISBN\b|^\W*(see also|main article)", re.I)


def _speakable(raw: str) -> str | None:
    """One sentence of a page cleaned for speech: no citations, brackets or
    parentheses; 7-30 words; a real sentence (ends with a full stop)."""
    text = re.sub(r"\[[^\]]*\]|\([^)]*\)", "", raw or "")
    text = re.sub(r"\s+([,.;:!?])", r"\1", re.sub(r"\s+", " ", text)).strip(" -–—•*#")
    if not text or _JUNK.search(text) or not text.endswith((".", "!")):
        return None
    words = text.split()
    if not 7 <= len(words) <= 30 or not text[0].isupper():
        return None
    letters = [c for c in text if c.isalpha()]
    if not letters or sum(c.isascii() for c in letters) / len(letters) < 0.95:
        return None
    return text
