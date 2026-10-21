# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""The panel: show_panel(what) puts a result on Irene's second surface.

  "the last research" / "it" / "that"   the newest result - research or an answer
  "the sources" / "the links"           the last research's sources only
  "the videos"                          its YouTube cards only
  "the Eiffel Tower research"           an earlier research, matched by its words
  "close" / "hide it"                   takes the panel down

Content is the HUD's wire format (hud/src/ui/content.ts): a title and a list of
typed blocks - headings, text, links, screenshots, images, video cards. Links,
screenshots and videos open in his own Chrome when clicked (core checks the URL
was one it put there). Images are data: URIs; nothing is fetched by the HUD.
"""
from __future__ import annotations

import re

from . import research as R
from .registry import ToolContext, ToolError, tool

CLOSE = re.compile(r"\b(close|hide|clear|dismiss|take (it |that )?(down|away)|put (it )?away|nothing|off)\b", re.I)
SOURCES = re.compile(r"\b(sources?|links?|references?|citations?|where (it|that) came from)\b", re.I)
VIDEOS = re.compile(r"\b(videos?|youtube|clips?)\b", re.I)
RESEARCH_WORDS = re.compile(r"\b(research|results?|findings|what you found|sources?|videos?)\b", re.I)
# words in `what` that say where to show it, not what
FILLER = set("panel screen show put display last latest that this those them the earlier previous one research results "
             "result sources source links link videos video please again it everything full detail details".split())
IMAGES_PER_RESEARCH = 3  # main images: the first few sources (screenshots go with every source)


def text_blocks(text: str) -> list[dict]:
    """A reply's <display> text (light markdown) as panel blocks."""
    blocks: list[dict] = []
    for para in re.split(r"\n\s*\n", text.strip()):
        para = para.strip()
        if not para:
            continue
        m = re.match(r"^#{1,3}\s+(.*)", para)
        if m and "\n" not in para:
            blocks.append({"kind": "heading", "text": m.group(1).strip(), "level": 3})
            continue
        clean = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda g: g.group(1) or g.group(2), para)
        clean = re.sub(r"^\s*[*-]\s+", "• ", clean, flags=re.M)
        blocks.append({"kind": "text", "text": clean})
    return blocks


def research_content(found: R.Research, only: str | None = None) -> dict:
    """A research as panel content: the answer, every source (link, extract,
    screenshot, main image) and the videos - or only the sources or videos."""
    blocks: list[dict] = []
    if only is None and found.answer:
        blocks += [{"kind": "heading", "text": "Answer"}, *text_blocks(found.answer)]
    if only is None and found.claims:
        # every claim she made, with the fetched text that backs it
        blocks.append({"kind": "heading", "text": "What backs it up", "level": 3})
        for c in found.claims:
            blocks.append({"kind": "quote", "text": c["quote"], "attribution": f"[{c['source']}] {c['site']} - for: {c['text']}"})
    if only in (None, "sources"):
        blocks.append({"kind": "heading", "text": "Sources"})
        for s in found.sources:
            blocks.append({"kind": "heading", "text": f"[{s.index}] {s.title}", "level": 3})
            blocks.append({"kind": "link", "text": s.url.split("://", 1)[-1][:90], "url": s.url, "note": s.site})
            blocks.append({"kind": "text", "text": s.extract})
            if s.screenshot:
                blocks.append({"kind": "screenshot", "src": s.screenshot, "caption": f"on {s.site}", "url": s.url})
            if s.image and s.index <= IMAGES_PER_RESEARCH:
                blocks.append({"kind": "image", "src": s.image, "alt": s.title, "caption": f"main image - {s.site}"})
        if not found.sources:
            blocks.append({"kind": "text", "text": "No page could be read for this one."})
    if only in (None, "videos") and found.videos:
        blocks.append({"kind": "heading", "text": "Videos"})
        blocks += [
            {"kind": "video", "title": v.title, "channel": v.channel, "duration": v.duration, "url": v.url,
             **({"thumbnail": v.thumbnail} if v.thumbnail else {})}
            for v in found.videos
        ]
    parts = [f"{len(found.sources)} sources", *([f"{len(found.videos)} videos"] if found.videos else []), found.at]
    # "research": which saved research this is, so clearing or expiry can take it down
    return {"title": found.question[:1].upper() + found.question[1:], "subtitle": " · ".join(parts), "blocks": blocks, "research": found.id}


def links_in(content: dict | None) -> set[str]:
    """Every URL a click on this content may open (inside a box too)."""

    def walk(blocks) -> set[str]:
        out: set[str] = set()
        for b in blocks or []:
            if not isinstance(b, dict):
                continue
            if b.get("url"):
                out.add(b["url"])
            out |= walk(b.get("blocks"))
        return out

    return walk((content or {}).get("blocks"))


def _match(what: str, items: list[R.Research]) -> R.Research | None:
    words = R._terms(what) - FILLER
    if not words:
        return None
    scored = [(len(words & R._terms(r.question)), k, r) for k, r in enumerate(items)]
    best = max(scored, key=lambda t: (t[0], -t[1]), default=None)
    return best[2] if best and best[0] > 0 else None


def resolve(what: str, answers: list[dict]) -> tuple[dict | None, str]:
    """(content to show, or None to close; a one-line note for the model).
    `answers` are earlier displayed replies as panel content, newest first, each
    with an "at" stamp (YYYYmmdd-HHMMSS) comparable with a research id."""
    what = (what or "").strip()
    if CLOSE.search(what) and not SOURCES.search(what):
        return None, "panel closed"
    researches = R.history()
    only = "sources" if SOURCES.search(what) else "videos" if VIDEOS.search(what) else None
    found = _match(what, researches)
    if found is None and (only or RESEARCH_WORDS.search(what)):
        found = researches[0] if researches else None
    if found is None:
        newest_answer = answers[0] if answers else None
        newest_research = researches[0] if researches else None
        if newest_answer and (not newest_research or newest_answer.get("at", "") > newest_research.id):
            content = {k: v for k, v in newest_answer.items() if k != "at"}
            return content, f"on the panel: {content['title']!r}"
        found = newest_research
    if found is None:
        raise ToolError("there's nothing to show yet - no research or displayed answer so far")
    content = research_content(found, only)
    shown = {"sources": "its sources", "videos": "its videos"}.get(only, f"{len(found.sources)} sources and {len(found.videos)} videos")
    return content, f"on the panel: the research {found.question!r} - {shown}"


@tool(
    "show_panel",
    "Show a result on Irene's panel (her second screen): the last research, its sources "
    "or videos, an earlier research by topic, or the last detailed answer; or close it.",
    {"type": "object", "properties": {"what": {"type": "string", "description": "e.g. 'last research', 'sources', 'the eiffel tower research', 'that', 'close'"}}, "required": ["what"]},
    readonly=True,
    cue="reading",
)
async def show_panel(ctx: ToolContext, what: str) -> str:
    content, note = resolve(what, ctx.panel_answers())
    await ctx.show_panel(content)
    return note
