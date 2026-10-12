// Theatrical expressions: emoji-level faces, for when she is filmed (a skit -
// core/irene/skit.py - watched on a phone). The everyday expressions are a pair of
// 7x7 eyes; these are the whole face, drawn big enough to read at a glance on a
// six-inch screen: their own mouth, brows, tears, a halo, hands over the face,
// shoulders. They hold for as long as the expression does (a gesture's pose fades
// after two seconds; these don't), and they move with her face (shiftX/Y, tilt).
//
//   sobbing   😭  eyes squeezed > <, a wailing mouth, tears pouring off both sides,
//                 shoulders heaving
//   innocent  😇  serene closed arcs, a tiny smile, blush, a glowing halo, a slow bob
//   peeking   🫣  both hands up over her face, fingers spread, one eye through the gap
//   smug      😏  one brow high, one flat, a one-sided smirk, dead still

import type { Emotion } from "../face/faceState";
import { EYE_H, EYE_W, EYE_Y, LEFT_EYE_X, MOUTH_X, MOUTH_Y, RIGHT_EYE_X } from "./face";
import type { FaceLook } from "./face";
import { FADE, INK, blit, capsule, clamp01, drawShape, easeOutBack, sprite } from "./grid";
import type { Frame, Ink, Vec } from "./grid";
import { HANDS, drawHand } from "./hands";
import type { HandPose } from "./hands";

export interface Theatre {
  /** Changes to the face before it is drawn (its mouth is the theatre's own). */
  look: (look: FaceLook, t: number) => void;
  /** Drawn over the face. `t`: ms since the expression arrived. */
  draw: (frame: Frame, look: FaceLook, t: number) => void;
}

const TAU = Math.PI * 2;
const EYE_CX_L = LEFT_EYE_X + EYE_W / 2;
const EYE_CX_R = RIGHT_EYE_X + EYE_W / 2;
const FACE_CX = (EYE_CX_L + EYE_CX_R) / 2;

/** Where the face is now: offsets and the head tilt (her left eye drops by `tilt`). */
function at(look: FaceLook) {
  const sx = Math.round(look.shiftX ?? 0);
  const sy = Math.round(look.shiftY ?? 0);
  const tilt = Math.round(look.tilt ?? 0);
  return { sx, sy, tilt };
}

/** A thick stroke through points: capsules joint to joint. */
function stroke(frame: Frame, points: Vec[], radius: number, ink: Ink, alpha = 1, fill: number | null = 1): void {
  for (let k = 0; k + 1 < points.length; k += 1) {
    const a = points[k];
    const b = points[k + 1];
    drawShape(
      frame,
      (x, y) => capsule(x, y, a, b, radius),
      { x0: Math.min(a.x, b.x) - radius - 1, y0: Math.min(a.y, b.y) - radius - 1, x1: Math.max(a.x, b.x) + radius + 1, y1: Math.max(a.y, b.y) + radius + 1 },
      ink,
      alpha,
      FADE.fast,
      1,
      fill,
    );
  }
}

/** A smooth curve sampled as a polyline: f(u) for u in 0..1. */
function curve(f: (u: number) => Vec, steps = 10): Vec[] {
  return Array.from({ length: steps + 1 }, (_, k) => f(k / steps));
}

// ---- 😭 sobbing -------------------------------------------------------------------

const SOB_HZ = 1.15; // heaves a second
const sob = (t: number) => Math.max(0, Math.sin((t / 1000) * SOB_HZ * TAU));

// the wail: a big open mouth, wider at the bottom, its top lip pulled down
const WAIL = sprite([
  "....#######....",
  "..##_______##..",
  ".#___________#.",
  "#_____________#",
  "#_____________#",
  "#_____________#",
  ".#############.",
]);
// her top teeth, and her tongue at the bottom of the wail
const TEETH = sprite(["..#########..", "...#######..."]);
const TONGUE = sprite(["..+###+..", ".#######.", "#########"]);

