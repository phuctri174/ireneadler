// A number line: ticks and labels from..to, points marked, intervals shaded
// (open or closed ends).
//
//   { "template": "number_line", "from": -5, "to": 5, "points"?: [2],
//     "intervals"?: [{ "from": -2, "to": 3, "closed"?: [true, false] }] }

import type { Template } from "../kit";
import { arrow, dot, line, ring, short, text, title } from "../kit";
import type { Stroke } from "../strokes";
import { BoardError, list, num, numbers, obj, optStr } from "../validate";

interface Interval {
  from: number;
  to: number;
  closed: [boolean, boolean];
}

export const template: Template<{ from: number; to: number; points: number[]; intervals: Interval[]; title: string | null }> = {
  parse(a) {
    const from = num(a, "from");
    const to = num(a, "to");
    if (to <= from) throw new BoardError("to must be above from");
    const inside = (v: number) => v >= from && v <= to;
    const points = numbers(a, "points", { def: [], max: 8 });
    if (!points.every(inside)) throw new BoardError("points must lie between from and to");
    const intervals = list(a, "intervals", { def: [], max: 3 }).map((raw, i) => {
      const it = obj(raw, `intervals[${i}]`);
      const iv = { from: num(it, "from"), to: num(it, "to"), closed: (Array.isArray(it.closed) ? it.closed.map(Boolean) : [true, true]) as [boolean, boolean] };
      if (iv.to < iv.from || !inside(iv.from) || !inside(iv.to)) throw new BoardError(`intervals[${i}] must lie on the line`);
      return iv;
    });
    return { from, to, points, intervals, title: optStr(a, "title", 24) ?? null };
  },
  render({ from, to, points, intervals, title: t }) {
    const X0 = 8;
    const X1 = 120;
    const Y = 40;
    const x = (v: number) => X0 + ((v - from) / (to - from)) * (X1 - X0);
    const out: Stroke[] = [];
    if (t) out.push(title(t));
    out.push(arrow(X0 - 4, Y, X1 + 5, Y, "white", 2), arrow(X1 - 4, Y, X0 - 5, Y, "white", 2));
    // ticks at a round step
    const raw = (to - from) / 10;
    const mag = 10 ** Math.floor(Math.log10(raw));
    const step = [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
    for (let v = Math.ceil(from / step) * step; v <= to + 1e-9; v += step) {
      out.push(line(x(v), Y - 2, x(v), Y + 2, "white", 0.7), text(x(v), Y + 5, short(Math.round(v * 1e6) / 1e6), "accent", "center", 1, 0.8));
    }
    intervals.forEach((iv, i) => {
      const y = Y - 6 - i * 5;
      out.push(line(x(iv.from), y, x(iv.to), y, "amber"), line(x(iv.from), y + 1, x(iv.to), y + 1, "amber", 0.5));
      for (const [v, closed] of [[iv.from, iv.closed[0]], [iv.to, iv.closed[1]]] as const) out.push(closed ? dot(x(v), y, 1.5, "amber") : ring(x(v), y, 1.8, "amber"));
    });
    points.forEach((p) => out.push(dot(x(p), Y, 1.6, "cyan"), text(x(p), Y - 10 - intervals.length * 5, short(p), "cyan", "center")));
    return out;
  },
};
