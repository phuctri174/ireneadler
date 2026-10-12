// A binary tree from its level-order array (null for a missing child), up to 4 levels.
//
//   { "template": "binary_tree", "values": [8, 3, 10, 1, 6, null, 14], "highlight"?: [6] }

import type { Template } from "../kit";
import { line, ring, text, title } from "../kit";
import type { Stroke } from "../strokes";
import { BoardError, list, optStr } from "../validate";

export const template: Template<{ nodes: (string | null)[]; highlight: string[]; title: string | null }> = {
  parse(a) {
    const nodes = list(a, "values", { min: 1, max: 15 }).map((v, i) => {
      if (v === null) return null;
      if (typeof v !== "string" && typeof v !== "number") throw new BoardError(`values[${i}] must be a value or null`);
      return String(v).slice(0, 3);
    });
    if (nodes[0] === null) throw new BoardError("the root can't be null");
    nodes.forEach((v, i) => {
      if (v !== null && i > 0 && nodes[Math.floor((i - 1) / 2)] === null) throw new BoardError(`values[${i}] has no parent`);
    });
    const highlight = list(a, "highlight", { def: [], max: 15 }).map((v) => String(v));
    return { nodes, highlight, title: optStr(a, "title", 24) ?? null };
  },
  render({ nodes, highlight, title: t }) {
    const out: Stroke[] = [title(t ?? "BINARY TREE")];
    const levels = Math.ceil(Math.log2(nodes.length + 1));
    const pos = (i: number) => {
      const level = Math.floor(Math.log2(i + 1));
      const k = i - (2 ** level - 1);
      const slots = 2 ** level;
      return { x: 4 + ((k + 0.5) * 120) / slots, y: 18 + level * (levels > 3 ? 14 : 17) };
    };
    nodes.forEach((v, i) => {
      if (v === null || i === 0) return;
      const p = pos(i);
      const q = pos(Math.floor((i - 1) / 2));
      out.push(line(q.x, q.y + 5, p.x, p.y - 5, "accent", 0.6));
    });
    nodes.forEach((v, i) => {
      if (v === null) return;
      const p = pos(i);
      const hot = highlight.includes(v);
      out.push(ring(p.x, p.y, 5, hot ? "amber" : "accent"), text(p.x + 1, p.y - 2, v, hot ? "amber" : "white", "center"));
    });
    return out;
  },
};
