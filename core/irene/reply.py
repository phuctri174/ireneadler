"""Split a model reply into what is spoken, what is shown, and what she shows.

Only <speak> content ever reaches TTS. <display> is screen-only. A <cue> (or the
older <react>) names one cue from the registry (react.py), one per sentence; cues
are stripped from both, and an unknown or missing name simply means no cue. Text
outside the tags is treated as display, never speech, so an untagged reply is
silent rather than read aloud verbatim.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import board
from .voice import strip_tags
from .react import React, resolve

# a spoken answer runs 60-100 words (persona.md); this is the hard stop
MAX_SPOKEN_WORDS = 110

_SPEAK = re.compile(r"<speak>(.*?)</speak>", re.S | re.I)
_DISPLAY = re.compile(r"<display>(.*?)</display>", re.S | re.I)
_REACT = re.compile(r"<(?:react|cue)>(.*?)</(?:react|cue)>", re.S | re.I)
_ANY_TAG = re.compile(r"</?(speak|display|react|cue)>", re.I)
_SENTENCE_END = re.compile(r"[.!?…](?=\s|$)")
# a whole line in brackets is stage direction ("(Irene waves)", "[image of a board]"):
# the model narrating an action instead of doing it with a tag
_NARRATION = re.compile(
    r"^[ \t]*(\([^()\n]*\)|\[[^\[\]\n]*\]|Irene (\w+ )?\w+s\b[^\n]{0,80}\.)[ \t]*$", re.M
)


# a bracketed token that is not one of her voice tags ([laugh]): a citation "[1]"
# or the model's "[draw]" (live, in an explained shinai) - never read out
_NOT_A_VOICE_TAG = re.compile(r"\s*\[(?!(?:laugh|sigh|gasp|chuckle)\])[^\[\]\n]{1,24}\]", re.I)


def spoken(text: str) -> str:
    """Speech as TTS gets it: markdown emphasis asterisks and stray [brackets]
    dropped, words and voice tags kept."""
    return _NOT_A_VOICE_TAG.sub("", text.replace("*", ""))


def for_display(text: str) -> str:
    """Speech as he reads it: no [laugh]-style voice tags."""
    return strip_tags(text)


_MD_LINK = re.compile(r"\[([^\]]+)\]\((?:https?://|www\.)[^)]+\)")
_URL = re.compile(r"\(?\b(?:https?://|www\.)\S+\)?")
_MD_MARKS = re.compile(r"\*\*|__|^#{1,6}\s*|`", re.M)


def for_chat(text: str, limit: int = 700) -> str:
    """Display text as the chat bar shows it: readable, no URLs or markdown links
    (sources belong on the panel), and short."""
    text = _MD_LINK.sub(r"\1", text)
    text = _URL.sub("", text)
    text = _MD_MARKS.sub("", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+\n", "\n", re.sub(r"\n{3,}", "\n\n", text)).strip()
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + " …"


def drop_narration(text: str) -> str:
    return _NARRATION.sub("", text).strip("\n")


@dataclass(frozen=True)
class Reply:
    speak: str
    display: str
    # the first cue, and every cue in the order they play
    react: React | None = None
    cues: tuple[React, ...] = ()
    # the <draw>, if the reply had one: a spec to send, or why it can't be drawn
    draw: board.Draw | None = None


# an apology, or the "oh dear" that opens one
APOLOGY = re.compile(
    r"\bapolog\w*|\bmy fault\b|\bsorry\b|\bmy bad\b|\bnot again\b|\bdid i forget\b|\brepeating myself\b"
    r"|\bslipped up\b|\bi got (?:it|that) wrong\b|\bmix-?up\b|\bmy memory\b|^\W*(?:oh dear|oops|oh no|goodness|oh,? goodness)\W*$",
    re.I,
)


# "I don't know" and stopping: she researches instead (Round 7) - never a reply
IGNORANCE = re.compile(
    r"\bi (?:don'?t|do not) (?:really )?(?:know|have (?:any |much |the |that |current |up-to-date |recent )?(?:info|information|details|data|figures|numbers))\b(?! what you mean| which)"
    r"|\bi'?m (?:not (?:sure|certain|aware)|unsure)\b(?! (?:what|which|if you) )|\bno idea\b|\bnot something i (?:know|have)\b"
    r"|\bi (?:can'?t|cannot|couldn'?t) (?:say|recall|remember|tell you|confirm)\b|\bbeyond (?:my|what i) (?:knowledge|know)\b"
    r"|\b(?:my|the) (?:knowledge|training(?: data)?|information) (?:cut ?off|only goes|doesn'?t (?:go|cover|include)|is limited|ends)\b|\bas of my (?:last|knowledge|training)\b"
    r"|\bi haven'?t (?:heard|got|seen) (?:anything|much|any)\b|\byou(?:'d| would)? (?:might )?(?:want|need) to (?:check|look it up|google)\b",
    re.I,
)


def admits_ignorance(speak: str) -> bool:
    """She says she doesn't know (or to go look it up) instead of finding out."""
    return bool(IGNORANCE.search(speak or ""))


def is_apology(sentence: str) -> bool:
    return bool(APOLOGY.search(sentence or ""))


