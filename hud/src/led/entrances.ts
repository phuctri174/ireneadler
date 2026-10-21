// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// Summon entrances: how Irene arrives. The hand sign always plays the domain
// expansion (led/summon.ts, keyed to its own clip); every other summon picks one of
// these from config/entrances.json (never the same twice running).
//
// Each is a short film at the domain expansion's length (5.8 s), in its shape:
//
//   build-up  fade up from black, letterbox in, a wide shot of her whole body
//             (led/figure.ts) in a lit place (led/backdrops.ts), doing something
//   peak      the moment it is all for - an impact, a release, a reveal - with a
//             flash, a shake, light breaking over her
//   settle    the camera pushes in, then cuts to her own face in close-up, wearing
//             the scene's signature (the hat, the headband, the queen, the card,
//             the glow), while she says her line; the bars slide away
//
// Like scenes, an entrance is look(t) - the face it wears after the cut - and
// draw(frame, t), painted over the face (the shot hides it until the cut).
// A new entrance is its entry here plus one in the registry (with its line and
// sound effects); hud/tests/entrances.verify.mjs checks both halves agree.

import type { BackdropName } from "./backdrops";
import { LAMP, drawBackdrop, place } from "./backdrops";
import { FADE, INK, ROWS, blit, clamp01, ease, lerp, sprite } from "./grid";
import type { Frame, Ink, Vec } from "./grid";
import type { Camera, Joints, Light, Outfit, Pose, Track } from "./figure";
import { BARE, HAND_SPRING, HIP_H, STAND, anticipate, animate, arc, box, cone, drawArm, drawFigure, follow, knee, overshoot, ellipse, groundShadow, litShape, polygon, reach, resolve, sample, walk } from "./figure";
import { begin, composite, cutToFace, dim, flash, fog, glow, hash, letterbox, lightCone, motes, pool, shake, span, sparks } from "./film";
import type { SceneLook } from "./scenes";

/** Every entrance is as long as the domain expansion's clip. */
export const ENTRANCE_MS = 5800;
/** When the shot cuts to her face (her line starts just after it). */
const CUT = 3900;
const CUT_MS = 260;

const TAU = Math.PI * 2;
const RAD = Math.PI / 180;

// ---- the shared skeleton --------------------------------------------------------------

/** Pin both wrists to targets (her space) with arm IK - for things held in two hands. */
function grip(p: Pose, a: Vec | null, b: Vec | null): Pose {
  const out = { ...p };
  if (a) {
    const r = reach(out, "A", a);
    out.aA = r.a;
    out.eA = r.e;
  }
  if (b) {
    const r = reach(out, "B", b);
    out.aB = r.a;
    out.eB = r.e;
  }
  return out;
}

function lerpCam(a: Camera, b: Camera, u: number): Camera {
  const k = clamp01(u);
  return { x: lerp(a.x, b.x, k), y: lerp(a.y, b.y, k), s: lerp(a.s, b.s, k) };
}

/** A camera framing a point of her space at screen (sx, sy) at scale s. */
function frameOn(x: number, y: number, s: number, sx = 64, sy = 36): Camera {
  return { x: sx - x * s, y: sy + y * s, s };
}

/** Toward a point, from a point (screen space): the light's direction on her. */
function toward(from: Vec, to: Vec, ink: Ink, power: number): Light {
  return { dir: { x: to.x - from.x, y: to.y - from.y }, ink, power };
}

/**
 * The film: the shot (until the cut, faded up from black, letterboxed) laid over
 * her face; after the cut, her face with the scene's signature drawn on it while
 * the bars slide away and, at the very end, the signature fades.
 */
function film(frame: Frame, t: number, shot: (f: Frame, t: number) => void, signature: (f: Frame, t: number, alpha: number) => void): void {
  const over = cutToFace(t, CUT, CUT_MS);
  if (over > 0) {
    const s = begin();
    shot(s, t);
    dim(s, span(t, 0, 420));
    letterbox(s, span(t, 60, 420));
    composite(frame, s, over);
  }
  if (t >= CUT) {
    const alpha = span(t, CUT, CUT + 180) * (1 - span(t, ENTRANCE_MS - 520, ENTRANCE_MS - 40));
    signature(frame, t, alpha);
    letterbox(frame, 1 - span(t, CUT + 120, CUT + 620));
  }
}

/** The close-up's light from one side: a soft glow along that edge of the matrix. */
function edgeLight(frame: Frame, side: -1 | 1, level: number, ink: Ink, alpha: number): void {
  pool(frame, { x: side < 0 ? -6 : 134, y: 34 }, 26, 40, level * alpha, ink);
}

// ---- victorian: Irene Adler, on a gas-lit street at night ----------------------------
// The same robot, cosplaying a Victorian lady: a wide flowered hat on her box head,
// a red cape and a ruff over her chassis, her machined legs plainly showing - and
// very pleased with herself about it. A carriage crosses in the fog; she walks out
// of the dark, stops under the lamp, turns, and tips her hat to him - the lamp
// flares, her screen winks. Then her face under the brim: "Charmed, I'm sure."

const VIC: Outfit = { collar: true, cape: { hem: 1.7, flare: 1.55, ink: INK.red }, hat: { tip: 0 } };
const V = { walk: 250, stop: 2400, turn: 2950, tip: 3250, peak: 3350, push: 3000 };
const V_START = 9.5;
const V_END = 0.7;

function vicTravel(t: number): number {
  const u = clamp01((t - V.walk) / (V.stop - V.walk));
  return lerp(V_START, V_END, 1 - (1 - u) ** 1.7);
}

const VIC_HAND = { x: V_END + 1.45, y: 6.95 };
const vicStill: Pose = { ...STAND, x: V_END, turn: -0.8, aA: -18, eA: 40, aB: 12, eB: -10, fAx: V_END - 0.3, fBx: V_END + 0.3 };
const vicFacing: Pose = { ...vicStill, turn: 0.12, head: -7, lean: -2, hip: 5, aA: -16, eA: 55 };
const vicTip = grip({ ...vicFacing, head: -10 }, null, VIC_HAND);
const vicTrack: Track = resolve(
  [
    { t: V.stop, p: vicStill },
    { t: V.stop + 380, p: { hip: 4, lean: -1.5 }, e: "out" },
    { t: V.turn, p: vicFacing },
    { t: V.tip, p: vicTip, e: "back" },
    { t: V.tip + 380, p: { ...vicTip, eB: vicTip.eB - 10, head: -6 } },
    { t: CUT, p: { ...vicTip, head: -12, eB: vicTip.eB - 6 } },
  ],
  vicStill,
);

function vicPose(t: number): Pose {
  if (t < V.stop) {
    const x = vicTravel(t);
    const stepping = clamp01((V.stop - t) / 260);
    const w = walk((V_START - x) / 2.0, x, 0.45 * stepping, -1);
    return { ...vicStill, ...w, x, turn: -0.8, aA: -18, eA: 40, y: lerp(HIP_H, w.y ?? HIP_H, stepping) };
  }
  return sample(vicTrack, t);
}

function vicCam(t: number): Camera {
  const wide = { x: 64 - 0.6 * 6.1 + Math.min(0, vicTravel(t) - 2) * -1.2, y: 66, s: 6.1 };
  const medium = frameOn(V_END + 0.1, 5.3, 10.5, 64, 33);
  return lerpCam(wide, medium, span(t, V.push, V.peak + 300));
}

function vicShot(frame: Frame, t: number): void {
  const cam = vicCam(t);
  drawBackdrop(frame, "gaslight", t, cam);
  const pose = animate(vicPose, t);
  const tip = span(t, V.tip - 120, V.tip + 160) * (1 - 0.6 * span(t, V.tip + 420, CUT));
  const lamp = place(cam, LAMP.x, LAMP.y);
  const flare = Math.exp(-(((t - V.peak) / 170) ** 2));
  groundShadow(frame, cam, pose.x + 0.5, 1.4, 0.35);
  // her screen: cheerful walking in, amused once she's turned, a wink on the tip
  const emotion = t > V.tip - 60 && t < V.tip + 520 ? "wink" : t > V.turn - 200 ? "amused" : "happy";
  const j = drawFigure(frame, pose, { ...VIC, hat: { tip } }, cam, toward(place(cam, pose.x, 4.6), lamp, INK.amber, 0.95 + flare * 0.4), { emotion });
  // the lamp flares as she tips the hat; a glint catches her eye
  glow(frame, lamp, Math.max(1, 0.26 * cam.s) * (1 + flare * 0.5), 0.95, INK.amber, INK.white);
  if (flare > 0.05) {
    const eye = { x: j.head.x + 0.75 * cam.s, y: j.head.y - 0.5 * cam.s };
    for (const [dx, dy, k] of [[0, 0, 1], [1, 0, 0.6], [-1, 0, 0.6], [0, 1, 0.6], [0, -1, 0.6], [2, 0, 0.3], [-2, 0, 0.3], [0, -2, 0.3], [0, 2, 0.3]] as const) {
      frame.lighten(Math.round(eye.x + dx), Math.round(eye.y + dy), flare * k, INK.white, FADE.fast);
    }
  }
}

