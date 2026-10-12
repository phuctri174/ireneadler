// What the board is made of: strokes. Every template and every freehand drawing
// comes down to a list of these, drawn in order; the board reveals them one after
// another, each growing in as if sketched - a line from one end, a box around its
// edge, a circle round, a label letter by letter, a fill top to bottom.

import { COLS, FADE, INK, ROWS } from "../led/grid";
import type { Frame, Ink } from "../led/grid";
import { glyphCells, textWidth } from "./font";

export type Color = "accent" | "white" | "amber" | "pink" | "red" | "cyan";

export const COLORS: Record<Color, Ink> = {
  accent: INK.accent,
  white: INK.white,
  amber: INK.amber,
  pink: INK.pink,
  red: INK.red,
  cyan: INK.cyan,
};

interface Base {
  color?: Color;
  /** Brightness 0..1 (default 1; fills default dimmer). */
  level?: number;
  /** When it appears (ms on the board's clock) - a drawing composed as she speaks
   * (core/irene/compose.py) - instead of the opening sketch's own schedule. */
  at?: number;
}

export type Stroke =
  | (Base & { kind: "line"; x1: number; y1: number; x2: number; y2: number; dash?: number })
  | (Base & { kind: "arrow"; x1: number; y1: number; x2: number; y2: number; head?: number })
  | (Base & { kind: "rect"; x: number; y: number; w: number; h: number })
  | (Base & { kind: "fill"; x: number; y: number; w: number; h: number })
  | (Base & { kind: "circle"; x: number; y: number; r: number; from?: number; to?: number })
  | (Base & { kind: "disc"; x: number; y: number; r: number })
  | (Base & { kind: "text"; x: number; y: number; text: string; size?: number; align?: "left" | "center" | "right" })
  | (Base & { kind: "cells"; cells: { x: number; y: number; v?: number }[] });

const put = (frame: Frame, x: number, y: number, v: number, ink: Ink): void => {
  const cx = Math.round(x);
  const cy = Math.round(y);
  if (cx < 0 || cx >= COLS || cy < 0 || cy >= ROWS) return;
  frame.cover(cx, cy, v, ink, FADE.prop);
};

function linePoints(x1: number, y1: number, x2: number, y2: number): { x: number; y: number }[] {
  const n = Math.max(1, Math.ceil(Math.max(Math.abs(x2 - x1), Math.abs(y2 - y1))));
  const out = [];
  for (let k = 0; k <= n; k += 1) out.push({ x: x1 + ((x2 - x1) * k) / n, y: y1 + ((y2 - y1) * k) / n });
  return out;
}

function arrowHead(x1: number, y1: number, x2: number, y2: number, size: number): { x: number; y: number }[][] {
  const a = Math.atan2(y2 - y1, x2 - x1);
  const wing = (s: number) => ({ x: x2 - Math.cos(a + s) * size, y: y2 - Math.sin(a + s) * size });
  return [linePoints(x2, y2, wing(0.55).x, wing(0.55).y), linePoints(x2, y2, wing(-0.55).x, wing(-0.55).y)];
}

/** Rough length of a stroke in cells - how long it takes to sketch. */
export function strokeLength(s: Stroke): number {
  switch (s.kind) {
    case "line":
    case "arrow":
      return Math.hypot(s.x2 - s.x1, s.y2 - s.y1) + (s.kind === "arrow" ? 4 : 0);
    case "rect":
      return 2 * (s.w + s.h);
    case "fill":
      return s.h * 2;
    case "circle":
      return 2 * Math.PI * s.r * (((s.to ?? 360) - (s.from ?? 0)) / 360);
    case "disc":
      return s.r * 3;
    case "text":
      return [...s.text].length * 3;
    case "cells":
      return Math.sqrt(s.cells.length) * 2;
  }
}

