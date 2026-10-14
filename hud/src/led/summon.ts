// The domain-expansion sequence, keyed to the summon clip as heard. Core sends
// summon/start as the clip begins and summon/part2 as "Irene Adler" starts; the
// HUD stamps each on arrival and this draws from those stamps.
//
//   start   a dark visor band slides across both eyes; her right hand rises into
//           the crossed index/middle sign and holds it for the whole sequence
//   part2   her left hand hooks the band's lower edge and lifts it off ONE eye:
//           the band pivots on its right end and stays tilted over the other.
//           The revealed eye burns ice-blue - white-blue core, deeper ring, a
//           sharp highlight, a faint shimmer around it
//   +hold   ~1.5 s, then band, hands and ice fade; both eyes return to cyan

import type { Emotion } from "../face/faceState";
import { EYE_H, EYE_W, EYE_Y, LEFT_EYE_X, RIGHT_EYE_X } from "./face";
import { COLS, FADE, INK, ROWS, clamp01, ease, easeOutBack, lerp } from "./grid";
import type { Frame, Ink } from "./grid";
import { HANDS, drawHand } from "./hands";
import { polygon } from "./figure";

export interface SummonTimes {
  /** performance.now() when summon/start arrived. */
  start: number;
  /** When summon/part2 arrived, once it has. */
  part2: number | null;
  /** How long the revealed eye holds (ms) - a skit line's own; the summon's is HOLD_MS. */
  hold?: number;
  /** A skit line's speech bubble, snapping in on the reveal (led/bubble.ts). */
  bubble?: string;
}

const BAND_IN_MS = 380;
const SIGN_DELAY_MS = 160;
const SIGN_RISE_MS = 620;
const HOOK_IN_MS = 220;
const LIFT_MS = 450;
const HOLD_MS = 1500;
const FADE_MS = 500;
/** After part2, how long the summon's sequence keeps drawing. */
export const SUMMON_TAIL_MS = HOOK_IN_MS + LIFT_MS + HOLD_MS + FADE_MS + 60;
/** After part2, how long THIS sequence keeps drawing (a skit line holds longer). */
export function summonTail(times: SummonTimes): number {
  return HOOK_IN_MS + LIFT_MS + (times.hold ?? HOLD_MS) + FADE_MS + 60;
}
/** After part2, when the eye is at full burn: the impact, the speech bubble. */
export const REVEAL_MS = HOOK_IN_MS + LIFT_MS * 0.75;

// the band: centred on the face, exactly over both eyes with an equal margin each
// side. Its right end is pinned, so lifting it off the left eye tilts it up and
// leaves it lying across the right one.
const BAND_MARGIN = 6;
const BAND_X0 = LEFT_EYE_X - BAND_MARGIN;
const BAND_X1 = RIGHT_EYE_X + EYE_W + BAND_MARGIN;
const PIVOT = { x: BAND_X1, y: EYE_Y + EYE_H / 2 };
const BAND_LENGTH = BAND_X1 - BAND_X0;
const BAND_HALF = EYE_H / 2 + 4.5; // the eye rows plus a margin above and below
const TILT_DEG = 26; // enough to clear the left eye, not so much it leaves the right
// where the left hand grabs: the band's lower-left corner, just outside the left
// eye, so lifting it never puts the hand over the eye it reveals
const HOOK_ALONG = PIVOT.x - (LEFT_EYE_X - 2);
const SIGN = { x: 106, restY: 44, awayY: 96 };

interface Phase {
  across: number; // band slid in, 0..1
  hook: number; // left hand arriving at the edge, 0..1
  lift: number; // band tilt, 0..1
  fade: number; // whole sequence's opacity, 1 -> 0 at the end
}

function phase(times: SummonTimes, now: number): Phase {
  const across = ease((now - times.start) / BAND_IN_MS);
  if (times.part2 === null) return { across, hook: 0, lift: 0, fade: 1 };
  const t = now - times.part2;
  const hook = easeOutBack(t / HOOK_IN_MS);
  const lift = ease((t - HOOK_IN_MS) / LIFT_MS);
  const fade = 1 - ease((t - HOOK_IN_MS - LIFT_MS - (times.hold ?? HOLD_MS)) / FADE_MS);
  return { across, hook, lift, fade };
}

export interface SummonLook {
  /** Eyes open and round for the reveal, whatever mood core has set. */
  emotion?: Emotion;
  /** No blinking under the visor - a blink would show through as nothing. */
  steady: boolean;
}