/** Her face under the brim in close-up: hat, flowers, plume, the lamp's glow at the side. */
function vicSignature(frame: Frame, t: number, alpha: number): void {
  // "Charmed": she dips the brim a touch, then lifts it again
  const tipK = Math.sin(clamp01((t - 4480) / 560) * Math.PI) * 0.7;
  const rot = (-5 - tipK * 4) * RAD;
  const cs = Math.cos(rot);
  const sn = Math.sin(rot);
  const at = (x: number, y: number): Vec => ({ x: 64 + (x - 64) * cs - (y - 9) * sn, y: 9 + tipK * 2 + (x - 64) * sn + (y - 9) * cs });
  const lamp: Light = { dir: { x: -1, y: -0.35 }, ink: INK.amber, power: 0.95 };
  const felt = { ink: INK.white, fill: 0.22, rim: 0.65 };
  edgeLight(frame, -1, 0.24, INK.amber, alpha);
  fog(frame, t, 58, 71, 0.12 * alpha, 1);
  // the brim's shadow falls across the top of her eyes - deeper over the left one
  for (let r = 10; r <= 20; r += 1) {
    for (let c = 28; c < 100; c += 1) {
      const depth = c < 64 ? 19 : 15;
      if (r > depth) continue;
      const i = r * 128 + c;
      frame.value[i] *= lerp(1, 0.25, alpha * clamp01((depth - r) / 4));
    }
  }
  // the plume: a feather sweeping back across the top-left
  const plume = [at(58, 1), at(40, -5), at(20, -4), at(4, 3)];
  const plumeR = [2.2, 4.2, 3.4, 1.2];
  for (let k = 0; k < plume.length - 1; k += 1) {
    litShape(frame, (x, y) => cone(x, y, plume[k], plume[k + 1], plumeR[k], plumeR[k + 1]), { x0: 0, y0: 0, x1: 66, y1: 12 }, { ink: INK.white, fill: 0.34, rim: 0.7 }, lamp, alpha, false);
  }
  // the crown, a dome cut off by the top of the frame
  const base = at(64, 8);
  litShape(
    frame,
    (x, y) => {
      const lx = (x - base.x) * cs + (y - base.y) * sn;
      const ly = -(x - base.x) * sn + (y - base.y) * cs;
      return Math.max((Math.hypot(lx / 30, ly / 22) - 1) * 22, ly);
    },
    { x0: 30, y0: 0, x1: 98, y1: 10 },
    felt,
    lamp,
    alpha,
    false,
  );
  // the ribbon round it
  litShape(frame, (x, y) => cone(x, y, at(37, 6.5), at(91, 6.5), 1.6, 1.6), { x0: 30, y0: 0, x1: 98, y1: 9 }, { ink: INK.pink, fill: 0.55, rim: 0.85 }, lamp, alpha, false);
  // the brim: an oval far wider than her face, its underside in shadow
  const brim = at(64, 11);
  litShape(frame, (x, y) => ellipse(x, y, brim, 74, 4.6, rot / RAD), { x0: 0, y0: 0, x1: 127, y1: 20 }, { ink: INK.white, fill: 0.14, rim: 0.7 }, lamp, alpha, false);
  // flowers heaped at the front, where the ribbon ties
  const flowers: [number, number, Ink, number][] = [
    [88, 3, INK.pink, 4.6],
    [97, 6, INK.amber, 3.4],
    [94, -1, INK.white, 3.2],
    [104, 7, INK.pink, 2.8],
    [81, -1, INK.pink, 3],
  ];
  for (const [fx, fy, ink, r] of flowers) {
    const c = at(fx, fy);
    litShape(frame, (x, y) => ellipse(x, y, c, r, r) - 0.55 * Math.cos(Math.atan2(y - c.y, x - c.x) * 5), { x0: c.x - r - 2, y0: c.y - r - 2, x1: c.x + r + 2, y1: c.y + r + 2 }, { ink, fill: 0.62, rim: 0.95 }, lamp, alpha, false);
  }
}

function vicLook(t: number): SceneLook {
  // poised and slightly amused under the brim; the wink lands on "Charmed"
  if (t < CUT) return { emotion: "amused", mouth: "smirk" };
  if (t > 4480 && t < 4980) return { emotion: "wink", mouth: "smirk", gazeY: 1 };
  return { emotion: "amused", mouth: "smirk", gazeY: 1 };
}

// ---- kendo: a men strike in the dojo, the kiai, zanshin, and the helmet comes off ------
// Kamae facing the practice dummy; two sliding steps of pressure; then the strike -
// the shinai up, the stamp, the kiai, the hit (flash, shake, sparks); she carries
// through, turns, and lifts off her men: underneath, her screen face.

const KENDO: Outfit = { bogu: true, men: true, skirt: { hem: 0.55, flare: 1.0 } };
const K = { step1: 650, step2: 1150, raise: 2150, strike: 2330, hit: 2480, pass: 2850, turn: 3100, off: 3300, push: 3150 };
const DUMMY = { x: 3.7, head: 6.1 };
const SHINAI = 4.0;

interface Sword {
  /** Rear hand (arm A) on the hilt, her space; the blade's elevation, degrees. */
  g: Vec;
  up: number;
}

function blade(s: Sword): Vec {
  return { x: Math.cos(s.up * RAD), y: Math.sin(s.up * RAD) };
}

const kTrack: Track = resolve([
  { t: 0, p: { x: -3.4, turn: 0.86, y: 3.08, lean: 3, fAx: -3.85, fAy: 0.34, fBx: -2.85 } },
  { t: K.step1 - 160, p: { x: -3.4, fBx: -2.55 }, e: "out" },
  { t: K.step1, p: { x: -2.85, fAx: -3.3, fBx: -2.3 }, e: "io" },
  { t: K.step2 - 160, p: { fBx: -1.95 }, e: "out" },
  { t: K.step2, p: { x: -2.3, fAx: -2.75, fBx: -1.75 }, e: "io" },
  { t: K.raise, p: { y: 2.98, lean: 5 } },
  { t: K.strike, p: { y: 3.08, lean: -2, fBx: -1.6 }, e: "snap" },
  { t: K.hit, p: { x: 0.9, y: 2.95, lean: 9, fAx: -0.2, fBx: 1.75, fAy: 0.42 }, e: "snap" },
  { t: K.hit + 170, p: { x: 1.05, y: 3.05, lean: 5, fAx: 0.3, fBx: 1.75, fAy: 0.32 }, e: "out" },
  { t: K.pass, p: { x: 0.45, y: 3.12, lean: 2, fAx: -0.05, fAy: 0.26, fBx: 1.0 }, e: "io" },
  { t: K.turn, p: { turn: 0.15, fAx: 0.05, fBx: 0.85, lean: 0, y: HIP_H } },
  { t: K.off + 350, p: { turn: 0.05, lean: -3, head: -6 } },
  { t: CUT, p: { turn: 0.0, lean: -1, head: 4 } },
]);

/** The sword as keyed: the hilt travels arcs (raised up and back over her head,
 *  then cut down and forward), the blade's angle eased - before the springs. */
function kSwordKeyed(t: number, x: number): Sword {
  const kamae = { g: { x: x + 0.7, y: 3.75 }, up: 24 + Math.sin(t / 170) * 2.5 * span(t, K.step2, K.raise) };
  // anticipation for the raise: the tip dips first
  const dip = { g: { x: x + 0.62, y: 3.6 }, up: 12 };
  const over = { g: { x: x + 0.2, y: 6.85 }, up: 152 };
  const strike = { g: { x: x + 1.25, y: 5.3 }, up: 6 };
  const after = { g: { x: x + 1.05, y: 4.7 }, up: 14 };
  const back = { g: { x: x + 0.6, y: 3.6 }, up: -30 };
  const go = (a: Sword, b: Sword, u: number, bulge: number): Sword => ({ g: arc(a.g, b.g, u, bulge), up: lerp(a.up, b.up, u) });
  if (t < K.raise - 160) return kamae;
  if (t < K.raise) return go(kamae, dip, ease((t - K.raise + 160) / 160), 0);
  // up and back over her head: a high arc, fast out
  if (t < K.strike) return go(dip, over, 1 - (1 - (t - K.raise) / (K.strike - K.raise)) ** 3, 0.55);
  // the cut: down and forward on a wide arc, accelerating into the hit
  if (t < K.hit) return go(over, strike, ((t - K.strike) / (K.hit - K.strike)) ** 1.8, -0.7);
  if (t < K.pass) return go(strike, after, ease((t - K.hit) / (K.pass - K.hit)), 0.1);
  if (t < K.turn + 120) return go(after, back, ease((t - K.pass) / (K.turn + 120 - K.pass)), -0.25);
  // lowered to her side while the men comes off
  return go(back, { g: { x: x + 0.7, y: 3.2 }, up: -80 }, span(t, K.off - 100, K.off + 250), -0.2);
}

const SWORD_SPRINGS = { gx: HAND_SPRING, gy: HAND_SPRING, up: { w: 30, z: 0.42 } };

