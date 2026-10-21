# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""What he has told her this session, kept where she always sees it.

The conversation history holds everything, but in a long session the thing that
matters most - a correction ("no, I mean first dan"), a preference ("keep it
short"), a requirement ("I'm preparing for my exam next month") - is one message
among dozens, fading as the context grows or gone once the oldest turns are
compacted. So his own words for those are noted here as he says them and put in
front of every message (Conversation.context), with what she has already looked
up and what she answered. A correction stays in force for the rest of the session
unless he changes it again.

Deterministic, like the rest of her grounding: a note is his sentence, verbatim,
never the model's paraphrase of it.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

MAX_NOTES = 16
MAX_LOOKUPS = 8

# he is correcting her, or what she understood
_CORRECTION = re.compile(
    r"^\W*(?:no|nope|nah|not quite|wrong)\b|\bi (?:meant|mean)\b|\byou (?:got|have) (?:that|it|this) wrong\b|\bthat'?s (?:not (?:right|it|what i)|wrong|incorrect)\b"
    r"|\bnot (?:that|this) one\b|\bi (?:said|asked)\b|\bi didn'?t (?:say|ask|mean)\b|\bi was (?:asking|talking) about\b|^\W*actually\b|\btry again\b|\bthat'?s not what\b",
    re.I,
)
# something that should hold for the rest of the session
_LASTING = re.compile(
    r"\bi (?:prefer|like|love|hate|don'?t like|want|need|'d rather|would rather)\b|\bfrom now on\b|\b(?:always|never)\b|\bdon'?t (?:ever )?\w+"
    r"|\bremember (?:that|this|it)\b|\bkeep (?:it|them|your answers?|things)\b|\bcall me\b|\bstop (?:\w+ing)\b"
    r"|\bmy (?:name|birthday|exam|goal|deadline|budget|favou?rite \w+|job|school|team|dojo|sensei|grade|rank)\b"
    r"|\bi'?m (?:a|an|allergic|vegetarian|vegan|learning|preparing|training|studying|working on|trying to|going to|choosing|deciding|picking|comparing|planning|looking (?:at|for)|thinking about)\b"
    r"|\bi have (?:a|an|my)\b.*\b(?:exam|test|deadline|meeting|interview|grading|tournament|shiai)\b",
    re.I,
)
# not a note: small talk and plain commands that happen to match
_NOT_A_NOTE = re.compile(r"^\W*(?:no(?:pe)?|nah|ok(?:ay)?|thanks?|thank you|cool|nice)\W*$|^\W*(?:no|nope)\W*(?:thanks?|thank you)\b", re.I)


# he asks her to recall something from earlier - a question, not a complaint
_RECALL = re.compile(
    r"\bremind me\b|\bagain\?|\bwhat(?:'s| was| were| did| is) (?:my|i|we|the name)\b|\bwhen(?:'s| is| was) my\b|\bwho(?:'s| is) my\b|\bgo(?:ing)? back to\b|\bback to (?:what|my|the)\b"
    r"|\bdid i (?:say|tell|mention)\b|\bwhat did (?:we|you|i)\b|\bwhere (?:does|did|was)\b.*\?|\bwhich (?:\w+ )?(?:was|did) i\b|\bdid we (?:settle|agree|decide|land)\b",
    re.I,
)
RECALL_HINT = (
    "He is asking you to recall something from earlier in this session: answer it plainly and "
    "exactly from the conversation and the notes - only what was really said or looked up, never "
    "an invented detail. It is a question, not a complaint: no apology, no 'sorry', no 'my fault', "
    "no 'did I forget'."
)


def recall_hint(said: str) -> str:
    return RECALL_HINT if _RECALL.search(said or "") else ""


@dataclass
class Note:
    kind: str  # "correction" | "lasting"
    said: str
    about: str = ""  # a correction: what it corrects (his previous message, or her answer)
    at: float = field(default_factory=time.monotonic)


@dataclass
class Lookup:
    question: str
    answer: str


class SessionNotes:
    def __init__(self) -> None:
        self.notes: list[Note] = []
        self.lookups: list[Lookup] = []

    def clear(self) -> None:
        self.notes.clear()
        self.lookups.clear()

    def hear(self, said: str, previous_user: str = "", previous_answer: str = "") -> Note | None:
        """His message: noted if it corrects her or should hold for the session."""
        text = " ".join((said or "").split())
        if len(text) < 4 or _NOT_A_NOTE.search(text) or text.startswith("["):
            return None
        if _CORRECTION.search(text):
            about = previous_answer if re.search(r"\bwrong\b|\btry again\b|\bthat'?s not\b", text, re.I) and previous_answer else previous_user
            note = Note("correction", text[:220], " ".join(about.split())[:160])
        elif _LASTING.search(text):
            note = Note("lasting", text[:220])
        else:
            return None
        # the same thing said again replaces the older note
        self.notes = [n for n in self.notes if _words(n.said) != _words(note.said)]
        self.notes.append(note)
        del self.notes[:-MAX_NOTES]
        return note

    def looked_up(self, question: str, answer: str) -> None:
        answer = " ".join((answer or "").split())
        self.lookups = [x for x in self.lookups if x.question.lower() != question.lower()]
        self.lookups.append(Lookup(question.strip()[:120], answer[:320]))
        del self.lookups[:-MAX_LOOKUPS]

    def section(self) -> str:
        if not self.notes and not self.lookups:
            return ""
        # neutral on purpose: worded as "he corrected you", the model apologised for
        # mistakes it never made ("Slipped up there again") on every later turn
        parts = ["## Noted this session (use it quietly - never mention these notes or apologise for them)"]
        if self.notes:
            parts.append("What he has told you, in his words. It still holds unless he changes it; where he clarified something, the clarification is what counts:")
            for n in self.notes:
                if n.kind == "correction" and n.about:
                    parts.append(f'- "{n.said}" (he was clarifying: "{n.about}")')
                else:
                    parts.append(f'- "{n.said}"')
        if self.lookups:
            parts.append("Already looked up this session, and what you said - answer questions about these from here, no new research:")
            for k, x in enumerate(self.lookups, 1):
                parts.append(f'{k}. "{x.question}" -> {x.answer}')
        return "\n".join(parts)


def _words(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[a-z0-9']+", text.lower()))
