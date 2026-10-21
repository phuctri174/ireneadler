# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""She draws what she explains - a spec she composes herself, laid out here.

Round 8: no picture is anticipated any more. After </speak> she writes one
<draw>{...}</draw>: WHAT is on the board and how it is arranged, from a small
vocabulary - never coordinates, never a per-topic template:

    {"title": "Water cycle", "layout": "cycle", "items": ["Evaporation", ...]}

  layouts   flow, cycle, row, column, grid, tree, layers, compare, timeline,
            sequence, parts, radial, outline (structured text: headings with a few
            words - her choice when a subject is too tangled to draw honestly)
  items     a label, or {"label", "items" (what it holds), "shape", "on" (where
            it sits), "at" (a date), "value", "row"/"col"}
  links     [from, to, label?] - arrows between items, messages in a sequence
  helpers   {"chess": [moves]} - any line of moves, checked legal (python-chess);
            {"chart": "line"|"bar", "points": [[label, number], ...]} - axes and
            bars; the layers layout joins every node to the next layer (a neural
            net); a flow with links becomes a node graph

Everything is checked and laid out here, on the 128x72 board (her face keeps the
top-right corner, x >= 100, y < 16; text is 4 px a character, 5 px high). A spec
the model writes loosely - a <display> instead of <draw>, "steps" for "items",
links to a node it never listed - is read the way it was meant; one that still
can't be drawn (not JSON, nothing in it) raises SpecError, is logged to
logs/draw-specs.jsonl, and the board falls back to her keywords. Never a crash.

Each item becomes an element with stable shape ids; the board reveals an element
as she names it (board_sync, like Round 7), and whatever she never names as the
answer ends. Numbers that change (prices, stocks, weather) are drawn only when
the pages she researched give them: numbers(), below.
"""
from __future__ import annotations

import json
import logging
import math
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .compose import ADV, caps, fit_title, gist, plain, width, wrap2

log = logging.getLogger("irene.drawing")

W, H = 128, 72
TOP, BOTTOM, LEFT, RIGHT = 16, 71, 1, 126
FACE = (100, 16)  # her face: x >= 100 while y < 16
MAX_SHAPES = 240
LOG_PATH = Path(__file__).resolve().parents[1] / "logs" / "draw-specs.jsonl"

LAYOUTS = ("flow", "cycle", "row", "column", "grid", "tree", "layers", "compare", "timeline", "sequence", "parts", "radial", "outline", "graph")
# what the model calls a layout, and what it means
_LAYOUT_ALIASES = {
    "steps": "flow", "process": "flow", "pipeline": "flow", "chain": "flow", "flowchart": "flow", "flow chart": "flow", "step": "flow",
    "loop": "cycle", "circle": "cycle", "ring": "cycle", "cyclic": "cycle",
    "hierarchy": "tree", "taxonomy": "tree", "family tree": "tree", "org chart": "tree",
    "network": "graph", "nodes": "graph", "node graph": "graph", "neural network": "layers", "layer": "layers", "stack": "column",
    "sort": "flow", "array": "row", "queue": "row", "sequence of values": "row",
    "comparison": "compare", "versus": "compare", "vs": "compare", "table": "grid", "matrix": "grid",
    "list": "outline", "text": "outline", "bullets": "outline", "keywords": "outline", "notes": "outline", "summary": "outline",
    "diagram": "parts", "labelled": "parts", "labeled": "parts", "cross-section": "parts", "cross section": "parts", "anatomy": "parts", "inside": "parts",
    "concept": "radial", "mind map": "radial", "mindmap": "radial", "hub": "radial", "star": "radial", "map": "column", "regions": "column",
    "columns": "row", "horizontal": "row", "rows": "column", "vertical": "column", "lanes": "grid", "history": "timeline", "dates": "timeline",
    "messages": "sequence", "handshake": "sequence",
}
SHAPES = ("box", "round", "circle", "oval", "dot", "diamond", "person", "heart", "cylinder", "none")
_SHAPE_ALIASES = {"rect": "box", "rectangle": "box", "square": "box", "ellipse": "oval", "pill": "oval", "body": "person", "human": "person",
                  "figure": "person", "tube": "cylinder", "can": "cylinder", "point": "dot", "ball": "circle", "sphere": "circle", "cell": "circle"}
# every ordered layout reveals an item with the ones before it
ORDERED = ("flow", "cycle", "timeline", "sequence", "layers")
LIMIT = {"flow": 8, "cycle": 8, "row": 5, "compare": 3, "column": 6, "grid": 16, "tree": 24, "layers": 7, "timeline": 8, "sequence": 4,
         "parts": 8, "radial": 8, "outline": 16, "graph": 10}

_STOP = set("the a an and or of to in on at for by with from is are was were be its it this that as into than then".split())


class SpecError(ValueError):
    """A spec that can't be drawn: why, in a few words."""


# ---- the spec, read the way she meant it ------------------------------------------------


@dataclass
class Item:
    label: str
    items: list["Item"] = field(default_factory=list)
    shape: str | None = None
    on: str | None = None
    at: str | None = None
    value: float | None = None
    row: int | None = None
    col: int | None = None


@dataclass
class Spec:
    layout: str
    title: str
    items: list[Item] = field(default_factory=list)
    links: list[tuple[str, str, str]] = field(default_factory=list)
    shape: str | None = None
    # helpers
    chart: str | None = None
    points: list[tuple[str, float]] = field(default_factory=list)
    unit: str = ""
    moves: list[str] = field(default_factory=list)
    # a chess position as a FEN (a position, not a line of moves)
    fen: str = ""
    # what normalising had to fix, for the log
    fixed: list[str] = field(default_factory=list)


_SPEC_KEYS = {"layout", "items", "chess", "chart", "points", "moves", "nodes", "steps", "parts", "events", "links", "edges", "layers", "sides", "type", "kind"}


def is_spec(obj: object) -> bool:
    """A composed drawing (hers, laid out here) - not a HUD template or freehand shapes."""
    return isinstance(obj, dict) and "template" not in obj and "shapes" not in obj and bool(_SPEC_KEYS & set(obj))


def loads(text: str) -> dict:
    """Her spec's JSON, forgiving what a model gets wrong now and then: a code fence,
    a trailing comma, text around the object."""
    text = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip())
    start = text.find("{")
    if start < 0:
        raise SpecError("no JSON object")
    body = text[start : text.rfind("}") + 1] if "}" in text else text[start:]
    for attempt in (body, re.sub(r",\s*([}\]])", r"\1", body)):
        try:
            obj = json.loads(attempt)
        except json.JSONDecodeError as error:
            why = error.msg
            continue
        if not isinstance(obj, dict):
            raise SpecError("a drawing must be a JSON object")
        return obj
    raise SpecError(f"not JSON: {why}")


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return " ".join(str(value).split())


