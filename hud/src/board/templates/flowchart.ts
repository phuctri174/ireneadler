// A flowchart: start/end as rounded caps, processes as boxes, decisions as
// diamonds; laid out in layers top to bottom from the links, arrows between with
// their labels (yes/no).
//
//   { "template": "flowchart",
//     "nodes": [{ "id": "a", "text": "Start", "kind": "start" }, { "id": "b", "text": "x > 0?", "kind": "decision" }, ...],
//     "links": [["a", "b"], ["b", "c", "yes"], ["b", "d", "no"]] }

import type { Template } from "../kit";
import { arrow, box, line, text } from "../kit";
import type { Stroke } from "../strokes";
import { BoardError, list, obj, str } from "../validate";

const KINDS = ["start", "end", "process", "decision", "io"] as const;
type Kind = (typeof KINDS)[number];

interface FNode {
  id: string;
  text: string;
  kind: Kind;
  layer: number;
  slot: number;
  of: number;
}
interface Link {
  from: number;
  to: number;
  label: string | null;
}

export const template: Template<{ nodes: FNode[]; links: Link[] }> = {
  parse(a) {
    const raw = list(a, "nodes", { min: 1, max: 12 }).map((r, i) => {
      const n = obj(r, `nodes[${i}]`);
      return { id: str(n, "id", { max: 12 }), text: str(n, "text", { max: 20 }), kind: str(n, "kind", { def: "process", oneOf: KINDS }) as Kind };
    });
    const ids = raw.map((n) => n.id);
    if (new Set(ids).size !== ids.length) throw new BoardError("node ids must be unique");
    const links = list(a, "links", { def: [], max: 20 }).map((r, i): Link => {
      if (!Array.isArray(r) || r.length < 2 || r.length > 3) throw new BoardError(`links[${i}] must be [from, to] or [from, to, label]`);
      const from = ids.indexOf(String(r[0]));
      const to = ids.indexOf(String(r[1]));
      if (from < 0 || to < 0) throw new BoardError(`links[${i}] names a node that isn't there`);
      return { from, to, label: r[2] === undefined ? null : String(r[2]).slice(0, 4) };
    });
    // layers: longest path from a source, ignoring links that go back up (loops)
    const layer = raw.map(() => 0);
    for (let pass = 0; pass < raw.length; pass += 1) {
      for (const l of links) if (l.to !== l.from && layer[l.to] < layer[l.from] + 1 && l.to > l.from) layer[l.to] = layer[l.from] + 1;
    }
    const depth = Math.max(...layer) + 1;
    if (depth > 6) throw new BoardError("at most 6 levels fit on the board");
    const nodes = raw.map((n, i) => ({ ...n, layer: layer[i], slot: 0, of: 1 }));
    for (let d = 0; d < depth; d += 1) {
      const here = nodes.filter((n) => n.layer === d);
      if (here.length > 3) throw new BoardError("at most 3 boxes side by side");
      here.forEach((n, k) => Object.assign(n, { slot: k, of: here.length }));
    }
    return { nodes, links };
  },
  render({ nodes, links }) {
    const depth = Math.max(...nodes.map((n) => n.layer)) + 1;
    const rowH = Math.min(12, Math.floor(70 / depth));
    const pos = (n: FNode) => ({ x: ((n.slot + 0.5) * 98) / n.of, y: 2 + n.layer * rowH + Math.floor((rowH - 9) / 2) });
    const out: Stroke[] = [];
    const W = 34;
    for (const n of nodes) {
      const p = pos(n);
      const x = Math.round(p.x - W / 2);
      if (n.kind === "decision") {
        // a diamond
        const cx = p.x;
        const cy = p.y + 4;
        out.push(line(cx - W / 2, cy, cx, cy - 5, "amber"), line(cx, cy - 5, cx + W / 2, cy, "amber"), line(cx + W / 2, cy, cx, cy + 5, "amber"), line(cx, cy + 5, cx - W / 2, cy, "amber"));
      } else if (n.kind === "start" || n.kind === "end") {
        out.push(box(x + 2, p.y, W - 4, 9, "cyan"), line(x, p.y + 2, x, p.y + 6, "cyan"), line(x + W - 1, p.y + 2, x + W - 1, p.y + 6, "cyan"));
      } else {
        out.push(box(x, p.y, W, 9, n.kind === "io" ? "pink" : "accent"));
      }
      const label = n.text.toUpperCase();
      out.push(text(p.x + 1, p.y + 2, label.length > 8 ? `${label.slice(0, 7)}.` : label, "white", "center"));
    }
    for (const l of links) {
      const a = pos(nodes[l.from]);
      const b = pos(nodes[l.to]);
      if (nodes[l.to].layer > nodes[l.from].layer) {
        out.push(arrow(a.x, a.y + 10, b.x, b.y - 1, "white", 2));
        // the label just below where the arrow leaves, on its outside
        if (l.label) out.push(text(a.x + (b.x - a.x) * 0.3 + (b.x >= a.x ? 3 : -3), a.y + 10, l.label.toUpperCase(), "amber", b.x >= a.x ? "left" : "right"));
      } else {
        // a loop back up: out to the side and round
        const side = Math.max(a.x, b.x) + W / 2 + 4;
        out.push(line(a.x + W / 2, a.y + 4, side, a.y + 4, "white", 0.6), line(side, a.y + 4, side, b.y + 4, "white", 0.6), arrow(side, b.y + 4, b.x + W / 2 + 1, b.y + 4, "white", 2));
        if (l.label) out.push(text(side + 2, (a.y + b.y) / 2, l.label.toUpperCase(), "amber"));
      }
    }
    return out;
  },
};
