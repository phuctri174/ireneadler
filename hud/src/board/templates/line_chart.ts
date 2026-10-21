// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// A line chart: points joined in order, the axis range labelled, highest point marked.
//
//   { "template": "line_chart", "values": [3, 5, 4], "labels"?: [...], "title"?: "...", "unit"?: "" }

import type { Template } from "../kit";
import { dot, line, short, text, title } from "../kit";
import type { Stroke } from "../strokes";
import type { Series } from "./bar_chart";
import { parseSeries } from "./bar_chart";

const X0 = 22;
const X1 = 122;
const TOP = 22;
const BASE = 60;

export const template: Template<Series> = {
  parse: (a) => parseSeries(a, 40),
  render({ labels, values, title: t, unit }) {
    const out: Stroke[] = [];
    if (t) out.push(title(t));
    const hi = Math.max(...values);
    const lo = Math.min(...values);
    const span = hi - lo || 1;
    const x = (i: number) => (values.length === 1 ? (X0 + X1) / 2 : X0 + ((X1 - X0) * i) / (values.length - 1));
    const y = (v: number) => BASE - ((v - lo) / span) * (BASE - TOP);
    out.push(line(X0 - 2, BASE + 1, X1, BASE + 1, "white", 0.5), line(X0 - 2, TOP - 1, X0 - 2, BASE + 1, "white", 0.5));
    out.push(text(X0 - 4, TOP - 1, `${short(hi)}${unit}`, "white", "right", 1, 0.7), text(X0 - 4, BASE - 4, `${short(lo)}${unit}`, "white", "right", 1, 0.7));
    for (let i = 1; i < values.length; i += 1) out.push(line(x(i - 1), y(values[i - 1]), x(i), y(values[i]), "accent"));
    values.forEach((v, i) => out.push(dot(x(i), y(v), v === hi ? 1.5 : 0.8, v === hi ? "amber" : "accent")));
    const every = Math.max(1, Math.ceil(labels.length / 8));
    labels.forEach((l, i) => {
      if (i % every === 0 || i === labels.length - 1) out.push(text(x(i), BASE + 4, l.toUpperCase().slice(0, 4), "accent", "center", 1, 0.8));
    });
    return out;
  },
};
