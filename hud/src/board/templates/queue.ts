// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// A queue: items front to back, left to right; dequeue from the front, enqueue at the back.
//
//   { "template": "queue", "values": ["a", "b", "c"], "enqueue"?: "d", "dequeue"?: true }

import type { Template } from "../kit";
import { arrow, text, title } from "../kit";
import type { Stroke } from "../strokes";
import { BoardError, bool, optStr, strings } from "../validate";
import { cellsRow } from "./array";

export const template: Template<{ values: string[]; enqueue: string | null; dequeue: boolean }> = {
  parse(a) {
    const values = strings(a, "values", { def: [], max: 9, each: 5 });
    const dequeue = bool(a, "dequeue");
    if (dequeue && values.length === 0) throw new BoardError("can't dequeue an empty queue");
    return { values, enqueue: optStr(a, "enqueue", 5) ?? null, dequeue };
  },
  render({ values, enqueue, dequeue }) {
    const out: Stroke[] = [title("QUEUE")];
    const y = 30;
    const x0 = 18;
    const row = cellsRow(values.length ? values : [" "], x0, y, 92);
    out.push(...row.stroke);
    const first = row.xs[0];
    const last = row.xs[row.xs.length - 1];
    out.push(text(first, y + 14, "FRONT", "amber", "center"), text(last, y + 14, "BACK", "cyan", "center"));
    if (dequeue) out.push(arrow(first - 4, y + 5, 2, y + 5, "amber", 2), text(2, y - 8, "OUT", "amber"));
    if (enqueue) {
      const x = last + row.w;
      out.push(arrow(126, y + 5, x - 2, y + 5, "cyan", 2), text(124, y - 8, enqueue.toUpperCase(), "cyan", "right"));
    }
    out.push(text(64, 56, "FIFO: FIRST IN, FIRST OUT", "accent", "center", 1, 0.6));
    return out;
  },
};
