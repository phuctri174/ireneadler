// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// An array: a row of cells with their indices, some highlighted, named pointers
// (i, j, lo, hi, mid...) as arrows under their cells.
//
//   { "template": "array", "values": [5, 2, 9], "highlight"?: [1], "pointers"?: { "i": 0, "j": 2 }, "title"?: "..." }

import type { Template } from "../kit";
import { arrow, box, fill, text, title } from "../kit";
import type { Stroke } from "../strokes";
import { BoardError, numbers, obj, optStr, strings } from "../validate";

interface ArrayArgs {
  values: string[];
  highlight: number[];
  pointers: [string, number][];
  title: string | null;
}

export function cellsRow(values: string[], x0: number, y: number, maxW = 120): { stroke: Stroke[]; w: number; xs: number[] } {
  const longest = Math.max(1, ...values.map((v) => v.length));
  const w = Math.min(Math.floor(maxW / values.length), Math.max(9, longest * 4 + 3));
  const out: Stroke[] = [];
  const xs: number[] = [];
  values.forEach((v, i) => {
    const x = x0 + i * w;
    xs.push(x + Math.floor(w / 2));
    const room = Math.max(1, Math.floor((w - 2) / 4));
    out.push(box(x, y, w + 1, 11, "accent"), text(x + Math.floor(w / 2) + 1, y + 3, v.length > room ? v.slice(0, room) : v, "white", "center"));
  });
  return { stroke: out, w, xs };
}

export const template: Template<ArrayArgs> = {
  parse(a) {
    const values = strings(a, "values", { min: 1, max: 16, each: 6 });
    const highlight = numbers(a, "highlight", { def: [], max: 16 });
    if (highlight.some((i) => !Number.isInteger(i) || i < 0 || i >= values.length)) throw new BoardError("highlight indices must be inside the array");
    const pointers: [string, number][] = [];
    if (a.pointers !== undefined) {
      for (const [k, v] of Object.entries(obj(a.pointers, "pointers"))) {
        // {"lo": 0} or, the other way round, {"0": "lo"}
        const [name, at] = typeof v === "string" && /^\d+$/.test(k) ? [v, Number(k)] : [k, v];
        if (typeof at !== "number" || !Number.isInteger(at) || at < 0 || at >= values.length) throw new BoardError(`pointer ${name} must be an index inside the array`);
        pointers.push([name.slice(0, 4), at]);
      }
      if (pointers.length > 4) throw new BoardError("at most 4 pointers");
    }
    return { values, highlight, pointers, title: optStr(a, "title", 24) ?? null };
  },
  render({ values, highlight, pointers, title: t }) {
    const out: Stroke[] = [];
    if (t) out.push(title(t));
    const width = Math.min(124, values.length * Math.max(9, Math.max(...values.map((v) => v.length)) * 4 + 3));
    const x0 = Math.floor((128 - width) / 2);
    const y = 26;
    const row = cellsRow(values, x0, y);
    highlight.forEach((i) => out.push(fill(x0 + i * row.w + 1, y + 1, row.w - 1, 9, "amber", 0.35)));
    out.push(...row.stroke);
    row.xs.forEach((x, i) => out.push(text(x + 1, y - 7, String(i), "accent", "center", 1, 0.6)));
    const seen = new Map<number, number>();
    for (const [name, at] of pointers) {
      const k = seen.get(at) ?? 0;
      seen.set(at, k + 1);
      const x = row.xs[at] + 1;
      out.push(arrow(x, y + 22 + k * 8, x, y + 13, "amber", 2), text(x, y + 24 + k * 8, name.toUpperCase(), "amber", "center"));
    }
    return out;
  },
};