/** The sword as it moves: the keyed path through springs (the cut overshoots past
 *  the strike and settles; the raise lags and whips). */
function kSword(t: number): Sword {
  const flat = (time: number): { gx: number; gy: number; up: number } => {
    const k = kSwordKeyed(time, sample(kTrack, time).x);
    return { gx: k.g.x, gy: k.g.y, up: k.up };
  };
  const f = follow(flat, t, SWORD_SPRINGS);
  return { g: { x: f.gx, y: f.gy }, up: f.up };
}

function kPose(base: Pose, t: number): Pose {
  const p = { ...base };
  if (t >= K.off) {
    // both hands up to the men's sides, lifting it off; then down again
    const lift = span(t, K.off, K.off + 450);
    const down = span(t, K.off + 520, CUT);
    const head = { x: p.x, y: 6.2 + lift * 1.0 };
    const gA = { x: lerp(head.x - 1.3, p.x - 0.9, down), y: lerp(head.y, 3.4, down) };
    const gB = { x: lerp(head.x + 1.3, p.x + 0.9, down), y: lerp(head.y, 3.5, down) };
    return grip(p, gA, down < 1 ? gB : null);
  }
  const s = kSword(t);
  const d = blade(s);
  return grip(p, s.g, { x: s.g.x + d.x * 0.52, y: s.g.y + d.y * 0.52 });
}

function kCam(t: number): Camera {
  const wide = { x: 64 - 0.3 * 6.2, y: 66, s: 6.2 };
  const tense = { x: 64 - 0.1 * 7.6, y: 66 + 1.2, s: 7.6 };
  const medium = frameOn(0.5, 5.3, 10.5, 64, 33);
  const c = lerpCam(wide, tense, span(t, 600, K.raise));
  return lerpCam(c, medium, span(t, K.push, CUT - 150));
}

function drawDummy(frame: Frame, cam: Camera, t: number, light: Light): void {
  const hitK = t > K.hit ? Math.exp(-(t - K.hit) / 260) * Math.sin((t - K.hit) / 45) : 0;
  const base = place(cam, DUMMY.x, 0);
  const top = place(cam, DUMMY.x + hitK * 0.25, DUMMY.head - 0.6);
  litShape(frame, (x, y) => cone(x, y, base, top, 0.22 * cam.s, 0.16 * cam.s), { x0: base.x - 4, y0: top.y - 2, x1: base.x + 4, y1: base.y }, { ink: INK.amber, fill: 0.12 }, light);
  const torso = [place(cam, DUMMY.x - 0.6 + hitK * 0.15, 5.3), place(cam, DUMMY.x + 0.6 + hitK * 0.15, 5.3), place(cam, DUMMY.x + 0.52, 3.8), place(cam, DUMMY.x - 0.52, 3.8)];
  litShape(frame, (x, y) => polygon(x, y, torso) - 0.06 * cam.s, { x0: torso[0].x - 2, y0: torso[0].y - 2, x1: torso[1].x + 2, y1: torso[2].y + 2 }, { ink: INK.amber, fill: 0.16 }, light);
  const head = place(cam, DUMMY.x + hitK * 0.35, DUMMY.head);
  litShape(frame, (x, y) => ellipse(x, y, head, 0.5 * cam.s, 0.6 * cam.s), { x0: head.x - 0.7 * cam.s, y0: head.y - 0.8 * cam.s, x1: head.x + 0.7 * cam.s, y1: head.y + 0.8 * cam.s }, { ink: INK.amber, fill: 0.2 }, light);
  for (const v of [-0.3, 0, 0.3]) {
    const a = { x: head.x - 0.4 * cam.s, y: head.y + v * cam.s };
    const b = { x: head.x + 0.1 * cam.s, y: head.y + v * cam.s };
    litShape(frame, (x, y) => cone(x, y, a, b, 0.05 * cam.s, 0.05 * cam.s), { x0: a.x - 2, y0: a.y - 2, x1: b.x + 2, y1: b.y + 2 }, { ink: INK.white, fill: 0.7, rim: 0.8 }, light, 1, false);
  }
}

function kShot(frame: Frame, t: number): void {
  const jolt = shake(t, [K.hit], 2.2, 420);
  const base = kCam(t);
  const cam = { ...base, x: base.x + jolt.x, y: base.y + jolt.y };
  drawBackdrop(frame, "dojo", t, cam);
  const light: Light = { dir: { x: -0.75, y: -1 }, ink: INK.white, power: 0.85 };
  drawDummy(frame, cam, t, light);
  // her body follows its springs (the strike shifts her weight, she recoils); her
  // arms are solved to the sword, whose own path already has the springs and arcs -
  // both hands stay on the one hilt
  const pose = animate((time) => sample(kTrack, time), t);
  const solved = kPose(sample(kTrack, t), t);
  for (const k of ["aA", "eA", "aB", "eB"] as const) pose[k] = solved[k];
  groundShadow(frame, cam, pose.x, 1.3, 0.35);
  const kiai = Math.exp(-(((t - K.hit) / 240) ** 2));
  const menOn = t < K.off + 220;
  const outfit: Outfit = { ...KENDO, men: menOn };
  const sword = kSword(t);
  const held = (j: Joints): void => {
    const d = blade(sword);
    const g = { x: sword.g.x, y: sword.g.y };
    const a = place(cam, g.x - d.x * 0.35, g.y - d.y * 0.35);
    const b = place(cam, g.x + d.x * SHINAI, g.y + d.y * SHINAI);
    // the blade blurs through the strike: a fan of fading copies behind it
    if (t > K.strike && t < K.hit + 60) {
      for (let k = 1; k <= 4; k += 1) {
        const prev = kSword(t - k * 26);
        const pd = blade(prev);
        const pb = place(cam, prev.g.x + pd.x * SHINAI, prev.g.y + pd.y * SHINAI);
        const pa = place(cam, prev.g.x, prev.g.y);
        litShape(frame, (x, y) => cone(x, y, pa, pb, 0.05 * cam.s, 0.03 * cam.s), { x0: Math.min(pa.x, pb.x) - 2, y0: Math.min(pa.y, pb.y) - 2, x1: Math.max(pa.x, pb.x) + 2, y1: Math.max(pa.y, pb.y) + 2 }, { ink: INK.white, fill: 0.5 - k * 0.1, rim: 0.4 }, light, 0.6 - k * 0.12, false);
      }
    }
    litShape(frame, (x, y) => cone(x, y, a, b, 0.085 * cam.s, 0.06 * cam.s), { x0: Math.min(a.x, b.x) - 2, y0: Math.min(a.y, b.y) - 2, x1: Math.max(a.x, b.x) + 2, y1: Math.max(a.y, b.y) + 2 }, { ink: INK.amber, fill: 0.5, rim: 0.7 }, light);
    // the tsuba, a small guard ring
    const tsuba = place(cam, g.x + d.x * 0.62, g.y + d.y * 0.62);
    litShape(frame, (x, y) => ellipse(x, y, tsuba, 0.16 * cam.s, 0.16 * cam.s), { x0: tsuba.x - 3, y0: tsuba.y - 3, x1: tsuba.x + 3, y1: tsuba.y + 3 }, { ink: INK.white, fill: 0.5, rim: 0.8 }, light, 1, false);
    void j;
  };
  const emotion = t < K.off + 220 ? "firedUp" : "proud";
  const j = drawFigure(frame, pose, outfit, cam, light, { held, emotion, eyes: kiai > 0.3 ? INK.white : INK.cyan });
  // the men, lifted off and carried up out of the shot
  if (!menOn) {
    const u = span(t, K.off + 220, CUT);
    // carried up between her hands, then away
    const c = { x: (j.handA.x + j.handB.x) / 2, y: Math.min(j.handA.y, j.handB.y) - 0.2 * cam.s - u * 0.6 * cam.s };
    litShape(frame, (x, y) => box(x, y, c, 1.25 * cam.s, 0.95 * cam.s, 0.55 * cam.s), { x0: c.x - 1.4 * cam.s, y0: c.y - 1.1 * cam.s, x1: c.x + 1.4 * cam.s, y1: c.y + 1.1 * cam.s }, { ink: INK.cyan, fill: 0.3 }, light, 1 - span(t, K.off + 500, K.off + 800));
  }
  // the hit: sparks off the men, the stamp's dust, speed lines, the flash
  const tip = place(cam, DUMMY.x - 0.2, DUMMY.head + 0.25);
  sparks(frame, t, K.hit, tip, 22, 1.2, 5, INK.white);
  if (t > K.hit && t < K.hit + 600) {
    const u = (t - K.hit) / 600;
    for (let k = 0; k < 3; k += 1) {
      const r = (2 + u * 14 + k * 3) * (cam.s / 7);
      for (let a = 0; a < 40; a += 1) {
        const ang = (a / 40) * TAU;
        frame.lighten(Math.round(tip.x + Math.cos(ang) * r), Math.round(tip.y + Math.sin(ang) * r * 0.6), (1 - u) * (0.6 - k * 0.15), INK.white, FADE.fast);
      }
    }
    const foot = place(cam, pose.fBx, 0);
    for (let k = 0; k < 10; k += 1) {
      const dx = (hash(k) - 0.5) * 2 * (3 + u * 10);
      frame.lighten(Math.round(foot.x + dx), Math.round(foot.y - hash(k * 3) * 4 * (1 - u) - 1), (1 - u) * 0.45, INK.white, FADE.fast);
    }
  }
  if (t > K.strike && t < K.hit + 200) {
    const k = 1 - span(t, K.hit, K.hit + 200);
    for (let n = 0; n < 9; n += 1) {
      const y = 12 + hash(n * 7) * 44;
      const x0 = 4 + hash(n) * 30;
      for (let x = x0; x < x0 + 10 + hash(n * 3) * 14; x += 1) frame.lighten(Math.round(x), Math.round(y), 0.3 * k, INK.white, FADE.fast);
    }
  }
  flash(frame, Math.exp(-(t - K.hit) / 50) * (t >= K.hit ? 0.32 : 0));
}

