// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// A stack: items bottom to top, the top marked, an optional push or pop shown.
//
//   { "template": "stack", "values": ["a", "b", "c"], "push"?: "d" | "pop"?: true }

import type { Template } from "../kit";
import { arrow, box, line, text, title } from "../kit";
import type { Stroke } from "../strokes";
import { BoardError, bool, optStr, strings } from "../validate";

const X = 34;
const W = 30;
const H = 7;
const BASE = 66;

export const template: Template<{ values: string[]; push: string | null; pop: boolean }> = {
  parse(a) {
    const values = strings(a, "values", { def: [], max: 6, each: 6 });
    const push = optStr(a, "push", 6) ?? null;
    const pop = bool(a, "pop");
    if (push && pop) throw new BoardError("push or pop, not both");
    if (pop && values.length === 0) throw new BoardError("can't pop an empty stack");
    return { values, push, pop };
  },
  render({ values, push, pop }, { t }) {
    const out: Stroke[] = [title("STACK")];
    // the container: open at the top
    out.push(line(X - 1, BASE - 6 * H - 2, X - 1, BASE, "white", 0.6), line(X + W, BASE - 6 * H - 2, X + W, BASE, "white", 0.6), line(X - 1, BASE, X + W, BASE, "white", 0.6));
    const moving = Math.min(1, Math.max(0, (t - 1400) / 700));
    values.forEach((v, i) => {
      const y = BASE - (i + 1) * H;
      const top = i === values.length - 1;
      const lift = top && pop ? moving * 22 : 0;
      out.push(box(X + 1, y - lift, W - 2, H, top ? "amber" : "accent"), text(X + W / 2, y + 1 - lift, v.toUpperCase(), "white", "center"));
    });
    const topY = BASE - values.length * H;
    if (push) {
      const y = topY - H - (1 - moving) * 22;
      out.push(box(X + 1, y, W - 2, H, "cyan"), text(X + W / 2, y + 1, push.toUpperCase(), "white", "center"), text(X + W + 8, topY - 10, "PUSH", "cyan"));
    }
    if (pop) out.push(text(X + W + 8, topY - 4, "POP", "amber"));
    if (values.length) out.push(arrow(X + W + 22, topY + 3, X + W + 2, topY + 3, "amber", 2), text(X + W + 24, topY + 1, "TOP", "amber"));
    out.push(text(X + W + 8, BASE - 5, "LIFO", "accent", "left", 1, 0.6));
    return out;
  },
};
