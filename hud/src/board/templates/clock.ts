// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// An analog clock: a given time, or the live time with a sweeping second hand.
//
//   { "template": "clock", "time"?: "14:05", "label"?: "Tokyo" }

import type { Template } from "../kit";
import { dot, line, ring, text, title } from "../kit";
import type { Stroke } from "../strokes";
import { BoardError, optStr } from "../validate";

const C = { x: 36, y: 40, r: 26 };

export const template: Template<{ fixed: { h: number; m: number } | null; label: string | null }> = {
  parse(a) {
    const time = optStr(a, "time", 5);
    let fixed = null;
    if (time) {
      const m = /^(\d{1,2}):(\d{2})$/.exec(time);
      if (!m || Number(m[1]) > 23 || Number(m[2]) > 59) throw new BoardError("time must be HH:MM, 24h");
      fixed = { h: Number(m[1]), m: Number(m[2]) };
    }
    return { fixed, label: optStr(a, "label", 15) ?? null };
  },
  render({ fixed, label }, { now }) {
    const h = fixed ? fixed.h : now.getHours();
    const m = fixed ? fixed.m : now.getMinutes();
    const s = fixed ? null : now.getSeconds() + now.getMilliseconds() / 1000;
    const hand = (deg: number, len: number) => ({ x: C.x + Math.sin((deg * Math.PI) / 180) * len, y: C.y - Math.cos((deg * Math.PI) / 180) * len });
    const out: Stroke[] = [title(label ?? (fixed ? "CLOCK" : "NOW")), ring(C.x, C.y, C.r, "white")];
    for (let k = 0; k < 12; k += 1) {
      const a = hand(k * 30, C.r - 1);
      const b = hand(k * 30, C.r - (k % 3 === 0 ? 5 : 3));
      out.push(line(a.x, a.y, b.x, b.y, "white", k % 3 === 0 ? 1 : 0.5));
    }
    for (const [n, deg] of [["12", 0], ["3", 90], ["6", 180], ["9", 270]] as const) {
      const p = hand(deg, C.r - 10);
      out.push(text(p.x, p.y - 2, n, "accent", "center", 1, 0.8));
    }
    const hp = hand((h % 12) * 30 + m * 0.5, C.r * 0.5);
    const mp = hand(m * 6 + (s ?? 0) * 0.1, C.r * 0.8);
    out.push(line(C.x, C.y, hp.x, hp.y, "white"), line(C.x, C.y, mp.x, mp.y, "accent"));
    if (s !== null) {
      const sp = hand(s * 6, C.r * 0.88);
      out.push(line(C.x, C.y, sp.x, sp.y, "amber", 0.8));
    }
    out.push(dot(C.x, C.y, 1.2, "amber"));
    out.push(text(84, 34, `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`, "white", "center", 2));
    return out;
  },
};
