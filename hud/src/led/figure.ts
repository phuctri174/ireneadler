// Irene's whole body, for the entrances: she is a ROBOT - a chunky, friendly
// desk-robot in the EMO style. A big rounded head that is a screen (her own eyes
// on it, the same eye art as her big face), a short boxy chassis, and limbs made
// of machined segments with a visible joint at every bend: shoulder, elbow,
// wrist, hip, knee, ankle. Block feet. Nothing about her is a human body.
//
// It is drawn the way good sprite art is: silhouette first, then shading, then
// detail. Every part has a dark outline that separates it from what is behind,
// and three tones from ONE light source - a highlight edge on the side facing the
// light, a mid tone, a shadow side away from it (litShape). Shell is white, joints
// and her eyes are cyan; a scene's light may tint the highlights. That's the whole
// palette.
//
// Units are her own, y up from the ground (~7 units tall standing); a camera turns
// them into LEDs (cam.s LEDs per unit, the ground at row cam.y). Angles are degrees
// from straight down, positive turning toward +x (the viewer's right). Arm A is
// the one on the viewer's left.
//
// Motion with weight: poses are keyframed, and animate() makes them move like a
// machine with mass - forearms and head trail the shoulders and settle, cape and
// skirt swing from how fast her hips just moved, she idles with a small bob. Legs
// are solved (two-bone IK) from where the feet stand, so a crouch bends the knees.

import { COLS, FADE, INK, ROWS, clamp01, ease, easeOutBack, lerp, upscale } from "./grid";
import type { Frame, Ink, Vec } from "./grid";
import { EYE_COLS, EYE_ROWS, eyeGrids } from "../face/faceState";
import type { Emotion } from "../face/faceState";

// ---- proportions (her units) -----------------------------------------------------------

export const HIP_H = 3.2; // hip joints above the ground, standing
const TORSO = 1.85; // hips to the shoulder line
const SHOULDER = 0.98; // half the shoulder width (joint centres)
const HIP_JOINT = 0.42;
const UPPER = 1.15;
const FORE = 1.0;
const HAND = 0.42;
const THIGH = 1.5;
const SHIN = 1.45;
const ANKLE = 0.26; // ankle joint above the ground
const NECK = 0.2;
/** Half the head's width and height: a wide rounded box, wider than her chassis. */
export const HEAD_W = 1.42;
export const HEAD_H = 0.98;

// ---- maths -----------------------------------------------------------------------------

const RAD = Math.PI / 180;

function dir(deg: number): Vec {
  return { x: Math.sin(deg * RAD), y: Math.cos(deg * RAD) };
}

function add(a: Vec, b: Vec, k = 1): Vec {
  return { x: a.x + b.x * k, y: a.y + b.y * k };
}

/** A tapered capsule from a (radius ra) to b (radius rb). */
export function cone(px: number, py: number, a: Vec, b: Vec, ra: number, rb: number): number {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const h = Math.hypot(dx, dy) || 1e-6;
  const ux = dx / h;
  const uy = dy / h;
  const qx = Math.abs((px - a.x) * uy - (py - a.y) * ux);
  const qy = (px - a.x) * ux + (py - a.y) * uy;
  const k0 = Math.max(-0.99, Math.min(0.99, (ra - rb) / h));
  const k1 = Math.sqrt(1 - k0 * k0);
  const k = -qx * k0 + qy * k1;
  if (k < 0) return Math.hypot(qx, qy) - ra;
  if (k > k1 * h) return Math.hypot(qx, qy - h) - rb;
  return qx * k1 + qy * k0 - ra;
}

/** An ellipse centred at c with radii (rx, ry), turned by rot degrees. */
export function ellipse(px: number, py: number, c: Vec, rx: number, ry: number, rot = 0): number {
  const cs = Math.cos(rot * RAD);
  const sn = Math.sin(rot * RAD);
  const x = (px - c.x) * cs + (py - c.y) * sn;
  const y = -(px - c.x) * sn + (py - c.y) * cs;
  return (Math.hypot(x / rx, y / ry) - 1) * Math.min(rx, ry);
}

/** A rounded box centred at c, half-size (hw, hh), corner radius r, turned by rot degrees. */
export function box(px: number, py: number, c: Vec, hw: number, hh: number, r: number, rot = 0): number {
  const cs = Math.cos(rot * RAD);
  const sn = Math.sin(rot * RAD);
  const x = (px - c.x) * cs + (py - c.y) * sn;
  const y = -(px - c.x) * sn + (py - c.y) * cs;
  const qx = Math.abs(x) - hw + r;
  const qy = Math.abs(y) - hh + r;
  return Math.hypot(Math.max(qx, 0), Math.max(qy, 0)) + Math.min(Math.max(qx, qy), 0) - r;
}

/** Any closed polygon (exact distance, negative inside). */
export function polygon(px: number, py: number, v: readonly Vec[]): number {
  let d = (px - v[0].x) ** 2 + (py - v[0].y) ** 2;
  let s = 1;
  for (let i = 0, j = v.length - 1; i < v.length; j = i, i += 1) {
    const ex = v[j].x - v[i].x;
    const ey = v[j].y - v[i].y;
    const wx = px - v[i].x;
    const wy = py - v[i].y;
    const t = Math.max(0, Math.min(1, (wx * ex + wy * ey) / (ex * ex + ey * ey || 1)));
    const bx = wx - ex * t;
    const by = wy - ey * t;
    d = Math.min(d, bx * bx + by * by);
    const c1 = py >= v[i].y;
    const c2 = py < v[j].y;
    const c3 = ex * wy > ey * wx;
    if ((c1 && c2 && c3) || (!c1 && !c2 && !c3)) s = -s;
  }
  return s * Math.sqrt(d);
}

// ---- light and the shaded-shape rasteriser ----------------------------------------------

export interface Light {
  /** Toward the light, screen space (y down): {x: -1, y: -1} is a lamp up and left. */
  dir: Vec;
  /** The highlight's colour (a lamp's amber, a spotlight's white). */
  ink: Ink;
  /** 0..1.2: how strong the light is - 0 is no highlight at all. */
  power: number;
}

export interface Shade {
  ink: Ink;
  /** The mid tone: what most of the shape is. */
  fill: number;
  /** Kept for callers; the highlight comes from the light. */
  rim?: number;
  fade?: number;
}

