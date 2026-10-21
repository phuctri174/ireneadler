// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// The illustration board. When Irene explains something visually her face shrinks
// to the top-right corner (still emoting) and the rest of the matrix becomes a
// drawing board. A drawing arrives from core as the JSON of a <draw> tag:
//
//   { "template": "chessboard", "fen": "...", ... }   accurate things, by template
//   { "shapes": [ { "type": "line", ... }, ... ] }     freehand, from primitives
//
// prepare() checks it completely first - an unknown template, a bad argument, an
// illegal FEN - and returns null for anything it can't draw exactly: nothing is
// drawn, nothing throws. Templates live one per module in board/templates/ and
// are found there automatically; config/board.json describes them to the model.

import { COLS, ROWS } from "../led/grid";
import type { Frame } from "../led/grid";
import { ICONS } from "./icons";
import { FACE_CORNER, iconStrokes } from "./kit";
import type { RenderContext } from "./kit";
import type { Stroke } from "./strokes";
import { drawStroke, schedule } from "./strokes";
import { TEMPLATES } from "./templates/index";
import { BoardError, bool, list, num, obj, str } from "./validate";
import type { Args } from "./validate";

export { FACE_CORNER };

export interface Prepared {
  kind: "template" | "shapes";
  name: string;
  args: unknown;
  // illustrating her answer (core/irene/illustrate.py): the drawing's labels show
  // only once she has named them, each glowing amber as it appears
  sync?: { labels: string[]; reveal: { key: string; at: number }[] };
}

const LABEL_FRESH_MS = 1400;

/** A labelled drawing's labels as she names them: unnamed ones hidden, new ones amber. */
function revealLabels(strokes: Stroke[], sync: NonNullable<Prepared["sync"]>, t: number): Stroke[] {
  const out: Stroke[] = [];
  for (const s of strokes) {
    // "DŌ" is the do: compared without its macron
    const key = s.kind === "text" ? s.text.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "") : "";
    if (!key || !sync.labels.includes(key)) {
      out.push(s);
      continue;
    }
    const named = sync.reveal.find((r) => r.key === key && r.at <= t);
    if (!named) continue;
    out.push(t - named.at < LABEL_FRESH_MS ? { ...s, color: "amber" } : s);
  }
  return out;
}

function syncOf(s: Args): Prepared["sync"] {
  if (s.sync !== true || !Array.isArray(s.labels)) return undefined;
  const reveal = (Array.isArray(s.reveal) ? s.reveal : []).map((raw, i) => {
    const r = obj(raw, `reveal[${i}]`);
    return { key: str(r, "key", { max: 24 }).toLowerCase(), at: num(r, "at", { min: 0, max: 600000, def: 0 }) };
  });
  return { labels: s.labels.map((l) => String(l).toLowerCase()), reveal };
}

// ---- freehand primitives -----------------------------------------------------------

const COLOR_NAMES = ["accent", "white", "amber", "pink", "red", "cyan"] as const;
// a composed drawing (core/irene/drawing.py) sends at most 240
const MAX_SHAPES = 240;
// a composed drawing's newest labels glow amber this long (core/irene/compose.py)
const SHAPE_FRESH_MS = 1400;
// how long one composed shape takes to sketch itself in
const SHAPE_DRAW_MS = 420;

function color(a: Args) {
  // "fill": "red" is a model's way of saying fill it, in red
  const raw = a.color ?? (typeof a.fill === "string" ? a.fill : undefined);
  if (raw === undefined) return undefined;
  const name = String(raw).toLowerCase();
  return ((COLOR_NAMES as readonly string[]).includes(name) ? name : name === "grey" || name === "gray" || name === "black" ? "white" : "accent") as Stroke["color"];
}

function filled(a: Args): boolean {
  return typeof a.fill === "string" ? true : bool(a, "fill");
}

/** A freehand coordinate or size: a sketch, so off-grid values are pulled onto it. */
function coord(a: Args, key: string, max: number, def?: number): number {
  return Math.min(max + 8, Math.max(-8, num(a, key, { def })));
}