def number(value) -> float | None:
    """ "$2,650.40", "45%", "3.2k", 12 -> the number; anything else -> None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?|-?\.\d+", str(value or ""))
    if not m:
        return None
    n = float(m.group(0).replace(",", ""))
    tail = str(value)[m.end() : m.end() + 9].strip().lower()
    for word, scale in (("trillion", 1e12), ("billion", 1e9), ("million", 1e6), ("thousand", 1e3), ("t", 1e12), ("b", 1e9), ("m", 1e6), ("k", 1e3)):
        if tail.startswith(word) and (len(word) > 1 or not tail[1:2].isalpha()):
            return n * scale
    return n


def _item(raw, fixed: list[str], depth: int = 0) -> Item | None:
    if isinstance(raw, (str, int, float)) and not isinstance(raw, bool):
        return Item(_text(raw))
    if isinstance(raw, list) and raw and all(isinstance(x, (str, int, float)) for x in raw):
        # ["Hanoi", "North"]: a label and what it holds
        return Item(_text(raw[0]), [Item(_text(x)) for x in raw[1:]])
    if not isinstance(raw, dict):
        return None
    label = next((_text(raw[k]) for k in ("label", "text", "name", "title", "step", "event", "node", "part", "id") if raw.get(k) not in (None, "")), "")
    kids_raw = next((raw[k] for k in ("items", "children", "parts", "nodes", "sub", "points", "details", "contains") if isinstance(raw.get(k), list)), [])
    if not label and len(raw) == 1:
        # {"Evaporation": "water rises"}: the key is the label
        (key, val), = raw.items()
        label = _text(key)
        kids_raw = val if isinstance(val, list) else [val] if isinstance(val, (str, int, float)) else []
    kids = [k for k in (_item(x, fixed, depth + 1) for x in kids_raw[:12]) if k is not None] if depth < 5 else []
    if not label and "note" in raw:
        label = _text(raw["note"])
    at = next((_text(raw[k]) for k in ("at", "date", "year", "when", "time") if raw.get(k) not in (None, "")), None)
    value = next((number(raw[k]) for k in ("value", "count", "amount", "y", "price") if raw.get(k) is not None), None)
    shape = str(raw.get("shape") or "").lower().strip() or None
    shape = _SHAPE_ALIASES.get(shape, shape) if shape else None
    if shape and shape not in SHAPES:
        fixed.append(f"shape {shape!r} -> box")
        shape = "box"
    on = next((str(raw[k]).lower().strip() for k in ("on", "where", "position", "location", "anchor", "side") if raw.get(k)), None)
    row = raw.get("row") if isinstance(raw.get("row"), int) else None
    col = next((raw[k] for k in ("col", "column") if isinstance(raw.get(k), int)), None)
    if not label and not kids and at is None:
        return Item("") if depth else None  # an unnamed node in a layer is fine
    return Item(label, kids, shape, on, at, value, row, col)


def _link(raw) -> tuple[str, str, str] | None:
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        return _text(raw[0]), _text(raw[1]), _text(raw[2]) if len(raw) > 2 else ""
    if isinstance(raw, dict):
        a = next((raw[k] for k in ("from", "source", "a", "start") if k in raw), None)
        b = next((raw[k] for k in ("to", "target", "b", "end") if k in raw), None)
        if a is not None and b is not None:
            return _text(a), _text(b), _text(raw.get("label") or raw.get("text") or raw.get("message") or "")
    return None


def _moves(raw) -> list[str]:
    if isinstance(raw, dict):
        raw = raw.get("moves") or raw.get("line") or raw.get("pgn") or []
    if isinstance(raw, str):
        raw = re.sub(r"\d+\s*\.(?:\.\.)?", " ", raw).split()
    return [str(m).strip() for m in raw if str(m).strip()] if isinstance(raw, list) else []


def _points(raw) -> list[tuple[str, float]]:
    out = []
    for p in raw if isinstance(raw, list) else []:
        if isinstance(p, (list, tuple)) and len(p) >= 2:
            label, value = _text(p[0]), number(p[1])
        elif isinstance(p, dict):
            label = next((_text(p[k]) for k in ("label", "x", "date", "name", "time", "at", "category") if p.get(k) not in (None, "")), "")
            value = next((number(p[k]) for k in ("value", "y", "price", "close", "amount", "count") if p.get(k) is not None), None)
        else:
            label, value = "", number(p)
        if value is not None:
            out.append((label, value))
    return out


def read(raw: dict, title: str = "") -> Spec:
    """Her spec, normalised; SpecError if nothing in it can be drawn."""
    if not isinstance(raw, dict):
        raise SpecError("a drawing must be a JSON object")
    fixed: list[str] = []
    title = _text(raw.get("title") or raw.get("name") or raw.get("topic") or title)
    layout = str(raw.get("layout") or raw.get("type") or raw.get("kind") or "").lower().strip().replace("_", " ")
    # ---- helpers
    if raw.get("template") == "chessboard" or "chess" in raw or "fen" in raw or layout in ("chess", "chessboard", "board") or ("moves" in raw and not raw.get("items")):
        inner = raw.get("chess") if isinstance(raw.get("chess"), (dict, list, str)) else raw
        fen = (inner.get("fen") if isinstance(inner, dict) else None) or raw.get("fen")
        moves = _moves(inner if not isinstance(inner, dict) or "moves" in inner else raw.get("moves"))
        return Spec("chess", title, moves=moves, fen=str(fen).strip() if fen else "", fixed=fixed)
    chart = str(raw.get("chart") or "").lower().strip()
    if layout in ("chart", "line", "bar", "line chart", "bar chart", "graph") and ("points" in raw or "data" in raw or "values" in raw):
        chart = chart or ("bar" if "bar" in layout else "line")
    if chart in ("line", "bar", "line chart", "bar chart", "trend", "bars", "column", "columns") or (chart and ("points" in raw or "data" in raw)):
        kind = "bar" if chart.startswith(("bar", "column")) else "line"
        pts = _points(raw.get("points") or raw.get("data") or [])
        if not pts and isinstance(raw.get("values"), list):
            labels = raw.get("labels") if isinstance(raw.get("labels"), list) else [""] * len(raw["values"])
            pts = [(_text(lb), v) for lb, v in zip(labels, map(number, raw["values"])) if v is not None]
        if not pts and isinstance(raw.get("items"), list):
            pts = [(it.label, it.value) for it in (_item(x, fixed) for x in raw["items"]) if it is not None and it.value is not None]
        unit = _text(raw.get("unit") or raw.get("units") or "")
        return Spec(kind, title, points=pts, unit=unit, chart=kind, fixed=fixed)
    # ---- a composed picture
    items_raw = next((raw[k] for k in ("items", "nodes", "steps", "parts", "events", "layers", "sides", "stages", "elements", "entries", "regions", "values", "list") if isinstance(raw.get(k), list)), None)
    if items_raw is None:
        raise SpecError("no items")
    items = [i for i in (_item(x, fixed) for x in items_raw[:24]) if i is not None]
    links = [ln for ln in map(_link, next((raw[k] for k in ("links", "edges", "arrows", "connections", "messages") if isinstance(raw.get(k), list)), [])) if ln]
    shape = str(raw.get("shape") or "").lower().strip() or None
    shape = _SHAPE_ALIASES.get(shape, shape) if shape else None
    if shape and shape not in SHAPES:
        fixed.append(f"shape {shape!r} -> box")
        shape = "box"
    if layout not in LAYOUTS:
        guess = _LAYOUT_ALIASES.get(layout)
        if guess is None:
            guess = next((v for k, v in _LAYOUT_ALIASES.items() if k in layout), None)
        if guess is None:
            # no (known) layout: what the items look like
            guess = ("timeline" if sum(1 for i in items if i.at) >= 2 else "graph" if links else "parts" if shape or any(i.on for i in items)
                     else "column" if any(i.items for i in items) else "flow")
        if layout:
            fixed.append(f"layout {layout!r} -> {guess}")
        layout = guess
    if not any(i.label or i.items for i in items):
        raise SpecError("no labelled items")
    spec = Spec(layout, title, items, links, shape, fixed=fixed)
    _settle(spec)
    return spec


def _settle(spec: Spec) -> None:
    """Every layout's own needs: a form that can't hold what she wrote becomes the
    nearest one that can (logged as a fix), never a refusal."""
    fixed = spec.fixed
    if spec.layout in ("flow", "graph", "cycle") and spec.links:
        # links that only restate the chain: a flow - or, closing back on its
        # start, a cycle (live: the water cycle came as a tangled graph)
        order = _chain(spec)
        if order is not None:
            closed = order[-1] == order[0]
            spec.items = order[:-1] if closed else order
            spec.links = []
            if closed and spec.layout != "cycle":
                fixed.append("a closed chain -> cycle")
            spec.layout = "cycle" if closed else "flow"
    if spec.layout == "flow" and spec.links:
        spec.layout = "graph"
    if spec.layout in ("row", "column", "grid") and spec.links and not any(i.items for i in spec.items):
        pass  # boxes joined by arrows: drawn as they are
    if spec.layout == "timeline":
        for it in spec.items:
            if not it.at:
                m = re.search(r"\b(1\d{3}|20\d{2})\b", it.label)
                if m:
                    it.at, it.label = m.group(1), re.sub(r"\s*[-:,(]?\s*\b" + m.group(1) + r"\b\)?\s*[-:,]?\s*", " ", it.label).strip()
        if sum(1 for i in spec.items if i.at) < 2:
            fixed.append("timeline without dates -> flow")
            spec.layout = "flow"
    if spec.layout == "sequence":
        if not spec.links:
            fixed.append("sequence without messages -> flow")
            spec.layout = "flow"
        else:
            named = {i.label.lower() for i in spec.items}
            for a, b, _ in spec.links:
                for end in (a, b):
                    if end and end.lower() not in named:
                        named.add(end.lower())
                        spec.items.append(Item(end))
    if spec.layout == "compare" and len(spec.items) < 2:
        fixed.append("compare with one side -> column")
        spec.layout = "column"
    if spec.layout == "layers" and len(spec.items) < 2:
        spec.layout = "column"
    if spec.layout == "tree":
        _merge_tree(spec)
    if spec.layout in ("flow", "cycle", "radial") and len([i for i in spec.items if i.label]) < 2 and any(i.items for i in spec.items):
        spec.layout = "column" if spec.layout != "radial" else "radial"
    if spec.layout == "graph":
        named = {i.label.lower(): i for i in spec.items}
        for a, b, _ in spec.links:
            for end in (a, b):
                if end and _find(named, end) is None and len(spec.items) < LIMIT["graph"]:
                    # a link to a node she never listed: the node, not a dangling arrow
                    fixed.append(f"added node {end!r}")
                    spec.items.append(Item(end))
                    named[end.lower()] = spec.items[-1]
    spec.items = [i for i in spec.items if i.label or i.items or spec.layout == "layers"][: LIMIT.get(spec.layout, 12)]
    if not spec.items:
        raise SpecError("no labelled items")
    if spec.layout in ("flow", "cycle", "graph", "radial", "timeline") and len(spec.items) < 2:
        spec.layout = "outline" if spec.items[0].items else "column"


def _chain(spec: Spec) -> list[Item] | None:
    """The items in link order when the links are one path through all of them
    (ending where it began, for a loop); None for anything branching."""
    named = {i.label.lower(): i for i in spec.items if i.label}
    nxt: dict[int, Item] = {}
    into: dict[int, int] = {}
    for a, b, _ in spec.links:
        ia, ib = _find(named, a), _find(named, b)
        if ia is None or ib is None or id(ia) in nxt or ia is ib:
            return None
        nxt[id(ia)] = ib
        into[id(ib)] = into.get(id(ib), 0) + 1
    if any(v > 1 for v in into.values()) or len(nxt) < len(named) - 1:
        return None
    start = next((i for i in named.values() if id(i) not in into), None) or next(iter(named.values()))
    order, node = [start], start
    while id(node) in nxt and len(order) <= len(named):
        node = nxt[id(node)]
        order.append(node)
        if node is start:
            break
    closed = order[-1] is start and len(order) > 2
    if len({id(i) for i in order}) != len(named) or (len(order) != len(named) + closed):
        return None
    return order


def _find(named: dict, label: str):
    key = label.lower().strip()
    if key in named:
        return named[key]
    for k, v in named.items():
        if k and (k.startswith(key) or key.startswith(k)) and min(len(k), len(key)) >= 3:
            return v
    return None


def _merge_tree(spec: Spec) -> None:
    """A tree written flat - {"50": [30, 70]}, {"30": [20, 40]} - is one tree."""
    top = spec.items
    changed = True
    while changed and len(top) > 1:
        changed = False
        for k, root in enumerate(top):
            for other in top:
                if other is root:
                    continue
                spot = _descendant(other, root.label)
                if spot is not None:
                    spot.items.extend(c for c in root.items if c.label not in {x.label for x in spot.items})
                    top.pop(k)
                    changed = True
                    break
            if changed:
                break
    spec.items = top


def _descendant(node: Item, label: str) -> Item | None:
    for c in node.items:
        if c.label == label:
            return c
        found = _descendant(c, label)
        if found is not None:
            return found
    return None


# ---- the drawing: shapes grouped into elements -------------------------------------------


@dataclass
class Element:
    id: str
    label: str
    shapes: list[dict] = field(default_factory=list)
    order: int = 0
    # shown only once these are (an arrow between two boxes)
    needs: tuple[str, ...] = ()


@dataclass
class Drawn:
    kind: str
    title: str
    base: list[dict] = field(default_factory=list)
    elements: list[Element] = field(default_factory=list)

    @property
    def ordered(self) -> bool:
        return self.kind in ORDERED

    def shapes(self, shown: set[str] | None = None) -> list[dict]:
        els = self.elements if shown is None else [e for e in self.elements if e.id in shown]
        return [*self.base, *(s for e in els for s in e.shapes)]

    def visual(self) -> bool:
        """A picture, not only words: her outline, or the keywords, is text."""
        return self.kind not in ("outline", "keywords")


class Pen:
    """Collects shapes: the drawing's frame (base) or one element's, each with its id."""

    def __init__(self, kind: str, title: str):
        self.drawn = Drawn(kind, title)
        self._n = 0
        if title:
            self.base(_label(2, 2, fit_title(title, 96), "white"), "title")

    def element(self, label: str, needs: tuple[str, ...] = ()) -> Element:
        el = Element(f"e{len(self.drawn.elements)}", label, [], len(self.drawn.elements), needs)
        self.drawn.elements.append(el)
        return el

    def base(self, shape: dict, name: str | None = None) -> None:
        self._n += 1
        self.drawn.base.append({"id": name or f"b{self._n}", **shape})

    def add(self, el: Element | None, shape: dict) -> None:
        if el is None:
            self.base(shape)
            return
        el.shapes.append({"id": f"{el.id}.{len(el.shapes)}", **shape})


def _label(x, y, text, color="white", align="left") -> dict:
    return {"type": "label", "x": round(x), "y": round(y), "text": text, "color": color, "align": align}


def _line(x1, y1, x2, y2, color="accent", dashed=False, level=None) -> dict:
    s = {"type": "line", "x1": round(x1), "y1": round(y1), "x2": round(x2), "y2": round(y2), "color": color}
    if dashed:
        s["dashed"] = True
    if level is not None:
        s["level"] = level
    return s


def _arrow(x1, y1, x2, y2, color="cyan") -> dict:
    return {"type": "arrow", "x1": round(x1), "y1": round(y1), "x2": round(x2), "y2": round(y2), "color": color}


def _rect(x, y, w, h, color="accent", fill=False) -> dict:
    s = {"type": "rect", "x": round(x), "y": round(y), "w": max(1, round(w)), "h": max(1, round(h)), "color": color}
    if fill:
        s["fill"] = True
    return s


def _circle(x, y, r, color="accent", fill=False) -> dict:
    s = {"type": "circle", "x": round(x), "y": round(y), "r": max(1, round(r)), "color": color}
    if fill:
        s["fill"] = True
    return s


def _dot(x, y, r=1, color="amber") -> dict:
    return {"type": "dot", "x": round(x), "y": round(y), "r": r, "color": color}


def _poly(points, color="accent") -> dict:
    return {"type": "polygon", "points": [[round(x), round(y)] for x, y in points], "color": color}


@dataclass
class Box:
    x: float
    y: float
    w: float
    h: float

    @property
    def cx(self) -> float:
        return self.x + (self.w - 1) / 2

    @property
    def cy(self) -> float:
        return self.y + (self.h - 1) / 2

    @property
    def bottom(self) -> float:
        return self.y + self.h - 1

    @property
    def right(self) -> float:
        return self.x + self.w - 1

    def edge(self, tx: float, ty: float, gap: float = 1) -> tuple[float, float]:
        """Where the line from the centre towards (tx, ty) leaves the box."""
        dx, dy = tx - self.cx, ty - self.cy
        if dx == 0 and dy == 0:
            return self.cx, self.cy
        hw, hh = (self.w - 1) / 2 + gap, (self.h - 1) / 2 + gap
        t = min(hw / abs(dx) if dx else math.inf, hh / abs(dy) if dy else math.inf)
        return self.cx + dx * t, self.cy + dy * t


def lines_for(text: str, px: int, rows: int = 2) -> list[str]:
    """`text` in capitals within `px`: on up to two lines, or one."""
    px = max(3, int(px))
    if rows == 1:
        return [caps(text, px)] if caps(text, px) else []
    return wrap2(text, px) or []


def boxed(pen: Pen, el: Element | None, cx: float, cy: float, lines: list[str], color="accent", text="white", fill=False) -> Box:
    """A box with its label centred in it, at (cx, cy)."""
    w = max((width(ln) for ln in lines), default=3) + 4
    h = 6 * max(1, len(lines)) + 3
    box = Box(round(cx - (w - 1) / 2), round(cy - (h - 1) / 2), w, h)
    box.x = min(max(box.x, LEFT), RIGHT - w + 1)
    box.y = min(max(box.y, TOP), BOTTOM - h + 1)
    pen.add(el, _rect(box.x, box.y, w, h, color, fill))
    for k, ln in enumerate(lines):
        pen.add(el, _label(box.x + (w - 1) / 2 + 1, box.y + 2 + 6 * k, ln, text, "center"))
    return box


def arrow_between(pen: Pen, el, a: Box, b: Box, color="cyan") -> None:
    x1, y1 = a.edge(b.cx, b.cy, 1)
    x2, y2 = b.edge(a.cx, a.cy, 1)
    if math.hypot(x2 - x1, y2 - y1) >= 3:
        pen.add(el, _arrow(x1, y1, x2, y2, color))


def spread(n: int, lo: float, hi: float) -> list[float]:
    if n <= 1:
        return [(lo + hi) / 2]
    return [lo + (hi - lo) * k / (n - 1) for k in range(n)]


# ---- layouts --------------------------------------------------------------------------------


def _flow(pen: Pen, spec: Spec) -> None:
    items = spec.items
    n = len(items)
    gap = 7
    longest = max(len(w) for i in items for w in caps(i.label, 10_000).split() or ["?"])
    # every arrangement (rows, row gap) at the widest labels it fits, scored: whole
    # words first, then the most characters, then the fewest rows. Taking the first
    # that fitted put six steps in one row as "EX- EC-", "EM- PI-" (live, a lecture board)
    best = None
    best_score = None
    for rows in (1, 2, 3, 4):
        per = math.ceil(n / rows)
        chunks = [items[k : k + per] for k in range(0, n, per)]
        for chars in range(14, 2, -1):
            sized = [[lines_for(i.label, chars * ADV) for i in row] for row in chunks]
            widths = [[max(width(ln) for ln in (ls or ["?"])) + 4 for ls in row] for row in sized]
            if all(sum(ws) + gap * (len(ws) - 1) <= RIGHT - LEFT + 1 for ws in widths):
                break
        else:
            continue
        heights = [max(6 * len(ls) + 3 for ls in row) for row in sized]
        row_gap = next((g for g in (7, 5, 4) if sum(heights) + g * (len(heights) - 1) <= BOTTOM - TOP + 1), None)
        if row_gap is None:
            continue
        score = (chars >= min(longest, 14), chars, -rows)
        if best_score is None or score > best_score:
            best, best_score = (sized, widths, heights, row_gap), score
    sized, widths, heights, row_gap = best or (sized, widths, heights, 7)
    total = sum(heights) + row_gap * (len(heights) - 1)
    y = TOP + (BOTTOM - TOP + 1 - total) / 2
    prev: Box | None = None
    k = 0
    for row, ws, h in zip(sized, widths, heights):
        x = LEFT + (RIGHT - LEFT + 1 - (sum(ws) + gap * (len(ws) - 1))) / 2
        for c, (ls, w) in enumerate(zip(row, ws)):
            el = pen.element(items[k].label)
            box = boxed(pen, el, x + (w - 1) / 2, y + (h - 1) / 2, ls)
            if prev is not None and c > 0:
                pen.add(el, _arrow(prev.right + 1, box.cy, box.x - 1, box.cy))
            elif prev is not None:
                # down to the next row: from under the last box, across, into this one
                mid = box.y - max(2, row_gap // 2 + 1)
                pen.add(el, _line(prev.cx, prev.bottom + 1, prev.cx, mid, "cyan"))
                pen.add(el, _line(prev.cx, mid, box.cx, mid, "cyan"))
                pen.add(el, _arrow(box.cx, mid, box.cx, box.y - 1))
            prev = box
            x += w + gap
            k += 1
        y += h + row_gap


def _around(n: int, rx: float, ry: float, cx: float = 64, cy: float = 44) -> list[tuple[float, float]]:
    return [(cx + rx * math.cos(-math.pi / 2 + 2 * math.pi * k / n), cy + ry * math.sin(-math.pi / 2 + 2 * math.pi * k / n)) for k in range(n)]


def _ring(pen: Pen, spec: Spec, center: bool) -> None:
    items = spec.items
    n = len(items)
    chars = 12 if n <= 3 else 10 if n <= 4 else 8 if n <= 6 else 6
    longest = max(len(w) for i in items for w in caps(i.label, 10_000).split() or ["?"])
    # a word a little longer than the room still goes on whole
    chars = max(chars, min(longest, chars + 3), min(longest, 11))
    # two lines for every label: one line cut "Software Engineering" to "SOFTWARE" and
    # "Programming" to "PROGRAMMI" (live, a radial of seven)
    rows = 2
    cx, cy = 64, 44
    hub: Box | None = None
    if center:
        hub = boxed(pen, None, cx, cy, lines_for(spec.title or "?", 40), "amber", "white", fill=True)
    boxes = []
    for k, ((x, y), it) in enumerate(zip(_around(n, 46, 20, cx, cy), items)):
        el = pen.element(it.label)
        boxes.append((el, boxed(pen, el, x, y, lines_for(it.label, chars * ADV, rows))))
    for k, (el, box) in enumerate(boxes):
        if center and hub is not None:
            x1, y1 = hub.edge(box.cx, box.cy, 1)
            x2, y2 = box.edge(hub.cx, hub.cy, 1)
            pen.add(el, _line(x1, y1, x2, y2, "accent"))
        elif n > 2 or k == 0:
            nxt = boxes[(k + 1) % n][1]
            # the arrow into the next step appears with it; the one closing the loop with the first
            owner = boxes[(k + 1) % n][0] if k + 1 < n else el
            arrow_between(pen, owner, box, nxt)


def _containers(pen: Pen, spec: Spec, compare: bool = False) -> None:
    """Side by side: each item a column headed by its name, holding its items."""
    items = spec.items
    k = len(items)
    gap = 3
    cw = (RIGHT - LEFT + 1 - gap * (k - 1)) / k
    if not any(i.items for i in items):
        _boxes_in_row(pen, spec)
        return
    chars = max(2, int((cw - 3) // ADV))
    for c, it in enumerate(items):
        x = LEFT + c * (cw + gap)
        head = pen.element(it.label)
        head_lines = lines_for(it.label, chars * ADV)
        if compare:
            pen.add(head, _label(x + cw / 2, TOP, head_lines[0] if head_lines else "", "amber", "center"))
            pen.add(head, _line(x + 2, TOP + 7, x + cw - 3, TOP + 7, "amber"))
            y = TOP + 11
        else:
            pen.add(head, _rect(x, TOP, cw, BOTTOM - TOP + 1, "accent"))
            for j, ln in enumerate(head_lines):
                pen.add(head, _label(x + cw / 2, TOP + 3 + 6 * j, ln, "amber", "center"))
            y = TOP + 4 + 6 * len(head_lines)
            pen.add(head, _line(x + 2, y, x + cw - 3, y, "accent"))
            y += 3
        for kid in it.items:
            ls = lines_for(kid.label, (chars - 1) * ADV if compare else chars * ADV)
            if y + 6 * len(ls) - 1 > BOTTOM - (0 if compare else 2):
                ls = ls[:1]
                if y + 5 > BOTTOM - (0 if compare else 2):
                    break
            el = pen.element(kid.label)
            for j, ln in enumerate(ls):
                if compare:
                    if j == 0:
                        pen.add(el, _dot(x + 1, y + 2, 1, "accent"))
                    pen.add(el, _label(x + 5, y + 6 * j, ln))
                else:
                    pen.add(el, _label(x + cw / 2, y + 6 * j, ln, "white", "center"))
            y += 6 * len(ls) + 2
    if compare and k == 2:
        pen.base(_line(LEFT + cw + 1, TOP, LEFT + cw + 1, BOTTOM, "accent"))


def _boxes_in_row(pen: Pen, spec: Spec) -> None:
    items = spec.items
    k = len(items)
    cw = (RIGHT - LEFT + 1) / k
    boxes = {}
    for c, it in enumerate(items):
        el = pen.element(it.label)
        boxes[it.label.lower()] = (el, boxed(pen, el, LEFT + cw * (c + 0.5), 44, lines_for(it.label, cw - 6)))
    _links(pen, spec, boxes)


def _links(pen: Pen, spec: Spec, boxes: dict) -> None:
    for a, b, _ in spec.links:
        ea, eb = _find(boxes, a), _find(boxes, b)
        if ea and eb and ea is not eb:
            arrow_between(pen, pen.element(f"{a} {b}", needs=(ea[0].id, eb[0].id)), ea[1], eb[1])


def _rows(pen: Pen, spec: Spec) -> None:
    """Stacked: each item a band with its name on the left and its items after it."""
    items = spec.items
    k = len(items)
    if not any(i.items for i in items):
        rh = (BOTTOM - TOP + 1) / k
        boxes = {}
        for r, it in enumerate(items):
            el = pen.element(it.label)
            boxes[it.label.lower()] = (el, boxed(pen, el, 64, TOP + rh * (r + 0.5), lines_for(it.label, 110, 1 if rh < 15 else 2)))
        _links(pen, spec, boxes)
        return
    gap = 2
    rh = (BOTTOM - TOP + 1 - gap * (k - 1)) / k
    head_chars = min(12, max(len(caps(i.label, 10_000)) for i in items))
    hw = head_chars * ADV + 3
    for r, it in enumerate(items):
        y = TOP + r * (rh + gap)
        head = pen.element(it.label)
        pen.add(head, _rect(LEFT, y, RIGHT - LEFT + 1, rh, "accent"))
        two = rh >= 15 and len(caps(it.label, 10_000)) > head_chars
        hl = lines_for(it.label, head_chars * ADV, 2 if two else 1)
        for j, ln in enumerate(hl):
            pen.add(head, _label(LEFT + 2, y + (rh - 6 * len(hl) + 1) / 2 + 6 * j, ln, "amber"))
        # its items as chips, left to right, on as many lines as the band holds
        lines_room = max(1, int((rh - 1) // 8))
        x, line_no = LEFT + hw + 2, 0
        for kid in it.items:
            text = caps(kid.label, RIGHT - (LEFT + hw + 2) - 4)
            w = width(text) + 4
            if x + w - 1 > RIGHT - 1:
                line_no += 1
                x = LEFT + hw + 2
                if line_no >= lines_room:
                    break
            cy = y + (rh - 8 * lines_room + 1) / 2 + 8 * line_no + 3
            el = pen.element(kid.label)
            pen.add(el, _rect(x, cy - 3, w, 7, "cyan"))
            pen.add(el, _label(x + 2, cy - 2, text))
            x += w + 3


def _grid(pen: Pen, spec: Spec) -> None:
    items = spec.items
    n = len(items)
    placed = [i for i in items if i.row is not None and i.col is not None]
    if len(placed) >= n * 0.6:
        rows = max(i.row for i in placed) + 1
        cols = max(i.col for i in placed) + 1
        taken = {(i.row, i.col) for i in placed}
        spots = iter((r, c) for r in range(rows + 2) for c in range(cols) if (r, c) not in taken)
        cells = [(i.row, i.col) if i in placed else next(spots) for i in items]
        rows = max(r for r, _ in cells) + 1
    else:
        cols = max(1, math.ceil(math.sqrt(n * 1.8)))
        rows = math.ceil(n / cols)
        cells = [(k // cols, k % cols) for k in range(n)]
    rows, cols = min(rows, 6), min(cols, 8)
    cw, ch = (RIGHT - LEFT + 1) / cols, (BOTTOM - TOP + 1) / rows
    boxes = {}
    for it, (r, c) in zip(items, cells):
        if r >= rows or c >= cols:
            continue
        el = pen.element(it.label)
        text = it.label if not it.items else f"{it.label}: {it.items[0].label}"
        boxes[it.label.lower()] = (el, boxed(pen, el, LEFT + cw * (c + 0.5), TOP + ch * (r + 0.5), lines_for(text, cw - 6, 2 if ch >= 17 else 1)))
    _links(pen, spec, boxes)


def _tree(pen: Pen, spec: Spec) -> None:
    roots = spec.items
    virtual = len(roots) > 1
    # (node, depth, parent index) breadth first
    order: list[tuple[Item, int, int]] = []
    queue = [(r, 0, -1) for r in roots]
    while queue and len(order) < LIMIT["tree"]:
        node, d, parent = queue.pop(0)
        order.append((node, d, parent))
        queue += [(c, d + 1, len(order) - 1) for c in node.items if c.label]
    depth = max(d for _, d, _ in order) + 1
    kids: dict[int, list[int]] = {}
    for k, (_, _, p) in enumerate(order):
        kids.setdefault(p, []).append(k)
    # leaves left to right, parents over their children
    xs: dict[int, float] = {}
    leaves: list[int] = []

    def walk(k: int) -> None:
        if not kids.get(k):
            leaves.append(k)
            return
        for c in kids[k]:
            walk(c)

    for r in kids.get(-1, []):
        walk(r)
    sp = (RIGHT - LEFT + 1) / max(1, len(leaves))
    for j, leaf in enumerate(leaves):
        xs[leaf] = LEFT + sp * (j + 0.5)

    def place(k: int) -> float:
        if k not in xs:
            xs[k] = sum(place(c) for c in kids[k]) / len(kids[k])
        return xs[k]

    for r in kids.get(-1, []):
        place(r)
    step = min(14, (BOTTOM - TOP - 8) / max(1, depth - 1)) if depth > 1 else 0
    chars = max(2, min(12, int((sp - 2) // ADV)))
    boxes: dict[int, tuple[Element, Box]] = {}
    for k, (node, d, parent) in enumerate(order):
        # a lone root gets room for its name even when its leaves are close together
        room = chars if kids.get(parent, []) != [k] or parent >= 0 else 20
        el = pen.element(node.label, needs=(boxes[parent][0].id,) if parent in boxes else ())
        box = boxed(pen, el, xs[k], TOP + 4 + d * step, lines_for(node.label, room * ADV, 1))
        if parent in boxes:
            pb = boxes[parent][1]
            pen.add(el, _line(pb.cx, pb.bottom + 1, box.cx, box.y - 1, "accent"))
        boxes[k] = (el, box)
    if virtual and spec.title:
        pass  # a forest: its title is the root


def _layers(pen: Pen, spec: Spec) -> None:
    layers = spec.items[: LIMIT["layers"]]
    nodes = [[c.label for c in (lay.items or [Item("")])][:6] for lay in layers]
    # a hidden layer is more than one neuron (live: one node a layer drew a line)
    for k in range(1, len(nodes) - 1):
        if len(nodes[k]) < 3:
            nodes[k] = nodes[k] + [""] * (3 - len(nodes[k]))
    extra = [max(0, len(lay.items) - 6) for lay in layers]
    lm = min(36, max((width(caps(t, 32)) for t in nodes[0] if t), default=0) + 5) if any(nodes[0]) else 4
    rm = min(36, max((width(caps(t, 32)) for t in nodes[-1] if t), default=0) + 5) if any(nodes[-1]) else 4
    xs = spread(len(layers), LEFT + lm + 2, RIGHT - rm - 2)
    gap_px = (xs[1] - xs[0]) if len(xs) > 1 else 120
    names = [caps(lay.label, 2 * gap_px - 4) if lay.label else "" for lay in layers]
    stagger = any(width(t) > gap_px - 3 for t in names)
    tops = [[t] if t else [] for t in names]
    y0 = TOP + (12 if stagger else 6) + 3
    at: list[list[tuple[float, float]]] = []
    for k, (lay, names) in enumerate(zip(layers, nodes)):
        el = pen.element(lay.label or " ".join(n for n in names if n))
        for ln in tops[k]:
            x = min(max(xs[k] + 1, width(ln) / 2 + LEFT), RIGHT - width(ln) / 2)
            pen.add(el, _label(x, TOP + (6 if stagger and k % 2 else 0), ln, "amber", "center"))
        ys = spread(len(names), y0 + 2, BOTTOM - 3) if len(names) > 1 else [(y0 + BOTTOM) / 2]
        at.append([(xs[k], y) for y in ys])
        if k:
            # every node joined to every node of the layer before: appears with this layer
            for (x1, y1) in at[k - 1]:
                for (x2, y2) in at[k]:
                    pen.add(el, _line(x1 + 3, y1, x2 - 3, y2, "accent", level=0.35))
        for j, ((x, y), name) in enumerate(zip(at[k], names)):
            pen.add(el, _circle(x, y, 2, "amber" if k in (0, len(layers) - 1) else "cyan"))
            if name and k == 0:
                pen.add(el, _label(x - 5, y - 2, caps(name, lm - 5), "white", "right"))
            elif name and k == len(layers) - 1:
                pen.add(el, _label(x + 5, y - 2, caps(name, rm - 5), "white"))
        if extra[k]:
            pen.add(el, _label(xs[k] + 1, BOTTOM - 4, f"+{extra[k]}", "white", "center"))


_MONTHS = "jan feb mar apr may jun jul aug sep oct nov dec".split()


def _when(at: str) -> tuple[float, str]:
    """A date as she wrote it -> (sort key, short text): "1944-06-06" -> JUN 1944."""
    s = (at or "").strip()
    m = re.search(r"(-?\d{3,4})\s*(bc|bce)\b", s, re.I)
    if m:
        return -float(m.group(1)), f"{m.group(1)} BC"
    y = re.search(r"\b(\d{4})\b", s)
    if not y:
        n = number(s)
        return (n if n is not None else 0.0), caps(s, 32)
    year = int(y.group(1))
    month = 0
    iso = re.search(r"\b\d{4}-(\d{1,2})", s)
    if iso:
        month = int(iso.group(1))
    else:
        named = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", s, re.I)
        if named:
            month = _MONTHS.index(named.group(1).lower()) + 1
    return year + month / 13, (f"{_MONTHS[month - 1].upper()} {year}" if month else str(year))


def _timeline(pen: Pen, spec: Spec) -> None:
    dated = [(i, *_when(i.at)) for i in spec.items if i.at]
    dated.sort(key=lambda t: t[1])
    years = [d for _, _, d in dated]
    # a month only where two events share a year
    shown = [d if " " in d and sum(1 for o in years if o.split()[-1] == d.split()[-1]) > 1 else d.split()[-1] if re.fullmatch(r"[A-Z]{3} \d{4}", d) else d for d in years]
    dw = max(width(s) for s in shown)
    ax = LEFT + dw + 3
    rh = min(9, (BOTTOM - TOP + 1) / len(dated))
    pen.base(_line(ax, TOP, ax, min(BOTTOM, TOP + rh * len(dated)), "accent"))
    for k, ((it, _, _), when) in enumerate(zip(dated, shown)):
        y = TOP + k * rh + (rh - 5) / 2
        el = pen.element(f"{it.label} {when}")
        pen.add(el, _label(ax - 3, y, when, "amber", "right"))
        pen.add(el, _dot(ax, y + 2, 1, "amber"))
        pen.add(el, _label(ax + 4, y, caps(it.label, RIGHT - ax - 4), "white"))


def _sequence(pen: Pen, spec: Spec) -> None:
    who = spec.items[: LIMIT["sequence"]]
    cw = (RIGHT - LEFT + 1) / len(who)
    xs = {}
    for k, it in enumerate(who):
        x = LEFT + cw * (k + 0.5)
        box = boxed(pen, None, x, TOP + 3, lines_for(it.label, cw - 6, 1), "amber")
        xs[it.label.lower()] = x
        pen.base(_line(x, box.bottom + 1, x, BOTTOM, "accent", dashed=True))
    msgs = [(a, b, lbl) for a, b, lbl in spec.links if _find(xs, a) is not None and _find(xs, b) is not None][:6]
    step = min(9, (BOTTOM - (TOP + 11)) / max(1, len(msgs)))
    for k, (a, b, lbl) in enumerate(msgs):
        xa, xb = _find(xs, a), _find(xs, b)
        y = TOP + 11 + k * step
        el = pen.element(lbl or f"{a} {b}")
        if xa == xb:
            pen.add(el, _line(xa, y + 5, xa + 6, y + 5, "cyan"))
            pen.add(el, _arrow(xa + 6, y + 7, xa + 1, y + 7))
            if lbl:
                pen.add(el, _label(xa + 8, y + 3, caps(lbl, RIGHT - xa - 8)))
            continue
        pen.add(el, _arrow(xa + (2 if xb > xa else -2), y + 6, xb + (-2 if xb > xa else 2), y + 6))
        if lbl:
            pen.add(el, _label((xa + xb) / 2 + 1, y, caps(lbl, abs(xb - xa) - 4), "white", "center"))


# where a part sits, as a fraction of the outline's half-size
_ANCHORS = {
    "center": (0, 0), "centre": (0, 0), "middle": (0, 0), "inside": (0.15, 0.1), "core": (0, 0),
    "top": (0, -0.62), "bottom": (0, 0.62), "left": (-0.62, 0), "right": (0.62, 0),
    "top-left": (-0.45, -0.45), "top-right": (0.45, -0.45), "bottom-left": (-0.45, 0.45), "bottom-right": (0.45, 0.45),
    "upper": (0, -0.5), "lower": (0, 0.5), "front": (-0.62, 0), "back": (0.62, 0), "base": (0, 0.8), "tip": (0, -0.85),
    # a country or a region, north up
    "north": (0, -0.62), "south": (0, 0.62), "east": (0.62, 0), "west": (-0.62, 0), "northeast": (0.45, -0.45),
    "northwest": (-0.45, -0.45), "southeast": (0.45, 0.45), "southwest": (-0.45, 0.45), "northern": (0, -0.62), "southern": (0, 0.62),
    "central": (0, 0), "eastern": (0.62, 0), "western": (-0.62, 0), "coast": (0.55, 0.1), "coastal": (0.55, 0.1),
}
_EDGE = re.compile(r"\b(edge|outline|outside|border|surface|wall|skin|shell|membrane|rim|around)\b")
# a standing figure, centre x 30: named body points
_BODY = {
    "top of head": (30, 18), "head": (30, 21), "crown": (30, 18), "face": (30, 23), "eyes": (30, 22), "mouth": (30, 25),
    "throat": (30, 29), "neck": (30, 29), "shoulder": (22, 32), "shoulders": (22, 32), "chest": (30, 36), "heart": (32, 36),
    "arm": (18, 39), "arms": (18, 39), "elbow": (17, 41), "wrist": (15, 46), "forearm": (16, 44), "hand": (14, 48), "hands": (14, 48),
    "torso": (30, 41), "stomach": (30, 43), "abdomen": (30, 43), "side": (26, 44), "waist": (30, 47), "hips": (30, 49), "back": (30, 40),
    "legs": (26, 58), "leg": (26, 58), "thigh": (26, 55), "knee": (25, 59), "shin": (24, 64), "calf": (24, 64), "feet": (23, 69), "foot": (23, 69),
}


def _outline(pen: Pen, shape: str, cx: float, cy: float, rx: float, ry: float) -> None:
    if shape == "person":
        pen.base(_circle(30, 21, 4))
        pen.base(_line(30, 26, 30, 49))
        pen.base(_line(20, 31, 40, 31))
        pen.base(_line(20, 31, 14, 47))
        pen.base(_line(40, 31, 46, 47))
        pen.base(_line(30, 49, 23, 69))
        pen.base(_line(30, 49, 37, 69))
    elif shape == "circle":
        pen.base(_circle(cx, cy, min(rx, ry)))
    elif shape == "oval":
        pen.base(_poly([(cx + rx * math.cos(a), cy + ry * 0.75 * math.sin(a)) for a in (2 * math.pi * k / 16 for k in range(16))]))
    elif shape == "diamond":
        pen.base(_poly([(cx, cy - ry), (cx + rx, cy), (cx, cy + ry), (cx - rx, cy)]))
    elif shape == "heart":
        pts = [(16 * math.sin(t) ** 3, -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t))) for t in (2 * math.pi * k / 16 for k in range(16))]
        pen.base(_poly([(cx + x / 17 * rx, cy + 2 + y / 17 * ry) for x, y in pts]))
    elif shape == "cylinder":
        top = [(cx + rx * 0.8 * math.cos(a), cy - ry + 4 * math.sin(a)) for a in (2 * math.pi * k / 12 for k in range(12))]
        pen.base(_poly(top))
        pen.base(_line(cx - rx * 0.8, cy - ry, cx - rx * 0.8, cy + ry))
        pen.base(_line(cx + rx * 0.8, cy - ry, cx + rx * 0.8, cy + ry))
        pen.base(_line(cx - rx * 0.8, cy + ry, cx + rx * 0.8, cy + ry))
    elif shape != "none":
        pen.base(_rect(cx - rx, cy - ry, 2 * rx + 1, 2 * ry + 1))


def _anchor(part: Item, shape: str, cx, cy, rx, ry, k: int, n: int) -> tuple[float, float]:
    on = (part.on or "").replace("_", " ").replace("centre", "center").strip()
    if shape == "person":
        side = -1 if "right" in on else 1 if "left" in on else 0  # facing him: its right is on his left
        for name, (x, y) in sorted(_BODY.items(), key=lambda kv: -len(kv[0])):
            if name in on or (not on and name in part.label.lower()):
                return (x if x == 30 or not side else 30 + side * abs(30 - x)), y
        return 30, 26 + 40 * (k + 0.5) / max(1, n)
    if _EDGE.search(on) or (not on and _EDGE.search(part.label.lower())):
        a = -math.pi / 3 + k * 0.7
        return cx + rx * math.cos(a), cy + ry * math.sin(a) * (0.75 if shape == "oval" else 1)
    key = on.replace(" ", "-")
    for name, (fx, fy) in _ANCHORS.items():
        if key == name or key.replace("-", "") == name.replace("-", ""):
            return cx + fx * rx, cy + fy * ry
    for name, (fx, fy) in _ANCHORS.items():
        if name in key.split("-"):
            return cx + fx * rx, cy + fy * ry
    # nowhere said: spread inside
    a = 2 * math.pi * k / max(1, n)
    return cx + 0.45 * rx * math.cos(a), cy + 0.45 * ry * math.sin(a)


def _parts(pen: Pen, spec: Spec) -> None:
    shape = spec.shape or ("person" if any(p.on and any(b in p.on for b in ("head", "throat", "wrist", "waist", "chest", "hand", "feet", "legs")) for p in spec.items) else "box")
    cx, cy, rx, ry = 30, 44, 24, 25
    if shape == "circle":
        rx = ry = 25
    _outline(pen, shape, cx, cy, rx, ry)
    parts = spec.items[: LIMIT["parts"]]
    anchors = [_anchor(p, shape, cx, cy, rx, ry, k, len(parts)) for k, p in enumerate(parts)]
    # two parts on one spot: side by side, not on top of each other
    seen: dict[tuple[int, int], int] = {}
    for k, (x, y) in enumerate(anchors):
        key = (round(x / 3), round(y / 3))
        if key in seen and not (parts[k].shape in ("circle", "oval") and parts[k].on in ("center", "centre", "core", "middle")):
            seen[key] += 1
            anchors[k] = (x + 5 * seen[key], y + 3 * seen[key])
        else:
            seen.setdefault(key, 0)
    # the labels in one column on the right, in the order of their parts, top to bottom
    lx = 60 if shape != "person" else 56
    order = sorted(range(len(parts)), key=lambda k: anchors[k][1])
    rows = spread(len(parts), TOP, BOTTOM - 5) if len(parts) > 1 else [anchors[0][1] - 2]
    want = {k: min(max(anchors[k][1] - 2, TOP), BOTTOM - 5) for k in order}
    ys = {}
    last = TOP - 7
    for k, row in zip(order, rows):
        y = max(want[k], last + 7) if len(parts) * 7 <= BOTTOM - TOP else row
        ys[k] = y
        last = y
    over = last - (BOTTOM - 5)
    if over > 0:
        for k in order:
            ys[k] = max(TOP, ys[k] - over)
        last = TOP - 7
        for k in order:
            ys[k] = max(ys[k], last + 7)
            last = ys[k]
    rings = 0
    for k, part in enumerate(parts):
        el = pen.element(part.label)
        x, y = anchors[k]
        if part.shape in ("circle", "oval") and (part.on or "") in ("center", "centre", "core", "middle", ""):
            # layers inside layers: each ring inside the last
            rings += 1
            r = max(3, min(rx, ry) * (1 - 0.3 * rings))
            pen.add(el, _circle(cx, cy, r, "cyan") if part.shape == "circle" else _poly([(cx + r * 1.3 * math.cos(a), cy + r * 0.7 * math.sin(a)) for a in (2 * math.pi * j / 12 for j in range(12))], "cyan"))
            x, y = cx + r * 0.7, cy - r * 0.7
        elif part.shape in ("circle", "oval", "box", "round", "diamond", "cylinder"):
            if part.shape == "circle":
                pen.add(el, _circle(x, y, 4, "cyan"))
            elif part.shape == "oval":
                pen.add(el, _poly([(x + 6 * math.cos(a), y + 3 * math.sin(a)) for a in (2 * math.pi * j / 12 for j in range(12))], "cyan"))
            elif part.shape == "diamond":
                pen.add(el, _poly([(x, y - 4), (x + 4, y), (x, y + 4), (x - 4, y)], "cyan"))
            else:
                pen.add(el, _rect(x - 4, y - 3, 9, 7, "cyan"))
        elif part.shape == "dot":
            for dx, dy in ((0, 0), (3, 2), (-3, 2)):
                pen.add(el, _dot(x + dx, y + dy, 1, "cyan"))
        pen.add(el, _dot(x, y, 1, "amber"))
        pen.add(el, _line(x + 2, y, lx - 2, ys[k] + 2, "accent"))
        pen.add(el, _label(lx, ys[k], caps(part.label, RIGHT - lx), "white"))


def _outline_text(pen: Pen, spec: Spec) -> None:
    """Structured text: headings, a few words under each."""
    rows = []
    for it in spec.items:
        rows.append((it, 0))
        rows += [(kid, 1) for kid in it.items[:4]]
    two = len(rows) > 9
    col_w = (RIGHT - LEFT + 1) / (2 if two else 1)
    per = 9
    head: Element | None = None
    for k, (it, depth) in enumerate(rows[: per * (2 if two else 1)]):
        x = LEFT + (k // per) * col_w + depth * 5
        y = TOP + (k % per) * 6 + 1
        el = pen.element(it.label, needs=(head.id,) if depth and head else ())
        if depth == 0:
            head = el
        text = caps(it.label, col_w - depth * 5 - 3)
        if depth:
            pen.add(el, _dot(x - 3, y + 2, 1, "accent"))
        pen.add(el, _label(x, y, text, "amber" if depth == 0 else "white"))


def _short(v: float, unit: str) -> str:
    a = abs(v)
    s = f"{v / 1e12:.1f}T" if a >= 1e12 else f"{v / 1e9:.1f}B" if a >= 1e9 else f"{v / 1e6:.1f}M" if a >= 1e6 else f"{v / 1e3:.0f}K" if a >= 1e5 else f"{v:.0f}" if a >= 100 else f"{v:.0f}" if v == int(v) else f"{v:.1f}"
    s = s.replace(".0T", "T").replace(".0B", "B").replace(".0M", "M")
    u = unit.strip()
    if u.lower() in ("$", "usd", "us$", "dollars", "dollar"):
        return f"${s}"
    if u in ("€", "£", "¥", "eur", "gbp"):
        return {"eur": "€", "gbp": "£"}.get(u, u) + s
    if u in ("%", "percent"):
        return f"{s}%"
    if u.lower() in ("°c", "c", "celsius", "degrees"):
        return f"{s}°C" if u.lower() != "degrees" else f"{s}°"
    return s


def _line_chart(pen: Pen, spec: Spec) -> None:
    pts = spec.points
    if len(pts) > 24:
        keep = sorted({round(k * (len(pts) - 1) / 23) for k in range(24)})
        pts = [pts[k] for k in keep]
    vals = [v for _, v in pts]
    lo, hi = min(vals), max(vals)
    if hi == lo:
        lo, hi = lo - 1, hi + 1
    top_s, low_s = _short(hi, spec.unit), _short(lo, spec.unit)
    ax = LEFT + max(width(top_s), width(low_s)) + 3
    y_top, y_bot = TOP + 7, 62
    x0, x1 = ax + 3, RIGHT - 2
    pen.base(_line(ax, TOP + 4, ax, y_bot + 1, "accent"))
    pen.base(_line(ax, y_bot + 1, RIGHT, y_bot + 1, "accent"))
    pen.base(_label(ax - 2, y_top - 2, top_s, "white", "right"))
    pen.base(_label(ax - 2, y_bot - 4, low_s, "white", "right"))
    xs = spread(len(pts), x0, x1)
    ys = [y_bot - (v - lo) / (hi - lo) * (y_bot - y_top) for v in vals]
    el = pen.element(spec.title)
    for k in range(len(pts)):
        if k:
            pen.add(el, _line(xs[k - 1], ys[k - 1], xs[k], ys[k], "cyan"))
        pen.add(el, _dot(xs[k], ys[k], 1, "amber"))
    # the first, the last and, when there's room, one between: under the axis
    marks = [0, len(pts) - 1]
    if len(pts) > 2:
        marks.insert(1, len(pts) // 2)
    for k in marks:
        text = caps(pts[k][0], 36)
        if not text:
            continue
        align = "left" if k == 0 else "right" if k == len(pts) - 1 else "center"
        x = xs[k] - 1 if k == 0 else xs[k] + 1 if k == len(pts) - 1 else xs[k]
        pen.add(el, _label(max(LEFT, x) if align == "left" else x, y_bot + 4, text, "white", align))
    last = pen.element(f"{pts[-1][0]} {_short(vals[-1], spec.unit)}")
    pen.add(last, _label(min(xs[-1], RIGHT) + 1, max(TOP, ys[-1] - 7), _short(vals[-1], spec.unit), "amber", "right"))


def _bar_chart(pen: Pen, spec: Spec) -> None:
    pts = spec.points[:8]
    top = max(abs(v) for _, v in pts) or 1
    lw = min(40, max(width(caps(lb, 40)) for lb, _ in pts) + 2)
    vw = max(width(_short(v, spec.unit)) for _, v in pts) + 3
    bar_x = LEFT + lw + 2
    room = RIGHT - bar_x - vw
    rh = min(9, (BOTTOM - TOP + 1) / len(pts))
    pen.base(_line(bar_x - 1, TOP, bar_x - 1, TOP + rh * len(pts) - 2, "accent"))
    for k, (lb, v) in enumerate(pts):
        y = TOP + k * rh
        el = pen.element(lb)
        w = max(1, round(abs(v) / top * room))
        pen.add(el, _label(bar_x - 3, y, caps(lb, lw), "white", "right"))
        pen.add(el, _rect(bar_x, y, w, min(5, rh - 2), "amber", fill=True))
        pen.add(el, _label(bar_x + w + 2, y, _short(v, spec.unit), "cyan"))


# ---- compiling ------------------------------------------------------------------------------


def compile(spec: Spec) -> Drawn:  # noqa: A001 - the spec's compiler
    """The spec laid out: every shape on the board, out of her face's corner."""
    if spec.layout in ("line", "bar"):
        if len(spec.points) < 2:
            raise SpecError("a chart needs at least two numbers")
    pen = Pen(spec.layout, spec.title)
    lay = {
        "flow": _flow, "graph": _graph, "cycle": lambda p, s: _ring(p, s, False), "radial": lambda p, s: _ring(p, s, True),
        "row": _containers, "compare": lambda p, s: _containers(p, s, compare=True), "column": _rows, "grid": _grid,
        "tree": _tree, "layers": _layers, "timeline": _timeline, "sequence": _sequence, "parts": _parts,
        "outline": _outline_text, "line": _line_chart, "bar": _bar_chart, "keywords": _outline_text,
    }.get(spec.layout)
    if lay is None:
        raise SpecError(f"no layout {spec.layout!r} to lay out")
    lay(pen, spec)
    drawn = pen.drawn
    shapes = drawn.shapes()
    if len(shapes) > MAX_SHAPES:
        # too much for the board: the last elements go
        while drawn.elements and len(drawn.shapes()) > MAX_SHAPES:
            drawn.elements.pop()
    if not drawn.elements:
        raise SpecError("nothing to draw")
    for s in drawn.shapes():
        _clamp(s)
    return drawn


