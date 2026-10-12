// A bar chart from numbers she has: one bar per label, value on top.
//
//   { "template": "bar_chart", "labels": ["Mon", "Tue"], "values": [3, 5], "title"?: "...", "unit"?: "h" }

import type { Template } from "../kit";
import { fill, line, short, text, title } from "../kit";
import type { Stroke } from "../strokes";
import { BoardError, numbers, optStr, strings } from "../validate";

export interface Series {
  labels: string[];
  values: number[];
  title: string | null;
  unit: string;
}

export function parseSeries(a: Record<string, unknown>, max = 12): Series {
  const values = numbers(a, "values", { min: 1, max });
  const labels = strings(a, "labels", { def: values.map((_, i) => String(i + 1)), max, each: 12 });
  if (labels.length !== values.length) throw new BoardError("labels and values must be the same length");
  return { labels, values, title: optStr(a, "title", 24) ?? null, unit: optStr(a, "unit", 4) ?? "" };
}

const X0 = 10;
const X1 = 124;
const TOP = 22;
const BASE = 62;

export const template: Template<Series> = {
  parse: (a) => parseSeries(a),
  render({ labels, values, title: t, unit }) {
    const out: Stroke[] = [];
    if (t) out.push(title(t));
    const hi = Math.max(0, ...values);
    const lo = Math.min(0, ...values);
    const span = hi - lo || 1;
    const y = (v: number) => BASE - ((v - lo) / span) * (BASE - TOP);
    const slot = (X1 - X0) / values.length;
    const w = Math.max(2, Math.min(12, Math.floor(slot * 0.62)));
    out.push(line(X0 - 2, y(0), X1, y(0), "white", 0.6));
    values.forEach((v, i) => {
      const cx = X0 + slot * i + slot / 2;
      const top = Math.min(y(v), y(0));
      const h = Math.max(1, Math.abs(y(v) - y(0)));
      out.push(fill(Math.round(cx - w / 2), Math.round(top), w, Math.round(h), v === hi ? "amber" : "accent", 0.85));
      out.push(text(cx, Math.round(top) - 7, `${short(v)}${unit}`, "white", "center"));
      const label = labels[i].toUpperCase();
      const room = Math.max(1, Math.floor((slot + 1) / 4));
      out.push(text(cx, BASE + 3, label.length > room ? label.slice(0, room) : label, "accent", "center", 1, 0.8));
    });
    return out;
  },
};
