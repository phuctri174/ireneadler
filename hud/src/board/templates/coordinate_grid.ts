// A coordinate grid: axes through the origin (when it's in range), grid lines,
// points (labelled if given) and line segments.
//
//   { "template": "coordinate_grid", "x": [-5, 5], "y": [-4, 4],
//     "points"?: [[1, 2, "A"]], "segments"?: [[0, 0, 3, 2]] }

import type { Template } from "../kit";
import { dot, line, short, text } from "../kit";
import type { Stroke } from "../strokes";
import { BoardError, list, numbers } from "../validate";

interface Point {
  x: number;
  y: number;
  label: string | null;
}

export const template: Template<{ xr: [number, number]; yr: [number, number]; points: Point[]; segments: number[][] }> = {
  parse(a) {
    const xr = numbers(a, "x", { def: [-5, 5], min: 2, max: 2 }) as [number, number];
    const yr = numbers(a, "y", { def: [-4, 4], min: 2, max: 2 }) as [number, number];
    if (xr[1] <= xr[0] || yr[1] <= yr[0]) throw new BoardError("ranges must go low to high");
    const inX = (v: number) => v >= xr[0] && v <= xr[1];
    const inY = (v: number) => v >= yr[0] && v <= yr[1];
    const points = list(a, "points", { def: [], max: 10 }).map((raw, i): Point => {
      if (!Array.isArray(raw) || raw.length < 2 || typeof raw[0] !== "number" || typeof raw[1] !== "number") throw new BoardError(`points[${i}] must be [x, y] or [x, y, "label"]`);
      if (!inX(raw[0]) || !inY(raw[1])) throw new BoardError(`points[${i}] is off the grid`);
      return { x: raw[0], y: raw[1], label: raw[2] === undefined ? null : String(raw[2]).slice(0, 3) };
    });
    const segments = list(a, "segments", { def: [], max: 8 }).map((raw, i) => {
      // [x1, y1, x2, y2] or [[x1, y1], [x2, y2]]
      const flat = Array.isArray(raw) && raw.length === 2 && raw.every(Array.isArray) ? (raw as unknown[][]).flat() : raw;
      if (!Array.isArray(flat) || flat.length !== 4 || flat.some((v) => typeof v !== "number")) throw new BoardError(`segments[${i}] must be [x1, y1, x2, y2]`);
      return flat as number[];
    });
    return { xr, yr, points, segments };
  },
  render({ xr, yr, points, segments }) {
    const X0 = 10;
    const X1 = 96;
    const Y0 = 6;
    const Y1 = 66;
    const px = (v: number) => X0 + ((v - xr[0]) / (xr[1] - xr[0])) * (X1 - X0);
    const py = (v: number) => Y1 - ((v - yr[0]) / (yr[1] - yr[0])) * (Y1 - Y0);
    const out: Stroke[] = [];
    const stepOf = (lo: number, hi: number) => {
      const raw = (hi - lo) / 10;
      const mag = 10 ** Math.floor(Math.log10(raw));
      return [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
    };
    const sx = stepOf(xr[0], xr[1]);
    const sy = stepOf(yr[0], yr[1]);
    for (let v = Math.ceil(xr[0] / sx) * sx; v <= xr[1] + 1e-9; v += sx) out.push(line(px(v), Y0, px(v), Y1, "white", 0.15));
    for (let v = Math.ceil(yr[0] / sy) * sy; v <= yr[1] + 1e-9; v += sy) out.push(line(X0, py(v), X1, py(v), "white", 0.15));
    const ox = xr[0] <= 0 && xr[1] >= 0 ? px(0) : X0;
    const oy = yr[0] <= 0 && yr[1] >= 0 ? py(0) : Y1;
    out.push(line(X0, oy, X1, oy, "white", 0.8), line(ox, Y0, ox, Y1, "white", 0.8));
    out.push(text(X1 + 3, oy - 2, "X", "white"), text(ox + 3, Y0, "Y", "white"));
    out.push(text(X0, oy + 2, short(xr[0]), "accent", "center", 1, 0.7), text(X1, oy + 2, short(xr[1]), "accent", "center", 1, 0.7));
    out.push(text(ox - 2, Y0, short(yr[1]), "accent", "right", 1, 0.7), text(ox - 2, Y1 - 4, short(yr[0]), "accent", "right", 1, 0.7));
    for (const [x1, y1, x2, y2] of segments) out.push(line(px(x1), py(y1), px(x2), py(y2), "amber"));
    for (const p of points) {
      out.push(dot(px(p.x), py(p.y), 1.4, "cyan"));
      const label = p.label ?? `(${short(p.x)},${short(p.y)})`;
      out.push(text(px(p.x) + 3, py(p.y) - 6, label.toUpperCase(), "cyan"));
    }
    return out;
  },
};