def _clamp(s: dict) -> None:
    """Every coordinate on the board (a label's text is fitted where it is made)."""
    for k in ("x", "x1", "x2"):
        if k in s:
            s[k] = min(max(s[k], 0), W - 1)
    for k in ("y", "y1", "y2"):
        if k in s:
            s[k] = min(max(s[k], 0), H - 1)
    if "points" in s:
        s["points"] = [[min(max(x, 0), W - 1), min(max(y, 0), H - 1)] for x, y in s["points"]]


def _graph(pen: Pen, spec: Spec) -> None:
    """A node graph: columns by how far along the links a node is, arrows between."""
    nodes = spec.items
    index = {n.label.lower(): k for k, n in enumerate(nodes)}
    edges = []
    for a, b, _ in spec.links:
        ka, kb = _find(index, a), _find(index, b)
        if ka is not None and kb is not None and ka != kb:
            edges.append((ka, kb))
    # longest path from a source, ignoring any link that closes a loop
    layer = [0] * len(nodes)
    for _ in range(len(nodes)):
        for a, b in edges:
            if layer[b] < layer[a] + 1 <= len(nodes):
                layer[b] = layer[a] + 1
    top = max(layer)
    if top >= len(nodes) - 0 and top > 0:
        layer = [min(v, len(nodes) - 1) for v in layer]
    cols: dict[int, list[int]] = {}
    for k, v in enumerate(layer):
        cols.setdefault(v, []).append(k)
    order = sorted(cols)
    L = len(order)
    room = RIGHT - LEFT + 1
    # each column as wide as its longest word needs, when the board has the room (equal
    # thirds broke "PERFORMANCE" into "PERFORMA-" - live, a lecture board); the rest of
    # the width shared out evenly
    word = {k: max(width(w) for w in (caps(nodes[k].label, 10_000).split() or ["?"])) + 7 for k in range(len(nodes))}
    need = [max(word[k] for k in cols[key]) + 2 for key in order]
    boxes: dict[str, tuple[Element, Box]] = {}
    # too wide left to right for whole words: top to bottom instead, a layer per row, when
    # its words fit across and its rows fit down
    across = all(sum(word[k] for k in cols[key]) + 3 * (len(cols[key]) - 1) <= room for key in order)
    if sum(need) > room and across and 15 * L + 4 * (L - 1) <= BOTTOM - TOP + 1:
        ys = spread(L, TOP + 7, BOTTOM - 7)
        for r, key in enumerate(order):
            members = cols[key]
            n = len(members)
            for i, k in enumerate(members):
                el = pen.element(nodes[k].label)
                boxes[nodes[k].label.lower()] = (el, boxed(pen, el, LEFT + room * (i + 0.5) / n, ys[r], lines_for(nodes[k].label, room / n - 7, 2)))
        for a, b in edges:
            ea, eb = boxes[nodes[a].label.lower()], boxes[nodes[b].label.lower()]
            arrow_between(pen, eb[0] if layer[b] > layer[a] else pen.element("", needs=(ea[0].id, eb[0].id)), ea[1], eb[1])
        return
    if sum(need) <= room:
        spare = (room - sum(need)) / L
        widths = [n + spare for n in need]
    else:
        widths = [room / L] * L
    lefts = [LEFT + sum(widths[:c]) for c in range(L)]
    pos: dict[int, float] = {}
    for c, key in enumerate(order):
        members = cols[key]
        # under the nodes that lead to them: fewer crossings
        members.sort(key=lambda k: sum(pos.get(a, 0) for a, b in edges if b == k) / max(1, sum(1 for a, b in edges if b == k)) if any(b == k for _, b in edges) else k)
        rows = 2 if len(members) <= 3 else 1
        ys = spread(len(members), TOP + 6, BOTTOM - 6)
        for k, y in zip(members, ys):
            pos[k] = y
            el = pen.element(nodes[k].label)
            boxes[nodes[k].label.lower()] = (el, boxed(pen, el, lefts[c] + widths[c] / 2, y, lines_for(nodes[k].label, widths[c] - 7, rows)))
    for a, b in edges:
        ea, eb = boxes[nodes[a].label.lower()], boxes[nodes[b].label.lower()]
        arrow_between(pen, eb[0] if layer[b] > layer[a] else pen.element("", needs=(ea[0].id, eb[0].id)), ea[1], eb[1])