export function summonLook(times: SummonTimes, now: number): SummonLook {
  if (times.part2 === null) return { steady: true };
  const p = phase(times, now);
  return { steady: p.fade > 0.5, emotion: p.fade > 0.05 ? "neutral" : undefined };
}

/** Band-local (u along, v across) -> world, for the band tilted by `deg`. */
function toWorld(u: number, v: number, deg: number): { x: number; y: number } {
  const r = (deg * Math.PI) / 180;
  const c = Math.cos(r);
  const s = Math.sin(r);
  return { x: PIVOT.x + u * c - v * s, y: PIVOT.y + u * s + v * c };
}

function drawBand(frame: Frame, p: Phase, now: number, times: SummonTimes): void {
  const r = (TILT_DEG * p.lift * Math.PI) / 180;
  const c = Math.cos(r);
  const s = Math.sin(r);
  const length = BAND_LENGTH * p.across;
  const alpha = p.fade;
  if (alpha <= 0.01 || length < 1) return;
  // the light that scans inside the band while it's down - only until the reveal
  const scanU = -BAND_LENGTH + (((now - times.start) / 900) % 1) * BAND_LENGTH;
  const scanOn = times.part2 === null ? 1 : 0;
  for (let y = 0; y < ROWS; y += 1) {
    for (let x = 0; x < COLS; x += 1) {
      const dx = x + 0.5 - PIVOT.x;
      const dy = y + 0.5 - PIVOT.y;
      const u = dx * c + dy * s;
      const v = -dx * s + dy * c;
      if (u > 0.5 || u < -length - 0.5 || Math.abs(v) > BAND_HALF + 0.5) continue;
      const edge = Math.abs(v) > BAND_HALF - 0.6 || u < -length + 0.6;
      const lead = p.across < 1 && u < -length + 1.5;
      let level: number;
      let ink: Ink;
      if (lead) {
        level = 0.9;
        ink = INK.white;
      } else if (edge) {
        level = 0.55;
        ink = INK.white;
      } else {
        // a solid body: dim slate cells with faint visor slats, plus the scan light
        const slat = Math.round(v + BAND_HALF) % 3 === 0 ? 0.27 : 0.19;
        const scan = Math.max(0, 1 - Math.abs(u - scanU) / 5) * 0.4 * scanOn;
        level = Math.max(scan, slat);
        ink = scan > slat ? INK.red : INK.white;
      }
      const i = y * COLS + x;
      frame.value[i] = frame.value[i] * (1 - alpha) + level * alpha;
      if (alpha > 0.5) frame.ink[i] = ink;
      frame.fade[i] = FADE.fast;
    }
  }
}

/**
 * The revealed eye, drawn as its own glowing disc over the left eye's place -
 * independent of the eye art and of anything under it - so it is always ice-blue:
 * a bright white-blue core, a slightly darker ring, a small sharp highlight and a
 * faint shimmer of cells around it.
 */
