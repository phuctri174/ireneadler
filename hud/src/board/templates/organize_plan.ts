// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// An organize_files dry-run plan as before / after: the loose files on the left,
// the folders they would go into on the right, an arrow between.
//
//   { "template": "organize_plan", "moves": [["tax.pdf", "Documents/tax.pdf"], ...], "root"?: "Downloads" }

import type { Template } from "../kit";
import { arrow, line, text, title } from "../kit";
import type { Stroke } from "../strokes";
import { BoardError, list, optStr } from "../validate";
import { drawRows, rowsOf, treeOf } from "./folder_tree";
import type { Row } from "./folder_tree";

export const template: Template<{ root: string; before: Row[]; after: Row[]; count: number }> = {
  parse(a) {
    const moves = list(a, "moves", { min: 1, max: 60 }).map((raw, i) => {
      if (!Array.isArray(raw) || raw.length !== 2 || raw.some((p) => typeof p !== "string" || !p.trim())) throw new BoardError(`moves[${i}] must be ["from", "to"]`);
      return raw as [string, string];
    });
    return {
      root: optStr(a, "root", 20) ?? "FOLDER",
      before: rowsOf(treeOf(moves.map(([from]) => from))),
      after: rowsOf(treeOf(moves.map(([, to]) => to))),
      count: moves.length,
    };
  },
  render({ root, before, after, count }) {
    const out: Stroke[] = [title(`${root} - ${count} FILES`)];
    out.push(text(4, 10, "BEFORE", "accent"), text(68, 18, "AFTER", "accent"));
    out.push(...drawRows(before, 4, 18, 7, 52, "accent"));
    out.push(line(62, 18, 62, 68, "white", 0.25), arrow(55, 44, 66, 44, "amber", 3));
    out.push(...drawRows(after, 68, 26, 6, 58, "accent"));
    return out;
  },
};
