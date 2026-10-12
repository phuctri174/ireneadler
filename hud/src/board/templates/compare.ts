// Two options side by side, as she compares them - core only
// (core/irene/illustrate.py): each point goes under the option the sentence is
// about, the moment that sentence is heard ("at", ms since the board went up).
//
//   { "template": "compare", "left": "Python", "right": "Rust",
//     "points": [{ "side": "right", "text": "memory safe", "at": 0 }, ...] }
//
// The newest point glows amber, then settles; five fit under each side.

import type { Template } from "../kit";
import { dot, line, text } from "../kit";
import type { Stroke } from "../strokes";
import { list, num, obj, str } from "../validate";

const HEAD_Y = 18;
const FIRST_Y = 29;
const ROW = 8;
const SHOWN = 5;
const FRESH_MS = 1400;
const CHARS = 14;
const COLUMN = { left: 3, right: 67 } as const;

interface Point {
  side: "left" | "right";
  text: string;
  at: number;
}

export const template: Template<{ left: string; right: string; points: Point[] }> = {
  parse(a) {
    const points = list(a, "points", { def: [], max: 16 }).map((raw, i) => {
      const p = obj(raw, `points[${i}]`);
      return {
        side: str(p, "side", { oneOf: ["left", "right"] }) as Point["side"],
        text: str(p, "text", { max: 30 }),
        at: num(p, "at", { min: 0, max: 600000, def: 0 }),
      };
    });
    return { left: str(a, "left", { max: 15 }), right: str(a, "right", { max: 15 }), points };
  },
  render({ left, right, points }, { t }) {
    const out: Stroke[] = [];
    // the two names, a rule under each, and a divider down the middle
    for (const [side, name] of [["left", left], ["right", right]] as const) {
      const x = COLUMN[side];
      out.push(text(x, HEAD_Y, name.toUpperCase().slice(0, CHARS + 1), "amber"));
      out.push(line(x, HEAD_Y + 8, x + 58, HEAD_Y + 8, "accent", 0.6));
    }
    out.push(line(63, HEAD_Y, 63, 70, "accent", 0.35));
    for (const side of ["left", "right"] as const) {
      const shown = points.filter((p) => p.side === side && p.at <= t).slice(-SHOWN);
      shown.forEach((p, i) => {
        const y = FIRST_Y + i * ROW;
        const fresh = t - p.at < FRESH_MS;
        out.push(dot(COLUMN[side] + 1, y + 2, 1, fresh ? "amber" : "accent"));
        out.push(text(COLUMN[side] + 5, y, p.text.toUpperCase().slice(0, CHARS), fresh ? "amber" : "white"));
      });
    }
    return out;
  },
};