function iceEye(frame: Frame, glow: number, now: number): void {
  if (glow <= 0.02) return;
  const cx = LEFT_EYE_X + EYE_W / 2;
  const cy = EYE_Y + EYE_H / 2;
  const radius = EYE_W / 2 - 0.5;
  // the cyan eye art is a rounded square, larger than the disc: put its corners out
  for (let y = EYE_Y; y < EYE_Y + EYE_H; y += 1) {
    for (let x = LEFT_EYE_X; x < LEFT_EYE_X + EYE_W; x += 1) {
      const i = y * COLS + x;
      if (frame.ink[i] === INK.accent) frame.value[i] *= 1 - glow;
    }
  }
  for (let y = Math.floor(cy - radius - 1); y <= Math.ceil(cy + radius + 1); y += 1) {
    for (let x = Math.floor(cx - radius - 1); x <= Math.ceil(cx + radius + 1); x += 1) {
      if (x < 0 || x >= COLS || y < 0 || y >= ROWS) continue;
      const d = Math.hypot(x + 0.5 - cx, y + 0.5 - cy) / radius;
      if (d > 1.08) continue;
      const core = d < 0.58;
      // soft rim so the disc isn't a hard-edged block
      const edge = d > 0.92 ? Math.max(0, (1.08 - d) / 0.16) : 1;
      const level = (core ? 1 : 0.72) * edge;
      const i = y * COLS + x;
      frame.value[i] = frame.value[i] * (1 - glow) + level * glow;
      if (glow > 0.3) frame.ink[i] = core ? INK.iceCore : INK.iceRing;
      frame.fade[i] = FADE.fast;
    }
  }
  // a small sharp highlight inside the core, upper left - added light, never a hole
  for (const [hx, hy] of [[-3, -4], [-2, -4], [-3, -3], [-2, -3]] as const) {
    frame.lighten(Math.floor(cx + hx), Math.floor(cy + hy), glow, INK.white, FADE.fast);
  }
  // faint shimmer round the eye: each cell breathing slowly in and out (never a blink)
  for (let k = 0; k < 28; k += 1) {
    const on = 0.5 + 0.5 * Math.sin(now / 420 + k * 1.9);
    const angle = (k / 28) * Math.PI * 2;
    const reach = radius + 2 + ((k * 7) % 4);
    const level = (0.06 + on * 0.2) * glow;
    frame.lighten(Math.round(cx + Math.cos(angle) * reach), Math.round(cy + Math.sin(angle) * reach), level, INK.iceRing, FADE.fast);
  }
  // the iris: six bright spokes turning slowly through the ring - the eye is alive
  const turn = now / 650;
  for (let k = 0; k < 6; k += 1) {
    const a = turn + (k / 6) * Math.PI * 2;
    for (let d = radius * 0.6; d <= radius * 0.95; d += 0.5) {
      frame.lighten(Math.round(cx - 0.5 + Math.cos(a) * d), Math.round(cy - 0.5 + Math.sin(a) * d), 0.9 * glow, INK.iceCore, FADE.fast);
    }
  }
  // a halo ring breathing just outside it, and three sparks orbiting the halo
  const halo = radius + 3;
  const breathe = 0.35 + 0.25 * Math.sin(now / 280);
  for (let a = 0; a < 96; a += 1) {
    const ang = (a / 96) * Math.PI * 2;
    frame.lighten(Math.round(cx - 0.5 + Math.cos(ang) * halo), Math.round(cy - 0.5 + Math.sin(ang) * halo), breathe * glow, INK.iceRing, FADE.fast);
  }
  for (let k = 0; k < 3; k += 1) {
    const ang = now / 420 + (k / 3) * Math.PI * 2;
    const sx = Math.round(cx - 0.5 + Math.cos(ang) * (halo + 1.5));
    const sy = Math.round(cy - 0.5 + Math.sin(ang) * (halo + 1.5));
    frame.lighten(sx, sy, glow, INK.white, FADE.fast);
    frame.lighten(sx + 1, sy, 0.5 * glow, INK.iceCore, FADE.fast);
  }
  // a lens-flare streak through the eye, flaring at the reveal and then glinting
  const streak = (0.35 + 0.3 * Math.max(0, Math.sin(now / 520))) * glow;
  for (let d = radius + 1; d < radius + 16; d += 1) {
    const fall = 1 - (d - radius) / 16;
    frame.lighten(Math.round(cx - 0.5 + d), Math.round(cy - 0.5), streak * fall, INK.iceCore, FADE.fast);
    frame.lighten(Math.round(cx - 0.5 - d), Math.round(cy - 0.5), streak * fall, INK.iceCore, FADE.fast);
  }
}

export function drawSummon(frame: Frame, times: SummonTimes, now: number): void {
  const p = phase(times, now);
  drawBand(frame, p, now, times);

  // the crossed-finger sign: rises with the band and holds to the end
  const rise = easeOutBack((now - times.start - SIGN_DELAY_MS) / SIGN_RISE_MS);
  const signY = lerp(SIGN.awayY, SIGN.restY, rise);
  if (signY < SIGN.awayY - 0.5 && p.fade > 0.01) {
    const tremble = times.part2 === null ? Math.sin(now * 0.05) * 0.4 : 0;
    drawHand(frame, HANDS.crossed, { x: SIGN.x + tremble, y: signY, rot: 4, scale: 1.45, alpha: p.fade, fade: FADE.fast });
  }

  if (times.part2 === null) return;

  // the revealed eye before the hand, so the hand's fingers stay in front of it
  iceEye(frame, clamp01((p.lift - 0.35) / 0.4) * p.fade, now);

  // the left hand hooks the band's lower-left corner and lifts it
  const deg = TILT_DEG * p.lift;
  const r = (deg * Math.PI) / 180;
  const normal = { x: -Math.sin(r), y: Math.cos(r) };
  const edge = toWorld(-HOOK_ALONG, BAND_HALF, deg);
  const reach = lerp(20, 5, clamp01(p.hook));
  if (p.fade > 0.01) {
    drawHand(frame, HANDS.hook, {
      x: edge.x + normal.x * reach,
      y: edge.y + normal.y * reach,
      rot: deg - 8,
      scale: 1.05,
      mirror: true,
      alpha: p.fade * clamp01(p.hook * 1.5),
      fade: FADE.fast,
    });
  }
}

