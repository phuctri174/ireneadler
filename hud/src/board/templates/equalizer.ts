// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// Equalizer bars dancing while music plays, with what's playing underneath.
//
//   { "template": "equalizer", "title"?: "Lo-fi beats", "bars"?: 16 }

import type { Template } from "../kit";
import { fill, iconStrokes, text } from "../kit";
import type { Stroke } from "../strokes";
import { num, optStr } from "../validate";

export const template: Template<{ title: string | null; bars: number }> = {
  parse(a) {
    return { title: optStr(a, "title", 30) ?? null, bars: num(a, "bars", { min: 4, max: 24, def: 16, int: true }) };
  },
  render({ title, bars }, { t }) {
    const out: Stroke[] = [...iconStrokes("music", 4, 4, 1)];
    const slot = 120 / bars;
    const w = Math.max(2, Math.floor(slot * 0.66));
    for (let i = 0; i < bars; i += 1) {
      // a few sines per bar at different speeds: lively, never in lockstep
      const level = 0.25 + 0.75 * Math.abs(Math.sin(t / (310 + i * 37) + i * 1.3) * 0.6 + Math.sin(t / (170 + i * 23) + i) * 0.4);
      const h = Math.max(2, Math.round(level * 36));
      const x = Math.round(4 + slot * i + (slot - w) / 2);
      out.push(fill(x, 58 - h, w, h, h > 28 ? "pink" : h > 18 ? "amber" : "accent", 0.9));
    }
    if (title) out.push(text(64, 62, title.toUpperCase(), "white", "center"));
    return out;
  },
};
