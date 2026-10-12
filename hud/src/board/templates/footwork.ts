// Kendo footwork (ashi-sabaki) as footprints and numbered arrows, seen from above,
// forward = up. Start positions dim, end positions bright; right foot ahead as in
// chudan, left heel raised.
//   okuri-ashi   the leading foot moves first, the other follows at once (any direction)
//   ayumi-ashi   ordinary walking steps, feet passing each other
//   tsugi-ashi   the left foot is drawn up behind the right, then the right steps out
//   hiraki-ashi  a diagonal side-step, turning to keep facing the opponent
//
//   { "template": "footwork", "step": "okuri_ashi", "direction"?: "forward|back|left|right" }

import type { Template } from "../kit";
import { arrow, box, fill, text, title } from "../kit";
import type { Stroke } from "../strokes";
import { str } from "../validate";

const STEPS = ["okuri_ashi", "ayumi_ashi", "tsugi_ashi", "hiraki_ashi"] as const;
type Step = (typeof STEPS)[number];
type Dir = "forward" | "back" | "left" | "right";

interface Foot {
  side: "R" | "L";
  x: number;
  y: number;
}
interface Move {
  side: "R" | "L";
  to: { x: number; y: number };
}

const R0 = { x: 44, y: 44 };
const L0 = { x: 34, y: 52 };

function plan(step: Step, dir: Dir): { moves: Move[]; notes: string[] } {
  switch (step) {
    case "okuri_ashi": {
      const d = { forward: [0, -16], back: [0, 16], left: [-14, 0], right: [14, 0] }[dir];
      // the foot on the side you go leads: forward/right -> right foot first
      const lead: "R" | "L" = dir === "forward" || dir === "right" ? "R" : "L";
      const other: "R" | "L" = lead === "R" ? "L" : "R";
      const at = (s: "R" | "L") => (s === "R" ? R0 : L0);
      return {
        moves: [
          { side: lead, to: { x: at(lead).x + d[0], y: at(lead).y + d[1] } },
          { side: other, to: { x: at(other).x + d[0], y: at(other).y + d[1] } },
        ],
        notes: [`1 ${lead === "R" ? "RIGHT" : "LEFT"} FOOT`, "  MOVES FIRST", `2 ${other === "R" ? "RIGHT" : "LEFT"} FOLLOWS`, "NEVER CROSS"],
      };
    }
    case "ayumi_ashi":
      return {
        moves: [
          { side: "L", to: { x: L0.x, y: L0.y - 22 } },
          { side: "R", to: { x: R0.x, y: R0.y - 26 } },
        ],
        notes: ["1 LEFT PASSES", "2 RIGHT PASSES", "LIKE WALKING", "LONG DISTANCES"],
      };
    case "tsugi_ashi":
      return {
        moves: [
          { side: "L", to: { x: L0.x, y: R0.y + 4 } },
          { side: "R", to: { x: R0.x, y: R0.y - 18 } },
        ],
        notes: ["1 LEFT DRAWN UP", "  BEHIND RIGHT", "2 RIGHT STEPS", "CLOSES DISTANCE"],
      };
    case "hiraki_ashi":
      return {
        moves: [
          { side: "R", to: { x: R0.x + 14, y: R0.y - 8 } },
          { side: "L", to: { x: L0.x + 14, y: L0.y - 6 } },
        ],
        notes: ["1 RIGHT STEPS", "  DIAGONALLY", "2 LEFT FOLLOWS", "TURN TO FACE"],
      };
  }
}

function print(f: Foot, bright: boolean): Stroke[] {
  // a footprint: a rounded box, toe up
  return [fill(f.x - 2, f.y - 4, 5, 8, "accent", bright ? 0.4 : 0.12), box(f.x - 2, f.y - 4, 5, 8, "accent", bright ? 1 : 0.35), text(f.x, f.y - 2, f.side, "white", "center", 1, bright ? 1 : 0.4)];
}

export const template: Template<{ step: Step; dir: Dir }> = {
  parse(a) {
    const step = str(a, "step", { def: "okuri_ashi", oneOf: STEPS }) as Step;
    const dir = str(a, "direction", { def: "forward", oneOf: ["forward", "back", "left", "right"] }) as Dir;
    return { step, dir: step === "okuri_ashi" ? dir : "forward" };
  },
  render({ step, dir }) {
    const { moves, notes } = plan(step, dir);
    const out: Stroke[] = [title(step.replace("_", "-").toUpperCase() + (step === "okuri_ashi" ? ` ${dir.toUpperCase()}` : ""))];
    const feet: Record<"R" | "L", Foot> = { R: { side: "R", ...R0 }, L: { side: "L", ...L0 } };
    out.push(...print(feet.R, false), ...print(feet.L, false));
    moves.forEach((m, i) => {
      const from = feet[m.side];
      out.push(arrow(from.x, from.y, m.to.x, m.to.y, "amber", 3), text((from.x + m.to.x) / 2 + 5, (from.y + m.to.y) / 2 - 2, String(i + 1), "amber"));
      feet[m.side] = { side: m.side, ...m.to };
      out.push(...print(feet[m.side], true));
    });
    out.push(text(20, 66, "FORWARD", "white", "center", 1, 0.5), arrow(8, 68, 8, 60, "white", 2));
    notes.forEach((n, i) => out.push(text(66, 22 + i * 8, n, i < 3 ? "white" : "accent")));
    return out;
  },
};
