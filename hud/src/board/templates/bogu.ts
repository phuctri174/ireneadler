// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// Bogu, the kendo armour, on a figure seen from the front, each part labelled:
// men (the helmet: grille, and flaps over the shoulders), kote (the gauntlets),
// dō (the chest protector) and tare (the waist protector, its flaps).
//
//   { "template": "bogu", "highlight"?: "do" }

import type { Template } from "../kit";
import { box, fill, line, ring, text, title } from "../kit";
import type { Color, Stroke } from "../strokes";
import { str } from "../validate";

const PARTS = ["men", "kote", "do", "tare"] as const;
type Part = (typeof PARTS)[number];

const CX = 34;

export function boguFigure(c: (part: Part, base: Color) => Color): Stroke[] {
  const out: Stroke[] = [];
  // men: the helmet with its grille, and the men-dare flaps over the shoulders
  out.push(ring(CX, 15, 9, c("men", "white")));
  for (let y = 10; y <= 20; y += 2) out.push(line(CX - 5, y, CX + 5, y, c("men", "white"), 0.6));
  out.push(line(CX, 8, CX, 21, c("men", "white"), 0.6));
  out.push(fill(CX - 17, 23, 9, 7, c("men", "white"), 0.3), fill(CX + 9, 23, 9, 7, c("men", "white"), 0.3));
  // dō: the curved chest protector
  out.push(box(CX - 9, 25, 19, 17, c("do", "accent")));
  for (const y of [29, 32]) out.push(line(CX - 7, y, CX + 7, y, c("do", "accent"), 0.5));
  // arms in the keikogi sleeves, down to the kote
  out.push(line(CX - 11, 27, CX - 15, 40, "white", 0.4), line(CX + 11, 27, CX + 15, 40, "white", 0.4));
  // kote: the padded gauntlets
  out.push(fill(CX - 18, 40, 6, 8, c("kote", "accent"), 0.5), box(CX - 18, 40, 6, 8, c("kote", "accent")));
  out.push(fill(CX + 13, 40, 6, 8, c("kote", "accent"), 0.5), box(CX + 13, 40, 6, 8, c("kote", "accent")));
  // tare: a belt and five flaps (three large in front, two small at the sides)
  out.push(line(CX - 10, 43, CX + 10, 43, c("tare", "white")));
  for (const [x, w, h] of [[-10, 6, 10], [-3, 6, 11], [4, 6, 10]] as const) out.push(box(CX + x, 44, w, h, c("tare", "white")));
  out.push(box(CX - 14, 44, 4, 7, c("tare", "white"), 0.6), box(CX + 10, 44, 4, 7, c("tare", "white"), 0.6));
  // hakama below
  out.push(line(CX - 10, 55, CX - 14, 69, "white", 0.35), line(CX + 10, 55, CX + 14, 69, "white", 0.35), line(CX, 56, CX, 69, "white", 0.25));
  return out;
}

export const template: Template<{ highlight: Part[] | null }> = {
  parse(a) {
    // one part, or a list of them
    const raw = a.highlight;
    const list = raw === undefined || raw === null ? [] : Array.isArray(raw) ? raw : [raw];
    const picked = list.map((h) => str({ h }, "h", { oneOf: PARTS }) as Part);
    return { highlight: picked.length === 0 || picked.length === PARTS.length ? null : picked };
  },
  render({ highlight }) {
    const c = (part: Part, base: Color): Color => (highlight?.includes(part) ? "amber" : base);
    const out: Stroke[] = [title("BOGU"), ...boguFigure(c)];
    const labels: [Part, number, number, string][] = [
      ["men", 16, 15, "MEN"],
      ["do", 33, 33, "DŌ"],
      ["kote", 44, 49, "KOTE"],
      ["tare", 51, 49, "TARE"],
    ];
    labels.forEach(([part, y, fromX, label], i) => {
      const ly = 17 + i * 12;
      out.push(line(fromX + 12, y, 66, ly + 2, c(part, "white"), 0.45), text(68, ly, label, c(part, "white"), "left", 2));
    });
    return out;
  },
};
