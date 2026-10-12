// The shinai, lying tip to the right, every part labelled:
// kensen (the tip end), sakigawa (the leather tip cap), nakayui (the leather tie
// about a quarter of the way down from the tip), tsuru (the string along the back,
// from the tsukagawa to the sakigawa), tsuba (the guard), tsuka (the hilt) and
// tsukagawa (the leather sleeve over the tsuka).
//
//   { "template": "shinai", "highlight"?: "nakayui" }

import type { Template } from "../kit";
import { dot, fill, line, text, title } from "../kit";
import type { Color, Stroke } from "../strokes";
import { str } from "../validate";

const PARTS = ["kensen", "sakigawa", "nakayui", "tsuru", "tsuba", "tsuka", "tsukagawa"] as const;
type Part = (typeof PARTS)[number];

// A real shinai's proportions across the whole board: the tsuka about a quarter
// of its length, the sakigawa the last twentieth, the nakayui a quarter of the way
// back from the tip. (It used to stop at x=96, stubby, with the tip crowded.)
const Y = 38; // the shinai's axis
const BUTT = 4;
const TIP = 123;
const LENGTH = TIP - BUTT;
const TSUBA = Math.round(BUTT + LENGTH * 0.24);
const SAKIGAWA = Math.round(TIP - LENGTH * 0.06);
const NAKAYUI = Math.round(TIP - LENGTH * 0.25);

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
    const out: Stroke[] = [title("SHINAI")];
    // tsuka under its leather tsukagawa, butt end rounded
    out.push(fill(BUTT, Y - 2, TSUBA - BUTT - 1, 5, c("tsukagawa", "white"), 0.35));
    out.push(line(BUTT, Y - 2, TSUBA - 2, Y - 2, c("tsukagawa", "white")), line(BUTT, Y + 2, TSUBA - 2, Y + 2, c("tsukagawa", "white")), line(BUTT, Y - 2, BUTT, Y + 2, c("tsukagawa", "white")));
    // tsuba: a round guard, seen edge-on as a tall disc
    out.push(fill(TSUBA - 1, Y - 6, 3, 13, c("tsuba", "amber"), 0.8));
    // a tsubadome, the little stopper that holds the tsuba on
    out.push(fill(TSUBA + 2, Y - 2, 2, 5, c("tsuba", "amber"), 0.45));
    // the blade: four staves tapering a little toward the tip
    out.push(line(TSUBA + 4, Y - 2, SAKIGAWA - 1, Y - 1, "accent"), line(TSUBA + 4, Y + 2, SAKIGAWA - 1, Y + 1, "accent"), line(TSUBA + 4, Y, SAKIGAWA - 1, Y, "accent", 0.35));
    // nakayui: the leather tie, a band round the staves
    out.push(fill(NAKAYUI - 1, Y - 3, 3, 7, c("nakayui", "white"), 0.9));
    // sakigawa: the leather cap, and the kensen at its very end
    out.push(fill(SAKIGAWA, Y - 2, TIP - SAKIGAWA, 5, c("sakigawa", "white"), 0.55));
    out.push(dot(TIP, Y, 1.4, c("kensen", "pink")));
    // tsuru: the string along the back (top), tsukagawa to sakigawa
    out.push(line(BUTT + 14, Y - 3, SAKIGAWA, Y - 3, c("tsuru", "cyan"), 0.8));
    // labels with leader lines: above the blade, then below it
    const above: [Part, number, string][] = [
      ["tsukagawa", 16, "TSUKAGAWA"],
      ["tsuru", 62, "TSURU"],
      ["nakayui", NAKAYUI, "NAKAYUI"],
      ["kensen", TIP - 1, "KENSEN"],
    ];
    const below: [Part, number, string][] = [
      ["tsuka", 16, "TSUKA"],
      ["tsuba", TSUBA, "TSUBA"],
      ["sakigawa", Math.round((SAKIGAWA + TIP) / 2), "SAKIGAWA"],
    ];
    above.forEach(([part, x, label], i) => {
      const ly = 22 + (i % 2) * 7;
      out.push(line(x, ly + 6, x, Y - 4, c(part, "white"), 0.5), text(Math.min(Math.max(x, 2 + label.length * 2), 124 - label.length * 2), ly, label, c(part, "white"), "center"));
    });
    below.forEach(([part, x, label], i) => {
      const ly = 50 + (i % 2) * 7;
      out.push(line(x, Y + 4, x, ly - 1, c(part, "white"), 0.5), text(Math.min(Math.max(x, 2 + label.length * 2), 124 - label.length * 2), ly, label, c(part, "white"), "center"));
    });
    return out;
  },
};
