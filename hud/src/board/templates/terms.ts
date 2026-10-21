// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// The key terms of a research answer, appearing one at a time as she says them -
// core only (never offered to the model): core/irene/terms.py picks each term from
// a grounded sentence and the fetched text behind it, and sends it the moment that
// sentence is heard; the HUD stamps it with the board's own clock ("at", ms since
// the board went up) and redraws.
//
//   { "template": "terms", "title"?: "kendo dan grades", "terms": [{ "text": "Shodan", "at": 0 }, ...] }
//
// A term types itself in, glows amber while it's new, then settles to white. Seven
// fit below her face; after that the newest seven stay.

import type { Template } from "../kit";
import { BELOW_CORNER, dot, line, text, title } from "../kit";
import type { Stroke } from "../strokes";
import { list, num, obj, str } from "../validate";

const ROW = 8;
const SHOWN = 7;
const TYPE_MS = 32; // per character as it types in
const FRESH_MS = 1400;

interface Term {
  text: string;
  at: number;
}

export const template: Template<{ title: string | null; terms: Term[] }> = {
  parse(a) {
    const terms = list(a, "terms", { min: 1, max: 24 }).map((raw, i) => {
      const t = obj(raw, `terms[${i}]`);
      return { text: str(t, "text", { max: 30 }), at: num(t, "at", { min: 0, max: 600000, def: 0 }) };
    });
    return { title: a.title === undefined || a.title === null ? null : str(a, "title", { max: 24 }), terms };
  },
  render({ title: heading, terms }, { t }) {
    const out: Stroke[] = [];
    if (heading) out.push(title(heading));
    const shown = terms.filter((term) => term.at <= t).slice(-SHOWN);
    shown.forEach((term, i) => {
      const y = BELOW_CORNER + 2 + i * ROW;
      const age = t - term.at;
      const fresh = age < FRESH_MS;
      const typed = term.text.slice(0, Math.max(1, Math.floor(age / TYPE_MS) + 1)).toUpperCase();
      out.push(dot(3, y + 2, 1, fresh ? "amber" : "accent"));
      out.push(text(7, y, typed, fresh ? "amber" : "white"));
      // a line sweeps under the newest one as it lands
      if (fresh && i === shown.length - 1) {
        const w = Math.min(1, age / 500) * (typed.length * 4);
        out.push(line(7, y + 6, 7 + w, y + 6, "amber", 0.5));
      }
    });
    return out;
  },
};