# ---- live data: only the real numbers ---------------------------------------------------------

LIVE = re.compile(
    r"\b(prices?|stocks?|shares?|share price|market|markets|nasdaq|dow|s&p|crypto|bitcoin|btc|ethereum|gold|silver|oil|forex|exchange rate|"
    r"weather|temperature|forecast|rain|inflation|interest rate|mortgage rate|score|standings|polls?|gpu prices?|"
    r"this (?:week|month|year)|today|right now|currently|latest|so far)\b",
    re.I,
)
_NUM = re.compile(r"(?<![\w.])-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])-?\d+(?:\.\d+)?")


def source_numbers(text: str) -> list[float]:
    return [float(m.group(0).replace(",", "")) for m in _NUM.finditer(text or "")]


def numbers(spec: Spec, question: str, sources: str | None, series: str | None = None) -> str | None:
    """Why a chart's numbers can't be drawn, or None. Researched: every number must be
    one the pages give (to half a percent - she rounds 2,654.37 to 2,654) - and when
    research fetched the real series, one THAT gives (live: three invented NVIDIA
    prices matched stray numbers on the pages). Not researched: numbers that change
    (a price, a stock, the weather) aren't drawn."""
    if spec.layout not in ("line", "bar"):
        return None
    about = f"{question} {spec.title}"
    if sources is None:
        return "live numbers without research" if LIVE.search(about) else None
    have = source_numbers(series if series else sources)
    scaled = have + [h * s for h in have for s in (1e3, 1e6, 1e9, 1e12)]
    # to half a percent, or to the unit when she rounded to a whole number
    near = lambda v: max(0.005 * abs(v), 1.0 if v == int(v) and abs(v) >= 10 else 0.01)  # noqa: E731
    missing = [v for _, v in spec.points if not any(abs(h - v) <= near(v) for h in scaled)]
    if missing:
        return f"{len(missing)} of {len(spec.points)} numbers not in the pages she read ({', '.join(_short(v, spec.unit) for v in missing[:3])})"
    return None


