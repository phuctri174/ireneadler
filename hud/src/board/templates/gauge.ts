// Gauges: up to four dials, a half-ring each filled to its value.
//
//   { "template": "gauge", "items": [{ "label": "CPU", "value": 40, "max"?: 100, "detail"?: "8 cores" }] }

import type { Template } from "../kit";
import { ring, text, title } from "../kit";
import type { Stroke } from "../strokes";
import type { Reading } from "./progress";
import { parseReadings } from "./progress";
import { optStr } from "../validate";

export function gauges(items: Reading[], top = 26): Stroke[] {
  const out: Stroke[] = [];
  const slot = 124 / items.length;
  items.forEach((it, i) => {
    const cx = 2 + slot * i + slot / 2;
    const cy = top + 16;
    const r = Math.min(14, slot / 2 - 3);
    const frac = Math.min(1, it.value / it.max);
    const hot = frac >= 0.85;
    // a 240-degree dial, from 7 o'clock round to 5 o'clock
    out.push(ring(cx, cy, r, "white", -120, 120, 0.25));
    if (frac > 0) out.push(ring(cx, cy, r, hot ? "red" : frac >= 0.6 ? "amber" : "accent", -120, -120 + 240 * frac), ring(cx, cy, r - 1, hot ? "red" : frac >= 0.6 ? "amber" : "accent", -120, -120 + 240 * frac, 0.6));
    out.push(text(cx, cy - 3, `${Math.round(frac * 100)}%`, "white", "center"));
    out.push(text(cx, cy + r + 1, it.label.toUpperCase(), "accent", "center"));
    if (it.detail) out.push(text(cx, cy + r + 8, it.detail.toUpperCase(), "white", "center", 1, 0.6));
  });
  return out;
}

export const template: Template<{ items: Reading[]; title: string | null }> = {
  parse: (a) => ({ items: parseReadings(a, 4), title: optStr(a, "title", 24) ?? null }),
  render({ items, title: t }) {
    return [...(t ? [title(t)] : []), ...gauges(items)];
  },
};
