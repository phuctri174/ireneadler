# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""The lecture's board: one drawing per topic, composed by her from that topic's own
words, shown as she reaches it in the spoken summary - and kept in the note.

  compose()    each topic -> a drawing spec she writes in the board's vocabulary
               (the one config/persona.md teaches - no per-topic recipe), from that
               topic's stretch of the transcript. Then every label is checked against
               those words: a label the lecturer never said is dropped, so the board
               never shows something he didn't teach. Too little left -> that topic
               gets an outline of its own points instead.
  TopicBoards  the board for the spoken summary: an overview of the topics first,
               then topic k's drawing the moment she starts topic k, built up over
               its sentences (drawing.SpecBoard per topic).
  render       each drawing as a PNG, drawn by the HUD's own board code (board_render
               -> board_rendered), for the note and its PDF: the same picture he saw.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import math
import re
import unicodedata
from pathlib import Path

from . import drawing
from .compose import fit_title, gist
from .lecture import clock

log = logging.getLogger("irene.lecture")

PERSONA = Path(__file__).resolve().parents[2] / "config" / "persona.md"
EXCERPT_WORDS = 650
MAX_ITEMS = 7
RENDER_TIMEOUT_S = 6.0

COMPOSE_PROMPT = """You are drawing ONE topic of a lecture on Irene's tiny board (128x72 LED dots), for a student who missed it.

How a drawing is written:
{vocabulary}

Rules for this drawing:
- Draw ONLY what the lecturer said in this topic. Every label must be the lecturer's own words from the transcript
  below - no outside knowledge, no example of your own, no number that isn't said.
- 3-{max_items} items, each label one to three words - of the lecturer's words, the shortest that say it (the board
  is 32 letters across: "Measure time", not "Measure performance"). The title is filled in for you.
- Choose the form that fits THIS content: steps -> flow, a loop -> cycle, two approaches -> compare, parts of a thing
  -> parts, a hierarchy -> tree, groups -> column/row, dates -> timeline, a concept and its aspects -> radial.
  {variety}
Return ONLY the JSON spec.

Topic: {title} ({start}-{end})
Its key points: {points}
The lecturer's words (automatic transcript):
{excerpt}"""


def vocabulary() -> str:
    """How she writes a drawing, as config/persona.md teaches it (one source)."""
    try:
        text = PERSONA.read_text(encoding="utf-8")
    except OSError:
        return ""
    m = re.search(r"The form comes from the content.*?(?=\n\s*Numbers that change)", text, re.S)
    return m.group(0).strip() if m else ""


# ---- grounding: only the lecturer's words go on the board ---------------------------------------


_SMALL = set("a an the and or of to in on at for by with from is are be it its this that as into vs".split())


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", (text or "").lower()) if not unicodedata.combining(c))


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9+#]+", _fold(text))


class Said:
    """The words of one topic's stretch of transcript, matched leniently: a plural, an
    -ing, an -ed is the same word ("measure" / "measuring")."""

    def __init__(self, text: str):
        self.words = set(_words(text))
        self.stems = {w[:5] for w in self.words if len(w) >= 5}

    def has(self, word: str) -> bool:
        return word in _SMALL or word in self.words or (len(word) >= 5 and word[:5] in self.stems)

    def grounded(self, label: str) -> bool:
        words = _words(label)
        return bool(words) and all(self.has(w) for w in words)


def ground(raw: dict, said: Said) -> tuple[dict, list[str]]:
    """The spec with every item the lecturer didn't say removed (and the links to it);
    (spec, the labels dropped)."""
    dropped: list[str] = []

    def keep(items) -> list:
        out = []
        for item in items or []:
            label = item if isinstance(item, str) else (item.get("label") if isinstance(item, dict) else None)
            if not isinstance(label, str):
                continue
            # a timeline's date is checked like a label
            date = item.get("at") if isinstance(item, dict) else None
            if not said.grounded(label) or (date and not said.grounded(str(date))):
                dropped.append(label)
                continue
            if isinstance(item, dict):
                item = {**item, "items": keep(item.get("items"))} if item.get("items") else dict(item)
                item.pop("value", None)  # no number she didn't hear
            out.append(item)
        return out

    spec = {k: v for k, v in raw.items() if k not in ("chess", "chart", "points")}
    spec["items"] = keep(raw.get("items") or raw.get("steps") or [])
    names = {_fold(x if isinstance(x, str) else x.get("label", "")) for x in _flat(spec["items"])}
    links = []
    for link in raw.get("links") or []:
        if isinstance(link, (list, tuple)) and len(link) >= 2 and _fold(str(link[0])) in names and _fold(str(link[1])) in names:
            label = str(link[2]) if len(link) > 2 and link[2] and said.grounded(str(link[2])) else ""
            links.append([link[0], link[1], label] if label else [link[0], link[1]])
    if links:
        spec["links"] = links
    else:
        spec.pop("links", None)
    return spec, dropped