function kSignature(frame: Frame, t: number, alpha: number): void {
  // no headband (he asked: she wears only the men) - just the dojo's light behind
  // her face, dust turning in it
  lightCone(frame, { x: -10, y: -6 }, { x: 30, y: 72 }, 30, 0.07 * alpha, INK.white);
  motes(frame, t, 8, 12, { x0: 0, y0: 14, x1: 40, y1: 70 }, 0.3 * alpha, INK.white, -0.003);
}

function kLook(t: number): SceneLook {
  if (t < CUT) return { emotion: "firedUp", mouth: "hidden" };
  if (t < 4350) return { emotion: "proud", mouth: "smile" };
  return { emotion: "happy", mouth: "smile", gazeY: 0 };
}

// ---- chess: a 2D board seen from above, her hand reaching in to deliver mate -------
// Shot like a film insert. The camera starts on her robot head, eyes narrowed over
// the board, then tilts down onto it: a flat 2D board under the lamp, classic
// pixel pieces. Her arm reaches in from her side of the table - a slight pull back
// first, a smooth reach (minimum-jerk, the curve real reaches follow), the hand
// closing on the queen, the piece lifting as it's carried in an arc, a press as it
// lands - mate: the board jumps, the enemy king topples. Her hand lifts away with
// a little follow-through; the camera tilts back up to her, amused; then her face.

const C = { pan: 450, panned: 1250, reach: 1300, grip: 1850, carry: 1950, land: 2550, release: 2700, topple: 2750, back: 3150, up: 3150, upped: 3750 };
/** Board: 8 x 8 squares, SQ LEDs each, in "table" space (rows from the board's top). */
const SQ = 7;
const BOARD_X = 64 - SQ * 4;
/** Where her head sits above the board in table space, and where the camera rests. */
const HEAD_ROW = -26;
const VIEW_HEAD = -40;
const VIEW_BOARD = -6;

type Glyph = "K" | "Q" | "R" | "B" | "N" | "P";
// 5 x 5 pixel pieces, the way a chess diagram draws them
const GLYPHS: Record<Glyph | "fallen", ReturnType<typeof sprite>> = {
  K: sprite(["..#..", ".###.", "..#..", ".###.", "#####"]),
  Q: sprite(["#.#.#", ".###.", "..#..", ".###.", "#####"]),
  R: sprite(["#.#.#", "#####", ".###.", ".###.", "#####"]),
  B: sprite(["..#..", ".#+#.", ".###.", "..#..", "#####"]),
  N: sprite([".##..", "####.", "..##.", ".###.", "#####"]),
  P: sprite([".....", "..#..", ".###.", "..#..", ".###."]),
  fallen: sprite([".....", "#....", "#####", "#.###", "....."]),
};

interface Piece {
  glyph: Glyph;
  mine: boolean;
  file: number;
  rank: number;
}
// her pieces at the top (her side), his at the bottom - a late middlegame, mate in one
const POSITION: Piece[] = [
  { glyph: "K", mine: true, file: 6, rank: 0 },
  { glyph: "R", mine: true, file: 0, rank: 0 },
  { glyph: "P", mine: true, file: 5, rank: 1 },
  { glyph: "P", mine: true, file: 6, rank: 1 },
  { glyph: "P", mine: true, file: 7, rank: 1 },
  { glyph: "B", mine: true, file: 2, rank: 2 },
  { glyph: "Q", mine: true, file: 3, rank: 1 },
  { glyph: "N", mine: false, file: 2, rank: 5 },
  { glyph: "P", mine: false, file: 5, rank: 6 },
  { glyph: "P", mine: false, file: 7, rank: 6 },
  { glyph: "R", mine: false, file: 0, rank: 7 },
  { glyph: "K", mine: false, file: 6, rank: 7 },
];
const QUEEN = POSITION.find((p) => p.glyph === "Q" && p.mine) as Piece;
const ENEMY_KING = POSITION.find((p) => p.glyph === "K" && !p.mine) as Piece;
/** Where the queen lands: next to his king, mate. */
const MATE = { file: 6, rank: 6 };

/** Centre of a square in table space. */
function square(file: number, rank: number): Vec {
  return { x: BOARD_X + file * SQ + SQ / 2, y: rank * SQ + SQ / 2 };
}

/** The elbow between a shoulder and a wrist, on the side that hangs lower (screen). */
function lowElbow(shoulder: Vec, wrist: Vec, a: number, b: number): Vec {
  const one = knee(shoulder, wrist, a, b, 1);
  const other = knee(shoulder, wrist, a, b, -1);
  return one.y >= other.y ? one : other;
}

/** Minimum-jerk: 0..1 with zero velocity and acceleration at both ends. */
function minJerk(u: number): number {
  const x = clamp01(u);
  return x * x * x * (10 - 15 * x + 6 * x * x);
}

/** The camera's vertical position over the table: on her head, down to the board, back up. */
function chessView(t: number): number {
  const down = minJerk((t - C.pan) / (C.panned - C.pan));
  const up = minJerk((t - C.up) / (C.upped - C.up));
  return lerp(lerp(VIEW_HEAD, VIEW_BOARD, down), VIEW_HEAD + 4, up);
}

/** Her reaching hand (table space): where it is, how closed, how high it lifts the piece. */
function chessHand(t: number): { at: Vec; grip: number; lift: number } {
  const rest = { x: 84, y: -6 };
  const queen = square(QUEEN.file, QUEEN.rank);
  const mate = square(MATE.file, MATE.rank);
  // anticipation: a small pull back before the reach
  const pull = Math.sin(clamp01((t - C.reach) / 220) * Math.PI) * 2.5;
  if (t < C.reach + 160) return { at: { x: rest.x + pull * 0.4, y: rest.y - pull }, grip: 0, lift: 0 };
  if (t < C.grip) {
    // the reach: out over the board on a rising arc, down onto the piece
    const u = minJerk((t - C.reach - 160) / (C.grip - C.reach - 160));
    return { at: arc(rest, queen, u, 7), grip: 0, lift: 0 };
  }
  if (t < C.carry) {
    const u = (t - C.grip) / (C.carry - C.grip);
    return { at: queen, grip: clamp01(u * 1.5), lift: minJerk(u) * 0.6 };
  }
  if (t < C.land) {
    // carried on an arc, lifted highest mid-way, accelerating down into the square
    const u = minJerk((t - C.carry) / (C.land - C.carry));
    return { at: arc(queen, mate, u, 9), grip: 1, lift: 0.6 + Math.sin(u * Math.PI) * 0.4 };
  }
  if (t < C.release) {
    // the press: down hard on the square
    const u = (t - C.land) / (C.release - C.land);
    return { at: mate, grip: 1 - clamp01((u - 0.4) * 2.5), lift: Math.max(0, 0.6 - u * 1.6) };
  }
  // away, with a little follow-through: it overshoots its rest and settles
  const u = (t - C.release) / (C.back - C.release);
  return { at: arc(mate, rest, minJerk(u), -6), grip: 0, lift: 0 };
}

/** The hand as it moves: the keyed path through a spring (it overshoots its marks
 *  and settles), and its velocity - the hand drags behind the wrist's motion. */
function chessHandMoving(t: number): { at: Vec; vel: Vec; grip: number; lift: number } {
  const flat = (time: number): { x: number; y: number } => chessHand(time).at;
  const at = follow(flat, t, { x: HAND_SPRING, y: HAND_SPRING });
  const before = follow(flat, t - 40, { x: HAND_SPRING, y: HAND_SPRING });
  const raw = chessHand(t);
  return { at, vel: { x: (at.x - before.x) / 40, y: (at.y - before.y) / 40 }, grip: raw.grip, lift: raw.lift };
}