function shape(raw: unknown, i: number): Stroke[] {
  const a = obj(raw, `shapes[${i}]`);
  // composed as she speaks: every stroke of the shape appears at its `at`
  const at = a.at === undefined ? undefined : num(a, "at", { min: 0, max: 600000 });
  return at === undefined ? shapeStrokes(a, i) : shapeStrokes(a, i).map((s) => ({ ...s, at }));
}

function shapeStrokes(a: Args, i: number): Stroke[] {
  const type = str(a, "type", { oneOf: ["line", "arrow", "rect", "circle", "label", "grid", "sprite", "dot", "polygon"] });
  const c = color(a);
  switch (type) {
    case "line":
    case "arrow":
      return [{ kind: type, x1: coord(a, "x1", COLS), y1: coord(a, "y1", ROWS), x2: coord(a, "x2", COLS), y2: coord(a, "y2", ROWS), color: c, ...(type === "line" && bool(a, "dashed") ? { dash: 2 } : {}), ...(a.level !== undefined ? { level: num(a, "level", { min: 0.1, max: 1 }) } : {}) }];
    case "rect": {
      const r = { x: coord(a, "x", COLS), y: coord(a, "y", ROWS), w: Math.max(1, Math.min(COLS, num(a, "w"))), h: Math.max(1, Math.min(ROWS, num(a, "h"))) };
      return filled(a) ? [{ kind: "fill", ...r, color: c }, { kind: "rect", ...r, color: c }] : [{ kind: "rect", ...r, color: c }];
    }
    case "circle": {
      const s = { x: coord(a, "x", COLS), y: coord(a, "y", ROWS), r: Math.max(1, Math.min(40, num(a, "r"))) };
      return filled(a) ? [{ kind: "disc", ...s, color: c, level: 0.35 }, { kind: "circle", ...s, color: c }] : [{ kind: "circle", ...s, color: c }];
    }
    case "dot":
      return [{ kind: "disc", x: coord(a, "x", COLS), y: coord(a, "y", ROWS), r: num(a, "r", { min: 0, max: 6, def: 1 }), color: c }];
    case "label":
      return [{ kind: "text", x: coord(a, "x", COLS), y: coord(a, "y", ROWS), text: str(a, "text", { max: 32 }), size: num(a, "size", { min: 1, max: 2, def: 1, int: true }), align: str(a, "align", { def: "left", oneOf: ["left", "center", "right"] }) as "left", color: c }];
    case "grid": {
      const x = coord(a, "x", COLS);
      const y = coord(a, "y", ROWS);
      const w = num(a, "w", { min: 2, max: COLS });
      const h = num(a, "h", { min: 2, max: ROWS });
      const cols = num(a, "cols", { min: 1, max: 32, int: true });
      const rows = num(a, "rows", { min: 1, max: 24, int: true });
      const out: Stroke[] = [];
      for (let k = 0; k <= cols; k += 1) out.push({ kind: "line", x1: x + (w * k) / cols, y1: y, x2: x + (w * k) / cols, y2: y + h, color: c, level: 0.5 });
      for (let k = 0; k <= rows; k += 1) out.push({ kind: "line", x1: x, y1: y + (h * k) / rows, x2: x + w, y2: y + (h * k) / rows, color: c, level: 0.5 });
      return out;
    }
    case "polygon": {
      const pts = list(a, "points", { min: 2, max: 16 }).map((p, k) => {
        if (!Array.isArray(p) || p.length !== 2 || typeof p[0] !== "number" || typeof p[1] !== "number") throw new BoardError(`shapes[${i}].points[${k}] must be [x, y]`);
        return { x: Math.min(COLS + 8, Math.max(-8, p[0])), y: Math.min(ROWS + 8, Math.max(-8, p[1])) };
      });
      return pts.map((p, k) => {
        const q = pts[(k + 1) % pts.length];
        return { kind: "line" as const, x1: p.x, y1: p.y, x2: q.x, y2: q.y, color: c };
      });
    }
    case "sprite":
      return iconStrokes(str(a, "name", { oneOf: Object.keys(ICONS) }), coord(a, "x", COLS), coord(a, "y", ROWS), num(a, "scale", { min: 1, max: 4, def: 1, int: true }));
  }
  throw new BoardError(`unknown shape ${type}`);
}