// ---- energy burst -------------------------------------------------------------
// Behind her head as the band lifts: short rays, sparks and one expanding ring in
// ice-blue and cyan, peaking with the eye reveal and gone about a second later.
// Drawn before the face and only outside an oval around it, so it reads as
// coming from behind her head and never lands on the revealed eye.

const HEAD = { x: COLS / 2, y: 33, rx: 42, ry: 30 };
const BURST_RISE = { from: 120, peak: HOOK_IN_MS + LIFT_MS * 0.75 }; // ms after part2
const BURST_FADE_MS = 1000;
const RAYS = 18;
const SPARKS = 40;

function outsideHead(x: number, y: number): number {
  // >0 outside the oval, in rough cell units
  return (Math.hypot((x - HEAD.x) / HEAD.rx, (y - HEAD.y) / HEAD.ry) - 1) * Math.min(HEAD.rx, HEAD.ry);
}

function hash(n: number): number {
  const s = Math.sin(n * 127.1 + 311.7) * 43758.5453;
  return s - Math.floor(s);
}

// ---- the domain: a black hole behind her, white hair -----------------------------
// For the domain expansion she gets spiky white hair - a crown of swept spikes over
// the top of her head, blue strands through it, the visor sliding across under it -
// and behind her a black hole: a great ring of white light round her head, a violet
// glow, dark blots eating into the ring as it turns, violet specks drifting. Both
// swell in as the visor arrives and go with the sequence; nothing flashes.

/** How present the domain is: swelling in from the start, gone with the fade. */
function domainLevel(times: SummonTimes, now: number): number {
  return ease((now - times.start) / 700) * phase(times, now).fade;
}

const HOLE = { x: COLS / 2, y: 26, r: 57 };

/** The black hole, behind her face. */
function drawBlackHole(frame: Frame, times: SummonTimes, now: number): void {
  const k = domainLevel(times, now);
  if (k <= 0.01) return;
  const t = now - times.start;
  const r = lerp(36, HOLE.r, ease(t / 900));
  const spin = t / 2600;
  for (let y = 0; y < ROWS; y += 1) {
    for (let x = 0; x < COLS; x += 1) {
      const dx = x + 0.5 - HOLE.x;
      const dy = y + 0.5 - HOLE.y;
      const d = Math.hypot(dx, dy);
      const ang = Math.atan2(dy, dx);
      // dark blots eating into the ring, turning slowly with it
      const blot = Math.sin(ang * 5 + spin * 2.1) * Math.sin(ang * 3 - spin * 1.3);
      const eaten = blot > 0.45 ? clamp01((blot - 0.45) / 0.25) : 0;
      const ring = Math.exp(-(((d - r) / 1.6) ** 2));
      const halo = Math.exp(-(((d - r) / 6) ** 2)) * 0.35;
      // inside: the faint violet of the singularity, deepening toward the ring
      const inner = d < r ? 0.1 * (d / r) ** 3 : 0;
      // behind her head: the ring shows above and round it, its lower half hidden
      // behind her face (it dissolves away below her eyes)
      const behind = 1 - ease((y - 42) / 18);
      // the accretion disk: spiral arms wound into the ring, turning with it
      const arm = Math.cos(2 * ang - 6 * Math.log(Math.max(d, 1) / r) - spin * 5);
      const disk = d > r * 0.45 && d < r * 1.35 ? clamp01((arm - 0.55) / 0.45) * 0.32 * Math.exp(-(((d - r) / (r * 0.4)) ** 2)) : 0;
      // a hot spot racing round the photon ring
      const hot = ring > 0.4 ? Math.max(0, Math.cos(ang - spin * 3.2)) ** 6 * 0.55 : 0;
      // gravitational lensing: faint ripples rolling outward from the ring
      const wave = ((t / 1500) % 1) * 30;
      const ripple = d > r ? Math.exp(-(((d - r - wave) / 1.2) ** 2)) * 0.16 * (1 - wave / 30) : 0;
      const level = (ring * (1 - eaten * 0.9) * 0.75 + halo * (1 - eaten * 0.6) + inner + disk + hot + ripple) * k * behind;
      if (level < 0.02) continue;
      frame.lighten(x, y, level, (ring > 0.5 && eaten < 0.3) || hot > 0.25 ? INK.white : INK.violet, FADE.fast);
    }
  }
  // violet specks spiralling IN to the ring - the hole is eating them (continuous: no twinkle)
  for (let i = 0; i < 46; i += 1) {
    const fall = (hash(i * 3 + 1) * 28 + t * 0.006) % 28;
    const a = hash(i + 7) * Math.PI * 2 + spin * 0.6 + fall * 0.09;
    const out = r + 3 + (28 - fall);
    const sx = HOLE.x + Math.cos(a) * out * 1.15;
    const sy = HOLE.y + Math.sin(a) * out * 0.8;
    const level = k * (0.25 + 0.2 * Math.sin(t / 700 + i));
    frame.lighten(Math.round(sx), Math.round(sy), level, INK.violet, FADE.fast);
    if (hash(i * 5) > 0.6) frame.lighten(Math.round(sx) + 1, Math.round(sy), level * 0.6, INK.violet, FADE.fast);
  }
}