function piece(frame: Frame, g: Glyph | "fallen", c: Vec, mine: boolean, lift: number, alpha = 1): void {
  const img = GLYPHS[g];
  // lifted: a shadow on the board under it, and the piece a little bigger
  if (lift > 0.05) {
    for (let y = 0; y < 5; y += 1) for (let x = 0; x < 5; x += 1) {
      if (Number.isNaN(img.cells[y * 5 + x])) continue;
      const col = Math.round(c.x - 2.5 + x + lift * 2);
      const row = Math.round(c.y - 2.5 + y + lift * 2);
      if (col >= 0 && col < 128 && row >= 0 && row < ROWS) frame.value[row * 128 + col] *= 0.3;
    }
  }
  const scale = lift > 0.5 ? 2 : 1;
  const ox = c.x - (5 * scale) / 2 - lift * 1.2;
  const oy = c.y - (5 * scale) / 2 - lift * 1.2;
  // a dark keyline first so the piece reads on any square
  for (let y = -1; y <= 5 * scale; y += 1) for (let x = -1; x <= 5 * scale; x += 1) {
    const sx = Math.floor(x / scale);
    const sy = Math.floor(y / scale);
    const inside = sx >= 0 && sy >= 0 && sx < 5 && sy < 5 && !Number.isNaN(img.cells[sy * 5 + sx]);
    if (inside) continue;
    let near = false;
    for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
      const nx = Math.floor((x + dx) / scale);
      const ny = Math.floor((y + dy) / scale);
      if (nx >= 0 && ny >= 0 && nx < 5 && ny < 5 && !Number.isNaN(img.cells[ny * 5 + nx]) && img.cells[ny * 5 + nx] > 0.5) near = true;
    }
    const col = Math.round(ox + x);
    const row = Math.round(oy + y);
    if (near && col >= 0 && col < 128 && row >= 0 && row < ROWS) frame.value[row * 128 + col] *= 1 - alpha;
  }
  blit(frame, img, Math.round(ox), Math.round(oy), { ink: mine ? INK.white : INK.cyan, alpha: alpha * (mine ? 1 : 0.85), scale, fade: FADE.fast });
}

function cShot(frame: Frame, t: number): void {
  const jolt = shake(t, [C.land], 1.4, 280);
  const view = chessView(t) + jolt.y;
  const toScreen = (p: Vec): Vec => ({ x: p.x + jolt.x, y: p.y - view });
  // the room behind her: the study, far and dim
  drawBackdrop(frame, "study", t, { x: 64, y: 140 - view * 0.4, s: 6 });
  // her: the robot behind the table, head over the board (her own arms are drawn
  // reaching, below - long, solved for the board)
  const s = 11;
  const headAt = toScreen({ x: 64, y: HEAD_ROW });
  const lookDown = 1 - minJerk((t - C.up) / (C.upped - C.up));
  const pose: Pose = { ...STAND, head: 0, lean: 0, blink: 0, gaze: 0 };
  const cam = { x: headAt.x, y: headAt.y + 6.25 * s - lookDown * 0.6 * s, s };
  const emotion = t < C.grip ? "focused" : t < C.release + 200 ? "firedUp" : "amused";
  const lamp: Light = { dir: { x: 0.3, y: -1 }, ink: INK.amber, power: 1 };
  drawFigure(frame, pose, BARE, cam, lamp, { emotion, noArms: true });
  // the table and the board, over her chassis
  const tableTop = toScreen({ x: 0, y: -4 }).y;
  for (let r = Math.max(0, Math.floor(tableTop)); r < ROWS; r += 1) {
    for (let c = 0; c < 128; c += 1) {
      const grain = 0.07 + 0.03 * Math.sin(c * 0.35 + Math.sin(r * 0.2) * 2);
      frame.cover(c, r, grain, INK.amber, FADE.scene);
    }
  }
  const bTop = toScreen({ x: BOARD_X, y: 0 });
  const jump = t > C.land && t < C.land + 140 ? 1 : 0;
  // the lamp's pool on the board
  pool(frame, toScreen(square(4, 4)), 70, 46, 0.12, INK.amber);
  for (let rank = 0; rank < 8; rank += 1) {
    for (let file = 0; file < 8; file += 1) {
      const light = (rank + file) % 2 === 0;
      for (let y = 0; y < SQ; y += 1) for (let x = 0; x < SQ; x += 1) {
        const col = Math.round(bTop.x + file * SQ + x);
        const row = Math.round(bTop.y + rank * SQ + y - jump);
        frame.cover(col, row, light ? 0.24 : 0.09, light ? INK.amber : INK.cyan, FADE.scene);
      }
    }
  }
  // the board's frame
  litShape(frame, (x, y) => -box(x, y, { x: bTop.x + SQ * 4, y: bTop.y + SQ * 4 - jump }, SQ * 4, SQ * 4, 0) - 0.01, { x0: bTop.x - 3, y0: bTop.y - 3, x1: bTop.x + SQ * 8 + 3, y1: bTop.y + SQ * 8 + 3 }, { ink: INK.amber, fill: 0.04 }, lamp, 1, false);
  for (const [x0, y0, x1, y1] of [[0, -1, SQ * 8, -1], [0, SQ * 8, SQ * 8, SQ * 8], [-1, 0, -1, SQ * 8], [SQ * 8, 0, SQ * 8, SQ * 8]]) {
    for (let k = 0; k <= Math.max(x1 - x0, y1 - y0); k += 1) {
      frame.cover(Math.round(bTop.x + x0 + (x1 > x0 ? k : 0)), Math.round(bTop.y + y0 + (y1 > y0 ? k : 0) - jump), 0.5, INK.amber, FADE.scene);
    }
  }
  // the pieces (the queen in her hand while it's carried; the king falls at mate)
  const hand = chessHandMoving(t);
  const carrying = t >= C.grip && t < C.release;
  const placed = t >= C.release;
  for (const p of POSITION) {
    if (p === QUEEN && (carrying || placed)) continue;
    const at = toScreen(square(p.file, p.rank));
    const hop = jump && hash(p.file * 8 + p.rank) > 0.4 ? 1 : 0;
    if (p === ENEMY_KING && t >= C.topple) {
      const fall = clamp01((t - C.topple) / 240);
      piece(frame, fall < 0.5 ? "K" : "fallen", { x: at.x + fall * 2, y: at.y - hop }, false, 0);
      continue;
    }
    piece(frame, p.glyph, { x: at.x, y: at.y - hop }, p.mine, 0);
  }
  if (placed) piece(frame, "Q", toScreen(square(MATE.file, MATE.rank)), true, 0);
  // the mate: a ring off the square, a red flicker on his king
  const mateAt = toScreen(square(MATE.file, MATE.rank));
  if (t > C.land && t < C.land + 600) {
    const u = (t - C.land) / 600;
    for (let a = 0; a < 48; a += 1) {
      const ang = (a / 48) * TAU;
      const r = 2 + u * 22;
      frame.lighten(Math.round(mateAt.x + Math.cos(ang) * r), Math.round(mateAt.y + Math.sin(ang) * r), (1 - u) * 0.7, INK.amber, FADE.fast);
    }
  }
  if (t > C.topple && t < C.topple + 500 && Math.floor((t - C.topple) / 90) % 2 === 0) {
    const k = toScreen(square(ENEMY_KING.file, ENEMY_KING.rank));
    for (let y = -4; y <= 4; y += 1) for (let x = -4; x <= 4; x += 1) frame.lighten(Math.round(k.x + x), Math.round(k.y + y), 0.35, INK.red, FADE.fast);
  }
  // her reaching arm: from her shoulder behind the table, solved to the hand
  const shoulder = toScreen({ x: 78, y: -14 });
  const target = toScreen(hand.at);
  const reachLen = 26 + 24;
  const d = Math.min(Math.hypot(target.x - shoulder.x, target.y - shoulder.y), reachLen - 1);
  const dirX = (target.x - shoulder.x) / (Math.hypot(target.x - shoulder.x, target.y - shoulder.y) || 1);
  const dirY = (target.y - shoulder.y) / (Math.hypot(target.x - shoulder.x, target.y - shoulder.y) || 1);
  const wrist = { x: shoulder.x + dirX * d, y: shoulder.y + dirY * d };
  // the elbow out to the side, away from her body
  const elbow = lowElbow(shoulder, wrist, 26, 24);
  // the hand trails the forearm: tipped back against the way the wrist is moving
  const tipX = dirX * 3 - hand.vel.x * 22;
  const tipY = dirY * 3 - hand.vel.y * 22;
  const tipLen = Math.hypot(tipX, tipY) || 1;
  const handAt = { x: target.x + (tipX / tipLen) * 3, y: target.y + (tipY / tipLen) * 3 };
  if (carrying) piece(frame, "Q", { x: handAt.x, y: handAt.y + 1 }, true, hand.lift);
  drawArm(frame, shoulder, elbow, wrist, handAt, 8, lamp, -1, hand.grip);
  // her other hand rests on the table edge, fingers tapping while she thinks
  const tap = t < C.reach ? Math.max(0, Math.sin(t / 110)) * 1.2 : 0;
  const restShoulder = toScreen({ x: 50, y: -14 });
  const restHand = toScreen({ x: 40, y: -2 + tap });
  const restWrist = { x: restHand.x + 2, y: restHand.y - 3 };
  drawArm(frame, restShoulder, lowElbow(restShoulder, restWrist, 9, 9), restWrist, restHand, 8, lamp, 1, 0.3);
  flash(frame, Math.exp(-(t - C.land) / 60) * (t >= C.land ? 0.3 : 0), INK.amber);
}