/** Her shell: white, a bright mid tone - she is the subject. */
const SHELL: Shade = { ink: INK.white, fill: 0.5 };
/** Her joints: cyan, the one accent colour on her. */
const JOINT: Shade = { ink: INK.cyan, fill: 0.62 };

/**
 * One shape in front of what is drawn, shaded like a sprite: a 1-LED dark outline
 * just outside it, then three tones from the light - the outermost LED on the side
 * facing the light is the highlight, a band on the far side is the shadow, the rest
 * is the mid tone. Edges are hard (no soft fill bleeding into the background).
 */
export function litShape(
  frame: Frame,
  sdf: (x: number, y: number) => number,
  bounds: { x0: number; y0: number; x1: number; y1: number },
  shade: Shade,
  light: Light,
  alpha = 1,
  outline = true,
): void {
  const x0 = Math.max(0, Math.floor(bounds.x0 - 2));
  const y0 = Math.max(0, Math.floor(bounds.y0 - 2));
  const x1 = Math.min(COLS - 1, Math.ceil(bounds.x1 + 2));
  const y1 = Math.min(ROWS - 1, Math.ceil(bounds.y1 + 2));
  const ln = Math.hypot(light.dir.x, light.dir.y) || 1;
  const lx = light.dir.x / ln;
  const ly = light.dir.y / ln;
  const fade = shade.fade ?? FADE.fast;
  const mid = shade.fill;
  const high = Math.min(1, mid + 0.3 + 0.35 * Math.min(1, light.power));
  const low = mid * 0.42;
  for (let row = y0; row <= y1; row += 1) {
    for (let col = x0; col <= x1; col += 1) {
      const px = col + 0.5;
      const py = row + 0.5;
      const d = sdf(px, py);
      if (d > 1.5) continue;
      const i = row * COLS + col;
      if (d > 0.5) {
        // the outline: a clean dark line round her, whatever is behind
        if (outline) frame.value[i] *= lerp(1, 0, alpha);
        continue;
      }
      const gx = sdf(px + 0.5, py) - sdf(px - 0.5, py);
      const gy = sdf(px, py + 0.5) - sdf(px, py - 0.5);
      const gl = Math.hypot(gx, gy) || 1;
      const facing = (gx * lx + gy * ly) / gl;
      const depth = -d;
      let level = mid;
      const ink = shade.ink;
      if (light.power > 0.05 && facing > 0.5 && depth < 1.1) {
        // the highlight stays in the part's own colour: the light's colour lives in
        // the scene, not as a rim round every edge of her
        level = high;
      } else if (facing < -0.3 && depth < 2.2) {
        level = low;
      }
      frame.value[i] = lerp(frame.value[i], level, alpha);
      if (alpha > 0.45) frame.ink[i] = ink;
      frame.fade[i] = fade;
    }
  }
}

/** Just the dark of a shape (a cast shadow, a cut-out), no tones. */
export function darken(frame: Frame, sdf: (x: number, y: number) => number, bounds: { x0: number; y0: number; x1: number; y1: number }, keep: number): void {
  const x0 = Math.max(0, Math.floor(bounds.x0));
  const y0 = Math.max(0, Math.floor(bounds.y0));
  const x1 = Math.min(COLS - 1, Math.ceil(bounds.x1));
  const y1 = Math.min(ROWS - 1, Math.ceil(bounds.y1));
  for (let row = y0; row <= y1; row += 1) {
    for (let col = x0; col <= x1; col += 1) {
      const d = sdf(col + 0.5, row + 0.5);
      if (d < 0.5) frame.value[row * COLS + col] *= lerp(keep, 1, clamp01(d + 0.5));
    }
  }
}

// ---- pose ------------------------------------------------------------------------------

export interface Pose {
  /** Hip joints: x across, y height above the ground (HIP_H standing). */
  x: number;
  y: number;
  /** Chassis tilt from upright, degrees (+ = top toward +x). */
  lean: number;
  /** Hips rolled to one side, degrees. */
  hip: number;
  /** Head tilt on the neck, degrees. */
  head: number;
  /** -1..1: 0 faces the viewer, +1 is a profile facing +x. */
  turn: number;
  /** Arms: shoulder angle and elbow bend (forearm = shoulder + elbow), wrist. */
  aA: number;
  eA: number;
  wA: number;
  aB: number;
  eB: number;
  wB: number;
  /** Ankles, in her space (y above the ground). */
  fAx: number;
  fAy: number;
  fBx: number;
  fBy: number;
  /** Extra swing of cape and skirt (units, + toward +x). */
  sway: number;
  /** Eyes on her screen: 0 open, 1 shut. And where they look, -1..1 across. */
  blink: number;
  gaze: number;
  /** Shoulders raised (a shrug, a bob), units. */
  lift: number;
}

export const STAND: Pose = {
  x: 0, y: HIP_H, lean: 0, hip: 0, head: 0, turn: 0,
  aA: -14, eA: 14, wA: 0, aB: 14, eB: -14, wB: 0,
  fAx: -0.46, fAy: ANKLE, fBx: 0.46, fBy: ANKLE,
  sway: 0, blink: 0, gaze: 0, lift: 0,
};

/**
 * How a key is arrived at: io (ease in-out), out, in, back (overshoots its target),
 * snap (very fast out), hold (a cut), antic (pulls back the other way first, then
 * goes - anticipation - and overshoots a touch at the end).
 */
export type Ease = "io" | "out" | "in" | "back" | "snap" | "hold" | "antic";

export interface Key {
  t: number;
  p: Partial<Pose>;
  /** How it arrives at this key from the one before. */
  e?: Ease;
}

function curve(e: Ease, u: number): number {
  switch (e) {
    case "out":
      return 1 - (1 - clamp01(u)) ** 3;
    case "in":
      return clamp01(u) ** 2.4;
    case "back":
      return easeOutBack(u);
    case "snap":
      return 1 - (1 - clamp01(u)) ** 6;
    case "hold":
      return u >= 1 ? 1 : 0;
    case "antic":
      return anticipate(u);
    default:
      return ease(u);
  }
}

/** Fill each key's missing fields from the keys before it (STAND first). */
export function resolve(keys: readonly Key[], from: Pose = STAND): { t: number; p: Pose; e: Ease }[] {
  let last = from;
  return keys.map((k) => {
    last = { ...last, ...k.p };
    return { t: k.t, p: last, e: k.e ?? "io" };
  });
}

export type Track = { t: number; p: Pose; e: Ease }[];

