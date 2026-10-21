# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""Further reading for a lecture note - only when he asks for it (or takes her offer).

"Look up more on the second topic": she researches that topic's concept online
(tools/research.py, her own browser), writes a few short explanations from the pages
she read, and keeps ONLY the sentences the pages support (grounding.py) - each with
the link it came from - plus a screenshot or two of those pages. They go into the
note's own walled-off section (lecture_note.research_box): its own label, colour and
page, so nothing she found online can ever pass for what his professor taught.
"""
from __future__ import annotations

import logging
import re
import time
from types import SimpleNamespace

from . import lecture_note, lecture_summary
from .grounding import Grounder

log = logging.getLogger("irene.lecture")

MAX_TOPICS = 3
MAX_ITEMS = 4
MAX_SHOTS = 2

EXPLAIN_PROMPT = """A student's lecture covered "{topic}" ({points}). Below are extracts from web pages about it.
Write {n} short sentences that explain {concept} for that student - plain, factual, one idea each - using ONLY the
extracts. After each sentence put the number of the extract it comes from, like [2]. No sentence without an extract
behind it; nothing from your own knowledge; no greetings, no questions.

{extracts}"""


# a sentence about the answer itself, not the subject - never a "fact" for the note
_META = re.compile(r"^\W*(?:here (?:are|is)|sure|okay|of course|certainly)\b|\bextracts?\b|\bbased (?:solely |only )?on\b"
                   r"|\bthe (?:provided|given) (?:text|pages|sources)\b|:\s*$", re.I)


def which(note: lecture_note.Note, topic: str) -> list[int]:
    """The sections he means: "2", "second", a title - or "all" (up to MAX_TOPICS)."""
    t = (topic or "").strip().lower()
    if t in ("", "all", "them", "all of them", "each", "every topic", "everything", "yes"):
        return list(range(1, min(len(note.sections), MAX_TOPICS) + 1))
    n = lecture_summary.which_section(t, SimpleNamespace(sections=note.sections))
    return [n] if n else []


def query(note: lecture_note.Note, k: int, topic: str) -> str:
    """What to look up: his words when they name a concept, else the topic's title."""
    sec = note.sections[k - 1]
    t = (topic or "").strip()
    words = re.sub(r"\b(?:the|topic|section|part|first|second|third|fourth|fifth|sixth|seventh|eighth|last|one|two|three|all|\d)\b", " ", t, flags=re.I)
    return " ".join(words.split()) if len(words.split()) >= 2 else sec["title"]


async def research_topic(note: lecture_note.Note, k: int, topic: str, chat, run_research) -> dict | None:
    """One topic looked up: {section, concept, items: [{text, url, title, site}], shots,
    at} - or None when nothing the pages say could be kept."""
    sec = note.sections[k - 1]
    concept = query(note, k, topic)
    question = f"{concept} ({sec['title']})" if concept != sec["title"] else concept
    found = await run_research(question)
    if not found.sources:
        log.info("lecture research: nothing found for %r", question)
        return None
    extracts = "\n\n".join(f"[{s.index}] {s.title} ({s.site}):\n" + "\n".join(s.passages[:3] or [s.extract]) for s in found.sources)
    prompt = EXPLAIN_PROMPT.format(topic=sec["title"], points=" ".join(sec.get("points") or [])[:400], n=MAX_ITEMS, concept=concept, extracts=extracts)
    text = await chat([{"role": "user", "content": prompt}])
    grounder = Grounder(found)
    by_index = {s.index: s for s in found.sources}
    items = []
    for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z])|\n+", text or ""):
        if not sentence.strip() or _META.search(sentence):
            continue  # about her answer, not the subject ("Here are 4 sentences... based on the extracts:")
        before = len(grounder.claims)
        kept = grounder.check(sentence.strip())
        if kept is None or len(grounder.claims) == before:
            continue  # unsupported by any page, or chatter with nothing to prove
        claim = grounder.claims[-1]
        source = by_index.get(claim.source)
        items.append({"text": kept, "url": claim.url, "title": source.title if source else claim.site, "site": claim.site})
        if len(items) >= MAX_ITEMS:
            break
    if not items:
        log.info("lecture research: %r - no sentence the pages support", question)
        return None
    used = {i["url"] for i in items}
    shots = [{"src": s.screenshot, "url": s.url, "caption": f"{s.site} - {s.title}"} for s in found.sources if s.screenshot and s.url in used][:MAX_SHOTS]
    log.info("lecture research: topic %d %r - %d sourced sentence(s) kept, %d cut, %d screenshot(s)", k, concept, len(items), len(grounder.dropped), len(shots))
    return {"section": k, "concept": concept, "items": items, "shots": shots, "at": time.time()}