function cSignature(frame: Frame, t: number, alpha: number): void {
  pool(frame, { x: 64, y: -6 }, 60, 14, 0.2 * alpha, INK.amber);
  // the queen, as a diagram piece, held up beside her face
  const rise = 1 - span(t, CUT, CUT + 380);
  const at = { x: 104, y: 32 + rise * 16 };
  for (let y = -1; y <= 20; y += 1) for (let x = -1; x <= 20; x += 1) {
    const col = Math.round(at.x + x);
    const row = Math.round(at.y + y);
    if (col >= 0 && col < 128 && row >= 0 && row < ROWS) frame.value[row * 128 + col] *= 1 - alpha * 0.9;
  }
  blit(frame, GLYPHS.Q, Math.round(at.x), Math.round(at.y), { ink: INK.white, alpha, scale: 4, fade: FADE.fast });
  motes(frame, t, 8, 31, { x0: 4, y0: 4, x1: 96, y1: 30 }, 0.25 * alpha, INK.amber, -0.002);
}

function cLook(t: number): SceneLook {
  if (t < CUT) return { emotion: "focused", mouth: "hidden" };
  if (t < 4400) return { emotion: "proud", mouth: "smirk", gazeX: 3 };
  return { emotion: "amused", mouth: "smirk", gazeX: 1 };
}

// ---- cards: a stage, one spotlight, a deck turned into a storm ---------------------------
// The spotlight snaps on: she riffles the deck, springs it hand to hand, then flings
// it up - the cards burst into a turning storm around her and fall like leaves; she
// plucks one out of the air and turns it to him. "Is this your card?"

const CARDS_OUTFIT: Outfit = BARE;
const D = { on: 160, riffle: 350, cascade: 1150, dip: 1900, toss: 2150, catch: 3150, push: 3150 };
const STORM = 30;

function dPose(t: number): Pose {
  let p: Pose = { ...STAND, x: 0, aA: -20, eA: 70, aB: 20, eB: -70 };
  const chest = 4.6;
  const L = { x: -0.42, y: chest };
  const R = { x: 0.42, y: chest };
  if (t < D.cascade) {
    // the riffle: thumbs flicking, the hands bobbing together
    const flick = Math.sin(t / 55) * 0.05 * span(t, D.riffle, D.riffle + 100);
    p = grip(p, { x: L.x, y: L.y + flick }, { x: R.x, y: R.y - flick });
  } else if (t < D.dip) {
    // the spring: the right hand lifts high on an arc (anticipating with a small
    // dip first), the deck cascading down into the left
    const u = anticipate((t - D.cascade) / 420);
    const lo = { x: -0.15, y: 3.9 };
    const hi = { x: 0.35, y: 6.2 };
    p = grip(p, arc(L, lo, u, -0.15), arc(R, hi, u, 0.45));
  } else if (t < D.toss) {
    // the wind-up: both hands sink low together, knees bending - the anticipation
    const u = ease((t - D.dip) / (D.toss - 40 - D.dip));
    p = grip({ ...p, y: HIP_H - 0.24 * u, lean: 4 * u }, arc({ x: -0.15, y: 3.9 }, { x: -0.2, y: 3.4 }, u, 0.1), arc({ x: 0.35, y: 6.2 }, { x: 0.2, y: 3.45 }, u, -0.5));
  } else {
    // the toss: both arms fling up and out on wide arcs, overshooting, then settle
    // open as the storm turns; she rises onto her toes with it
    const u = overshoot((t - D.toss) / 260);
    const settle = span(t, D.toss + 450, D.catch - 150);
    const upL = arc({ x: -0.2, y: 3.4 }, { x: -1.3, y: 7.1 }, u, -0.6);
    const upR = arc({ x: 0.2, y: 3.45 }, { x: 1.3, y: 7.1 }, u, 0.6);
    const restL = { x: -0.85, y: 3.6 };
    const restR = { x: 1.0, y: 3.7 };
    p = grip(
      { ...p, y: HIP_H - 0.24 + clamp01(u) * 0.3, lean: -3 * clamp01(u), head: -10 * clamp01(u) + settle * 8 },
      arc(upL, restL, settle, 0.3),
      arc(upR, restR, settle, -0.3),
    );
    if (t > D.catch - 200) {
      // she snaps a hand up and plucks one card out of the air: fast out, overshoot
      const c = overshoot((t - D.catch + 200) / 200);
      const r = reach(p, "B", arc(restR, { x: 1.25, y: 6.3 }, c, 0.35));
      p.aB = r.a;
      p.eB = r.e;
    }
  }
  p.head += span(t, D.push, CUT - 100) * -6;
  return p;
}

function dCam(t: number): Camera {
  const wide = frameOn(0, 3.6, 7.2, 64, 37);
  const storm = frameOn(0, 4.1, 6.3, 64, 37);
  const close = frameOn(0.55, 5.6, 11.5, 58, 33);
  const c = lerpCam(wide, storm, span(t, D.toss - 100, D.toss + 500));
  return lerpCam(c, close, span(t, D.push, CUT - 120));
}

/** One card, standing at c, turned by rot, flipping (flip = cos of its spin). */
function card(frame: Frame, c: Vec, size: number, rot: number, flip: number, light: Light, alpha = 1): void {
  const hw = size * 0.36 * Math.max(0.12, Math.abs(flip));
  const hh = size * 0.5;
  const cs = Math.cos(rot);
  const sn = Math.sin(rot);
  const sdf = (x: number, y: number): number => {
    const lx = (x - c.x) * cs + (y - c.y) * sn;
    const ly = -(x - c.x) * sn + (y - c.y) * cs;
    const qx = Math.abs(lx) - hw + 0.6;
    const qy = Math.abs(ly) - hh + 0.6;
    return Math.hypot(Math.max(qx, 0), Math.max(qy, 0)) + Math.min(Math.max(qx, qy), 0) - 0.6;
  };
  const face = flip >= 0;
  litShape(frame, sdf, { x0: c.x - hh - 2, y0: c.y - hh - 2, x1: c.x + hh + 2, y1: c.y + hh + 2 }, face ? { ink: INK.white, fill: 0.42, rim: 0.85 } : { ink: INK.red, fill: 0.3, rim: 0.7 }, light, alpha, size > 4);
  if (face && size > 3 && Math.abs(flip) > 0.5) frame.cover(Math.round(c.x), Math.round(c.y), 0.9 * alpha, INK.pink, FADE.fast);
}

function stormCard(k: number, t: number, cam: Camera): { at: Vec; rot: number; flip: number } | null {
  const u = (t - D.toss - hash(k) * 120) / 1000;
  if (u < 0) return null;
  // up out of her hands, then round her in a widening spiral, then drifting down
  const rise = Math.min(1, u * 2.2);
  const ang = hash(k * 3) * TAU + u * (2.4 + hash(k * 5) * 1.8);
  const radius = 0.4 + rise * (1.8 + hash(k * 7) * 2.2);
  const height = 3.6 + rise * (2.6 + hash(k * 11) * 2.8) - Math.max(0, u - 0.7) ** 1.6 * 4.2;
  const x = Math.sin(ang) * radius + Math.sin(u * 6 + k) * 0.25 * Math.max(0, u - 0.7);
  const at = place(cam, x, Math.max(0.15, height));
  return { at, rot: u * (3 + hash(k * 13) * 6) + k, flip: Math.cos(u * (9 + hash(k * 17) * 8) + k) };
}

