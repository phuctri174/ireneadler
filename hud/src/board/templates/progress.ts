// Progress bars: one row per item, filled to its share, percentage at the end.
//
//   { "template": "progress", "items": [{ "label": "Thesis", "value": 60, "max"?: 100 }], "title"?: "..." }

import type { Template } from "../kit";
import { box, fill, text, title } from "../kit";
import type { Stroke } from "../strokes";
import { BoardError, list, num, obj, optStr, str } from "../validate";

export interface Reading {
  label: string;
  value: number;
  max: number;
  detail?: string;
}

export function parseReadings(a: Record<string, unknown>, max = 6): Reading[] {
  return list(a, "items", { min: 1, max }).map((raw, i) => {
    const it = obj(raw, `items[${i}]`);
    const r = { label: str(it, "label", { max: 14 }), value: num(it, "value", { min: 0 }), max: num(it, "max", { min: 0.0001, def: 100 }), detail: optStr(it, "detail", 12) };
    if (r.value > r.max * 1.0001) throw new BoardError(`items[${i}] value is above its max`);
    return r;
  });
}

export const template: Template<{ items: Reading[]; title: string | null }> = {
  parse: (a) => ({ items: parseReadings(a), title: optStr(a, "title", 24) ?? null }),
  render({ items, title: t }) {
    const out: Stroke[] = [];
    if (t) out.push(title(t));
    const X = 48;
    const W = 60;
    items.forEach((it, i) => {
      const y = 20 + i * 8;
      const frac = it.value / it.max;
      out.push(text(X - 3, y, it.label.toUpperCase(), "white", "right"));
      out.push(box(X, y - 1, W, 7, "accent", 0.6), fill(X + 1, y, Math.round((W - 2) * frac), 5, frac >= 1 ? "amber" : "accent", 0.8));
      out.push(text(X + W + 3, y, `${Math.round(frac * 100)}%`, frac >= 1 ? "amber" : "white"));
    });
    return out;
  },
};