/** The keyframed pose at t (no follow-through). */
export function sample(track: Track, t: number): Pose {
  if (t <= track[0].t) return track[0].p;
  for (let i = 1; i < track.length; i += 1) {
    if (t < track[i].t) {
      const a = track[i - 1];
      const b = track[i];
      const u = curve(b.e, (t - a.t) / (b.t - a.t));
      const out = { ...a.p };
      for (const key of Object.keys(out) as (keyof Pose)[]) out[key] = a.p[key] + (b.p[key] - a.p[key]) * u;
      return out;
    }
  }
  return track[track.length - 1].p;
}

// ---- motion: the animation system ------------------------------------------------
// Keyframes say WHERE she goes; this says HOW a body gets there. Linear
// interpolation between poses is what made her arms look cheap: hands sliding in
// straight lines, every joint arriving at once, dead stops. So:
//   - every joint angle follows its keyed value through a damped spring, simulated
//     through time - it overshoots and settles, never stops dead
//   - lead order by stiffness: the shoulder initiates (stiffest), the elbow follows,
//     the wrist and hand trail last (softest: drag)
//   - the body (hips, lean) has its own heavier springs, so a strike shifts her
//     weight and recoils
//   - scenes move hands along arc() paths with anticipate()/overshoot curves, never
//     lerp() straight lines

/** Anticipation: dips the other way first (~10%), then goes, overshoots a touch, settles. */
export function anticipate(u: number): number {
  const x = clamp01(u);
  const back = -0.11 * Math.sin(Math.min(1, x / 0.28) * Math.PI);
  const go = ease((x - 0.18) / 0.82);
  const over = 0.06 * Math.sin(clamp01((x - 0.7) / 0.3) * Math.PI);
  return back * (x < 0.28 ? 1 : 0) + go + over;
}

/** Overshoot then settle: 0..1 that passes 1 by ~8% and comes back. */
export function overshoot(u: number): number {
  return easeOutBack(u);
}

/**
 * A point along a curved path from a to b at u (0..1): a quadratic curve bowed by
 * `bulge` (in the path's units) to the left of a->b - positive bows it up for a
 * path going right. Hands travel these, not straight lines.
 */
export function arc(a: Vec, b: Vec, u: number, bulge: number): Vec {
  const k = clamp01(u);
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const len = Math.hypot(dx, dy) || 1;
  const c = { x: (a.x + b.x) / 2 - (dy / len) * bulge, y: (a.y + b.y) / 2 + (dx / len) * bulge };
  const m = 1 - k;
  return { x: m * m * a.x + 2 * m * k * c.x + k * k * b.x, y: m * m * a.y + 2 * m * k * c.y + k * k * b.y };
}

/** A spring: natural frequency (rad/s) and damping ratio. */
interface Spring {
  w: number;
  z: number;
}

// lead order: the shoulder initiates, the elbow follows, the wrist trails (drag);
// the body is heavier still, the head lags it
const SPRINGS: Partial<Record<keyof Pose, Spring>> = {
  aA: { w: 34, z: 0.6 },
  aB: { w: 34, z: 0.6 },
  eA: { w: 24, z: 0.5 },
  eB: { w: 24, z: 0.5 },
  wA: { w: 15, z: 0.42 },
  wB: { w: 15, z: 0.42 },
  lean: { w: 20, z: 0.42 },
  x: { w: 26, z: 0.62 },
  y: { w: 22, z: 0.45 },
  hip: { w: 18, z: 0.5 },
  head: { w: 14, z: 0.45 },
};
/** How far back the simulation starts (springs forget faster than this). */
const FOLLOW_MS = 600;
const STEP_MS = 1000 / 120;

/**
 * Every field with a spring, followed from FOLLOW_MS ago to t (a pure function of t,
 * so any frame can be drawn alone). `fields` limits it (e.g. arms only).
 */
export function follow<T extends object>(at: (t: number) => T, t: number, springs: Partial<Record<keyof T, Spring>>): T {
  const keys = Object.keys(springs) as (keyof T)[];
  const t0 = t - FOLLOW_MS;
  const start = at(t0);
  const pos = keys.map((k) => start[k] as unknown as number);
  const vel = keys.map(() => 0);
  let target = start;
  for (let time = t0 + STEP_MS; time <= t + 1e-6; time += STEP_MS) {
    target = at(time);
    const dt = STEP_MS / 1000;
    keys.forEach((k, i) => {
      const { w, z } = springs[k] as Spring;
      const acc = w * w * ((target[k] as unknown as number) - pos[i]) - 2 * z * w * vel[i];
      vel[i] += acc * dt;
      pos[i] += vel[i] * dt;
    });
  }
  const out = { ...at(t) };
  keys.forEach((k, i) => {
    (out as Record<keyof T, unknown>)[k] = pos[i];
  });
  return out;
}

/**
 * The pose at t with a body's mass in it: every joint follows its keyed angle
 * through its spring (shoulder leads, elbow follows, wrist drags; the body shifts
 * and recoils), cloth swings back from the hips' motion, she idles with a small
 * servo bob. `at` is any pose over time - a keyframe track, a walk, IK targets.
 */
export function animate(at: (t: number) => Pose, t: number): Pose {
  const p = follow(at, t, SPRINGS);
  // the head also takes the body's lean a beat late
  const later = at(t - 150);
  p.head += (p.lean - later.lean) * 0.35;
  const before = at(t - 130);
  const longBefore = at(t - 300);
  const swing = -(p.x - before.x) * 2.1 + (before.x - longBefore.x) * 0.9 - (p.lean - before.lean) * 0.012;
  // cloth only swings so far, however fast she moves
  p.sway += Math.max(-0.55, Math.min(0.55, swing));
  p.y += 0.02 * Math.sin(t / 520);
  p.lift += 0.015 * Math.sin(t / 520);
  return p;
}

/** Springs for a held prop's path (a hilt, a hand in screen space): a hand's feel. */
export const HAND_SPRING: Spring = { w: 22, z: 0.48 };

// ---- outfit ------------------------------------------------------------------------------

