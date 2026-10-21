// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// A folder tree from a list of paths: folders first, indented, files under them.
//
//   { "template": "folder_tree", "root"?: "Downloads", "paths": ["pdf/tax.pdf", "img/cat.png"] }

import type { Template } from "../kit";
import { line, text, title } from "../kit";
import type { Color, Stroke } from "../strokes";
import { optStr, strings } from "../validate";

interface Node {
  name: string;
  children: Map<string, Node>;
  file: boolean;
}

export function treeOf(paths: string[]): Node {
  const root: Node = { name: "", children: new Map(), file: false };
  for (const p of paths) {
    const parts = p.replace(/\\/g, "/").split("/").filter(Boolean);
    let at = root;
    parts.forEach((part, i) => {
      if (!at.children.has(part)) at.children.set(part, { name: part, children: new Map(), file: i === parts.length - 1 });
      at = at.children.get(part) as Node;
      if (i < parts.length - 1) at.file = false;
    });
  }
  return root;
}

export interface Row {
  depth: number;
  name: string;
  file: boolean;
}

export function rowsOf(node: Node, depth = 0, out: Row[] = []): Row[] {
  const kids = [...node.children.values()].sort((a, b) => Number(a.file) - Number(b.file) || a.name.localeCompare(b.name));
  for (const k of kids) {
    out.push({ depth, name: k.name, file: k.file });
    rowsOf(k, depth + 1, out);
  }
  return out;
}

/** Tree rows drawn from (x, y), 7 rows apart, with branch lines; at most `max` rows. */
export function drawRows(rows: Row[], x: number, y: number, max: number, width: number, color: Color = "accent"): Stroke[] {
  const out: Stroke[] = [];
  const shown = rows.slice(0, rows.length > max ? max - 1 : max);
  shown.forEach((r, i) => {
    const rx = x + r.depth * 6;
    const ry = y + i * 7;
    if (r.depth > 0) out.push(line(rx - 4, ry + 2, rx - 1, ry + 2, color, 0.45), line(rx - 4, ry - 4, rx - 4, ry + 2, color, 0.45));
    const room = Math.max(3, Math.floor((width - (rx - x) - 6) / 4));
    const name = r.name.toUpperCase();
    // a folder gets a small tab icon, a file a page
    if (!r.file) out.push({ kind: "cells", cells: [[0, 0], [1, 0], [0, 1], [1, 1], [2, 1], [3, 1], [0, 2], [3, 2], [0, 3], [1, 3], [2, 3], [3, 3]].map(([cx, cy]) => ({ x: rx + cx, y: ry + cy + 1 })), color: "amber" });
    else out.push({ kind: "cells", cells: [[0, 0], [1, 0], [2, 0], [0, 1], [2, 1], [0, 2], [2, 2], [0, 3], [1, 3], [2, 3]].map(([cx, cy]) => ({ x: rx + cx, y: ry + cy + 1 })), color: "white" });
    out.push(text(rx + 6, ry, name.length > room ? `${name.slice(0, room - 1)}.` : name, r.file ? "white" : "amber"));
  });
  if (rows.length > max) out.push(text(x, y + (max - 1) * 7, `+${rows.length - max + 1} MORE`, "accent", "left", 1, 0.7));
  return out;
}

export const template: Template<{ root: string; rows: Row[] }> = {
  parse(a) {
    const paths = strings(a, "paths", { min: 1, max: 60, each: 120 });
    return { root: optStr(a, "root", 20) ?? "FOLDER", rows: rowsOf(treeOf(paths)) };
  },
  render({ root, rows }) {
    return [title(root), ...drawRows(rows, 4, 18, 8, 120)];
  },
};
