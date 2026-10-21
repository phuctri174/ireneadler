# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""A lecture, written up as a document - the way a research answer is.

The summary (lecture_summary.py) becomes a note he can keep and bring back:

  title, date, duration       from the capture's own clock
  overview                    her 2-3 sentences
  key points                  the lecture's main takeaways
  definitions                 terms the lecturer defined - each with his exact words
  homework / deadlines /      in their own box, each with the lecturer's exact quote
  exam hints                  and when he said it
  topic sections              with their times, points, and the board drawing she made
                              for each (lecture_board.py)
  further reading             ONLY if he asked for it (or took her offer): what she
                              looked up online - a separate, labelled, differently
                              styled section, every claim with its source link. It
                              is never mixed into what the lecturer said.
  transcript                  the whole automatic transcript, with times

Kept in the lecture's folder (core/data/lectures/<id>/note.json, and a PDF in the
panel's look next to it - never in his folders unasked), and listed with her
research on the panel (dashboard.py) so a click brings it back.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .lecture import STORE, clock
from .lecture_summary import TRANSCRIPT_BLOCK_S, Summary

log = logging.getLogger("irene.lecture")

NOTE = "note.json"
_KIND = {"homework": "Homework", "deadline": "Deadline", "exam": "Exam hint"}
# what the researched section says about itself, on the panel and on paper - he must
# never mistake something she found online for something his professor taught
RESEARCH_LABEL = "Further reading - researched by Irene online, NOT from the lecture"
RESEARCH_NOTE = ("Everything in this section was looked up by Irene after the lecture, from the web. The lecturer did not "
                 "say it. Each claim links to the page it came from.")


@dataclass
class Note:
    id: str  # the lecture session's id
    title: str
    started: float
    seconds: float
    words: int
    grade: str
    overview: str
    key_points: list[str]
    definitions: list[dict]  # {term, meaning, quote, at}
    alerts: list[dict]  # {kind, text, quote, at}
    sections: list[dict]  # {title, start, end, points, board?: {spec, layout}, image?: data URI}
    gaps: list[str] = field(default_factory=list)
    transcript: list[str] = field(default_factory=list)  # "[mm:ss] ..." blocks
    # added on request only (lecture_research.py): {section, concept, items: [{text,
    # url, title, site}], shots: [{src, url, caption}], at}
    research: list[dict] = field(default_factory=list)
    pdf: str = ""  # its PDF, in the lecture's folder
    written: float = 0.0

    @property
    def when(self) -> str:
        return datetime.fromtimestamp(self.started).strftime("%a %d %b %Y, %H:%M") if self.started else ""

    @property
    def at(self) -> str:
        """Sortable, like a research file's: "2026-10-14 09:32"."""
        return datetime.fromtimestamp(self.started).strftime("%Y-%m-%d %H:%M") if self.started else ""


def build(s: Summary, lines: list[dict], meta: dict) -> Note:
    meta = meta or {}
    secs = float(meta.get("seconds") or (lines[-1]["end"] if lines else 0))
    first = next((x["title"] for x in s.sections if not x["title"].endswith("(not summarised)")), "")
    title = s.title or first or "Lecture"
    sections = [{"title": x["title"], "start": x["start"], "end": x["end"], "points": list(x.get("points") or [])} for x in s.sections]
    return Note(
        id=str(meta.get("id") or ""), title=title, started=float(meta.get("started") or 0), seconds=secs,
        words=int(s.quality.get("words") or 0), grade=str(s.quality.get("grade") or "?"), overview=s.overview,
        key_points=list(s.key_points), definitions=list(s.definitions), alerts=list(s.alerts), sections=sections,
        gaps=list(s.gaps), transcript=_transcript(lines),
    )


def _transcript(lines: list[dict]) -> list[str]:
    out, buf, block_start = [], [], None
    for line in lines:
        if block_start is None:
            block_start = line["t"]
        if line["t"] - block_start >= TRANSCRIPT_BLOCK_S and buf:
            out.append(f"[{clock(block_start)}] " + " ".join(buf))
            buf, block_start = [], line["t"]
        buf.append(line["text"])
    if buf:
        out.append(f"[{clock(block_start or 0)}] " + " ".join(buf))
    return out


# ---- on disk ---------------------------------------------------------------------------------


def path_of(note_id: str) -> Path:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}_\d{6}", note_id or ""):
        raise ValueError(f"not a lecture id: {note_id!r}")
    return STORE / note_id / NOTE