function dShot(frame: Frame, t: number): void {
  const cam = dCam(t);
  drawBackdrop(frame, "stage", t, cam);
  const on = t >= D.on ? 1 : 0;
  const burst = Math.exp(-(((t - D.toss - 250) / 300) ** 2));
  const spot = { x: place(cam, 0, 0).x + 4, y: -8 };
  if (on) {
    lightCone(frame, spot, place(cam, 0, 0), 4.4 * cam.s, (0.16 + burst * 0.12) * Math.min(1, (t - D.on) / 80 + 0.6), INK.white);
    pool(frame, place(cam, 0, 0.05), 2.3 * cam.s, 0.42 * cam.s, 0.45 + burst * 0.2, INK.white);
  }
  const pose = animate(dPose, t);
  const light: Light = { dir: { x: spot.x - place(cam, 0, 4.4).x, y: spot.y - place(cam, 0, 4.4).y }, ink: INK.white, power: on ? 0.95 + burst * 0.3 : 0 };
  const behind: (() => void)[] = [];
  const front: (() => void)[] = [];
  for (let k = 0; k < STORM; k += 1) {
    const c = stormCard(k, t, cam);
    if (!c) continue;
    const depth = Math.cos(hash(k * 3) * TAU + ((t - D.toss) / 1000) * (2.4 + hash(k * 5) * 1.8));
    const keep = 1 - span(t, D.push, D.push + 450);
    if (keep > 0) (depth < 0 ? behind : front).push(() => card(frame, c.at, 0.55 * cam.s, c.rot, c.flip, light, keep));
  }
  for (const f of behind) f();
  groundShadow(frame, cam, 0, 1.2, 0.3);
  const held = (j: Joints): void => {
    // the deck in her hands until the toss; the caught card after
    if (t < D.toss) {
      const flutter = t > D.riffle && t < D.cascade;
      card(frame, j.wristA, 0.55 * cam.s, 0.2, 1, light);
      card(frame, j.wristB, 0.55 * cam.s, -0.2, 1, light);
      if (flutter) {
        for (let k = 0; k < 4; k += 1) {
          const u = ((t / 90 + k / 4) % 1);
          card(frame, { x: lerp(j.wristA.x, j.wristB.x, u), y: lerp(j.wristA.y, j.wristB.y, u) - Math.sin(u * Math.PI) * 2 }, 0.5 * cam.s, (u - 0.5) * 1.5, Math.cos(u * Math.PI * 3), light, 0.8);
        }
      }
      if (t >= D.cascade && t < D.dip) {
        for (let k = 0; k < 9; k += 1) {
          const u = ((t / 420 + k / 9) % 1);
          const p = { x: lerp(j.wristB.x, j.wristA.x, u) + Math.sin(u * Math.PI) * 0.9 * cam.s, y: lerp(j.wristB.y, j.wristA.y, u) };
          card(frame, p, 0.48 * cam.s, 0.4 + u, Math.cos(u * 7), light, 0.9);
        }
      }
    }
  };
  const emotion = t >= D.catch - 50 ? "wink" : t >= D.toss ? "excited" : "happy";
  const j = drawFigure(frame, pose, CARDS_OUTFIT, cam, light, { held, emotion });
  if (t >= D.catch) card(frame, { x: j.handB.x, y: j.handB.y - 0.2 * cam.s }, 0.62 * cam.s, -0.15, 1, light);
  for (const f of front) f();
  // the burst: sparkles flung out with the cards
  sparks(frame, t, D.toss + 80, place(cam, 0, 7.4), 26, 1.0, 21, INK.amber);
  sparks(frame, t, D.catch, place(cam, 1.0, 7.0), 12, 0.5, 33, INK.white);
  if (t < D.on) dim(frame, 0);
}

function dSignature(frame: Frame, t: number, alpha: number): void {
  const light: Light = { dir: { x: 0.3, y: -1 }, ink: INK.white, power: 0.9 };
  pool(frame, { x: 70, y: -10 }, 50, 22, 0.16 * alpha, INK.white);
  // the last cards still falling behind her face
  for (let k = 0; k < 6; k += 1) {
    const u = ((t - CUT) / 1900 + hash(k * 9)) % 1;
    const c = { x: 6 + hash(k) * 30 + Math.sin(u * 7 + k) * 3, y: -8 + u * 86 };
    card(frame, c, 7, u * 4 + k, Math.cos(u * 9 + k), light, alpha * 0.7);
  }
  // the card she caught, held up beside her face
  const rise = 1 - span(t, CUT, CUT + 360);
  const turn = Math.cos(clamp01((t - CUT - 120) / 380) * Math.PI);
  const c = { x: 112, y: 40 + rise * 26 };
  const size = 36;
  const flip = -turn;
  card(frame, c, size, -0.12, flip, light, alpha);
  if (flip > 0.5) {
    // its face: an ace of hearts - the big pip and a corner A
    const heart = (x: number, y: number): number => Math.min(ellipse(x, y, { x: c.x - 2.5, y: c.y - 1.5 }, 3.2, 3.2), ellipse(x, y, { x: c.x + 2.5, y: c.y - 1.5 }, 3.2, 3.2), polygon(x, y, [{ x: c.x - 5.6, y: c.y - 0.5 }, { x: c.x + 5.6, y: c.y - 0.5 }, { x: c.x, y: c.y + 6.5 }]));
    litShape(frame, heart, { x0: c.x - 8, y0: c.y - 7, x1: c.x + 8, y1: c.y + 9 }, { ink: INK.pink, fill: 0.85, rim: 1 }, light, alpha, false);
    const ax = c.x - 9;
    const ay = c.y - 14;
    for (const [x0, y0, x1, y1] of [[ax - 2, ay + 4, ax, ay - 2], [ax, ay - 2, ax + 2, ay + 4], [ax - 1, ay + 2, ax + 1, ay + 2]]) {
      litShape(frame, (x, y) => cone(x, y, { x: x0, y: y0 }, { x: x1, y: y1 }, 0.6, 0.6), { x0: ax - 4, y0: ay - 4, x1: ax + 4, y1: ay + 6 }, { ink: INK.pink, fill: 0.9, rim: 1 }, light, alpha, false);
    }
  }
  // gloved fingertips at its edge
  for (const k of [0, 1, 2]) litShape(frame, (x, y) => cone(x, y, { x: 99, y: 50 + k * 5 + rise * 26 }, { x: 104, y: 50 + k * 5 + rise * 26 }, 1.8, 1.6), { x0: 94, y0: 44, x1: 108, y1: 71 }, { ink: INK.white, fill: 0.32, rim: 0.6 }, light, alpha);
}

function dLook(t: number): SceneLook {
  if (t < CUT) return { emotion: "happy", mouth: "smirk" };
  if (t > 4520 && t < 5000) return { emotion: "wink", mouth: "smirk", gazeX: 2 };
  return { emotion: "happy", mouth: "smirk", gazeX: 2 };
}

// ---- energy wave: dusk on open ground, a charge that lights her up, then the beam ------
// Wind across the plain; she drops into a wide stance and cups her hands at her hip;
// a ball of light grows there, lighting her from below while the ground cracks and
// stones lift; a breath held - then she drives it forward and the beam crosses the
// whole sky (flash, shake, her hair thrown back). It thins to a thread and is gone.

const WAVE: Outfit = BARE;
const W = { stance: 450, charge: 950, hold: 2300, fire: 2450, fade: 3250, gone: 3550, push: 3450 };
const WX = -3.1;

const wStand: Pose = { ...STAND, x: WX, turn: 0.85, fAx: WX - 0.25, fBx: WX + 0.3 };
const wStance: Pose = { ...wStand, y: 2.62, lean: 6, fAx: WX - 1.05, fBx: WX + 0.95, head: -4 };
const wTrack: Track = resolve(
  [
    { t: 0, p: wStand },
    { t: W.stance, p: wStand },
    { t: W.charge, p: wStance, e: "out" },
    { t: W.hold, p: { lean: 3, y: 2.56 } },
    { t: W.fire - 20, p: { lean: -5, y: 2.52 }, e: "in" },
    { t: W.fire + 80, p: { lean: 14, x: WX - 0.15, fAx: WX - 1.35 }, e: "snap" },
    { t: W.fade, p: { lean: 11, x: WX - 0.35, fAx: WX - 1.55, fBx: WX + 0.8 } },
    { t: W.gone + 200, p: { lean: 2, y: 3.1, x: WX - 0.3, fAx: WX - 0.75, fBx: WX + 0.3, head: 0 } },
    { t: CUT, p: { turn: 0.3, head: -6, lean: -1, y: HIP_H } },
  ],
  wStand,
);

function wBall(t: number): { at: Vec; r: number } {
  const p = sample(wTrack, t);
  const grow = span(t, W.charge, W.hold);
  const squeeze = 1 - 0.25 * span(t, W.hold, W.fire - 20);
  return { at: { x: p.x - 0.75, y: 3.25 }, r: (0.12 + grow * 0.55) * squeeze };
}

function wPose(t: number): Pose {
  const p = sample(wTrack, t);
  const back = span(t, W.stance, W.charge);
  const fire = 1 - (1 - clamp01((t - W.fire + 20) / 110)) ** 3;
  const rest = span(t, W.gone, CUT - 100);
  const ball = wBall(t).at;
  const cupA = { x: ball.x - 0.05, y: ball.y - 0.35 };
  const cupB = { x: ball.x + 0.08, y: ball.y + 0.35 };
  const pushA = { x: p.x + 1.95, y: 4.4 };
  const pushB = { x: p.x + 2.05, y: 4.7 };
  const side = { x: p.x - 0.3, y: 2.9 };
  const mix = (a: Vec, b: Vec, u: number): Vec => ({ x: lerp(a.x, b.x, u), y: lerp(a.y, b.y, u) });
  if (t < W.stance) return { ...p, sway: 0.18 + Math.sin(t / 260) * 0.12 };
  const a = mix(mix(mix({ x: p.x - 0.5, y: 2.9 }, cupA, back), pushA, fire), side, rest);
  const b = mix(mix(mix({ x: p.x + 0.4, y: 3.0 }, cupB, back), pushB, fire), { x: p.x + 0.35, y: 2.95 }, rest);
  const out = grip(p, a, b);
  // the wind, and the beam's blast throwing her hair and dress back
  out.sway += 0.18 + Math.sin(t / 260) * 0.12 - 0.9 * fire * (1 - span(t, W.fade, W.gone));
  return out;
}

