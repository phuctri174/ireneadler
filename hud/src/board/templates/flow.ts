// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// A process, step by step as she explains it - core only (core/irene/illustrate.py):
// each step joins the chain the moment the sentence that names it is heard; the
// HUD stamps it with the board's own clock ("at", ms since the board went up).
//
//   { "template": "flow", "title"?: "photosynthesis", "steps": [{ "text": "Light", "at": 0 }, ...] }
//
// Boxes run down the board with arrows between; a new one glows amber, then
// settles. Four fit below the title; after that the newest four stay.

import type { Template } from "../kit";
import { arrow, box, fill, text, title } from "../kit";
import type { Stroke } from "../strokes";
import { list, num, obj, str } from "../validate";

const TOP = 17;
const PITCH = 13;
const BOX_H = 9;
const SHOWN = 4;
const FRESH_MS = 1400;
const CHARS = 24;

interface Step {
  text: string;
  at: number;
}

export const template: Template<{ title: string | null; steps: Step[] }> = {
  parse(a) {
    const steps = list(a, "steps", { def: [], max: 12 }).map((raw, i) => {
      const s = obj(raw, `steps[${i}]`);
      return { text: str(s, "text", { max: 30 }), at: num(s, "at", { min: 0, max: 600000, def: 0 }) };
    });
    return { title: a.title === undefined || a.title === null ? null : str(a, "title", { max: 24 }), steps };
  },
  render({ title: heading, steps }, { t }) {
    const out: Stroke[] = [];
    if (heading) out.push(title(heading));
    const shown = steps.filter((s) => s.at <= t).slice(-SHOWN);
    shown.forEach((s, i) => {
      const label = s.text.toUpperCase().slice(0, CHARS);
      const w = label.length * 4 + 5;
      const x = 4 + i * 6; // a gentle stagger, so it reads as a sequence
      const y = TOP + i * PITCH;
      const fresh = t - s.at < FRESH_MS;
      out.push(fill(x, y, w, BOX_H, fresh ? "amber" : "accent", fresh ? 0.25 : 0.12));
      out.push(box(x, y, w, BOX_H, fresh ? "amber" : "accent"));
      out.push(text(x + 3, y + 2, label, fresh ? "amber" : "white"));
      if (i > 0) {
        const px = 4 + (i - 1) * 6 + 6;
        out.push(arrow(px, y - PITCH + BOX_H, px + 3, y - 1, "accent", 2));
      }
    });
    return out;
  },
};