_SERIES_ROW = re.compile(r"^((?:[A-Z][a-z]{2} )?(?:[A-Z][a-z]{2} \d{1,2}|[A-Z][a-z]{2} \d{4}|\d\d:\d\d)): (?:high )?(-?[\d,]+(?:\.\d+)?)", re.M)


def series_chart(text: str, question: str = "") -> Spec | None:
    """The real series research fetched (tools/series.py), as a line chart - what the
    board shows when her own chart of it can't be drawn. None if it holds no rows."""
    points = [(m.group(1), float(m.group(2).replace(",", ""))) for m in _SERIES_ROW.finditer(text or "")]
    if len(points) < 2:
        return None
    head = (text or "").splitlines()[0]
    name = re.sub(r"\s*\(.*$|,.*$|:$", "", head).replace("Weather forecast for", "").strip() or question
    weather = "open-meteo" in head.lower() or "forecast" in head.lower()
    unit = "°C" if weather else "$" if "USD" in head else ""
    return Spec("line", caps(f"{name} highs" if weather else name, 96), points=points, unit=unit, chart="line", fixed=["charted from the series"])


# ---- the board as he hears it -------------------------------------------------------------------


def _words(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z0-9]+", plain(text).lower().replace("'", "")):
        if w in _STOP or (len(w) < 3 and not w.isdigit()):
            continue
        out.add(w[:5])
    return out