def _flat(items) -> list:
    out = []
    for i in items or []:
        out.append(i)
        if isinstance(i, dict):
            out += _flat(i.get("items"))
    return out


def outline(title: str, points: list[str]) -> drawing.Drawn:
    """A topic with no drawing that holds up: its points as a few words each."""
    items = [drawing.Item(g) for g in (gist(p, px=110) for p in points[:5]) if g]
    return drawing.compile(drawing.Spec("outline", title, items or [drawing.Item(fit_title(title, 110))]))


def overview(sections: list[dict], title: str) -> drawing.Drawn:
    """The lecture's topics, in order: the board while she gives the overview."""
    items = [drawing.Item(fit_title(s["title"], 110)) for s in sections[:8]]
    return drawing.compile(drawing.Spec("column" if len(items) <= 4 else "outline", title, items))


async def compose(sections: list[dict], lines: list[dict], chat) -> list[dict]:
    """For each section: {"spec": the grounded spec, "layout", "dropped": [labels]} or
    {"outline": True} when nothing drawable was left. One model call per topic."""
    out: list[dict] = []
    used: list[str] = []
    for sec in sections:
        inside = [x["text"] for x in lines if sec["start"] - 1 <= x["t"] < sec["end"]]
        excerpt = " ".join(" ".join(inside).split()[:EXCERPT_WORDS])
        said = Said(excerpt)
        variety = (f"Already drawn for earlier topics: {', '.join(used)}. Pick a different form unless this content "
                   f"really is one of those.") if used else ""
        prompt = COMPOSE_PROMPT.format(vocabulary=vocabulary(), max_items=MAX_ITEMS, variety=variety, title=sec["title"],
                                       start=clock(sec["start"]), end=clock(sec["end"]), points=" ".join(sec.get("points") or []),
                                       excerpt=excerpt)
        result: dict = {"outline": True}
        try:
            raw = drawing.loads(await chat([{"role": "user", "content": prompt}]))
        except Exception as error:  # noqa: BLE001 - a topic that can't be drawn gets its outline
            log.info("lecture board: topic %r - no spec (%s)", sec["title"], type(error).__name__)
            raw = None
        if isinstance(raw, dict) and not raw.get("chess"):
            spec, dropped = ground(raw, said)
            spec["title"] = sec["title"]
            leaves = [x for x in _flat(spec["items"])]
            if dropped:
                log.info("lecture board: topic %r - not said in the lecture, left off the board: %s", sec["title"], dropped)
            if len(leaves) >= 2:
                try:
                    read = drawing.read(spec)
                    drawing.compile(read)
                    result = {"spec": spec, "layout": read.layout, "dropped": dropped}
                    used.append(read.layout)
                except drawing.SpecError as error:
                    log.info("lecture board: topic %r - spec can't be drawn (%s)", sec["title"], error)
        out.append(result)
        log.info("lecture board: topic %r -> %s", sec["title"], result.get("layout") or "outline of its points")
    return out


def drawn_for(sec: dict, plan: dict) -> drawing.Drawn:
    if plan.get("spec"):
        try:
            return drawing.compile(drawing.read(plan["spec"]))
        except drawing.SpecError:
            pass
    return outline(sec["title"], sec.get("points") or [])


# ---- the board for the spoken summary --------------------------------------------------------------


def _norm(text: str) -> str:
    return " ".join(_words(text))


