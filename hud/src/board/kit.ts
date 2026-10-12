// What every board template works with: the contract, the free area (her face
// keeps the top-right corner), and small builders for strokes so a template reads
// as a description of the picture.

import { COLS, ROWS } from "../led/grid";
import { textWidth } from "./font";
import { ICONS } from "./icons";
import type { Color, Stroke } from "./strokes";
import { BoardError } from "./validate";
import type { Args } from "./validate";

export interface RenderContext {
  /** ms since the drawing was shown. */
  t: number;
  /** Wall clock, for live templates (a clock, a countdown). */
  now: Date;
}

export interface Template<A = unknown> {
  /** Checks and normalises the model's arguments; throws BoardError if it can't draw them exactly. */
  parse(args: Args): A;
  render(args: A, ctx: RenderContext): Stroke[];
}

/** Where her face sits while the board is up: drawings keep out of it. */
export const FACE_CORNER = { x: 100, y: 0, w: COLS - 100, h: 16 };
/** The free drawing area: everything but the corner. */
export const BOARD = { w: COLS, h: ROWS };
/** Below the corner the full width is free. */
export const BELOW_CORNER = FACE_CORNER.y + FACE_CORNER.h + 1;

// ---- builders --------------------------------------------------------------------

export const line = (x1: number, y1: number, x2: number, y2: number, color: Color = "accent", level?: number): Stroke => ({ kind: "line", x1, y1, x2, y2, color, level });
export const dashed = (x1: number, y1: number, x2: number, y2: number, color: Color = "accent", level?: number): Stroke => ({ kind: "line", x1, y1, x2, y2, color, level, dash: 2 });
export const arrow = (x1: number, y1: number, x2: number, y2: number, color: Color = "amber", head = 3): Stroke => ({ kind: "arrow", x1, y1, x2, y2, color, head });
export const box = (x: number, y: number, w: number, h: number, color: Color = "accent", level?: number): Stroke => ({ kind: "rect", x, y, w, h, color, level });
export const fill = (x: number, y: number, w: number, h: number, color: Color = "accent", level = 0.3): Stroke => ({ kind: "fill", x, y, w, h, color, level });
export const ring = (x: number, y: number, r: number, color: Color = "accent", from?: number, to?: number, level?: number): Stroke => ({ kind: "circle", x, y, r, color, from, to, level });
export const dot = (x: number, y: number, r: number, color: Color = "accent", level?: number): Stroke => ({ kind: "disc", x, y, r, color, level });
export const text = (x: number, y: number, value: string, color: Color = "white", align: "left" | "center" | "right" = "left", size = 1, level?: number): Stroke => ({ kind: "text", x, y, text: value, color, align, size, level });
export const title = (value: string, color: Color = "white"): Stroke => ({ kind: "text", x: 2, y: 2, text: value.toUpperCase(), color });

/** A label centred in a box, clipped to fit. */
export function boxed(x: number, y: number, w: number, h: number, label: string, color: Color = "accent", labelColor: Color = "white"): Stroke[] {
  const chars = Math.max(1, Math.floor((w - 2 + 1) / 4));
  const shown = label.length > chars ? `${label.slice(0, Math.max(1, chars - 1))}.` : label;
  return [box(x, y, w, h, color), text(x + Math.floor(w / 2), y + Math.floor((h - 5) / 2), shown, labelColor, "center")];
}

export function iconStrokes(name: string, x: number, y: number, scale = 1): Stroke[] {
  const icon = ICONS[name];
  if (!icon) throw new BoardError(`no icon ${name}`);
  const main: { x: number; y: number }[] = [];
  const second: { x: number; y: number }[] = [];
  icon.art.forEach((row, r) => {
    for (let c = 0; c < row.length; c += 1) {
      if (row[c] === ".") continue;
      for (let dy = 0; dy < scale; dy += 1) for (let dx = 0; dx < scale; dx += 1) (row[c] === "o" ? second : main).push({ x: x + c * scale + dx, y: y + r * scale + dy });
    }
  });
  const out: Stroke[] = [{ kind: "cells", cells: main, color: icon.color }];
  if (second.length) out.push({ kind: "cells", cells: second, color: icon.second ?? icon.color });
  return out;
}

export { textWidth };

/** Words into lines of at most `chars` characters (a long word is cut). */
export function wrap(value: string, chars: number): string[] {
  const lines: string[] = [];
  let current = "";
  for (const word of value.split(/\s+/).filter(Boolean)) {
    const w = word.length > chars ? `${word.slice(0, chars - 1)}.` : word;
    if (!current) current = w;
    else if (current.length + 1 + w.length <= chars) current += ` ${w}`;
    else {
      lines.push(current);
      current = w;
    }
  }
  if (current) lines.push(current);
  return lines;
}

/** Evenly spaced positions for n items across [from, to]. */
export function spread(n: number, from: number, to: number): number[] {
  if (n <= 1) return [(from + to) / 2];
  return Array.from({ length: n }, (_, k) => from + ((to - from) * k) / (n - 1));
}

/** A number as a short label: 1234 -> "1234", 12345 -> "12K", 0.5 -> "0.5". */
export function short(value: number): string {
  const a = Math.abs(value);
  if (a >= 1e6) return `${(value / 1e6).toFixed(a >= 1e7 ? 0 : 1)}M`;
  if (a >= 1e4) return `${Math.round(value / 1e3)}K`;
  if (Number.isInteger(value)) return String(value);
  return a >= 10 ? value.toFixed(0) : value.toFixed(1);
}
