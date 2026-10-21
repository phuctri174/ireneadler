// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// A graph: nodes round a circle, edges between them (arrows if directed, weights
// at the midpoints), a path highlighted.
//
//   { "template": "graph", "nodes": ["A", "B", "C"], "edges": [["A", "B", 4], ["B", "C"]],
//     "directed"?: false, "path"?: ["A", "B", "C"] }

import type { Template } from "../kit";
import { arrow, line, ring, text, title } from "../kit";
import type { Stroke } from "../strokes";
import { BoardError, bool, list, optStr, strings } from "../validate";

interface Edge {
  a: number;
  b: number;
  w: string | null;
}

export const template: Template<{ nodes: string[]; edges: Edge[]; directed: boolean; path: number[]; title: string | null }> = {
  parse(a) {
    // nodes as names, or as objects with a name/id/label
    const nodes = strings({ nodes: list(a, "nodes", { min: 1, max: 10 }).map((n) => (n && typeof n === "object" ? ((n as Record<string, unknown>).name ?? (n as Record<string, unknown>).id ?? (n as Record<string, unknown>).label) : n)) }, "nodes", { each: 3 });
    const index = (v: unknown, what: string) => {
      const i = nodes.indexOf(String(v));
      if (i < 0) throw new BoardError(`${what}: ${String(v)} is not a node`);
      return i;
    };
    const edges = list(a, "edges", { def: [], max: 24 }).map((raw, i): Edge => {
      if (!Array.isArray(raw) || raw.length < 2 || raw.length > 3) throw new BoardError(`edges[${i}] must be [from, to] or [from, to, weight]`);
      return { a: index(raw[0], `edges[${i}]`), b: index(raw[1], `edges[${i}]`), w: raw.length === 3 ? String(raw[2]).slice(0, 3) : null };
    });
    const path = list(a, "path", { def: [], max: 10 }).map((v, i) => index(v, `path[${i}]`));
    return { nodes, edges, directed: bool(a, "directed"), path, title: optStr(a, "title", 24) ?? null };
  },
  render({ nodes, edges, directed, path, title: t }) {
    const out: Stroke[] = [title(t ?? (directed ? "DIRECTED GRAPH" : "GRAPH"))];
    const c = { x: 52, y: 42 };
    const r = nodes.length === 1 ? 0 : 22;
    const at = (i: number) => ({ x: c.x + Math.sin((i / nodes.length) * Math.PI * 2) * r * 1.5, y: c.y - Math.cos((i / nodes.length) * Math.PI * 2) * r });
    const onPath = (e: Edge) => path.some((p, k) => k > 0 && ((path[k - 1] === e.a && p === e.b) || (!directed && path[k - 1] === e.b && p === e.a)));
    for (const e of edges) {
      const p = at(e.a);
      const q = at(e.b);
      const d = Math.hypot(q.x - p.x, q.y - p.y) || 1;
      const ux = (q.x - p.x) / d;
      const uy = (q.y - p.y) / d;
      const from = { x: p.x + ux * 6, y: p.y + uy * 6 };
      const to = { x: q.x - ux * 6, y: q.y - uy * 6 };
      const color = onPath(e) ? "amber" : "accent";
      out.push(directed ? arrow(from.x, from.y, to.x, to.y, color, 2) : line(from.x, from.y, to.x, to.y, color, onPath(e) ? 1 : 0.6));
      if (e.w) out.push(text((from.x + to.x) / 2 + 2, (from.y + to.y) / 2 - 5, e.w, "cyan", "center"));
    }
    nodes.forEach((n, i) => {
      const p = at(i);
      const hot = path.includes(i);
      out.push(ring(p.x, p.y, 5, hot ? "amber" : "white"), text(p.x + 1, p.y - 2, n.toUpperCase(), hot ? "amber" : "white", "center"));
    });
    return out;
  },
};
