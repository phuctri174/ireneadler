"""The illustration board, core side: the <draw> tag.

A reply may carry one <draw>{json}</draw>: a drawing she composed (a spec,
laid out by drawing.py - Round 8, how every explanation is drawn), a template
from config/board.json with its arguments (the live widgets: a clock, his
schedule, the PC's load...), or freehand {"shapes": [...]}. It is never spoken or
displayed as text. Core checks what it can cheaply - that it is JSON, names a known template or
has shapes, and has the template's required arguments - and sends it to the HUD,
which checks everything exactly (a legal FEN, labels that fit) and draws nothing
at all if anything is wrong. Invalid here means nothing is sent.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from . import drawing

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "board.json"
# the templates the model may draw; "internal" ones are core's own (the research
# terms board) - never offered to the model, and refused if it writes one
TEMPLATES: dict[str, dict] = {t["name"]: t for t in json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))["templates"] if not t.get("internal")}
# the ones still offered to her; a retired one (a topic recipe, or what her own
# specs now do) still draws if she writes it
OFFERED: dict[str, dict] = {n: t for n, t in TEMPLATES.items() if not t.get("retired")}
SHAPES = ("line", "arrow", "rect", "circle", "dot", "label", "grid", "sprite", "polygon")

DRAW = re.compile(r"<draw>(.*?)</draw>", re.S | re.I)
# a <draw> the model opened but never closed: everything after it is the drawing
DRAW_OPEN = re.compile(r"<draw>.*\Z", re.S | re.I)
# her drawing written in the wrong tag (live: two probes in fifteen): a <display>
# holding nothing but a spec is the drawing, never text on the panel
DISPLAY_SPEC = re.compile(r"<display>\s*(?:```(?:json)?\s*)?(\{.*?\})\s*(?:```\s*)?</display>", re.S | re.I)


@dataclass(frozen=True)
class Draw:
    spec: dict | None
    error: str | None = None
    # what she wrote, when it couldn't be read (for the log)
    raw: object = None


def _loads(text: str) -> object:
    text = text.strip()
    # models wrap JSON in a code fence now and then
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    return json.loads(text)


def check(spec: object) -> str | None:
    """Why this spec can't be drawn, or None. A composed spec is checked in full
    where it is laid out (drawing.read), with the question it answers."""
    if not isinstance(spec, dict):
        return "a drawing must be a JSON object"
    if drawing.is_spec(spec):
        return None
    name = spec.get("template")
    if name is not None:
        if name not in TEMPLATES:
            return f"no template {name!r}"
        missing = [k for k in TEMPLATES[name].get("required", []) if k not in spec]
        return f"{name} needs {', '.join(missing)}" if missing else None
    shapes = spec.get("shapes")
    if not isinstance(shapes, list) or not shapes:
        return "a drawing needs a template or a list of shapes"
    # a sketch keeps the shapes it can draw; one with none of them is refused
    if not any(isinstance(s, dict) and s.get("type") in SHAPES for s in shapes):
        return f"no drawable shapes: each needs a type ({', '.join(SHAPES)})"
    return None


def normalize(spec: object) -> object:
    """The unambiguous ways a model writes a template wrongly, made right:
    {"calendar": {...}}, {"type": "calendar", ...} and a template listed as the only
    freehand shape, {"shapes": [{"type": "stack", ...}]}. Anything else is left alone."""
    if not isinstance(spec, dict) or "template" in spec:
        return spec
    if len(spec) == 1:
        (name, args), = spec.items()
        if name in TEMPLATES and isinstance(args, dict):
            return {"template": name, **args}
    if spec.get("type") in TEMPLATES:
        rest = {k: v for k, v in spec.items() if k != "type"}
        return {"template": spec["type"], **rest}
    shapes = spec.get("shapes")
    if isinstance(shapes, list) and shapes and isinstance(shapes[0], dict) and shapes[0].get("type") in TEMPLATES:
        first = {k: v for k, v in shapes[0].items() if k != "type"}
        return {"template": shapes[0]["type"], **first}
    return spec


def _spec_in_display(raw: str) -> re.Match | None:
    for m in DISPLAY_SPEC.finditer(raw):
        try:
            if drawing.is_spec(json.loads(m.group(1))):
                return m
        except json.JSONDecodeError:
            continue
    return None


def parse(raw: str) -> Draw | None:
    """The reply's drawing: None if it has no <draw>, else a Draw (spec, or the error)."""
    m = DRAW.search(raw) or _spec_in_display(raw)
    if not m:
        return None
    try:
        spec = normalize(_loads(m.group(1)))
    except json.JSONDecodeError as error:
        return Draw(None, f"not JSON: {error.msg}", m.group(1))
    why = check(spec)
    return Draw(None, why, spec) if why else Draw(spec)


def strip(text: str) -> str:
    """Text without its <draw> block (closed or not), or a spec written as <display>."""
    text = DRAW_OPEN.sub("", DRAW.sub("", text))
    m = _spec_in_display(text)
    while m:
        text = text[: m.start()] + text[m.end() :]
        m = _spec_in_display(text)
    return text


_REGISTRY = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
_REQUEST = re.compile(_REGISTRY["request"], re.I)
_HINTS = {name: re.compile(t["hint"], re.I) for name, t in OFFERED.items() if t.get("hint")}


def wanted(text: str) -> str | None:
    """For a message asking for a picture: the template it names ("shapes" if none
    fits), else None. The longest keyword match wins, so "plot my chess rating"
    is a line chart, not a chessboard."""
    if not _REQUEST.search(text):
        return None
    best, length = None, 0
    for name, hint in _HINTS.items():
        for m in hint.finditer(text):
            if len(m.group(0)) > length:
                best, length = name, len(m.group(0))
    return best or "shapes"


def hint(text: str) -> str | None:
    """The line the prompt's Now section gets for a drawing request."""
    name = wanted(text)
    if name is None:
        return None
    if name == "shapes":
        return ("He is asking for a picture: after </speak>, compose it - one <draw>{...}</draw> spec, its form picked from "
                "what it shows (see Your drawing board). A copyrighted character or a logo: a generic stand-in, and say so.")
    return f'He is asking for a picture: after </speak>, draw it with the {name} template: <draw>{{"template": "{name}", ...}}</draw>.'


def catalogue() -> str:
    """The model's view of the templates: one line each, grouped by family."""
    families: dict[str, list[str]] = {}
    for t in OFFERED.values():
        families.setdefault(t["family"], []).append(f"- {t['name']}({t['args']}) - {t['when']}")
    return "\n".join(line for family in families.values() for line in family)


BOARD_SECTION = """## Drawing board: widgets

Besides the drawings you compose (Your drawing board, above), the board has live
widgets for his own things - a template with its arguments, after the </speak>:
    <draw>{{"template": "calendar", "month": "2026-09"}}</draw>
{catalogue}

A picture of an object (a house, a cat): freehand shapes on the 128x72 grid (x
0-127 right, y 0-71 down; keep clear of x>100, y<16 - your face is there):
{{"shapes": [{{"type": ...}}]}} with line/arrow (x1,y1,x2,y2), rect (x,y,w,h,fill?),
circle (x,y,r,fill?), polygon (points [[x,y],...]), dot (x,y,r?), label (x,y,text),
each with color? (accent, white, amber, pink, red, cyan). Never a copyrighted
character or a logo: a generic stand-in instead. No drawing for chat, advice,
opinions or feelings."""


def board_section() -> str:
    return BOARD_SECTION.format(catalogue=catalogue())