export interface Outfit {
  /** A skirt (a hakama) to `hem` units above the ground standing; `flare` half-wide at the hem. */
  skirt?: { hem: number; flare: number; ink?: Ink };
  /** A cape from the shoulders to `hem` units above the ground standing. */
  cape?: { hem: number; flare: number; ink?: Ink };
  /** A wide Victorian hat on her head; tip lifts and tilts it (0..1). */
  hat?: { tip: number };
  /** A ruffled collar round her neck. */
  collar?: boolean;
  /** Kendo do (breastplate) over her chassis. */
  bogu?: boolean;
  /** The kendo men: helmet and grille over her screen. */
  men?: boolean;
  /** Hands in this ink (gloves). */
  gloves?: Ink;
}

/** Just her - no costume. */
export const BARE: Outfit = {};

export interface Camera {
  /** Screen column of her x = 0, screen row of the ground, LEDs per unit. */
  x: number;
  y: number;
  s: number;
}

/** Where everything ended up, in LEDs: for props held in a hand, effects at a foot. */
export interface Joints {
  pelvis: Vec;
  chest: Vec;
  neck: Vec;
  head: Vec;
  shoulderA: Vec;
  shoulderB: Vec;
  elbowA: Vec;
  elbowB: Vec;
  wristA: Vec;
  wristB: Vec;
  handA: Vec;
  handB: Vec;
  kneeA: Vec;
  kneeB: Vec;
  ankleA: Vec;
  ankleB: Vec;
  /** The head's own up direction (screen) and the body's facing. */
  up: Vec;
  facing: number;
  scale: number;
}

/** Two-bone IK: the middle joint, bending toward `side` (+1 = +x). */
export function knee(hip: Vec, ankle: Vec, a: number, b: number, side: number): Vec {
  const dx = ankle.x - hip.x;
  const dy = ankle.y - hip.y;
  const reachLen = Math.min(a + b - 1e-3, Math.max(Math.abs(a - b) + 1e-3, Math.hypot(dx, dy)));
  const along = (a * a - b * b + reachLen * reachLen) / (2 * reachLen);
  const out = Math.sqrt(Math.max(0, a * a - along * along));
  const len = Math.hypot(dx, dy) || 1;
  const ux = dx / len;
  const uy = dy / len;
  let nx = -uy;
  let ny = ux;
  if (nx * side < 0) {
    nx = -nx;
    ny = -ny;
  }
  return { x: hip.x + ux * along + nx * out, y: hip.y + uy * along + ny * out };
}

/**
 * How far an elbow can bend, degrees of forearm past the upper arm: facing the
 * viewer, each forearm folds in toward her body; turned, both fold toward where
 * she faces. Never the other way past a little.
 */
export function bendLimit(side: "A" | "B", turn: number, e: number): number {
  const forward = Math.abs(turn) > 0.35 ? Math.sign(turn) : side === "A" ? 1 : -1;
  return forward > 0 ? Math.max(-12, Math.min(165, e)) : Math.max(-165, Math.min(12, e));
}

/** Width factor for things across her body as she turns. */
function across(turn: number): number {
  return 1 - 0.55 * Math.abs(Math.max(-1, Math.min(1, turn)));
}

/**
 * Arm IK: the shoulder angle and elbow bend that put arm `side`'s wrist at `target`
 * (her space). Of the two ways the elbow can go, the one that hangs lower.
 */
export function reach(pose: Pose, side: "A" | "B", target: Vec): { a: number; e: number } {
  const turn = Math.max(-1, Math.min(1, pose.turn));
  const lean = pose.lean * RAD;
  const up = { x: Math.sin(lean), y: Math.cos(lean) };
  const right = { x: Math.cos(lean), y: -Math.sin(lean) };
  const k = (side === "A" ? -1 : 1) * SHOULDER * across(turn);
  const sh = { x: pose.x + up.x * (TORSO + pose.lift) + right.x * k, y: pose.y + up.y * (TORSO + pose.lift) + right.y * k };
  const s = { x: sh.x, y: -sh.y };
  const w = { x: target.x, y: -target.y };
  const solve = (bend: number): { a: number; e: number } => {
    const el = knee(s, w, UPPER, FORE, bend);
    const a = Math.atan2(el.x - s.x, el.y - s.y) / RAD;
    const fore = Math.atan2(w.x - el.x, w.y - el.y) / RAD;
    let e = fore - a;
    while (e > 180) e -= 360;
    while (e < -180) e += 360;
    return { a, e };
  };
  const elbowY = (r: { a: number }): number => s.y + Math.cos(r.a * RAD) * UPPER;
  const [low, high] = [solve(1), solve(-1)].sort((p, q) => elbowY(q) - elbowY(p));
  const ok = (r: { e: number }): boolean => bendLimit(side, turn, r.e) === r.e;
  return ok(low) ? low : ok(high) ? high : low;
}

/** Where the joints are for a pose, in LEDs. */
export function joints(pose: Pose, cam: Camera): Joints {
  const s = cam.s;
  const to = (x: number, y: number): Vec => ({ x: cam.x + x * s, y: cam.y - y * s });
  const turn = Math.max(-1, Math.min(1, pose.turn));
  const wide = across(turn);
  const pelvis = to(pose.x, pose.y);
  const up = { x: Math.sin(pose.lean * RAD), y: -Math.cos(pose.lean * RAD) };
  const right = { x: -up.y, y: up.x };
  const roll = { x: Math.cos(pose.hip * RAD), y: Math.sin(pose.hip * RAD) };
  const sh = add(pelvis, up, (TORSO + pose.lift) * s);
  const shoulderA = add(sh, right, -SHOULDER * wide * s);
  const shoulderB = add(sh, right, SHOULDER * wide * s);
  const elbowA = add(shoulderA, dir(pose.aA), UPPER * s);
  const elbowB = add(shoulderB, dir(pose.aB), UPPER * s);
  const foreA = pose.aA + bendLimit("A", turn, pose.eA);
  const foreB = pose.aB + bendLimit("B", turn, pose.eB);
  const wristA = add(elbowA, dir(foreA), FORE * s);
  const wristB = add(elbowB, dir(foreB), FORE * s);
  const handA = add(wristA, dir(foreA + pose.wA), HAND * s);
  const handB = add(wristB, dir(foreB + pose.wB), HAND * s);
  const hipA = add(pelvis, roll, -HIP_JOINT * (1 - 0.4 * Math.abs(turn)) * s);
  const hipB = add(pelvis, roll, HIP_JOINT * (1 - 0.4 * Math.abs(turn)) * s);
  const ankleA = to(pose.fAx, pose.fAy);
  const ankleB = to(pose.fBx, pose.fBy);
  const sideA = Math.abs(turn) > 0.3 ? Math.sign(turn) : -1;
  const sideB = Math.abs(turn) > 0.3 ? Math.sign(turn) : 1;
  const kneeA = knee(hipA, ankleA, THIGH * s, SHIN * s, sideA);
  const kneeB = knee(hipB, ankleB, THIGH * s, SHIN * s, sideB);
  const neck = add(sh, up, 0.12 * s);
  const headUp = { x: Math.sin((pose.lean + pose.head) * RAD), y: -Math.cos((pose.lean + pose.head) * RAD) };
  const head = add(neck, headUp, (NECK + HEAD_H) * s);
  const chest = add(pelvis, up, 1.2 * s);
  return { pelvis, chest, neck, head, shoulderA, shoulderB, elbowA, elbowB, wristA, wristB, handA, handB, kneeA, kneeB, ankleA, ankleB, up: headUp, facing: turn, scale: s };
}

