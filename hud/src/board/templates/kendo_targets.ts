// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// The four datotsu-bui - where a strike or thrust scores - on a figure in bogu seen
// from the front: men (the top of the men), kote (the right kote; the figure's
// right is the viewer's left), dō (the right side of the dō; the left side,
// gyaku-dō, also counts) and tsuki (the throat, the tsuki-dare).
//
//   { "template": "kendo_targets", "highlight"?: "kote" }

import type { Template } from "../kit";
import { line, ring, text } from "../kit";
import type { Color, Stroke } from "../strokes";
import { str } from "../validate";
import { boguFigure } from "./bogu";

const TARGETS = ["men", "kote", "do", "tsuki"] as const;
type Target = (typeof TARGETS)[number];

// on the bogu figure (bogu.ts, centred at x 34)
const SPOTS: Record<Target, { x: number; y: number; label: string; note: string }> = {
  men: { x: 34, y: 7, label: "MEN", note: "TOP OF THE HEAD" },
  tsuki: { x: 34, y: 23, label: "TSUKI", note: "THROAT" },
  do: { x: 26, y: 35, label: "DŌ", note: "RIGHT SIDE" },
  kote: { x: 19, y: 44, label: "KOTE", note: "RIGHT FOREARM" },
};

export const template: Template<{ highlight: Target[] | null }> = {
  parse(a) {
    // one part, or a list of them
    const raw = a.highlight;
    const list = raw === undefined || raw === null ? [] : Array.isArray(raw) ? raw : [raw];
    const picked = list.map((h) => str({ h }, "h", { oneOf: TARGETS }) as Target);
    return { highlight: picked.length === 0 || picked.length === TARGETS.length ? null : picked };
  },
  render({ highlight }) {
    const out: Stroke[] = [text(64, 66, "DATOTSU-BUI", "accent", "left", 1, 0.7), ...boguFigure(() => "white" as Color)];
    TARGETS.forEach((target, i) => {
      const s = SPOTS[target];
      const hot = highlight === null || highlight.includes(target);
      const color: Color = hot ? "amber" : "accent";
      out.push(ring(s.x, s.y, 3, color), ring(s.x, s.y, 1, color));
      const ly = 17 + i * 12;
      out.push(line(s.x + 4, s.y, 62, ly + 2, color, 0.5), text(64, ly, s.label, hot ? "amber" : "white", "left", 1), text(64, ly + 6, s.note, "white", "left", 1, 0.55));
    });
    return out;
  },
};