def drop_apologies(text: str) -> str:
    """`text` without its sentences that apologise - for answers to a recall
    question, where there is nothing to be sorry for."""
    # tested without its <cue> tags: "<cue>sad</cue>Oh dear..." is still "Oh dear..."
    kept = [s for s in re.split(r"(?<=[.!?…])\s+", text or "") if s and not is_apology(_ANY_TAG.sub("", _REACT.sub("", s)))]
    return " ".join(kept)


def cap_words(text: str, limit: int = MAX_SPOKEN_WORDS) -> str:
    """Trim to `limit` words, preferring to end on the last full sentence."""
    words = text.split()
    if len(words) <= limit:
        return " ".join(words)
    clipped = " ".join(words[:limit])
    ends = [m.end() for m in _SENTENCE_END.finditer(clipped)]
    if ends:
        return clipped[: ends[-1]].strip()
    return clipped.rstrip(",;:") + "…"


_SPEAK_TAG = re.compile(r"</?speak>", re.I)


def unnest(raw: str) -> str:
    """Drops a <speak> written inside a <speak> block that is still open
    ("<speak>Hmm. <speak>The rest.</speak>"). Once one is in the history the model
    copies it into every reply after, so history keeps the cleaned form."""
    out, pos, open_ = [], 0, False
    for m in _SPEAK_TAG.finditer(raw):
        closing = m.group(0).startswith("</")
        out.append(raw[pos : m.start()])
        if closing or not open_:
            out.append(m.group(0))
        open_ = not closing
        pos = m.end()
    out.append(raw[pos:])
    return "".join(out)


# anything shaped like a tool call - a <tool_call> block (closed or cut off, with
# or without its "<"), or a fenced/bare JSON object naming a tool: never panel
# text, never speech (live, <tool_call>{"name": "screens_off()}</tool_call> was
# shown on the panel)
_CALL_TEXT = re.compile(
    r"<?tool_call>.*?(?:</tool_call>|$)"
    r"|```(?:json)?\s*\{[^`]*?\"name\"[^`]*?\}\s*```"
    r"|\{\s*\"name\"\s*:[^{}]*(?:\{[^{}]*\}[^{}]*)?\}",
    re.S,
)


def strip_calls(text: str) -> str:
    return _CALL_TEXT.sub("", text or "")


def parse_reply(raw: str) -> Reply:
    raw = strip_calls(unnest(raw))
    drawing = board.parse(raw)
    raw = board.strip(raw)
    cues: list[React] = []
    for cue in filter(None, map(resolve, _REACT.findall(raw))):
        if not cues or cues[-1].name != cue.name:
            cues.append(cue)
    raw = _REACT.sub("", raw)
    speech = spoken(" ".join(drop_narration(m).strip() for m in _SPEAK.findall(raw)))
    shown = [drop_narration(m) for m in _DISPLAY.findall(raw)]
    # anything left over after removing both kinds of block is display
    rest = drop_narration(_ANY_TAG.sub("", _DISPLAY.sub("", _SPEAK.sub("", raw)))).strip()
    if rest:
        shown.append(rest)
    return Reply(
        speak=for_display(cap_words(speech)),
        display="\n\n".join(s for s in shown if s.strip()),
        react=cues[0] if cues else None,
        cues=tuple(cues),
        draw=drawing,
    )


# A line that promises an action she has not taken. The model likes to answer a
# lookup with the SOUND of starting one - "Ooh, let me look that up for you..." -
# and then stop, which is worse than a slow answer: she claims an action she
# never took. brain.py treats one of these with no tool call as a filler, not a
# reply, and keeps the turn running.
#
# Promising to THINK is not on this list: "let me think" costs nothing and she
# can deliver it in the same breath. Only promises of work are.
_PROMISE = re.compile(
    r"\b(let me|i'?ll|i will|lemme|allow me to|give me a) "
    r"(just |quickly |go |go and |have a )?"
    r"(look|check|search|find|see|dig|fetch|pull|grab|research|investigate|consult)\b"
    r"|\b(looking|checking|searching|fetching|digging) (it |that |this )?(up|into|out|now)\b"
    r"|\b(one|just a|give me a) (moment|sec|second|minute|tick)\b"
    # "stand by" and "on it" as announcements only - not "I stand by it" or "stuck on it"
    r"|\b(hold on|hang on|bear with me|coming right up)\b"
    r"|\bstand by\b(?! (it|that|this|what|my|me|him|her|you|them)\b)"
    r"|(^|[.!?,]\s+|\b(i'?m|i am|already|straight) )on it\b"
    r"|\blet me look that up\b",
    re.I,
)
# ... but not when she is reporting work already done
_ALREADY = re.compile(
    r"\b(i (looked|checked|searched|found|read|dug)|"
    r"(looked|checked|searched) (it |that |this )?up|according to|the sources? say)\b",
    re.I,
)


def promises_action(speak: str) -> str | None:
    """The offending phrase if a spoken reply promises work, else None."""
    said = speak or ""
    if _ALREADY.search(said):
        return None
    found = _PROMISE.search(said)
    return found.group(0) if found else None


def drop_promise(speak: str) -> str:
    """The reply with the empty promise taken out, for when the work truly cannot
    be done - she says less rather than claiming something that never happened."""
    kept = [s for s in re.split(r"(?<=[.!?…])\s+", speak or "") if s.strip() and not promises_action(s)]
    return " ".join(kept).strip()