def save(note: Note) -> None:
    note.written = time.time()
    path = path_of(note.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(note), ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def load(note_id: str) -> Note | None:
    try:
        raw = json.loads(path_of(note_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return Note(**{k: v for k, v in raw.items() if k in Note.__dataclass_fields__})


def saved() -> list[Note]:
    """Every lecture note, newest first."""
    if not STORE.exists():
        return []
    out = []
    for path in sorted(STORE.glob(f"*/{NOTE}"), reverse=True):
        note = load(path.parent.name)
        if note is not None:
            out.append(note)
    return out


# ---- the document: panel blocks (the PDF prints the same, tools/pdf.py) ------------------------


def _bullets(items: list[str]) -> dict:
    return {"kind": "text", "text": "\n".join(f"• {p}" for p in items)}


def content(note: Note) -> dict:
    """The note as panel content - and, through tools/pdf.py, as paper."""
    sub = f"Lecture · {note.when} · {clock(note.seconds)} · {note.words:,} words · transcript {note.grade}"
    blocks: list[dict] = [{"kind": "heading", "text": "Overview"}]
    blocks.append({"kind": "text", "text": note.overview or "No overview - the summary couldn't be made; the full transcript is below."})
    if note.key_points:
        blocks.append({"kind": "box", "tone": "points", "title": "Key points", "blocks": [_bullets(note.key_points)]})
    # what he has to act on, in the lecturer's own words
    acts = [{"kind": "quote", "text": f"“{a['quote']}”", "attribution": f"{_KIND.get(a['kind'], a['kind'])} · said at {clock(a['at'])} · {a['text']}"}
            for a in note.alerts]
    if not acts:
        acts = [{"kind": "text", "text": "Nothing said in this lecture sounded like homework, a deadline or an exam hint."}]
    blocks.append({"kind": "box", "tone": "homework", "title": "Homework, deadlines & exam hints", "blocks": acts})
    if note.definitions:
        defs = []
        for d in note.definitions:
            defs.append({"kind": "text", "text": f"{d['term']} - {d['meaning']}"})
            defs.append({"kind": "quote", "text": f"“{d['quote']}”", "attribution": f"the lecturer, at {clock(d['at'])}"})
        blocks.append({"kind": "box", "tone": "definitions", "title": "Definitions", "blocks": defs})
    blocks.append({"kind": "heading", "text": "Topics"})
    for k, sec in enumerate(note.sections, 1):
        blocks.append({"kind": "heading", "level": 3, "text": f"{k} · {sec['title']} · {clock(sec['start'])}–{clock(sec['end'])}"})
        if sec.get("image"):
            blocks.append({"kind": "image", "src": sec["image"], "alt": f"Board drawing: {sec['title']}",
                           "caption": f"Irene's board for this topic - drawn from the lecture's words, {clock(sec['start'])}–{clock(sec['end'])}"})
        if sec.get("points"):
            blocks.append(_bullets(sec["points"]))
    if note.gaps:
        blocks.append({"kind": "text", "text": f"Not summarised (the transcript is below): {', '.join(note.gaps)}."})
    if note.research:
        blocks.append(research_box(note))
    blocks.append({"kind": "heading", "text": "Full transcript"})
    blocks.append({"kind": "text", "text": f"Automatic transcript (Whisper), confidence {note.grade}. Times are from the start of the lecture."})
    blocks += [{"kind": "text", "text": chunk} for chunk in note.transcript]
    return {"title": note.title, "subtitle": sub, "blocks": blocks, "lecture": note.id, "note": True}


def research_box(note: Note) -> dict:
    """What she looked up, walled off: its own box, its own label and colour."""
    inner: list[dict] = [{"kind": "text", "text": RESEARCH_NOTE}]
    for r in note.research:
        sec = r.get("section")
        title = note.sections[sec - 1]["title"] if sec and 0 < sec <= len(note.sections) else ""
        about = (f"Topic {sec}: {title}" if r["concept"] == title else f"{r['concept']} (topic {sec}: {title})") if title else r["concept"]
        inner.append({"kind": "heading", "level": 3, "text": about})
        for item in r.get("items", []):
            inner.append({"kind": "text", "text": item["text"]})
            if item.get("url"):
                inner.append({"kind": "link", "text": item.get("title") or item["url"], "url": item["url"], "note": item.get("site", "")})
        for shot in r.get("shots", []):
            inner.append({"kind": "screenshot", "src": shot["src"], "url": shot.get("url", ""), "caption": shot.get("caption", "")})
    return {"kind": "box", "tone": "research", "title": RESEARCH_LABEL, "blocks": inner}


def rail_item(note: Note) -> dict:
    """Its card in the panel's research list."""
    image = next((s["image"] for s in note.sections if s.get("image")), "")
    return {"id": f"lecture:{note.id}", "kind": "lecture", "title": note.title, "at": note.at,
            "sources": 0, "length": clock(note.seconds), "image": image}


# ---- on paper ------------------------------------------------------------------------------------


def pdf_name(note: Note) -> str:
    day = datetime.fromtimestamp(note.started).strftime("%Y-%m-%d") if note.started else "lecture"
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", f"{note.title} - {day}")
    return re.sub(r"\s+", " ", base).strip(" .")[:90] + ".pdf"


async def write_pdf(note: Note) -> Path:
    """The note as a PDF in the panel's look, next to the lecture (its previous PDF,
    if any, replaced: it is her copy, not his file)."""
    from tools import pdf

    data = await pdf.render_pdf(content(note), time.strftime("%Y-%m-%d %H:%M"))
    folder = STORE / note.id
    for old in folder.glob("*.pdf"):
        old.unlink(missing_ok=True)
    path = folder / pdf_name(note)
    path.write_bytes(data)
    note.pdf = str(path)
    save(note)
    log.info("lecture note: PDF written - %s (%d KB)", path.name, len(data) // 1024)
    return path