function boxOf(points: Vec[], pad: number): { x0: number; y0: number; x1: number; y1: number } {
  let x0 = Infinity;
  let y0 = Infinity;
  let x1 = -Infinity;
  let y1 = -Infinity;
  for (const p of points) {
    x0 = Math.min(x0, p.x);
    y0 = Math.min(y0, p.y);
    x1 = Math.max(x1, p.x);
    y1 = Math.max(y1, p.y);
  }
  return { x0: x0 - pad, y0: y0 - pad, x1: x1 + pad, y1: y1 + pad };
}

// ---- the robot ---------------------------------------------------------------------------

export interface FigureOptions {
  /** Whole figure's opacity (a fade in). */
  alpha?: number;
  /** What her screen shows: an emotion's eyes (her own eye art). */
  emotion?: Emotion;
  /** Eye colour on her screen (cyan; ice for power, white for a kiai). */
  eyes?: Ink;
  /** Drawn between her far arm and the rest (a sword held in front of the body). */
  held?: (j: Joints) => void;
  /** Leave her arms off (a scene draws its own, longer, with drawArm). */
  noArms?: boolean;
}

/**
 * One of her arms from given joints (LEDs), in her style: machined segments, a
 * joint disc at the shoulder, elbow and wrist, a mitten hand with a thumb. For
 * scenes that solve their own arms (chess, reaching across a board). `grip` 0..1
 * closes the hand.
 */
export function drawArm(frame: Frame, shoulder: Vec, elbow: Vec, wrist: Vec, hand: Vec, s: number, light: Light, thumb: 1 | -1 = 1, grip = 0): void {
  const joint = (c: Vec, r: number): void => litShape(frame, (x, y) => ellipse(x, y, c, r * s, r * s), boxOf([c], r * s + 1), JOINT, light);
  litShape(frame, (x, y) => cone(x, y, shoulder, elbow, 0.23 * s, 0.21 * s), boxOf([shoulder, elbow], 0.3 * s), SHELL, light);
  joint(shoulder, 0.26);
  litShape(frame, (x, y) => cone(x, y, elbow, wrist, 0.25 * s, 0.22 * s), boxOf([elbow, wrist], 0.3 * s), SHELL, light);
  joint(elbow, 0.19);
  const len = Math.hypot(hand.x - wrist.x, hand.y - wrist.y) || 1;
  const along = { x: (hand.x - wrist.x) / len, y: (hand.y - wrist.y) / len };
  const palm = add(wrist, along, len * 0.55);
  const rot = Math.atan2(along.y, along.x) / RAD;
  const t = add(palm, { x: -along.y, y: along.x }, thumb * (0.22 - 0.1 * grip) * s);
  litShape(frame, (x, y) => Math.min(box(x, y, palm, (0.3 - 0.06 * grip) * s, (0.22 - 0.04 * grip) * s, 0.12 * s, rot), ellipse(x, y, t, 0.1 * s, 0.1 * s)), boxOf([wrist, hand, t], 0.35 * s), SHELL, light);
  joint(wrist, 0.12);
}