function parseShapes(spec: Args): Stroke[] {
  // a sketch keeps the shapes it can draw; only a sketch with none of them is refused
  const raw = list(spec, "shapes", { min: 1, max: MAX_SHAPES });
  let firstError: unknown = null;
  const shapes = raw.flatMap((r, i) => {
    try {
      return shape(r, i);
    } catch (error) {
      firstError ??= error;
      return [];
    }
  });
  if (shapes.length === 0) throw firstError ?? new BoardError("no shapes to draw");
  const title = spec.title === undefined ? [] : [{ kind: "text" as const, x: 2, y: 2, text: str(spec, "title", { max: 24 }), color: "white" as const }];
  return [...title, ...shapes];
}

// ---- prepare and draw -------------------------------------------------------------

/**
 * A <draw> spec -> something the board can draw, or null (with the reason logged).
 * Templates are rendered once here too, so a template that would throw on these
 * arguments is caught now rather than mid-frame.
 */
export function prepare(spec: unknown, log: (why: string) => void = (why) => console.warn(`[irene] draw refused: ${why}`)): Prepared | null {
  try {
    const s = obj(spec, "draw");
    if (typeof s.template === "string") {
      const template = TEMPLATES[s.template];
      if (!template) throw new BoardError(`no template ${s.template}`);
      const args = template.parse(s);
      template.render(args, { t: 1e9, now: new Date() });
      const sync = syncOf(s);
      return sync ? { kind: "template", name: s.template, args, sync } : { kind: "template", name: s.template, args };
    }
    if (s.shapes !== undefined) return { kind: "shapes", name: "shapes", args: parseShapes(s) };
    throw new BoardError("a draw needs a template or shapes");
  } catch (error) {
    log(error instanceof Error ? error.message : String(error));
    return null;
  }
}

export function strokesOf(p: Prepared, ctx: RenderContext): Stroke[] {
  if (p.kind === "shapes") {
    // a composed drawing: each shape once its moment comes, its label amber while new
    return (p.args as Stroke[])
      .filter((s) => s.at === undefined || s.at <= ctx.t)
      .map((s) => (s.kind === "text" && s.at !== undefined && ctx.t - s.at < SHAPE_FRESH_MS ? { ...s, color: "amber" as const } : s));
  }
  const template = TEMPLATES[p.name];
  const strokes = template.render(p.args as never, ctx);
  return p.sync ? revealLabels(strokes, p.sync, ctx.t) : strokes;
}

/**
 * Paint the board at `elapsed` ms after it was shown: every stroke sketched in on
 * its own schedule, then whole. The face's corner is cleared last so her face,
 * drawn over it, is never overdrawn.
 */
export function drawBoard(frame: Frame, p: Prepared, elapsed: number, now: Date = new Date()): void {
  let strokes: Stroke[];
  try {
    strokes = strokesOf(p, { t: elapsed, now });
  } catch (error) {
    console.warn("[irene] board render failed", error);
    return;
  }
  const slots = schedule(strokes.filter((s) => s.at === undefined));
  let k = 0;
  strokes.forEach((s) => {
    // a composed shape sketches in from its own moment; the rest on the opening schedule
    const progress = s.at !== undefined ? (elapsed - s.at) / SHAPE_DRAW_MS : (elapsed - slots[k].start) / slots[k++].ms;
    drawStroke(frame, s, Math.min(1, Math.max(0, progress)));
  });
  for (let y = FACE_CORNER.y; y < FACE_CORNER.y + FACE_CORNER.h; y += 1) {
    for (let x = FACE_CORNER.x; x < COLS; x += 1) frame.value[y * COLS + x] = 0;
  }
}
