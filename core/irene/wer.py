# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""Word error rate, with the normalisation that makes it fair.

Whisper writes "25%", the corpus says "twenty-five percent"; Whisper writes
"Mr.", he said "Mister". Both sides are normalised the same way - lower case,
no punctuation, numbers and symbols spelled out, hyphens split - before words are
compared, so the rate counts words he said that came out wrong, not formatting.
"""
from __future__ import annotations

import re
import unicodedata

_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
_ORDINAL = {"1st": "first", "2nd": "second", "3rd": "third", "4th": "fourth", "5th": "fifth", "6th": "sixth",
            "12th": "twelfth", "13th": "thirteenth", "23rd": "twenty third", "30th": "thirtieth"}
_WORDS = {"mr": "mister", "mrs": "missus", "dr": "doctor", "%": " percent", "&": " and ", "vs": "versus",
          "okay": "ok", "o'clock": "oclock", "a.m": "am", "p.m": "pm", "metres": "meters", "metre": "meter",
          "favourite": "favorite", "summarise": "summarize", "organise": "organize", "practise": "practice",
          "defence": "defense", "colour": "color", "mum": "mom",
          # one word or two, the same words: "Goodnight" is not an error for "Good night"
          "goodnight": "good night", "proofread": "proof read"}


def number_words(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("" if n % 10 == 0 else " " + _ONES[n % 10])
    if n < 1000:
        rest = n % 100
        return _ONES[n // 100] + " hundred" + ("" if rest == 0 else " " + number_words(rest))
    if n < 1_000_000:
        rest = n % 1000
        return number_words(n // 1000) + " thousand" + ("" if rest == 0 else " " + number_words(rest))
    rest = n % 1_000_000
    return number_words(n // 1_000_000) + " million" + ("" if rest == 0 else " " + number_words(rest))


def normalize(text: str) -> list[str]:
    # "Huế", "Pokémon": the accent is spelling, not a word he said differently
    s = unicodedata.normalize("NFKD", (text or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("’", "'")
    s = re.sub(r"\$(\d+)(?:\.(\d\d))?", lambda m: f"{m.group(1)} dollars" + (f" {int(m.group(2))} cents" if m.group(2) else ""), s)
    s = re.sub(r"(\d+):(\d\d)", lambda m: f"{m.group(1)} {m.group(2) if m.group(2) != '00' else ''}", s)
    s = re.sub(r"(\d+)\.(\d+)", lambda m: f"{m.group(1)} point {' '.join(m.group(2))}", s)
    for short, full in _ORDINAL.items():
        s = re.sub(rf"\b{short}\b", full, s)
    s = re.sub(r"(\d),(\d{3})", r"\1\2", s)
    for short, full in _WORDS.items():
        s = re.sub(rf"(?<![a-z]){re.escape(short)}(?![a-z])", full, s)
    s = re.sub(r"\d+", lambda m: " " + number_words(int(m.group(0))) + " ", s)
    s = s.replace("-", " ")
    s = re.sub(r"\band\b", " ", s)  # "three hundred and forty" == "three hundred forty"
    return re.findall(r"[a-z]+(?:'[a-z]+)?", s)


def distance(ref: list[str], hyp: list[str]) -> int:
    """Word-level edit distance (substitutions + deletions + insertions)."""
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1]


def wer(reference: str, hypothesis: str) -> float:
    ref, hyp = normalize(reference), normalize(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    return distance(ref, hyp) / len(ref)