class SpecBoard:
    """One answer's drawing, element by element as she names it; the rest as the
    answer ends. Every message carries the whole drawing so far (board_sync
    spec/set, stable ids: the HUD keeps the moment each shape first appeared)."""

    def __init__(self, drawn: Drawn):
        self.drawn = drawn
        self.kind = drawn.kind
        self.shown: set[str] = set()
        self.started = False
        self._by_id = {e.id: e for e in drawn.elements}
        # an element that only joins others (an arrow between two boxes) has no name
        self._keys = {e.id: set() if _joins(e) else _words(e.label) for e in drawn.elements}

    def _named(self, sentence: str) -> set[str]:
        said = _words(sentence)
        hit = {e for e, keys in self._keys.items() if keys and len(keys & said) >= max(1, math.ceil(len(keys) / 2))}
        if hit and self.drawn.ordered:
            last = max(self._by_id[e].order for e in hit)
            hit |= {e.id for e in self.drawn.elements if e.order <= last}
        # a node named before its parent brings the parent up with it
        todo = list(hit)
        while todo:
            for n in self._by_id[todo.pop()].needs:
                if n not in hit:
                    hit.add(n)
                    todo.append(n)
        return hit

    def _settle(self) -> None:
        # what only joins others goes up once they are up
        for e in self.drawn.elements:
            if e.id not in self.shown and _joins(e) and all(n in self.shown for n in e.needs):
                self.shown.add(e.id)

    def _message(self, fresh: bool) -> dict:
        shapes = self.drawn.shapes(self.shown)
        if fresh or not self.started:
            self.started = True
            return {"type": "board_sync", "spec": {"shapes": shapes}}
        return {"type": "board_sync", "set": {"shapes": shapes}}

    def step(self, sentence: str, terms=()) -> dict | None:
        new = self._named(sentence) - self.shown
        if not new and self.started:
            return None
        self.shown |= new
        self._settle()
        return self._message(False)

    def snapshot(self) -> dict:
        """The drawing as it stands, as a new board (it arrived mid-answer)."""
        self._settle()
        return self._message(True)

    def finish(self) -> dict | None:
        rest = {e.id for e in self.drawn.elements} - self.shown
        if not rest and self.started:
            return None
        self.shown |= rest
        return self._message(False)