/** Draws her and returns where her joints are. */
export function drawFigure(frame: Frame, pose: Pose, outfit: Outfit, cam: Camera, light: Light, options: FigureOptions = {}): Joints {
  const j = joints(pose, cam);
  const s = cam.s;
  const alpha = options.alpha ?? 1;
  const turn = j.facing;
  const near = turn >= 0 ? "B" : "A";
  const far = near === "B" ? "A" : "B";
  const profile = Math.abs(turn) > 0.35;
  const wide = across(turn);
  const up = { x: Math.sin(pose.lean * RAD), y: -Math.cos(pose.lean * RAD) };
  const right = { x: -up.y, y: up.x };
  const hands: Shade = outfit.gloves !== undefined ? { ink: outfit.gloves, fill: 0.55 } : SHELL;
  const joint = (c: Vec, r: number): void => litShape(frame, (x, y) => ellipse(x, y, c, r * s, r * s), boxOf([c], r * s + 1), JOINT, light, alpha);

  // -- behind her: the cape ------------------------------------------------------------
  if (outfit.cape) {
    const c = outfit.cape;
    const sway = pose.sway * 1.35;
    const hemY = j.pelvis.y + (HIP_H - c.hem) * s;
    const cape: Vec[] = [
      add(j.shoulderA, right, -0.3 * s),
      { x: j.shoulderA.x - (c.flare - 0.7) * s + sway * s * 0.6, y: lerp(j.shoulderA.y, hemY, 0.5) },
      { x: j.pelvis.x - c.flare * s + sway * s, y: hemY },
      { x: j.pelvis.x + sway * s * 1.1, y: hemY + 0.2 * s },
      { x: j.pelvis.x + c.flare * s + sway * s, y: hemY },
      { x: j.shoulderB.x + (c.flare - 0.7) * s + sway * s * 0.6, y: lerp(j.shoulderB.y, hemY, 0.5) },
      add(j.shoulderB, right, 0.3 * s),
      add(j.neck, up, 0.05 * s),
    ];
    litShape(frame, (x, y) => polygon(x, y, cape), boxOf(cape, 1), { ink: c.ink ?? INK.red, fill: 0.36 }, light, alpha);
  }

  // -- limbs: machined segments, a joint disc at every bend --------------------------
  const arm = (side: "A" | "B"): void => {
    const sh = side === "A" ? j.shoulderA : j.shoulderB;
    const el = side === "A" ? j.elbowA : j.elbowB;
    const wr = side === "A" ? j.wristA : j.wristB;
    const hd = side === "A" ? j.handA : j.handB;
    litShape(frame, (x, y) => cone(x, y, sh, el, 0.23 * s, 0.21 * s), boxOf([sh, el], 0.25 * s), SHELL, light, alpha);
    litShape(frame, (x, y) => cone(x, y, el, wr, 0.25 * s, 0.22 * s), boxOf([el, wr], 0.25 * s), SHELL, light, alpha);
    joint(el, 0.17);
    // the hand: a rounded mitten with a thumb, along the forearm
    const along = { x: (hd.x - wr.x) / (HAND * s), y: (hd.y - wr.y) / (HAND * s) };
    const palm = add(wr, along, 0.26 * s);
    const rot = Math.atan2(along.y, along.x) / RAD;
    const thumb = add(palm, { x: -along.y, y: along.x }, (side === "A" ? 1 : -1) * 0.2 * s);
    litShape(frame, (x, y) => Math.min(box(x, y, palm, 0.27 * s, 0.2 * s, 0.12 * s, rot), ellipse(x, y, thumb, 0.1 * s, 0.1 * s)), boxOf([wr, hd, thumb], 0.32 * s), hands, light, alpha);
    joint(wr, 0.11);
  };
  const leg = (side: "A" | "B"): void => {
    const hip = add(j.pelvis, { x: Math.cos(pose.hip * RAD), y: Math.sin(pose.hip * RAD) }, (side === "A" ? -1 : 1) * HIP_JOINT * (1 - 0.4 * Math.abs(turn)) * s);
    const kn = side === "A" ? j.kneeA : j.kneeB;
    const an = side === "A" ? j.ankleA : j.ankleB;
    litShape(frame, (x, y) => cone(x, y, hip, kn, 0.27 * s, 0.24 * s), boxOf([hip, kn], 0.3 * s), SHELL, light, alpha);
    litShape(frame, (x, y) => cone(x, y, kn, an, 0.25 * s, 0.21 * s), boxOf([kn, an], 0.3 * s), SHELL, light, alpha);
    joint(kn, 0.19);
    // the foot: a block, toe forward (facing), slightly out (front view)
    const toe = profile ? Math.sign(turn) : side === "A" ? -0.4 : 0.4;
    const foot = { x: an.x + toe * 0.24 * s, y: an.y + 0.1 * s };
    litShape(frame, (x, y) => box(x, y, foot, (profile ? 0.42 : 0.3) * s, 0.15 * s, 0.08 * s), boxOf([foot], 0.5 * s), SHELL, light, alpha);
    joint(an, 0.12);
  };
  if (profile && !options.noArms) arm(far);
  leg(far);
  leg(near);
  // the hip unit and the hip joints
  litShape(frame, (x, y) => box(x, y, add(j.pelvis, up, -0.05 * s), 0.6 * wide * s + 0.25 * s, 0.3 * s, 0.14 * s, pose.lean), boxOf([j.pelvis], 1 * s), SHELL, light, alpha);

  // -- the chassis: a rounded box, a seam, her core light -------------------------------
  const chassisAt = add(j.pelvis, up, 1.0 * s);
  const hw = (0.86 * wide + 0.24) * s;
  litShape(frame, (x, y) => box(x, y, chassisAt, hw, 0.9 * s + pose.lift * s * 0.5, 0.3 * s, pose.lean), boxOf([chassisAt], 1.3 * s), SHELL, light, alpha);
  // a panel seam across the chest, and a small round core light
  const seamA = add(add(chassisAt, up, 0.38 * s), right, -hw * 0.72);
  const seamB = add(add(chassisAt, up, 0.38 * s), right, hw * 0.72);
  darken(frame, (x, y) => cone(x, y, seamA, seamB, 0.03 * s, 0.03 * s), boxOf([seamA, seamB], 0.2 * s), 0.35);
  const core = add(add(chassisAt, up, -0.05 * s), right, turn * hw * 0.35);
  if (!outfit.bogu) {
    const glow = Math.max(1, 0.15 * s);
    for (let r = Math.floor(core.y - glow - 1); r <= core.y + glow + 1; r += 1) {
      for (let c = Math.floor(core.x - glow - 1); c <= core.x + glow + 1; c += 1) {
        const d = Math.hypot(c + 0.5 - core.x, r + 0.5 - core.y);
        if (d <= glow) frame.cover(c, r, alpha * (d < glow * 0.5 ? 1 : 0.7), options.eyes ?? INK.cyan, FADE.fast);
      }
    }
  }
  if (outfit.bogu) {
    // the do: a lacquered breastplate over the chassis, its curve catching the light
    const plate = (x: number, y: number): number => box(x, y, add(chassisAt, up, 0.1 * s), hw * 0.92, 0.66 * s, 0.32 * s, pose.lean);
    litShape(frame, plate, boxOf([chassisAt], 1.3 * s), { ink: INK.cyan, fill: 0.2 }, light, alpha);
  }
  // shoulder joints sit on the chassis corners
  if (!profile) joint(j.shoulderA, 0.24);
  joint(near === "B" ? j.shoulderB : j.shoulderA, 0.24);

  // -- a skirt (hakama) over the hip unit ------------------------------------------------
  if (outfit.skirt) {
    const k = outfit.skirt;
    const sway = pose.sway * 0.9;
    const waist = add(j.pelvis, up, 0.35 * s);
    const hemY = j.pelvis.y + (HIP_H - k.hem) * s;
    const skirt: Vec[] = [
      add(waist, right, -(0.75 * wide + 0.2) * s),
      { x: j.pelvis.x + (-k.flare + sway) * s, y: hemY },
      { x: j.pelvis.x + sway * s * 1.15, y: hemY + 0.1 * s },
      { x: j.pelvis.x + (k.flare + sway) * s, y: hemY },
      add(waist, right, (0.75 * wide + 0.2) * s),
    ];
    litShape(frame, (x, y) => polygon(x, y, skirt), boxOf(skirt, 1), { ink: k.ink ?? INK.cyan, fill: 0.3 }, light, alpha);
    // pleats: two dark creases down from the waist
    for (const f of [-0.35, 0.35]) {
      const a = add(waist, right, f * s);
      const b = { x: j.pelvis.x + (f * k.flare * 1.4 + sway * 0.9) * s, y: hemY - 0.1 * s };
      darken(frame, (x, y) => cone(x, y, a, b, 0.03 * s, 0.05 * s), boxOf([a, b], 0.2 * s), 0.4);
    }
  }

  // -- the head: a rounded box, its front a screen with her eyes on it -------------------
  const headRot = Math.atan2(j.up.x, -j.up.y) / RAD;
  const headW = HEAD_W * (1 - 0.3 * Math.abs(turn)) * s;
  const headH = HEAD_H * s;
  // the neck: a short dark column
  litShape(frame, (x, y) => cone(x, y, add(j.neck, up, -0.1 * s), add(j.neck, j.up, (NECK + 0.2) * s), 0.22 * s, 0.2 * s), boxOf([j.neck], 0.6 * s), JOINT, light, alpha);
  if (outfit.collar) {
    // a ruff: a frilled ring of white round the neck
    const ruff = add(j.neck, up, 0.06 * s);
    litShape(frame, (x, y) => ellipse(x, y, ruff, (0.62 * wide + 0.15) * s, 0.2 * s) + 0.04 * s * Math.sin(Math.atan2(y - ruff.y, x - ruff.x) * 9), boxOf([ruff], 0.8 * s), { ink: INK.white, fill: 0.62 }, light, alpha);
  }
  // ear pods on the sides of her head
  const cs = Math.cos(headRot * RAD);
  const sn = Math.sin(headRot * RAD);
  const onHead = (u: number, v: number): Vec => ({ x: j.head.x + (u * cs - v * sn) * s, y: j.head.y + (u * sn + v * cs) * s });
  for (const e of [-1, 1]) {
    if (profile && e === Math.sign(turn)) continue;
    const pod = onHead(e * HEAD_W * (1 - 0.3 * Math.abs(turn)) + (profile ? -turn * 0.2 : 0), 0.05);
    litShape(frame, (x, y) => ellipse(x, y, pod, 0.17 * s, 0.3 * s, headRot), boxOf([pod], 0.4 * s), JOINT, light, alpha);
  }
  litShape(frame, (x, y) => box(x, y, j.head, headW, headH, 0.36 * s, headRot), boxOf([j.head], Math.max(headW, headH) + 1), SHELL, light, alpha);
  // the screen: inset, dark, turned with her head (it slides toward where she faces)
  const screenAt = onHead(turn * 0.24, 0.04);
  const screenW = (HEAD_W - 0.2) * (1 - 0.45 * Math.abs(turn)) * s;
  const screenH = (HEAD_H - 0.2) * s;
  const screen = (x: number, y: number): number => box(x, y, screenAt, screenW, screenH, 0.24 * s, headRot);
  const sb = boxOf([screenAt], Math.max(screenW, screenH) + 1);
  for (let r = Math.max(0, Math.floor(sb.y0)); r <= Math.min(ROWS - 1, sb.y1); r += 1) {
    for (let c = Math.max(0, Math.floor(sb.x0)); c <= Math.min(COLS - 1, sb.x1); c += 1) {
      const d = screen(c + 0.5, r + 0.5);
      if (d > 0.5) continue;
      const i = r * COLS + c;
      // dark glass; its top edge catches a thin line of the light
      const edgeLit = d > -1 && r < screenAt.y - screenH * 0.6;
      frame.value[i] = lerp(frame.value[i], edgeLit ? 0.22 : 0.02, alpha);
      frame.ink[i] = INK.cyan;
      frame.fade[i] = FADE.fast;
    }
  }
  if (!outfit.men) drawScreenEyes(frame, screenAt, screenW, screenH, pose, options, alpha);
  if (outfit.men) {
    drawScreenEyes(frame, screenAt, screenW, screenH, pose, options, alpha * 0.8);
    drawMen(frame, j, headW, headH, headRot, light, alpha);
  }
  if (outfit.hat) drawHat(frame, j, s, headRot, headW, outfit.hat.tip, light, alpha);

  // -- arms in front ---------------------------------------------------------------------
  options.held?.(j);
  if (options.noArms) return j;
  if (!profile) arm(far);
  arm(near);
  if (!profile) {
    joint(j.shoulderA, 0.24);
    joint(j.shoulderB, 0.24);
  } else {
    joint(near === "B" ? j.shoulderB : j.shoulderA, 0.24);
  }
  return j;
}

