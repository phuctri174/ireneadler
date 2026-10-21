// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// A countdown ring: the remaining time as an arc that shrinks, mm:ss in the middle,
// counting down from when it is shown.
//
//   { "template": "timer", "minutes"?: 5, "seconds"?: 0, "label"?: "tea" }

import type { Template } from "../kit";
import { ring, text, title } from "../kit";
import type { Stroke } from "../strokes";
import { BoardError, num, optStr } from "../validate";

const C = { x: 40, y: 42, r: 24 };
const SKETCH_MS = 1200;

export const template: Template<{ total: number; label: string | null }> = {
  parse(a) {
    const total = num(a, "minutes", { min: 0, max: 24 * 60, def: 0 }) * 60 + num(a, "seconds", { min: 0, max: 3600, def: 0 });
    if (total <= 0) throw new BoardError("a timer needs minutes or seconds");
    return { total, label: optStr(a, "label", 20) ?? null };
  },
  render({ total, label }, { t }) {
    const left = Math.max(0, total - Math.max(0, t - SKETCH_MS) / 1000);
    const frac = left / total;
    const done = left <= 0;
    const out: Stroke[] = [title(label ? `${label} timer` : "TIMER"), ring(C.x, C.y, C.r, "white", 0, 360, 0.25)];
    if (frac > 0) out.push(ring(C.x, C.y, C.r, frac < 0.2 ? "amber" : "accent", 0, 360 * frac), ring(C.x, C.y, C.r - 1, frac < 0.2 ? "amber" : "accent", 0, 360 * frac, 0.6));
    const secs = Math.ceil(left);
    const shown = done ? "DONE" : secs >= 3600 ? `${Math.floor(secs / 3600)}:${String(Math.floor((secs % 3600) / 60)).padStart(2, "0")}` : `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")}`;
    const blink = done && Math.floor(t / 400) % 2 === 0;
    out.push(text(C.x, C.y - 5, shown, done ? "amber" : "white", "center", 2, blink ? 0.3 : 1));
    out.push(text(84, 30, "LEFT", "accent"), text(84, 37, `${Math.round(frac * 100)}%`, "white"));
    return out;
  },
};