def _joins(e: Element) -> bool:
    return bool(e.needs) and all(s["type"] in ("arrow", "line") for s in e.shapes)


# ---- sections: the board split into a few panels, each its own small drawing -------------------
#
# A reusable structure, not a topic recipe: N side-by-side panels with a short
# header, each holding one of three small forms - a line chart with its arrow
# and change ("chart"), a sky icon with its numbers ("sky"), an icon with two or
# three key words ("story"). The daily briefing uses it (tools/briefing.py); the
# numbers it is given are the fetched ones, never hers.


@dataclass
class Section:
    header: str
    kind: str  # chart | sky | story
    points: list[tuple[str, float]] = field(default_factory=list)
    up: bool | None = None
    change: str = ""
    value: str = ""
    icon: str = ""
    lines: list[str] = field(default_factory=list)


SECTION_ICONS = ("sun", "cloud", "rain", "snow", "storm", "music", "lightbulb", "warning", "check", "cross", "heart", "star", "clock", "question")


def _sprite(x, y, name, scale=1) -> dict:
    return {"type": "sprite", "x": round(x), "y": round(y), "name": name, "scale": scale}


def _section_chart(pen: Pen, el: Element, s: Section, x0: float, x1: float) -> None:
    vals = [v for _, v in s.points]
    if len(vals) > 12:
        keep = sorted({round(k * (len(vals) - 1) / 11) for k in range(12)})
        vals = [vals[k] for k in keep]
    if len(vals) >= 2:
        lo, hi = min(vals), max(vals)
        if hi == lo:
            lo, hi = lo - 1, hi + 1
        y_top, y_bot = TOP + 10, TOP + 30
        pen.add(el, _line(x0 + 1, y_bot + 1, x1 - 1, y_bot + 1, "accent", level=0.5))
        xs = spread(len(vals), x0 + 2, x1 - 3)
        ys = [y_bot - (v - lo) / (hi - lo) * (y_bot - y_top) for v in vals]
        for k in range(1, len(vals)):
            pen.add(el, _line(xs[k - 1], ys[k - 1], xs[k], ys[k], "cyan"))
        pen.add(el, _dot(xs[-1], ys[-1], 1, "amber"))
    cx = (x0 + x1) / 2
    color = "cyan" if s.up else "red" if s.up is not None else "white"
    if s.up is not None:
        ax = x0 + 4
        pen.add(el, _arrow(ax, TOP + 43, ax, TOP + 35, color) if s.up else _arrow(ax, TOP + 35, ax, TOP + 43, color))
        pen.add(el, _label(ax + 4, TOP + 37, caps(s.change, x1 - ax - 5), color))
    elif s.change:
        pen.add(el, _label(cx, TOP + 37, caps(s.change, x1 - x0 - 2), color, "center"))
    if s.value:
        pen.add(el, _label(cx, TOP + 48, caps(s.value, x1 - x0 - 2), "white", "center"))