function tears(frame: Frame, x: number, y0: number, side: -1 | 1, t: number): void {
  // a stream from the outer corner of the eye, pouring down and out, then off her
  // face: bright drops travelling down it so it reads as running water
  const len = 72 - y0;
  const path = (u: number): Vec => ({ x: x + side * (2 + 10 * u * u), y: y0 + u * len });
  const flow = (t / 1000) * 1.6;
  for (let k = 0; k <= 24; k += 1) {
    const u = k / 24;
    const p = path(u);
    const wave = 0.55 + 0.45 * Math.sin((u * 4 - flow) * TAU);
    const width = 1.6 + 1.4 * u;
    drawShape(frame, (cx, cy) => Math.hypot(cx - p.x, cy - p.y) - width, { x0: p.x - 4, y0: p.y - 4, x1: p.x + 4, y1: p.y + 4 }, INK.iceCore, 1, FADE.fast, wave, 0.5 * wave);
  }
  // drops flying off the end as she shakes
  for (let k = 0; k < 3; k += 1) {
    const phase = ((t / 1000) * 1.3 + k / 3) % 1;
    const end = path(0.55 + 0.1 * k);
    const dx = end.x + side * (4 + phase * 14);
    const dy = end.y + phase * phase * 18 - 4 * Math.sin(phase * Math.PI);
    const a = 1 - phase;
    drawShape(frame, (cx, cy) => Math.hypot(cx - dx, cy - dy) - 1.3, { x0: dx - 3, y0: dy - 3, x1: dx + 3, y1: dy + 3 }, INK.iceCore, a, FADE.fast, 1, 0.6);
  }
}

const sobbing: Theatre = {
  look: (look) => {
    look.mouth = "hidden";
    look.blinking = false;
    look.gazeX = 0;
    look.gazeY = 0;
  },
  draw: (frame, look, t) => {
    const { sx, sy, tilt } = at(look);
    const heave = sob(t);
    // shoulders: two big arcs at the bottom of the matrix, hunched up with each sob
    const lift = Math.round(4 * heave);
    for (const side of [-1, 1] as const) {
      const cx = FACE_CX + side * 44 + sx;
      stroke(frame, curve((u) => ({ x: cx - side * 22 * u + side * 2, y: 73 - lift - Math.sin(u * Math.PI * 0.55) * 11 })), 2, INK.accent, 1, null);
    }
    // the wail, quivering with the sob and opening wider with her voice
    const open = Math.round(clamp01(look.level * 1.4) * 1.5);
    const quiver = Math.round(Math.sin((t / 1000) * 9 * TAU) * heave);
    const mx = FACE_CX - 22 + sx + quiver;
    const my = MOUTH_Y - 4 + sy - open * 2;
    blit(frame, WAIL, mx, my, { scale: 3, ink: INK.accent, cover: true });
    blit(frame, TEETH, mx + 3, my + 3, { scale: 3, ink: INK.white, cover: false });
    blit(frame, TONGUE, mx + 9, my + 12, { scale: 3, ink: INK.pink, cover: false });
    // tears off both sides
    tears(frame, LEFT_EYE_X + sx - 1, EYE_Y + EYE_H - 4 + sy + tilt, -1, t);
    tears(frame, RIGHT_EYE_X + EYE_W + sx + 1, EYE_Y + EYE_H - 4 + sy - tilt, 1, t + 400);
  },
};

// ---- 😇 innocent ------------------------------------------------------------------

const BLUSH = sprite([".-+++-.", "-+++++-", ".-+++-."]);
// a tiny content smile, closed - and barely open while she talks
const TINY = sprite(["#.....#", ".#...#.", "..###.."]);
const TINY_TALK = sprite(["#.....#", ".#---#.", "..###.."]);

const innocent: Theatre = {
  look: (look) => {
    look.mouth = "hidden";
    look.blinking = false;
    look.gazeX = 0;
    look.gazeY = 0;
  },
  draw: (frame, look, t) => {
    const { sx, sy } = at(look);
    // the halo: a glowing gold ring floating above her head, bobbing a beat behind her
    const bob = Math.sin((t / 1000) * 0.5 * TAU - 0.8) * 1.2;
    const hx = FACE_CX + sx;
    const hy = 5 + sy + bob;
    const ring = (x: number, y: number, rx: number, ry: number) => {
      const dx = (x - hx) / rx;
      const dy = (y - hy) / ry;
      return (Math.sqrt(dx * dx + dy * dy) - 1) * Math.min(rx, ry);
    };
    const glow = 0.55 + 0.15 * Math.sin((t / 1000) * 1.3 * TAU);
    drawShape(frame, (x, y) => Math.abs(ring(x, y, 27, 4.6)) - 1.6, { x0: hx - 31, y0: hy - 8, x1: hx + 31, y1: hy + 8 }, INK.amber, glow * 0.6, FADE.fast, 1, null);
    drawShape(frame, (x, y) => Math.abs(ring(x, y, 25, 3.6)) - 1.1, { x0: hx - 28, y0: hy - 6, x1: hx + 28, y1: hy + 6 }, INK.amber, 1, FADE.fast, 1, null);
    // blush under each closed eye
    for (const x of [LEFT_EYE_X + 1, RIGHT_EYE_X + 7]) {
      blit(frame, BLUSH, x + sx, EYE_Y + EYE_H + 2 + sy, { ink: INK.pink, scale: 2, cover: false });
    }
    // the tiny smile
    const talking = look.state === "speaking" && look.level > 0.3;
    blit(frame, talking ? TINY_TALK : TINY, FACE_CX - 10 + sx, MOUTH_Y + 1 + sy, { scale: 3, ink: INK.accent });
  },
};