/** Her own eyes - the same eye art as her big face - on her screen, small. */
function drawScreenEyes(frame: Frame, at: Vec, w: number, h: number, pose: Pose, options: FigureOptions, alpha: number): void {
  const eyes = eyeGrids("listening", options.emotion ?? "happy", pose.blink > 0.5);
  const scale = Math.max(1, Math.floor((h * 1.25) / EYE_ROWS));
  const size = EYE_COLS * scale;
  const gap = Math.max(2, Math.round(w * 0.22));
  const top = Math.round(at.y - size / 2);
  const shift = Math.round(pose.gaze * w * 0.15);
  const ink = options.eyes ?? INK.cyan;
  // drawn into a scratch frame and laid on, so the eyes never leak off the screen
  const left = Math.round(at.x - gap / 2 - size) + shift;
  const right = Math.round(at.x + gap / 2) + shift;
  upscale(frame, eyes.left, EYE_COLS, EYE_ROWS, scale, left, top, alpha, ink, FADE.fast);
  upscale(frame, eyes.right, EYE_COLS, EYE_ROWS, scale, right, top, alpha, ink, FADE.fast);
}

/** Kendo men: a padded helmet over her head, the steel grille across her screen. */
function drawMen(frame: Frame, j: Joints, headW: number, headH: number, rot: number, light: Light, alpha: number): void {
  const s = j.scale;
  const cs = Math.cos(rot * RAD);
  const sn = Math.sin(rot * RAD);
  const at = (u: number, v: number): Vec => ({ x: j.head.x + u * cs - v * sn, y: j.head.y + u * sn + v * cs });
  // the padded crown and the flaps (men-dare) over the shoulders, behind the grille
  const crown = (x: number, y: number): number => {
    const dome = box(x, y, at(0, -headH * 0.2), headW * 1.08, headH * 0.95, headH * 0.6, rot);
    return Math.max(dome, -(box(x, y, at(0, headH * 0.15), headW * 0.82, headH * 0.68, headH * 0.3, rot)));
  };
  litShape(frame, crown, { x0: j.head.x - headW * 1.2, y0: j.head.y - headH * 1.4, x1: j.head.x + headW * 1.2, y1: j.head.y + headH * 1.1 }, { ink: INK.cyan, fill: 0.3 }, light, alpha);
  for (const side of [-1, 1]) {
    const a = at(side * headW * 0.9, headH * 0.8);
    const b = { x: a.x + side * 0.5 * s, y: a.y + 0.55 * s };
    litShape(frame, (x, y) => cone(x, y, a, b, 0.2 * s, 0.26 * s), boxOf([a, b], 0.35 * s), { ink: INK.cyan, fill: 0.28 }, light, alpha);
  }
  // the grille: bars across the screen, one down the middle
  for (const v of [-0.5, -0.17, 0.17, 0.5]) {
    const a = at(-headW * 0.78, v * headH);
    const b = at(headW * 0.78, v * headH);
    litShape(frame, (x, y) => cone(x, y, a, b, 0.05 * s, 0.05 * s), boxOf([a, b], 0.15 * s), { ink: INK.white, fill: 0.8 }, light, alpha, false);
  }
  const top = at(0, -headH * 0.75);
  const bottom = at(0, headH * 0.75);
  litShape(frame, (x, y) => cone(x, y, top, bottom, 0.06 * s, 0.06 * s), boxOf([top, bottom], 0.15 * s), { ink: INK.white, fill: 0.85 }, light, alpha, false);
}