def _section_sky(pen: Pen, el: Element, s: Section, x0: float, x1: float) -> None:
    cx = (x0 + x1) / 2
    pen.add(el, _sprite(cx - 9, TOP + 9, s.icon if s.icon in SECTION_ICONS else "cloud", 2))
    for k, line in enumerate(s.lines[:2]):
        pen.add(el, _label(cx, TOP + 31 + 8 * k, caps(line, x1 - x0 - 2), "white" if k == 0 else "cyan", "center"))


def _section_story(pen: Pen, el: Element, s: Section, x0: float, x1: float) -> None:
    cx = (x0 + x1) / 2
    pen.add(el, _sprite(cx - 9, TOP + 9, s.icon if s.icon in SECTION_ICONS else "star", 2))
    for k, line in enumerate(s.lines[:3]):
        pen.add(el, _label(cx, TOP + 31 + 7 * k, caps(line, x1 - x0 - 2), "white", "center"))


def sections(parts: list[Section], title: str = "") -> Drawn:
    """The board in len(parts) panels, one element each (it appears whole, as she
    reaches it)."""
    if not parts:
        raise SpecError("nothing to draw")
    pen = Pen("sections", title)
    n = len(parts)
    w = (RIGHT - LEFT + 1) / n
    for k in range(1, n):
        x = LEFT + w * k - 1
        pen.base(_line(x, TOP, x, BOTTOM, "accent", dashed=True, level=0.5))
    lay = {"chart": _section_chart, "sky": _section_sky, "story": _section_story}
    for k, part in enumerate(parts):
        x0, x1 = LEFT + w * k + 1, LEFT + w * (k + 1) - 3
        el = pen.element(part.header)
        pen.add(el, _label((x0 + x1) / 2, TOP + 1, caps(part.header, x1 - x0), "amber", "center"))
        lay.get(part.kind, _section_story)(pen, el, part, x0, x1)
    drawn = pen.drawn
    for s in drawn.shapes():
        _clamp(s)
    return drawn


class SectionBoard(SpecBoard):
    """A sections drawing as he hears it: one panel per sentence, in order - the
    k-th sentence she says brings up the k-th panel; the rest stay up at the end."""

    def __init__(self, drawn: Drawn):
        super().__init__(drawn)
        self._steps = 0

    def _named(self, sentence: str) -> set[str]:
        self._steps += 1
        els = self.drawn.elements
        return {els[self._steps - 1].id} if self._steps <= len(els) else set()


def keywords(question: str, said: list[str], title: str) -> Drawn:
    """The fallback when her drawing can't be drawn: her key words, as structured text."""
    items = []
    for s in said:
        g = gist(s, px=110)
        if g and g not in {i.label for i in items} and len(items) < 8:
            items.append(Item(g))
    if not items:
        items = [Item(caps(title or question, 110) or "?")]
    spec = Spec("keywords", title, items)
    return compile(spec)


def record(question: str, origin: str, raw: object, outcome: str, why: str = "", kind: str = "", fixed: list[str] | None = None) -> None:
    """Every drawing she wrote, and what came of it (logs/draw-specs.jsonl) - how
    often a spec is invalid, and why."""
    row = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "question": question[:160], "origin": origin, "outcome": outcome, "why": why, "kind": kind, "fixed": fixed or []}
    row["spec"] = raw if isinstance(raw, (dict, list)) else str(raw)[:600]
    try:
        LOG_PATH.parent.mkdir(exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        log.warning("could not write %s", LOG_PATH)
    (log.warning if outcome == "invalid" else log.info)("draw spec %s (%s)%s%s", outcome, origin, f": {why}" if why else "", f" [{kind}]" if kind else "")
