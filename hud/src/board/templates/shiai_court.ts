// The shiai-jo, the match court, as the FIK Regulations of Kendo Shiai and Shinpan
// set it out (Art. 2): a square (or rectangle) 9 to 11 m a side, lines included,
// white lines 5-10 cm wide; a cross at the centre and two kaishi-sen (starting
// lines) at an equal distance either side of it; at least 1.5 m clear around it.
// The kaishi-sen's own length and spacing are in the Subsidiary Rules, so they
// are drawn to the usual proportion but not given a number here.
//
//   { "template": "shiai_court", "size"?: 9..11 }

import type { Template } from "../kit";
import { box, dashed, line, text, title } from "../kit";
import type { Stroke } from "../strokes";
import { num } from "../validate";

export const template: Template<{ size: number }> = {
  parse(a) {
    return { size: num(a, "size", { min: 9, max: 11, def: 11 }) };
  },
  render({ size }) {
    const side = 44; // cells for the court's side
    const x0 = 14;
    const y0 = 16;
    const m = side / size; // cells per metre
    const margin = Math.round(1.5 * m);
    const cx = x0 + side / 2;
    const cy = y0 + side / 2;
    const out: Stroke[] = [title("SHIAI-JŌ")];
    // the clear space around, then the court's boundary
    out.push(dashed(x0 - margin, y0 - margin, x0 + side + margin, y0 - margin, "white", 0.35), dashed(x0 + side + margin, y0 - margin, x0 + side + margin, y0 + side + margin, "white", 0.35), dashed(x0 + side + margin, y0 + side + margin, x0 - margin, y0 + side + margin, "white", 0.35), dashed(x0 - margin, y0 + side + margin, x0 - margin, y0 - margin, "white", 0.35));
    out.push(box(x0, y0, side + 1, side + 1, "white"));
    // the centre cross
    out.push(line(cx - 2, cy - 2, cx + 2, cy + 2, "amber"), line(cx - 2, cy + 2, cx + 2, cy - 2, "amber"));
    // the two kaishi-sen, equal distance either side of the centre
    const gap = Math.round(1.4 * m);
    const half = Math.round(0.5 * m);
    out.push(line(cx - half, cy - gap, cx + half, cy - gap, "cyan"), line(cx - half, cy + gap, cx + half, cy + gap, "cyan"));
    // labels to the right, each level with what it names, leaders straight across
    const edge = x0 + side + margin + 2;
    out.push(text(edge, y0 - 1, `${size} M SQUARE`, "white"));
    out.push(dashed(cx + half + 2, cy - gap, edge - 1, cy - gap, "cyan", 0.5), text(edge, cy - gap - 2, "KAISHI-SEN", "cyan"));
    out.push(dashed(cx + 4, cy, edge - 1, cy, "amber", 0.5), text(edge, cy - 2, "CENTRE", "amber"));
    out.push(dashed(cx + half + 2, cy + gap, edge - 1, cy + gap, "cyan", 0.5), text(edge, cy + gap - 2, "KAISHI-SEN", "cyan"));
    out.push(text(edge, y0 + side - 4, "1.5 M CLEAR", "white", "left", 1, 0.6));
    return out;
  },
};