/**
 * A wide Victorian hat on her box head - worn at a jaunty tilt: a round brim much
 * wider than her head, a domed crown, a pink ribbon and a cluster of pink flowers,
 * a white plume curling back. Clearly a costume on a robot.
 */
function drawHat(frame: Frame, j: Joints, s: number, headRot: number, headW: number, tip: number, light: Light, alpha: number): void {
  const rot = headRot - 10 - tip * 14;
  const cs = Math.cos(rot * RAD);
  const sn = Math.sin(rot * RAD);
  const lift = tip * 0.2;
  const k = headW / s;
  // u across, v down from the head centre, in her units
  const at = (u: number, v: number): Vec => ({ x: j.head.x + (u * cs - v * sn) * s, y: j.head.y + (u * sn + v * cs) * s });
  // the brim sits down on the top edge of her head, not floating above it
  const top = -HEAD_H + 0.14 - lift;
  const felt: Shade = { ink: INK.white, fill: 0.5 };
  // the plume first, behind the crown
  const plume = [at(0.3 * k, top - 0.35), at(-0.2 * k, top - 0.72), at(-0.85 * k, top - 0.68), at(-1.35 * k, top - 0.35)];
  const plumeR = [0.1, 0.2, 0.16, 0.05];
  for (let n = 0; n < plume.length - 1; n += 1) {
    litShape(frame, (x, y) => cone(x, y, plume[n], plume[n + 1], plumeR[n] * s, plumeR[n + 1] * s), boxOf([plume[n], plume[n + 1]], 0.3 * s), felt, light, alpha);
  }
  // the crown: a dome on the brim
  const base = at(0, top - 0.04);
  litShape(
    frame,
    (x, y) => {
      const lx = (x - base.x) * cs + (y - base.y) * sn;
      const ly = -(x - base.x) * sn + (y - base.y) * cs;
      return Math.max((Math.hypot(lx / (0.62 * k * s), ly / (0.66 * s)) - 1) * 0.62 * s, ly);
    },
    { x0: base.x - 0.9 * s, y0: base.y - 0.7 * s, x1: base.x + 0.9 * s, y1: base.y + 0.2 * s },
    felt,
    light,
    alpha,
  );
  // the ribbon round its foot
  const r0 = at(-0.6 * k, top - 0.12);
  const r1 = at(0.62 * k, top - 0.12);
  litShape(frame, (x, y) => cone(x, y, r0, r1, 0.08 * s, 0.08 * s), boxOf([r0, r1], 0.2 * s), { ink: INK.pink, fill: 0.62 }, light, alpha, false);
  // the brim: a long flat oval, much wider than her head
  const brim = at(0.1 * k, top);
  litShape(frame, (x, y) => ellipse(x, y, brim, 1.45 * k * s, 0.22 * s, rot), boxOf([brim], 1.55 * k * s), felt, light, alpha);
  // flowers heaped where the ribbon ties: pink, one white
  const flowers: [number, number, Ink, number][] = [
    [0.5, -0.26, INK.pink, 0.24],
    [0.78, -0.14, INK.pink, 0.19],
    [0.66, -0.48, INK.white, 0.16],
  ];
  for (const [u, v, ink, r] of flowers) {
    const c = at(u * k, top + v);
    litShape(frame, (x, y) => ellipse(x, y, c, r * s, r * s) - 0.025 * s * Math.cos(Math.atan2(y - c.y, x - c.x) * 5), boxOf([c], r * s + 1), { ink, fill: 0.68 }, light, alpha);
  }
}

/** A soft dark pool under her feet, so she stands on the ground and doesn't float. */
export function groundShadow(frame: Frame, cam: Camera, x: number, width: number, keep = 0.25): void {
  const c = { x: cam.x + x * cam.s, y: cam.y - 0.05 * cam.s };
  darken(frame, (px, py) => ellipse(px, py, c, width * cam.s, 0.22 * cam.s), { x0: c.x - width * cam.s - 1, y0: c.y - 0.3 * cam.s, x1: c.x + width * cam.s + 1, y1: c.y + 0.3 * cam.s }, keep);
}

/**
 * Walking: the pose fields a step cycle sets at `phase` (0..1 per two steps),
 * travelling at `x`. A servo bob on each step, arms swinging against the legs.
 */
export function walk(phase: number, x: number, stride = 0.5, facing = 0): Partial<Pose> {
  const a = phase * Math.PI * 2;
  const step = Math.sin(a);
  const liftA = Math.max(0, -Math.cos(a)) * 0.2;
  const liftB = Math.max(0, Math.cos(a)) * 0.2;
  const dirX = facing === 0 ? 0 : Math.sign(facing);
  return {
    x,
    y: HIP_H - 0.07 + Math.abs(Math.cos(a)) * 0.07,
    hip: step * 3,
    fAx: x - 0.4 * (1 - Math.abs(facing) * 0.6) + dirX * step * stride,
    fAy: ANKLE + liftA,
    fBx: x + 0.4 * (1 - Math.abs(facing) * 0.6) - dirX * step * stride,
    fBy: ANKLE + liftB,
    aA: -12 - step * 16 * (dirX || 0.4),
    aB: 12 - step * 16 * (dirX || 0.4),
  };
}