function wCam(t: number): Camera {
  const wide = frameOn(0, 3.5, 6.3, 64, 40);
  const low = frameOn(-1.2, 3.6, 7.6, 60, 42);
  const her = frameOn(WX + 0.1, 5.4, 10.5, 60, 33);
  const c = lerpCam(wide, low, span(t, W.stance, W.hold));
  return lerpCam(c, her, span(t, W.push, CUT - 120));
}

function wShot(frame: Frame, t: number): void {
  const charge = span(t, W.charge, W.hold);
  const jolt = shake(t, [W.fire], 2.6, 650);
  const rumble = charge > 0.5 && t < W.fire ? (charge - 0.5) * 0.9 : 0;
  const base = wCam(t);
  const cam = { ...base, x: base.x + jolt.x + Math.sin(t / 31) * rumble, y: base.y + jolt.y + Math.cos(t / 27) * rumble * 0.6 };
  drawBackdrop(frame, "ground", t, cam);
  const pose = animate(wPose, t);
  const ball = wBall(t);
  const ballAt = place(cam, ball.at.x, ball.at.y);
  const firing = t >= W.fire && t < W.gone;
  const beamK = firing ? Math.min(1, (t - W.fire) / 60) * (1 - span(t, W.fade, W.gone)) : 0;
  // the ground cracks under her, glowing
  if (charge > 0.2 && t < W.gone + 300) {
    const k = clamp01((charge - 0.2) * 1.4) * (1 - span(t, W.fade, W.gone + 300));
    for (let n = 0; n < 6; n += 1) {
      let p = place(cam, WX + (hash(n) - 0.5) * 0.6, 0);
      const ang = (hash(n * 3) - 0.5) * 2.6;
      for (let s = 0; s < 14 * k; s += 1) {
        p = { x: p.x + Math.cos(ang + Math.sin(s + n) * 0.6) * 1.3 * Math.sign(hash(n * 5) - 0.5), y: p.y + 0.25 };
        frame.lighten(Math.round(p.x), Math.round(p.y), 0.55 * k, INK.iceRing, FADE.fast);
      }
    }
    // stones and dust lifting off the ground around her
    motes(frame, t, 22, 3, { x0: place(cam, WX - 3, 0).x, y0: place(cam, 0, 4.5).y, x1: place(cam, WX + 3, 0).x, y1: place(cam, 0, 0).y }, 0.5 * k, INK.white, -0.012 * (0.5 + charge));
  }
  groundShadow(frame, cam, pose.x, 1.5, 0.3);
  const light: Light = t < W.charge ? { dir: { x: -1, y: -0.2 }, ink: INK.amber, power: 0.55 } : toward(place(cam, pose.x, 5), firing ? place(cam, pose.x + 3, 5.4) : ballAt, INK.iceCore, 0.6 + charge * 0.6 + beamK * 0.4);
  const held = (): void => {
    if (t >= W.charge && t < W.fire + 40) {
      // the ball: a white core in an ice-blue glow, crackling
      const r = ball.r * cam.s;
      glow(frame, ballAt, Math.max(1, r), 1, INK.iceRing, INK.iceCore);
      for (let k = 0; k < 4; k += 1) {
        if (hash(Math.floor(t / 70) * 7 + k) < 0.45) continue;
        let p = { ...ballAt };
        const ang = hash(Math.floor(t / 70) + k * 13) * TAU;
        for (let s = 0; s < 4 + charge * 6; s += 1) {
          p = { x: p.x + Math.cos(ang + (hash(s + k) - 0.5) * 1.6) * 1.4, y: p.y + Math.sin(ang + (hash(s * 3 + k) - 0.5) * 1.6) * 1.4 };
          frame.lighten(Math.round(p.x), Math.round(p.y), 0.7, INK.iceCore, FADE.fast);
        }
      }
    }
  };
  const emotion = t < W.charge ? "happy" : t < W.gone ? "firedUp" : "proud";
  const j = drawFigure(frame, pose, WAVE, cam, light, { held, emotion, eyes: charge > 0.4 ? INK.iceRing : INK.cyan });
  if (beamK > 0) {
    // the beam: from her palms to past the edge of the frame, a white core and a
    // wide ice-blue body, rippling
    const from = { x: (j.handA.x + j.handB.x) / 2, y: (j.handA.y + j.handB.y) / 2 };
    const width = (0.55 + 0.45 * Math.min(1, (t - W.fire) / 200)) * beamK * cam.s * 1.15;
    for (let x = Math.floor(from.x); x < 128; x += 1) {
      const d = x - from.x;
      const swell = Math.min(1, d / 6 + 0.3);
      const wob = Math.sin(x / 3 - t / 30) * 0.6;
      const half = width * swell + wob;
      for (let y = Math.floor(from.y - half - 3); y <= Math.ceil(from.y + half + 3); y += 1) {
        const dy = Math.abs(y + 0.5 - from.y);
        if (dy > half + 3) continue;
        if (dy < half * 0.45) frame.cover(x, y, 1, INK.iceCore, FADE.fast);
        else if (dy < half) frame.cover(x, y, 0.85, INK.iceRing, FADE.fast);
        else frame.lighten(x, y, 0.45 * (1 - (dy - half) / 3), INK.iceRing, FADE.fast);
      }
    }
    glow(frame, from, width * 0.9, 1, INK.iceRing, INK.iceCore);
    // the blast throws dust back along the ground
    for (let k = 0; k < 16; k += 1) {
      const u = ((t - W.fire) / 500 + hash(k)) % 1;
      const x = from.x - 4 - u * 60;
      const y = cam.y - hash(k * 5) * 10 * (1 - u) - 1;
      frame.lighten(Math.round(x), Math.round(y), 0.5 * (1 - u) * beamK, INK.white, FADE.fast);
      frame.lighten(Math.round(x + 1), Math.round(y), 0.3 * (1 - u) * beamK, INK.white, FADE.fast);
    }
  }
  // embers when it's gone
  if (t > W.fade) motes(frame, t, 14, 51, { x0: place(cam, WX, 0).x, y0: 8, x1: 127, y1: place(cam, 0, 4).y }, 0.45 * (1 - span(t, W.gone + 300, CUT)), INK.iceCore, -0.01);
  sparks(frame, t, W.gone - 80, place(cam, WX + 6, 5.5), 18, 1.2, 77, INK.iceCore);
  flash(frame, Math.exp(-(t - W.fire) / 60) * (t >= W.fire ? 0.34 : 0), INK.iceCore);
}

function wSignature(frame: Frame, t: number, alpha: number): void {
  // the last of the energy coming off her: rising sparks, a glow beneath, a thread of
  // light still crossing the frame behind her
  pool(frame, { x: 64, y: 80 }, 70, 22, 0.25 * alpha, INK.iceRing);
  motes(frame, t, 26, 61, { x0: 0, y0: 30, x1: 127, y1: 71 }, 0.55 * alpha, INK.iceCore, -0.016);
}

function wLook(t: number): SceneLook {
  if (t < CUT) return { emotion: "firedUp", mouth: "hidden" };
  if (t < 4700) return { emotion: "firedUp", mouth: "smirk", eyeInk: INK.iceRing };
  return { emotion: "happy", mouth: "smirk" };
}

// ---- registry ---------------------------------------------------------------------

export interface Entrance {
  /** Length on the matrix, ms; core's clip and config/entrances.json agree. */
  ms: number;
  /** The place it happens (led/backdrops.ts). */
  backdrop: BackdropName;
  look: (t: number) => SceneLook;
  draw: (frame: Frame, t: number) => void;
}

export const ENTRANCES = {
  victorian: { ms: ENTRANCE_MS, backdrop: "gaslight", look: vicLook, draw: (f: Frame, t: number) => film(f, t, vicShot, vicSignature) },
  kendo: { ms: ENTRANCE_MS, backdrop: "dojo", look: kLook, draw: (f: Frame, t: number) => film(f, t, kShot, kSignature) },
  chess: { ms: ENTRANCE_MS, backdrop: "study", look: cLook, draw: (f: Frame, t: number) => film(f, t, cShot, cSignature) },
  cards: { ms: ENTRANCE_MS, backdrop: "stage", look: dLook, draw: (f: Frame, t: number) => film(f, t, dShot, dSignature) },
  energy_wave: { ms: ENTRANCE_MS, backdrop: "ground", look: wLook, draw: (f: Frame, t: number) => film(f, t, wShot, wSignature) },
} satisfies Record<string, Entrance>;

export type EntranceName = keyof typeof ENTRANCES;

export const ENTRANCE_NAMES = Object.keys(ENTRANCES) as EntranceName[];

export function isEntrance(name: unknown): name is EntranceName {
  return typeof name === "string" && name in ENTRANCES;
}

export function entranceActive(name: EntranceName, elapsed: number): boolean {
  return elapsed >= 0 && elapsed < ENTRANCES[name].ms;
}

export function entranceLook(name: EntranceName, elapsed: number): SceneLook {
  const entrance: Entrance = ENTRANCES[name];
  return entrance.look(Math.max(0, elapsed));
}

export function drawEntrance(frame: Frame, name: EntranceName, elapsed: number): void {
  const entrance: Entrance = ENTRANCES[name];
  entrance.draw(frame, Math.max(0, elapsed));
}