// ---- 🫣 peeking --------------------------------------------------------------------

// fingers spread wide: the gap between index and middle is the peephole
const SPREAD: HandPose = {
  index: { ext: 1, lean: -40 },
  middle: { ext: 1, lean: 26 },
  ring: { ext: 1, lean: 20 },
  pinky: { ext: 0.95, lean: 26 },
  thumb: { ext: 0.8, lean: 10 },
};
const HANDS_UP_MS = 320;
// the eye in the peephole: white, its pupil slid to the side
const PEEP = sprite([".####.", "######", "######", ".####."]);
const PUPIL = sprite(["__", "__"]);
// where the gap between index and middle is, in the spread hand's own units
const GAP: Vec = { x: -2.6, y: -8.6 };

const peeking: Theatre = {
  look: (look) => {
    look.mouth = "hidden";
    look.blinking = false;
    look.gazeY = 0;
  },
  draw: (frame, look, t) => {
    const { sx, sy } = at(look);
    const up = easeOutBack(t / HANDS_UP_MS);
    const rise = (1 - up) * 30;
    // her right hand (viewer's left) flat over that eye; her left with its fingers
    // spread, the peephole between index and middle over the other eye
    drawHand(frame, HANDS.flat, { x: EYE_CX_L + sx + 7, y: 46 + sy + rise, rot: 6, scale: 2.3, mirror: true });
    const hand = { x: EYE_CX_R + sx + 3, y: 48 + sy + rise, scale: 2.3 };
    // the eye first, the spread hand over it: it shows only through the gap
    const ex = hand.x + GAP.x * hand.scale;
    const ey = hand.y + GAP.y * hand.scale;
    blit(frame, PEEP, ex - 9, ey - 6, { scale: 3, ink: INK.white });
    // looking sideways - and, now and then, a quick dart the other way
    const dart = Math.floor(t / 1400) % 3 === 2 ? 5 : 0;
    blit(frame, PUPIL, ex - 5 + dart, ey - 3, { scale: 3, ink: INK.white });
    drawHand(frame, SPREAD, hand);
  },
};

// ---- 😏 smug -------------------------------------------------------------------------

// a one-sided smirk: flat on her left, curling right up at the other corner
const smug: Theatre = {
  look: (look) => {
    look.mouth = "hidden";
    // dead still: no blinks, no glances - the stillness is the joke
    look.blinking = false;
    look.gazeX = 0;
    look.gazeY = 0;
  },
  draw: (frame, look, t) => {
    const { sx, sy, tilt } = at(look);
    const raise = easeOutBack(t / 380);
    // the raised brow (viewer's left), arched high above the eye; the other flat and
    // low, sitting right on the lid
    const ly = EYE_Y + sy + tilt;
    const ry = EYE_Y + sy - tilt;
    stroke(frame, curve((u) => ({ x: LEFT_EYE_X - 2 + sx + u * (EYE_W + 3), y: ly - 1 - raise * (3 + 4 * Math.sin(u * Math.PI)) + u * 2 })), 1.25, INK.accent);
    stroke(frame, [{ x: RIGHT_EYE_X - 1 + sx, y: ry + 4 }, { x: RIGHT_EYE_X + EYE_W + 1 + sx, y: ry + 3 }], 1.25, INK.accent);
    // the smirk: a flat line on her left side curving up hard at the right corner
    const my = MOUTH_Y + 8 + sy;
    const talking = look.state === "speaking" && look.level > 0.3;
    const mx = MOUTH_X + sx - tilt;
    stroke(frame, curve((u) => ({ x: mx + 4 + u * 30, y: my - (u > 0.6 ? ((u - 0.6) / 0.4) ** 1.6 * 9 : 0) + (talking ? Math.sin(u * Math.PI * 0.6) * 1.5 : 0) })), 1.4, INK.accent);
    // the dimple at the high corner
    stroke(frame, [{ x: mx + 36, y: my - 11 }, { x: mx + 37, y: my - 8 }], 0.7, INK.accent, 0.8);
  },
};

// ---- 😤 fuming -------------------------------------------------------------------------