/** Draw `s` sketched `p` of the way in (0..1). */
export function drawStroke(frame: Frame, s: Stroke, p: number): void {
  if (p <= 0) return;
  const ink = COLORS[s.color ?? "accent"] ?? INK.accent;
  const level = Math.min(1, Math.max(0, s.level ?? (s.kind === "fill" ? 0.3 : 1)));
  switch (s.kind) {
    case "line": {
      const pts = linePoints(s.x1, s.y1, s.x2, s.y2);
      const upto = Math.ceil(pts.length * p);
      for (let k = 0; k < upto; k += 1) {
        if (s.dash && Math.floor(k / s.dash) % 2 === 1) continue;
        put(frame, pts[k].x, pts[k].y, level, ink);
      }
      return;
    }
    case "arrow": {
      const shaft = linePoints(s.x1, s.y1, s.x2, s.y2);
      const upto = Math.ceil(shaft.length * Math.min(1, p / 0.8));
      for (let k = 0; k < upto; k += 1) put(frame, shaft[k].x, shaft[k].y, level, ink);
      if (p > 0.8) for (const wing of arrowHead(s.x1, s.y1, s.x2, s.y2, s.head ?? 3)) for (const pt of wing) put(frame, pt.x, pt.y, level, ink);
      return;
    }
    case "rect": {
      const { x, y, w, h } = s;
      const corners = [
        { x, y },
        { x: x + w - 1, y },
        { x: x + w - 1, y: y + h - 1 },
        { x, y: y + h - 1 },
        { x, y },
      ];
      const perimeter: { x: number; y: number }[] = [];
      for (let k = 0; k < 4; k += 1) perimeter.push(...linePoints(corners[k].x, corners[k].y, corners[k + 1].x, corners[k + 1].y));
      const upto = Math.ceil(perimeter.length * p);
      for (let k = 0; k < upto; k += 1) put(frame, perimeter[k].x, perimeter[k].y, level, ink);
      return;
    }
    case "fill": {
      const rows = Math.ceil(s.h * p);
      for (let dy = 0; dy < rows; dy += 1) for (let dx = 0; dx < s.w; dx += 1) put(frame, s.x + dx, s.y + dy, level, ink);
      return;
    }
    case "circle": {
      const from = ((s.from ?? 0) * Math.PI) / 180;
      const to = ((s.to ?? 360) * Math.PI) / 180;
      const end = from + (to - from) * p;
      const steps = Math.max(8, Math.ceil(Math.abs(to - from) * s.r * 1.5));
      for (let k = 0; k <= steps; k += 1) {
        const a = from + ((to - from) * k) / steps;
        if (a > end) break;
        // 0 degrees is 12 o'clock, clockwise - like a clock face
        put(frame, s.x + Math.sin(a) * s.r, s.y - Math.cos(a) * s.r, level, ink);
      }
      return;
    }
    case "disc": {
      const r = s.r * p;
      for (let y = Math.floor(s.y - r); y <= Math.ceil(s.y + r); y += 1) {
        for (let x = Math.floor(s.x - r); x <= Math.ceil(s.x + r); x += 1) {
          if (Math.hypot(x - s.x, y - s.y) <= r + 0.35) put(frame, x, y, level, ink);
        }
      }
      return;
    }
    case "text": {
      const size = s.size === 2 ? 2 : 1;
      const chars = [...s.text];
      const width = textWidth(s.text, size);
      const x0 = s.align === "center" ? s.x - Math.floor(width / 2) : s.align === "right" ? s.x - width + 1 : s.x;
      const shown = Math.ceil(chars.length * p);
      for (let k = 0; k < shown; k += 1) {
        for (const c of glyphCells(chars[k], x0 + k * 4 * size, s.y, size)) put(frame, c.x, c.y, level, ink);
      }
      return;
    }
    case "cells": {
      const shown = Math.ceil(s.cells.length * p);
      for (let k = 0; k < shown; k += 1) put(frame, s.cells[k].x, s.cells[k].y, level * (s.cells[k].v ?? 1), ink);
      return;
    }
  }
}

/** When each stroke starts and how long it takes, for a sketch of `strokes`. */
export function schedule(strokes: Stroke[], budgetMs = 1800): { start: number; ms: number }[] {
  // longer strokes take longer; the whole sketch is squeezed into the budget
  const raw = strokes.map((s) => 60 + Math.min(260, strokeLength(s) * 5));
  const total = raw.reduce((a, b) => a + b * 0.55, 0);
  const squeeze = total > budgetMs ? budgetMs / total : 1;
  let at = 0;
  return raw.map((ms) => {
    const slot = { start: at, ms: ms * squeeze };
    at += ms * 0.55 * squeeze; // strokes overlap a little, like a quick hand
    return slot;
  });
}