class TopicBoards:
    """The summary's board as he hears it: the overview of topics first; the k-th
    topic's drawing when she starts topic k, built up over that topic's sentences;
    each finished before the next replaces it. The same interface as
    drawing.SpecBoard (step / snapshot / finish), for illustrate.Live."""

    kind = "lecture"

    def __init__(self, first: drawing.Drawn, topics: list[drawing.Drawn], plan: list[tuple[str, int | None]]):
        self.boards = [drawing.SpecBoard(first), *(drawing.SpecBoard(d) for d in topics)]
        # each planned sentence: its words, and which board it belongs to (0 = overview)
        # (STAY, -1: after the topics - the last board stays up)
        self.plan = [(_norm(s), 0 if k is None else -1 if k < 0 else k + 1) for s, k in plan]
        self.cursor = 0
        self.current = 0
        # how many of the current board's sentences have been heard, of how many
        self.heard_in = 0

    def _sentences(self, board: int) -> int:
        return max(1, sum(1 for _, b in self.plan if b == board))

    def _match(self, sentence: str) -> int | None:
        said = _norm(sentence)
        if not said:
            return None
        head = said[:40]
        for i in range(self.cursor, len(self.plan)):
            planned = self.plan[i][0]
            if planned.startswith(head) or head in planned or planned in said:
                self.cursor = i + 1
                return self.plan[i][1]
        return None

    def _reveal(self, fresh: bool) -> dict:
        board = self.boards[self.current]
        els = board.drawn.elements
        upto = math.ceil(len(els) * min(1.0, self.heard_in / self._sentences(self.current)))
        board.shown |= {e.id for e in els[: max(1, upto)]}
        board._settle()
        return board._message(fresh)

    def step(self, sentence: str, terms=()) -> dict | None:
        k = self._match(sentence)
        if k is None or k < 0:
            return None
        fresh = k != self.current
        if fresh:
            self.current, self.heard_in = k, 0
            self.boards[k].started = False
        self.heard_in += 1
        return self._reveal(fresh)

    def snapshot(self) -> dict:
        return self._reveal(True)

    def finish(self) -> dict | None:
        return self.boards[self.current].finish()


# ---- the drawings as pictures, by the HUD's own board code -------------------------------------------


def render_spec(drawn: drawing.Drawn) -> dict:
    """Everything in the drawing, shown: what the HUD needs to draw it whole."""
    shapes = drawn.shapes({e.id for e in drawn.elements})
    return {"reveal": [], "notes": [], "shapes": [{**s, "at": 0} for s in shapes]}


class Renders:
    """board_render -> board_rendered, matched by id; only the HUD may answer."""

    def __init__(self) -> None:
        self._waiting: dict[str, asyncio.Future] = {}
        self._n = 0

    async def render(self, bridge, drawn: drawing.Drawn) -> str:
        """The drawing as a data:image/png URI, or "" (no HUD, or it didn't answer)."""
        if not getattr(bridge, "hud_connected", False):
            return ""
        self._n += 1
        rid = f"r{self._n}"
        future = asyncio.get_running_loop().create_future()
        self._waiting[rid] = future
        try:
            await bridge.send({"type": "board_render", "id": rid, "spec": render_spec(drawn)})
            return await asyncio.wait_for(future, RENDER_TIMEOUT_S)
        except asyncio.TimeoutError:
            log.warning("lecture board: the HUD didn't render drawing %s in %.0f s", rid, RENDER_TIMEOUT_S)
            return ""
        finally:
            self._waiting.pop(rid, None)

    async def on_rendered(self, message: dict) -> None:
        if message.get("_origin") != "hud":
            log.warning("board_rendered refused: not from the HUD (%s)", message.get("_origin"))
            return
        future = self._waiting.get(str(message.get("id", "")))
        png = str(message.get("png") or "")
        ok = png.startswith("data:image/png;base64,") and _is_png(png)
        if future is not None and not future.done():
            future.set_result(png if ok else "")


def _is_png(uri: str) -> bool:
    try:
        return base64.b64decode(uri.split(",", 1)[1][:24])[:8] == b"\x89PNG\r\n\x1a\n"
    except Exception:  # noqa: BLE001
        return False


RENDERS = Renders()
