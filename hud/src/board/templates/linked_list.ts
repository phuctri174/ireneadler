// A linked list: nodes with a value and a next pointer, arrows between, NULL at the
// end; doubly linked adds the back arrows. HEAD marks the first node.
//
//   { "template": "linked_list", "values": [3, 7, 1], "doubly"?: false, "highlight"?: [1] }

import type { Template } from "../kit";
import { arrow, box, fill, line, text, title } from "../kit";
import type { Stroke } from "../strokes";
import { BoardError, bool, numbers, strings } from "../validate";

export const template: Template<{ values: string[]; doubly: boolean; highlight: number[] }> = {
  parse(a) {
    const values = strings(a, "values", { min: 1, max: 6, each: 4 });
    const highlight = numbers(a, "highlight", { def: [], max: 6 });
    if (highlight.some((i) => !Number.isInteger(i) || i < 0 || i >= values.length)) throw new BoardError("highlight must be node indices");
    return { values, doubly: bool(a, "doubly"), highlight };
  },
  render({ values, doubly, highlight }) {
    const out: Stroke[] = [title(doubly ? "DOUBLY LINKED LIST" : "LINKED LIST")];
    const n = values.length;
    const gap = 6;
    const w = Math.min(19, Math.floor((112 - gap * n) / n));
    const y = 32;
    const x0 = 4;
    values.forEach((v, i) => {
      const x = x0 + i * (w + gap);
      if (highlight.includes(i)) out.push(fill(x + 1, y + 1, w - 6, 9, "amber", 0.35));
      out.push(box(x, y, w, 11, "accent"), line(x + w - 5, y, x + w - 5, y + 10, "accent", 0.6), text(x + (w - 5) / 2, y + 3, v.toUpperCase(), "white", "center"));
      out.push({ kind: "disc", x: x + w - 3, y: y + 5, r: 0.6, color: "amber" });
      const next = x + w + gap;
      if (i < n - 1) out.push(arrow(x + w - 2, y + 4, next - 1, y + 4, "amber", 2));
      if (doubly && i > 0) out.push(arrow(x - 1, y + 8, x - gap + 1, y + 8, "cyan", 2));
    });
    const end = x0 + n * (w + gap) - gap;
    out.push(arrow(end - 2, y + 4, end + 3, y + 4, "amber", 2), text(end + 5, y + 2, "NULL", "white", "left", 1, 0.6));
    out.push(arrow(x0 + 4, y - 9, x0 + 4, y - 2, "amber", 2), text(x0 + 7, y - 11, "HEAD", "amber"));
    return out;
  },
};
