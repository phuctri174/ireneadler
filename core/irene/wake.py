"""Wake phrases, found in what Whisper heard.

Stock openWakeWord has no model for "Irene", so until a custom one is trained
(Phase 7b) the wake word is a phrase at the START of an utterance: Silero VAD
hears speech, Whisper writes it down, and this decides whether it was for her.

  "Hey Irene"     always wakes her
  "Irene Adler"   always wakes her - and plays the Victorian entrance
  "Wake up Irene" always wakes her (a random entrance)
  "Wake up, daddy's home"  always wakes her (a random entrance)
  "Irene"         only while she is already awake (a follow-up), if enabled

Every one of them passes his speaker check first (speaker_id.py): the phrase is
only looked for in an utterance already judged his voice.

Whisper spells a name it half-heard many ways - "Hey, Irene", "Hi Irene", "Hey
Eileen", "Irene Adla" - so the match is on sounds-alike spellings, and whatever
follows the phrase is his command ("Hey Irene, what time is it?").
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# spellings Whisper produces for "Irene"
_IRENE = r"(?:irene|irine|irena|ireen|irin|i\s?rene|eirene|arene|eileen|irenee|irene's)"
_HEY = r"(?:hey|hay|hi|hei|a|ok|okay|oi)"
_ADLER = r"(?:adler|adla|addler|adlar|adlerr|adeler)"
_LEAD = r"^\W*(?:uh|um|so|oh)?\W*"

HEY_IRENE = re.compile(_LEAD + _HEY + r"\W+" + _IRENE + r"\b\W*", re.I)
IRENE_ADLER = re.compile(_LEAD + r"(?:" + _HEY + r"\W+)?" + _IRENE + r"\W+" + _ADLER + r"\b\W*", re.I)
BARE = re.compile(_LEAD + _IRENE + r"\b\W*", re.I)
# "Wake up Irene", "Wake up, Irene", "Wakeup Irene"
_WAKE_UP = r"wake\W*up"
WAKE_UP_IRENE = re.compile(_LEAD + _WAKE_UP + r"\W+" + _IRENE + r"\b\W*", re.I)
# "Wake up, daddy's home" (Whisper: "daddy's home", "daddy is home", "daddys home")
_DADDY = r"dadd?(?:y|ie)(?:'?s|\s+is)\W+(?:home|here|back)"
WAKE_UP_DADDY = re.compile(_LEAD + _WAKE_UP + r"\W+" + _DADDY + r"\b\W*", re.I)


@dataclass(frozen=True)
class Wake:
    # "adler" plays the Victorian entrance; "hey" a random one; "bare" is a follow-up
    phrase: str
    # what he said after the phrase, if anything ("what time is it?")
    rest: str


_HEY_ANYWHERE = re.compile(r"\b" + _HEY + r"\W+" + _IRENE + r"\b", re.I)
_ADLER_ANYWHERE = re.compile(r"\b" + _IRENE + r"\W+" + _ADLER + r"\b", re.I)
_WAKE_UP_ANYWHERE = re.compile(r"\b" + _WAKE_UP + r"\W+(?:" + _IRENE + r"|" + _DADDY + r")\b", re.I)


def find_within(text: str) -> Wake | None:
    """A full wake phrase anywhere in `text` - for the middle of other people's
    talk, where it is never at the start. Bare "Irene" never counts here."""
    said = text or ""
    m = _ADLER_ANYWHERE.search(said)
    if m:
        return Wake("adler", said[m.end():].strip(" ,.!?"))
    m = _HEY_ANYWHERE.search(said)
    if m:
        return Wake("hey", said[m.end():].strip(" ,.!?"))
    m = _WAKE_UP_ANYWHERE.search(said)
    if m:
        return Wake("wakeup", said[m.end():].strip(" ,.!?"))
    return None


def find(text: str, awake: bool = False, bare_while_awake: bool = True) -> Wake | None:
    """The wake phrase opening `text`, or None."""
    said = (text or "").strip()
    m = IRENE_ADLER.match(said)
    if m:
        return Wake("adler", said[m.end():].strip())
    m = HEY_IRENE.match(said)
    if m:
        return Wake("hey", said[m.end():].strip())
    m = WAKE_UP_IRENE.match(said) or WAKE_UP_DADDY.match(said)
    if m:
        return Wake("wakeup", said[m.end():].strip())
    if awake and bare_while_awake:
        m = BARE.match(said)
        if m:
            return Wake("bare", said[m.end():].strip())
    return None