/** How far her face moves down for the domain (rows), to make room for her hair
 *  above it - eased in with the domain, back up as it goes. */
export const DOMAIN_DROP = 8;

export function domainShift(times: SummonTimes, now: number): number {
  return Math.round(DOMAIN_DROP * domainLevel(times, now));
}

/** One spike of hair: from its root on the hairline, swept, to its tip. */
interface Spike {
  x: number;
  len: number;
  width: number;
  lean: number;
}

// a row of spikes across the top of her head - and only the top: none down her sides
const SPIKES: Spike[] = Array.from({ length: 9 }, (_, i) => {
  const u = (i - 4) / 4;
  return {
    x: COLS / 2 + u * 40,
    len: 8 + (1 - Math.abs(u)) * 3 + hash(i + 3) * 2,
    width: 9 - Math.abs(u) * 1.5,
    // they fan out: the outer ones lean away from the middle
    lean: u * 0.55 + (hash(i + 11) - 0.5) * 0.25,
  };
});
/** The hairline: just above her (lowered) visor. */
const HAIRLINE = 16;

/** Her white hair, across the top of the matrix above her lowered face. */
export function drawDomainHair(frame: Frame, times: SummonTimes, now: number): void {
  const k = domainLevel(times, now);
  if (k <= 0.01) return;
  const t = now - times.start;
  const grow = ease(t / 650);
  const sway = Math.sin(t / 900) * 0.04;
  const put = (x: number, y: number, level: number, ink: Ink): void => {
    if (x < 0 || x >= COLS || y < 0 || y >= ROWS) return;
    const i = y * COLS + x;
    frame.value[i] = frame.value[i] * (1 - k) + level * k;
    frame.ink[i] = ink;
    frame.fade[i] = FADE.fast;
  };
  // the mass: a cap over the top, from the hairline up to the top edge, rounded at
  // its ends so it sits on her head rather than across the screen
  const capW = 48;
  for (let y = 0; y <= HAIRLINE; y += 1) {
    for (let x = Math.round(COLS / 2 - capW); x <= Math.round(COLS / 2 + capW); x += 1) {
      const u = (x + 0.5 - COLS / 2) / capW;
      const bottom = HAIRLINE - 6 * u * u;
      // a band at the hairline, rounded at its ends: the spikes rise off its top
      const capTop = bottom - 6 + 3 * u * u;
      if (y + 0.5 > bottom || y + 0.5 < capTop || Math.abs(u) > 1) continue;
      put(x, y, y + 1.5 > bottom ? 0.6 : 0.85, INK.white);
    }
  }
  // the spikes, rising off it and out of the top of the screen
  const shapes: { pts: { x: number; y: number }[]; root: { x: number; y: number }; tip: { x: number; y: number } }[] = [];
  for (const sp of SPIKES) {
    const u = (sp.x - COLS / 2) / capW;
    const root = { x: sp.x, y: HAIRLINE - 6 * u * u - 3 };
    const lean = sp.lean + sway;
    const len = sp.len * grow;
    // tips stay inside the frame: the silhouette reads against the dark above it
    const tip = { x: root.x + Math.sin(lean) * len * 1.1, y: Math.max(0.5, root.y - Math.cos(lean) * len) };
    const half = sp.width / 2;
    shapes.push({ pts: [{ x: root.x - half, y: root.y + 2 }, tip, { x: root.x + half, y: root.y + 2 }], root, tip });
  }
  for (const sh of shapes) {
    const xs = sh.pts.map((p) => p.x);
    const ys = sh.pts.map((p) => p.y);
    for (let y = Math.max(0, Math.floor(Math.min(...ys))); y <= Math.min(ROWS - 1, Math.ceil(Math.max(...ys))); y += 1) {
      for (let x = Math.max(0, Math.floor(Math.min(...xs))); x <= Math.min(COLS - 1, Math.ceil(Math.max(...xs))); x += 1) {
        const d = polygon(x + 0.5, y + 0.5, sh.pts);
        if (d > 0.5) continue;
        put(x, y, d > -0.9 ? 0.6 : 0.88, INK.white);
      }
    }
  }
  // blue strands through each spike, and a few along the cap
  for (const sh of shapes) {
    for (let s2 = 0.05; s2 < 0.8; s2 += 0.05) {
      put(Math.round(lerp(sh.root.x, sh.tip.x, s2)), Math.round(lerp(sh.root.y, sh.tip.y, s2)), 0.6, INK.iceRing);
    }
  }
}