// steam off the top of her head: puffs that swell, drift up and out, and thin away
function steam(frame: Frame, x: number, y: number, side: -1 | 1, t: number): void {
  for (let k = 0; k < 3; k += 1) {
    const phase = ((t / 1000) * 1.4 + k / 3) % 1;
    const px = x + side * (phase * 10 + Math.sin(phase * TAU) * 1.5);
    const py = y - phase * 16;
    const r = 2 + phase * 4;
    const a = phase < 0.15 ? phase / 0.15 : 1 - (phase - 0.15) / 0.85;
    drawShape(frame, (cx, cy) => Math.hypot(cx - px, cy - py) - r, { x0: px - r - 2, y0: py - r - 2, x1: px + r + 2, y1: py + r + 2 }, INK.white, a * 0.85, FADE.fast, 0.9, 0.45);
  }
}

const fuming: Theatre = {
  look: (look) => {
    look.mouth = "hidden";
    look.blinking = false;
    look.gazeX = 0;
    look.gazeY = 0;
  },
  draw: (frame, look, t) => {
    const { sx, sy, tilt } = at(look);
    const slam = easeOutBack(t / 260);
    // brows driven down hard to the middle, red
    const ly = EYE_Y + sy + tilt;
    const ry = EYE_Y + sy - tilt;
    const drop = 7 * slam;
    stroke(frame, [{ x: LEFT_EYE_X - 2 + sx, y: ly + 2 }, { x: LEFT_EYE_X + EYE_W + 1 + sx, y: ly + 1 + drop }], 1.6, INK.red);
    stroke(frame, [{ x: RIGHT_EYE_X + EYE_W + 1 + sx, y: ry + 2 }, { x: RIGHT_EYE_X - 2 + sx, y: ry + 1 + drop }], 1.6, INK.red);
    // a clenched frown, gritted teeth showing while she talks
    const my = MOUTH_Y + 10 + sy;
    const talking = look.state === "speaking" && look.level > 0.25;
    if (talking) {
      drawShape(frame, (x, y) => Math.max(Math.abs(x - FACE_CX - sx) - 12, Math.abs(y - my + 2) - 2.2), { x0: FACE_CX + sx - 14, y0: my - 6, x1: FACE_CX + sx + 14, y1: my + 2 }, INK.white, 1, FADE.fast, 1, 1);
      for (let k = -2; k <= 2; k += 1) stroke(frame, [{ x: FACE_CX + sx + k * 5, y: my - 4 }, { x: FACE_CX + sx + k * 5, y: my }], 0.4, INK.accent, 0.8);
    }
    stroke(frame, curve((u) => ({ x: FACE_CX - 16 + sx + u * 32, y: my + 2 - Math.sin(u * Math.PI) * 5 })), 1.3, INK.accent);
    // and steam, both sides of her head
    steam(frame, LEFT_EYE_X - 13 + sx, EYE_Y + 10 + sy, -1, t);
    steam(frame, RIGHT_EYE_X + EYE_W + 13 + sx, EYE_Y + 10 + sy, 1, t + 330);
  },
};

// ---- 😱 shocked ------------------------------------------------------------------------

const shocked: Theatre = {
  look: (look) => {
    look.mouth = "hidden";
    look.blinking = false;
    look.gazeX = 0;
    look.gazeY = 0;
  },
  draw: (frame, look, t) => {
    const { sx, sy } = at(look);
    // the jaw drops - and opens a little further with her voice
    const drop = easeOutBack(t / 300);
    const open = clamp01(look.level * 1.4);
    const cx = FACE_CX + sx;
    const cy = MOUTH_Y + 6 + sy + drop * 4;
    const rx = 5 + 1.5 * open;
    const ry = 3 + drop * 6 + 2 * open;
    const oval = (x: number, y: number) => (Math.hypot((x - cx) / rx, (y - cy) / ry) - 1) * Math.min(rx, ry);
    drawShape(frame, (x, y) => Math.abs(oval(x, y)) - 1.3, { x0: cx - rx - 3, y0: cy - ry - 3, x1: cx + rx + 3, y1: cy + ry + 3 }, INK.accent, 1, FADE.fast, 1, 1);
    // shock lines over her head, flickering
    const flick = 0.6 + 0.4 * Math.abs(Math.sin((t / 1000) * 5 * TAU));
    for (const [dx, lean] of [[-14, -5], [0, 0], [14, 5]] as const) {
      const x = FACE_CX + sx + dx;
      stroke(frame, [{ x: x + lean * 0.4, y: 1 + sy }, { x: x + lean, y: 7 + sy }], 0.9, INK.white, flick);
    }
  },
};

export const THEATRE: Partial<Record<Emotion, Theatre>> = { sobbing, innocent, peeking, smug, fuming, shocked };

export function theatreFor(emotion: Emotion): Theatre | undefined {
  return THEATRE[emotion];
}