export function drawSummonBurst(frame: Frame, times: SummonTimes, now: number): void {
  drawBlackHole(frame, times, now);
  if (times.part2 === null) return;
  const t = now - times.part2;
  if (t < BURST_RISE.from || t > BURST_RISE.peak + BURST_FADE_MS) return;
  const rise = ease((t - BURST_RISE.from) / (BURST_RISE.peak - BURST_RISE.from));
  const decay = 1 - ease((t - BURST_RISE.peak) / BURST_FADE_MS);
  const power = t < BURST_RISE.peak ? rise : decay;
  const grow = clamp01((t - BURST_RISE.from) / (BURST_RISE.peak + BURST_FADE_MS - BURST_RISE.from));
  const put = (x: number, y: number, level: number, ink: Ink): void => {
    const cx = Math.round(x);
    const cy = Math.round(y);
    if (cx < 0 || cx >= COLS || cy < 0 || cy >= ROWS || outsideHead(cx + 0.5, cy + 0.5) < 0.5) return;
    frame.lighten(cx, cy, level, ink, FADE.fast);
  };
  // rays: start at the head's edge, reach outward, alternate ice-blue and cyan
  for (let r = 0; r < RAYS; r += 1) {
    const angle = (r / RAYS) * Math.PI * 2 + 0.17;
    const dx = Math.cos(angle);
    const dy = Math.sin(angle);
    const edge = 1 / Math.hypot(dx / HEAD.rx, dy / HEAD.ry); // oval radius along this angle
    const length = (9 + 14 * hash(r)) * (0.55 + 0.8 * grow);
    const start = edge + 1.5 + grow * 4;
    const ink = r % 2 === 0 ? INK.iceRing : INK.cyan;
    for (let s = 0; s < length; s += 0.7) {
      const along = 1 - s / length;
      put(HEAD.x + dx * (start + s), HEAD.y + dy * (start + s), power * (0.35 + 0.65 * along), ink);
    }
  }
  // one ring, expanding from the head's outline
  const ringOut = 2 + grow * 26;
  for (let a = 0; a < 220; a += 1) {
    const angle = (a / 220) * Math.PI * 2;
    const dx = Math.cos(angle);
    const dy = Math.sin(angle);
    const edge = 1 / Math.hypot(dx / HEAD.rx, dy / HEAD.ry);
    put(HEAD.x + dx * (edge + ringOut), HEAD.y + dy * (edge + ringOut), power * 0.8 * (1 - grow * 0.5), INK.iceCore);
  }
  // sparks: flung outward, twinkling
  for (let k = 0; k < SPARKS; k += 1) {
    const angle = hash(k + 1) * Math.PI * 2;
    const dx = Math.cos(angle);
    const dy = Math.sin(angle);
    const edge = 1 / Math.hypot(dx / HEAD.rx, dy / HEAD.ry);
    const dist = edge + 2 + (4 + 30 * hash(k + 50)) * grow;
    const twinkle = 0.55 + 0.45 * Math.sin(now * 0.006 + k * 1.7);
    put(HEAD.x + dx * dist, HEAD.y + dy * dist, power * twinkle, k % 3 === 0 ? INK.white : k % 2 ? INK.cyan : INK.iceRing);
  }
}

/** True while the sequence still has something on screen. */
export function summonActive(times: SummonTimes, now: number): boolean {
  if (times.part2 === null) return true;
  return now - times.part2 < summonTail(times);
}
