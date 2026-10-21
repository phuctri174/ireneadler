// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// Her boot-up as a spectacle: a 12 s high-tech title sequence drawn on one canvas
// over her whole interface, act by act, each bigger than the last:
//
//   COLD     0     dark. One point of light stutters on; a CRT line opens.
//   SYSTEMS  1100  six subsystems come online one at a time, each arriving from
//                  behind the screen (deep z -> its place, overshoot, settle) with a
//                  flash; a perspective grid rises, data streaks past the camera
//   SWEEP    3700  the diagnostic sweep: a volumetric beam crosses, everything it
//                  touches blooms; hundreds of ticks swarm, then lock into order
//   COLLAPSE 5600  everything implodes into the centre - a flash -
//   SILENCE  6000  held darkness. One heartbeat of light. (The music drops too.)
//   NAME     6900  I R E N E drop in one by one, each typing out its word - It's
//                  Really Everything, No Exaggeration - held to be read, folded
//                  back into IRENE, then ADLER (9750): the biggest hit
//   PANEL    10200 a bolt of light leaves for the second screen: its CRT powers on
//   ARRIVAL  10900 the name lifts away, a shutter of light opens onto her interface,
//                  a last flash - and she is there (12000)
//
// The camera is faked with perspective: everything lives at (x, y, z), projected
// through a camera that pushes in, pulls back and tilts, so layers at different
// depths move at different speeds. Motion uses springs (overshoot and settle),
// never linear. Light is additive ('lighter') with soft glow sprites for bloom.
// Pure function of t: any frame can be drawn alone (the screenshots, the tests).

export const SPECTACLE_MS = 12000;

export const ACT = {
  cold: 0,
  systems: 1100,
  sweep: 3700,
  order: 5300,
  collapse: 5600,
  silence: 6000,
  heart: 6500,
  name: 6900,
  adler: 9750,
  panel: 10200,
  arrival: 10900,
  flash: 11600,
} as const;

const SYSTEMS = ["CORE", "OPTICS", "VOICE", "MEMORY", "MOTION", "LINK"];
const SYSTEM_STEP = 400;
const LETTERS = ["I", "R", "E", "N", "E"];
const WORDS = ["It's", "Really", "Everything,", "No", "Exaggeration"];

const CYAN = [34, 224, 255];
const ICE = [168, 228, 255];
const WHITE = [234, 255, 255];
const AMBER = [255, 182, 72];

// ---- maths --------------------------------------------------------------------------

const clamp01 = (v: number): number => Math.min(1, Math.max(0, v));
const lerp = (a: number, b: number, u: number): number => a + (b - a) * u;
const smooth = (u: number): number => {
  const x = clamp01(u);
  return x * x * (3 - 2 * x);
};
/** 0..1 over [a, b], smoothstep. */
const span = (t: number, a: number, b: number): number => smooth((t - a) / (b - a));
/** An exponential ease-in: slow then rushing. */
const rush = (u: number): number => clamp01(u) ** 3;
/** Damped spring from 0 to 1: overshoots, rings, settles. `k` stiffness, `z` damping. */
function spring(ms: number, k = 9, z = 0.32): number {
  if (ms <= 0) return 0;
  const t = ms / 1000;
  const w = k * 3.4;
  const wd = w * Math.sqrt(1 - z * z);
  return 1 - Math.exp(-z * w * t) * (Math.cos(wd * t) + ((z * w) / wd) * Math.sin(wd * t));
}
/**
 * A swell at `at`: ramps up over RAMP_MS (centred a little before the moment, so it
 * peaks with the sound's hit), then dies away over `ms`. Never a jump: no brightness
 * in the sequence changes faster than this (he found the snaps dizzying).
 */
const RAMP_MS = 220;
const kick = (t: number, at: number, ms: number): number => {
  const start = at - RAMP_MS * 0.65;
  if (t < start) return 0;
  const rise = smooth((t - start) / RAMP_MS);
  return rise * Math.exp(-Math.max(0, t - start - RAMP_MS) / ms);
};

function rng(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

const rgba = (c: number[], a: number): string => `rgba(${c[0]},${c[1]},${c[2]},${clamp01(a).toFixed(3)})`;

// ---- the world -----------------------------------------------------------------------

interface Streak {
  x: number;
  y: number;
  z: number;
  speed: number;
  hue: number;
}

interface Tick {
  x: number;
  y: number;
  z: number;
  /** Where it locks into the formation. */
  gx: number;
  gy: number;
  phase: number;
  size: number;
}

const random = rng(20260921);
const STREAKS: Streak[] = Array.from({ length: 420 }, () => ({
  x: (random() - 0.5) * 9,
  y: (random() - 0.5) * 5,
  z: random() * 30,
  speed: 0.6 + random() * 1.6,
  hue: random(),
}));
// the swarm: chaotic, then a grid of readouts in perfect order behind the centre
const TICKS: Tick[] = Array.from({ length: 360 }, (_, i) => {
  const col = i % 30;
  const row = Math.floor(i / 30);
  return {
    x: (random() - 0.5) * 12,
    y: (random() - 0.5) * 6,
    z: 3 + random() * 9,
    gx: (col - 14.5) * 0.3,
    gy: (row - 5.5) * 0.34,
    phase: random() * Math.PI * 2,
    size: 0.6 + random() * 0.8,
  };
});
const READOUT = Array.from({ length: 6 }, () => Array.from({ length: 5 }, () => Math.floor(random() * 9999)));

interface View {
  w: number;
  h: number;
  /** Camera: its z, its tilt (radians, + looks down), x/y offset (a shake). */
  cz: number;
  tilt: number;
  ox: number;
  oy: number;
  f: number;
}

/** Project a point of the world onto the screen; null when behind the camera. */
function project(v: View, x: number, y: number, z: number): { x: number; y: number; k: number } | null {
  const cy = Math.cos(v.tilt);
  const sy = Math.sin(v.tilt);
  const yy = y * cy - z * sy;
  const zz = y * sy + z * cy - v.cz;
  if (zz <= 0.05) return null;
  const k = v.f / zz;
  return { x: v.w / 2 + x * k + v.ox, y: v.h / 2 - yy * k + v.oy, k };
}

/** The camera's move through the acts: slow push, pull back for the sweep, tilt. */
function camera(t: number, w: number, h: number): View {
  const f = h * 1.05;
  let cz = lerp(-6, -4.2, span(t, ACT.systems, ACT.sweep));
  cz = lerp(cz, -6.8, span(t, ACT.sweep, ACT.order));
  cz = lerp(cz, -2.6, rush((t - ACT.collapse) / (ACT.silence - ACT.collapse)) * (t < ACT.silence ? 1 : 0));
  if (t >= ACT.silence) cz = lerp(-5.2, -4.6, span(t, ACT.name, ACT.arrival));
  const tilt = lerp(0.32, 0.08, span(t, ACT.systems, ACT.sweep)) + 0.06 * span(t, ACT.sweep, ACT.order) - 0.14 * span(t, ACT.name, ACT.panel) * (t < ACT.silence ? 0 : 1);
  // impacts shake the camera
  const hits = [...SYSTEMS.map((_, i) => ACT.systems + i * SYSTEM_STEP), ...LETTERS.map((_, i) => ACT.name + i * 300), ACT.adler, ACT.panel, ACT.flash];
  let ox = 0;
  let oy = 0;
  for (const [i, at] of hits.entries()) {
    const k = kick(t, at, 140) * (at === ACT.adler ? 3 : at === ACT.flash ? 2 : 1) * h * 0.006;
    ox += Math.sin(t / 19 + i) * k;
    oy += Math.cos(t / 23 + i * 1.7) * k;
  }
  return { w, h, cz, tilt, ox, oy, f };
}

// ---- light ------------------------------------------------------------------------------

const glowCache = new Map<string, HTMLCanvasElement>();

/** A soft round glow sprite (bloom), cached per colour. */
function glowSprite(c: number[]): HTMLCanvasElement {
  const key = c.join(",");
  let g = glowCache.get(key);
  if (g) return g;
  g = document.createElement("canvas");
  g.width = g.height = 128;
  const x = g.getContext("2d") as CanvasRenderingContext2D;
  const grad = x.createRadialGradient(64, 64, 0, 64, 64, 64);
  grad.addColorStop(0, rgba(c, 1));
  grad.addColorStop(0.18, rgba(c, 0.55));
  grad.addColorStop(0.5, rgba(c, 0.12));
  grad.addColorStop(1, rgba(c, 0));
  x.fillStyle = grad;
  x.fillRect(0, 0, 128, 128);
  glowCache.set(key, g);
  return g;
}

function bloom(ctx: CanvasRenderingContext2D, x: number, y: number, r: number, c: number[], a: number): void {
  if (a <= 0.003 || r <= 0) return;
  ctx.globalAlpha = clamp01(a);
  ctx.drawImage(glowSprite(c), x - r, y - r, r * 2, r * 2);
  ctx.globalAlpha = 1;
}

/** A lens flare along the line from a light through the screen centre. */
function flare(ctx: CanvasRenderingContext2D, w: number, h: number, lx: number, ly: number, a: number, c: number[]): void {
  if (a <= 0.01) return;
  const cx = w / 2;
  const cy = h / 2;
  bloom(ctx, lx, ly, h * 0.22, c, a * 0.9);
  // anamorphic streak through the light
  const grad = ctx.createLinearGradient(lx - w * 0.6, ly, lx + w * 0.6, ly);
  grad.addColorStop(0, rgba(c, 0));
  grad.addColorStop(0.5, rgba(WHITE, a * 0.85));
  grad.addColorStop(1, rgba(c, 0));
  ctx.fillStyle = grad;
  ctx.fillRect(lx - w * 0.6, ly - h * 0.003, w * 1.2, h * 0.006);
  // ghosts along the axis
  for (const [k, r, ga] of [[0.4, 0.035, 0.25], [0.75, 0.06, 0.18], [1.3, 0.02, 0.35], [1.7, 0.09, 0.12]] as const) {
    const gx = lx + (cx - lx) * k * 2;
    const gy = ly + (cy - ly) * k * 2;
    ctx.strokeStyle = rgba(c, a * ga);
    ctx.lineWidth = h * 0.003;
    ctx.beginPath();
    ctx.arc(gx, gy, h * r, 0, Math.PI * 2);
    ctx.stroke();
    bloom(ctx, gx, gy, h * r * 1.4, c, a * ga * 0.6);
  }
}

// ---- the acts ----------------------------------------------------------------------------

function drawCold(ctx: CanvasRenderingContext2D, t: number, w: number, h: number): void {
  if (t > ACT.systems + 400) return;
  const fade = 1 - span(t, ACT.systems, ACT.systems + 400);
  // the first point of light, stuttering on
  // a point of light swelling up out of the black (no stutter)
  const swell = span(t, 150, 650);
  if (swell > 0) bloom(ctx, w / 2, h / 2, h * 0.05 * (0.4 + 0.6 * swell), ICE, 0.9 * fade * swell);
  // the CRT line: a hairline opening sideways with overshoot
  const open = spring(t - 650, 7, 0.38);
  if (t > 650) {
    const half = (w / 2) * open;
    const g = ctx.createLinearGradient(w / 2 - half, 0, w / 2 + half, 0);
    g.addColorStop(0, rgba(CYAN, 0));
    g.addColorStop(0.5, rgba(WHITE, 0.95 * fade));
    g.addColorStop(1, rgba(CYAN, 0));
    ctx.fillStyle = g;
    ctx.fillRect(w / 2 - half, h / 2 - h * 0.0015, half * 2, h * 0.003);
    bloom(ctx, w / 2, h / 2, h * 0.12 * open, CYAN, 0.35 * fade);
  }
}

function drawStreaks(ctx: CanvasRenderingContext2D, v: View, t: number): void {
  // speed by act: still, drifting, rushing, sucked inward, hyperspace at the name
  const speedAt = (time: number): number =>
    time < ACT.systems ? 0 : time < ACT.sweep ? 2 : time < ACT.collapse ? 5 : time < ACT.silence ? -14 : time < ACT.name ? 0 : time < ACT.panel ? 9 : 3;
  const vis = span(t, ACT.systems, ACT.systems + 700) * (t < ACT.silence || t > ACT.name ? 1 : 0) * (1 - span(t, ACT.arrival, ACT.flash));
  if (vis <= 0) return;
  ctx.lineCap = "round";
  // batched: 3 colours x 3 brightness buckets -> 9 strokes a frame, not 420
  const buckets = new Map<string, number[]>();
  for (const s of STREAKS) {
    // distance travelled: integrate the act speeds (piecewise, cheap enough)
    const travel = (time: number): number => {
      let d = 0;
      const edges = [ACT.systems, ACT.sweep, ACT.collapse, ACT.silence, ACT.name, ACT.panel, 1e9];
      let prev: number = ACT.systems;
      for (const e of edges.slice(1)) {
        if (time <= prev) break;
        const end = Math.min(time, e);
        d += speedAt(prev + 1) * ((end - prev) / 1000);
        prev = e;
      }
      return d * s.speed;
    };
    const z = (((s.z - travel(t)) % 30) + 30) % 30 + 0.2;
    const zPrev = z + Math.abs(speedAt(t)) * s.speed * 0.045 * Math.sign(speedAt(t) || 1);
    const a = project(v, s.x, s.y, z);
    const b = project(v, s.x, s.y, zPrev);
    if (!a || !b) continue;
    const near = clamp01(1 - z / 30);
    const key = `${s.hue < 0.75 ? 0 : s.hue < 0.92 ? 1 : 2}|${Math.min(2, Math.floor(near * 3))}`;
    let list = buckets.get(key);
    if (!list) buckets.set(key, (list = []));
    list.push(a.x, a.y, b.x, b.y);
  }
  for (const [key, list] of buckets) {
    const [hue, level] = key.split("|").map(Number);
    ctx.strokeStyle = rgba([CYAN, ICE, AMBER][hue], vis * (0.25 + ((level + 0.5) / 3) * 0.9));
    ctx.lineWidth = 1.5 + level * 1.2;
    ctx.beginPath();
    for (let k = 0; k < list.length; k += 4) {
      ctx.moveTo(list[k], list[k + 1]);
      ctx.lineTo(list[k + 2], list[k + 3]);
    }
    ctx.stroke();
  }
}

function drawGrid(ctx: CanvasRenderingContext2D, v: View, t: number): void {
  const vis = span(t, ACT.systems + 200, ACT.systems + 1200) * (1 - span(t, ACT.collapse, ACT.silence));
  if (vis <= 0) return;
  // the floor rises from below as it comes online
  const floor = lerp(-6, -2.2, spring(t - ACT.systems - 200, 5, 0.45));
  ctx.lineWidth = 1;
  for (let k = -16; k <= 16; k += 1) {
    const a = project(v, k * 0.8, floor, 0.5);
    const b = project(v, k * 0.8, floor, 40);
    if (!a || !b) continue;
    ctx.strokeStyle = rgba(CYAN, vis * 0.16);
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();
  }
  const scroll = (t / 1000) * 2.4;
  for (let k = 0; k < 40; k += 1) {
    const z = 0.5 + ((k - scroll) % 40 + 40) % 40;
    const a = project(v, -13, floor, z);
    const b = project(v, 13, floor, z);
    if (!a || !b) continue;
    // a pulse of light travelling down the grid
    const pulse = Math.exp(-(((z - ((t / 60) % 40)) / 1.5) ** 2));
    ctx.strokeStyle = rgba(pulse > 0.3 ? WHITE : CYAN, vis * (0.1 + 0.4 * pulse) * clamp01(1 - z / 40));
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();
  }
}

/** A subsystem module: arrives from behind the screen, flashes, comes alive. */
function drawSystem(ctx: CanvasRenderingContext2D, v: View, t: number, i: number): void {
  const at = ACT.systems + i * SYSTEM_STEP;
  if (t < at - 400) return;
  const angle = (i / SYSTEMS.length) * Math.PI * 2 - Math.PI / 2 + Math.PI / 6;
  const home = { x: Math.cos(angle) * 5.2, y: Math.sin(angle) * 2.15, z: 2.2 };
  // from deep behind the screen to home, with a spring's overshoot
  const arrive = spring(t - at + 400, 6, 0.36);
  // pulled into the centre at the collapse
  const pull = rush((t - ACT.collapse) / (ACT.silence - ACT.collapse)) * (t < ACT.silence ? 1 : 0);
  if (t >= ACT.silence) return;
  const x = lerp(home.x * 1.6, home.x, clamp01(arrive)) * (1 - pull);
  const y = lerp(home.y * 1.6, home.y, clamp01(arrive)) * (1 - pull);
  const z = lerp(26, home.z, arrive) + pull * 1.5;
  const p = project(v, x, y, z);
  if (!p) return;
  const s = p.k * 0.7;
  const alpha = clamp01((t - at + 400) / 250) * (1 - pull * 0.6);
  const hit = kick(t, at, 220);
  const swept = Math.max(sweepHit(t, p.x / v.w), 0);
  ctx.save();
  ctx.translate(p.x, p.y);
  // frame: corner brackets and a faint body
  ctx.fillStyle = rgba(CYAN, alpha * (0.05 + 0.08 * swept));
  ctx.fillRect(-s, -s * 0.62, s * 2, s * 1.24);
  ctx.strokeStyle = rgba(CYAN, alpha * Math.min(1, 0.65 + 0.35 * hit + 0.35 * swept));
  ctx.lineWidth = Math.max(1, s * 0.02);
  const c = s * 0.28;
  for (const [sx, sy] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) {
    ctx.beginPath();
    ctx.moveTo(sx * s, sy * s * 0.62 - sy * c * -1 * 0);
    ctx.lineTo(sx * s, sy * (s * 0.62 - c));
    ctx.moveTo(sx * s, sy * s * 0.62);
    ctx.lineTo(sx * (s - c), sy * s * 0.62);
    ctx.stroke();
  }
  // its instrument: a different wireframe per system, alive after it lands
  const live = clamp01((t - at) / 300);
  const spin = (t / 1000) * (0.8 + i * 0.3);
  ctx.strokeStyle = rgba(CYAN, alpha * 0.85);
  ctx.lineWidth = Math.max(1, s * 0.016);
  const r = s * 0.36;
  ctx.beginPath();
  switch (i) {
    case 0: // core: three counter-rotating arcs
      for (let k = 0; k < 3; k += 1) {
        const rr = r * (0.45 + k * 0.28);
        const a0 = spin * (k % 2 ? -1.6 : 1.2) + k;
        ctx.moveTo(Math.cos(a0) * rr, Math.sin(a0) * rr);
        ctx.arc(0, 0, rr, a0, a0 + Math.PI * (0.6 + 0.9 * live));
      }
      break;
    case 1: // optics: an iris
      for (let k = 0; k < 8; k += 1) {
        const a0 = (k / 8) * Math.PI * 2 + spin * 0.5;
        ctx.moveTo(Math.cos(a0) * r, Math.sin(a0) * r);
        ctx.lineTo(Math.cos(a0 + 1.2) * r * (0.25 + 0.3 * (1 - live)), Math.sin(a0 + 1.2) * r * (0.25 + 0.3 * (1 - live)));
      }
      ctx.moveTo(r, 0);
      ctx.arc(0, 0, r, 0, Math.PI * 2);
      break;
    case 2: // voice: a waveform
      for (let k = 0; k <= 40; k += 1) {
        const xx = -r * 1.5 + (k / 40) * r * 3;
        const yy = Math.sin(k * 0.7 + t / 70) * Math.sin(k * 0.13 + t / 400) * r * 0.7 * live;
        if (k === 0) ctx.moveTo(xx, yy);
        else ctx.lineTo(xx, yy);
      }
      break;
    case 3: // memory: a lattice of cells filling
      for (let gy = 0; gy < 4; gy += 1) {
        for (let gx = 0; gx < 8; gx += 1) {
          const filled = (gx + gy * 8) / 32 < live * (0.7 + 0.3 * Math.sin(t / 300 + gx));
          const cx = -r * 1.4 + gx * r * 0.4;
          const cy = -r * 0.6 + gy * r * 0.4;
          ctx.rect(cx, cy, r * 0.3, r * 0.3);
          if (filled) {
            ctx.fillStyle = rgba(CYAN, alpha * 0.5);
            ctx.fillRect(cx, cy, r * 0.3, r * 0.3);
          }
        }
      }
      break;
    case 4: // motion: a gimbal - two ellipses tumbling
      ctx.ellipse(0, 0, r, r * Math.abs(Math.cos(spin)), 0, 0, Math.PI * 2);
      ctx.moveTo(r * Math.abs(Math.sin(spin * 1.3)), 0);
      ctx.ellipse(0, 0, r * Math.abs(Math.sin(spin * 1.3)), r, 0, 0, Math.PI * 2);
      break;
    default: // link: a radar sweep
      ctx.moveTo(r, 0);
      ctx.arc(0, 0, r, 0, Math.PI * 2);
      ctx.moveTo(0, 0);
      ctx.lineTo(Math.cos(spin * 3) * r, Math.sin(spin * 3) * r);
      for (let k = 0; k < 4; k += 1) {
        const bx = Math.cos(k * 1.9 + 0.4) * r * 0.6;
        const by = Math.sin(k * 2.7) * r * 0.6;
        ctx.moveTo(bx + 3, by);
        ctx.arc(bx, by, 3, 0, Math.PI * 2);
      }
  }
  ctx.stroke();
  // label and readouts
  ctx.font = `700 ${Math.max(8, s * 0.13)}px "Cascadia Mono", Consolas, monospace`;
  ctx.textAlign = "left";
  ctx.fillStyle = rgba(WHITE, alpha);
  ctx.fillText(SYSTEMS[i], -s * 0.92, -s * 0.44);
  ctx.textAlign = "right";
  ctx.fillStyle = rgba(CYAN, alpha * 0.9);
  ctx.fillText(t < at ? "…" : "ONLINE", s * 0.92, -s * 0.44);
  ctx.font = `500 ${Math.max(7, s * 0.085)}px "Cascadia Mono", Consolas, monospace`;
  ctx.textAlign = "left";
  ctx.fillStyle = rgba(CYAN, alpha * 0.7);
  for (let k = 0; k < 3; k += 1) {
    const n = Math.floor(READOUT[i][k] * clamp01((t - at) / 900));
    ctx.fillText(`${["SYS", "BUS", "ERR"][k]} ${String(n).padStart(4, "0")}`, -s * 0.92, s * 0.32 + k * s * 0.1);
  }
  ctx.restore();
  // its arrival: a flash and a ring
  if (hit > 0.02) {
    ctx.globalCompositeOperation = "lighter";
    bloom(ctx, p.x, p.y, s * 1.6, WHITE, hit * 0.7);
    ctx.strokeStyle = rgba(ICE, hit);
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(p.x, p.y, s * (0.6 + (1 - hit) * 1.6), 0, Math.PI * 2);
    ctx.stroke();
    ctx.globalCompositeOperation = "source-over";
  }
}

/** How strongly a diagnostic sweep is over a screen x (0..1 across) at t. */
function sweepHit(t: number, xFrac: number): number {
  let best = 0;
  for (const [at, dirn] of [[ACT.sweep, 1], [ACT.sweep + 900, -1]] as const) {
    const u = (t - at) / 900;
    if (u < -0.1 || u > 1.2) continue;
    const pos = dirn > 0 ? lerp(-0.15, 1.15, smooth(u)) : lerp(1.15, -0.15, smooth(u));
    best = Math.max(best, Math.exp(-(((xFrac - pos) / 0.05) ** 2)));
  }
  return best;
}

function drawSweep(ctx: CanvasRenderingContext2D, t: number, w: number, h: number): void {
  for (const [at, dirn] of [[ACT.sweep, 1], [ACT.sweep + 900, -1]] as const) {
    const u = (t - at) / 900;
    if (u < -0.05 || u > 1.15) continue;
    const pos = (dirn > 0 ? lerp(-0.15, 1.15, smooth(u)) : lerp(1.15, -0.15, smooth(u))) * w;
    // a volumetric band: a wide soft glow and a hard core line
    const g = ctx.createLinearGradient(pos - w * 0.12, 0, pos + w * 0.12, 0);
    g.addColorStop(0, rgba(CYAN, 0));
    g.addColorStop(0.42, rgba(CYAN, 0.12));
    g.addColorStop(0.5, rgba(WHITE, 0.55));
    g.addColorStop(0.58, rgba(CYAN, 0.12));
    g.addColorStop(1, rgba(CYAN, 0));
    ctx.fillStyle = g;
    ctx.fillRect(pos - w * 0.12, 0, w * 0.24, h);
    ctx.fillStyle = rgba(WHITE, 0.9);
    ctx.fillRect(pos - 1.5, 0, 3, h);
    // god rays fanning from the beam
    for (let k = 0; k < 7; k += 1) {
      const yy = h * (0.1 + k * 0.13);
      ctx.strokeStyle = rgba(ICE, 0.12);
      ctx.lineWidth = h * 0.004;
      ctx.beginPath();
      ctx.moveTo(pos, yy);
      ctx.lineTo(pos - dirn * w * 0.25, yy + (k - 3) * h * 0.04);
      ctx.stroke();
    }
    flare(ctx, w, h, pos, h * 0.3, 0.8 * Math.sin(clamp01(u) * Math.PI), ICE);
  }
}

function drawSwarm(ctx: CanvasRenderingContext2D, v: View, t: number): void {
  const vis = span(t, ACT.systems + 300, ACT.systems + 1500) * (t < ACT.silence ? 1 : 0);
  if (vis <= 0) return;
  const order = spring(t - ACT.order + 500, 4.5, 0.42);
  const pull = rush((t - ACT.collapse) / (ACT.silence - ACT.collapse)) * (t < ACT.silence ? 1 : 0);
  const dim: [number, number, number, number][] = [];
  const bright: [number, number, number, number][] = [];
  for (const [i, k] of TICKS.entries()) {
    // chaos: each wanders on its own orbit; order: locks onto the grid behind
    const wx = k.x + Math.sin(t / 700 + k.phase) * 0.5;
    const wy = k.y + Math.cos(t / 900 + k.phase * 1.3) * 0.35;
    let x = lerp(wx, k.gx, clamp01(order));
    let y = lerp(wy, k.gy, clamp01(order));
    let z = lerp(k.z, 7, clamp01(order));
    x *= 1 - pull;
    y *= 1 - pull;
    z = lerp(z, 2.5, pull);
    const p = project(v, x, y, z);
    if (!p) continue;
    const swept = sweepHit(t, p.x / v.w);
    const lit = false;
    const size = Math.max(1.5, p.k * 0.03 * k.size);
    const rect: [number, number, number, number] =
      i % 3 === 0 ? [p.x - size, p.y - size * 0.3, size * 2, size * 0.6] : i % 3 === 1 ? [p.x - size * 0.3, p.y - size, size * 0.6, size * 2] : [p.x - size * 0.5, p.y - size * 0.5, size, size];
    (lit ? bright : dim).push(rect);
    void swept;
  }
  // two passes, one paint each
  ctx.fillStyle = rgba(CYAN, vis * 0.42);
  for (const r of dim) ctx.fillRect(r[0], r[1], r[2], r[3]);
  ctx.fillStyle = rgba(WHITE, vis * 0.95);
  for (const r of bright) ctx.fillRect(r[0], r[1], r[2], r[3]);
}

const STREAMS = Array.from({ length: 34 }, (_, i) => ({ x: (i < 17 ? -1 : 1) * (5.4 + (i % 17) * 0.28), speed: 0.6 + random() * 1.4, seed: Math.floor(random() * 1000), z: 4 + random() * 6 }));

/** Columns of scrolling data down both edges, as blocks of a hex dump: a far layer,
 *  slower than the near one. (fillRect, batched by colour: cheap at any density.) */
function drawStreams(ctx: CanvasRenderingContext2D, v: View, t: number): void {
  const vis = span(t, ACT.systems + 500, ACT.systems + 1600) * (1 - span(t, ACT.collapse, ACT.silence));
  if (vis <= 0) return;
  const rows = 22;
  const dim: number[][] = [];
  const bright: number[][] = [];
  for (const [i, st] of STREAMS.entries()) {
    const top = project(v, st.x, 3.4, st.z);
    if (!top) continue;
    const size = Math.max(6, top.k * 0.09);
    const scroll = (t / 1000) * st.speed * 6;
    // (the sweep lights these with its own travelling band, not a colour snap)
    for (let r = 0; r < rows; r += 1) {
      const y = top.y + ((r + scroll) % rows) * size * 1.3;
      const head = ((rows - 1 - Math.floor(scroll % rows) + r) % rows) < 2;
      // a block of 1-3 "characters", its length from the data
      const n = 1 + ((st.seed + r * 7 + Math.floor(t / 120)) % 3);
      const w = size * 0.55 * n + size * 0.12 * (n - 1);
      (head ? bright : dim).push([top.x - w / 2, y, w, size * 0.7, i % 3 === 0 ? 1 : 0.7]);
    }
  }
  ctx.fillStyle = rgba(CYAN, vis * 0.3);
  for (const [x, y, w, h] of dim) ctx.fillRect(x, y, w, h);
  ctx.fillStyle = rgba(WHITE, vis * 0.85);
  for (const [x, y, w, h] of bright) ctx.fillRect(x, y, w, h);
}

/** A wireframe globe turning behind the modules - the system's model of itself. */
function drawGlobe(ctx: CanvasRenderingContext2D, v: View, t: number): void {
  const vis = span(t, ACT.systems + 1200, ACT.systems + 2400) * (1 - span(t, ACT.collapse, ACT.silence));
  if (vis <= 0) return;
  const c = project(v, 0, 0, 7);
  if (!c) return;
  const r = c.k * 2.1 * spring(t - ACT.systems - 1200, 5, 0.45);
  const spin = t / 2600;
  ctx.lineWidth = 1.2;
  for (let k = 0; k < 12; k += 1) {
    const a = spin + (k / 12) * Math.PI;
    ctx.strokeStyle = rgba(CYAN, vis * 0.22);
    ctx.beginPath();
    ctx.ellipse(c.x, c.y, Math.abs(Math.cos(a)) * r, r, 0, 0, Math.PI * 2);
    ctx.stroke();
  }
  for (let k = 1; k < 8; k += 1) {
    const yy = (k / 8) * 2 - 1;
    const rr = Math.sqrt(1 - yy * yy) * r;
    ctx.strokeStyle = rgba(k === 4 ? WHITE : CYAN, vis * (k === 4 ? 0.4 : 0.18));
    ctx.beginPath();
    ctx.ellipse(c.x, c.y + yy * r, rr, rr * 0.12, 0, 0, Math.PI * 2);
    ctx.stroke();
  }
  // a few nodes lit on its surface, blinking
  for (let k = 0; k < 18; k += 1) {
    const lon = k * 2.4 + spin * 2;
    const lat = Math.sin(k * 1.7) * 1.2;
    const z = Math.cos(lon) * Math.cos(lat);
    if (z < 0) continue;
    const x = c.x + Math.sin(lon) * Math.cos(lat) * r;
    const y = c.y + Math.sin(lat) * r;
    bloom(ctx, x, y, c.k * 0.08, CYAN, vis * (0.35 + 0.25 * Math.sin(t / 600 + k)));
  }
}

/** The rings at the centre: where the name will land. */
function drawRings(ctx: CanvasRenderingContext2D, v: View, t: number): void {
  const vis = span(t, ACT.sweep - 600, ACT.sweep + 300) * (1 - span(t, ACT.collapse, ACT.silence));
  if (vis <= 0) return;
  const p = project(v, 0, 0, 4);
  if (!p) return;
  for (let k = 0; k < 5; k += 1) {
    const r = p.k * (0.35 + k * 0.22) * spring(t - ACT.sweep + 600 - k * 90, 5, 0.4);
    const a0 = (t / 1000) * (k % 2 ? -0.9 : 0.6) * (1 + k * 0.2) + k;
    ctx.strokeStyle = rgba(k === 2 ? WHITE : CYAN, vis * (0.5 - k * 0.07));
    ctx.lineWidth = Math.max(1, p.k * (0.012 - k * 0.0015));
    ctx.setLineDash([p.k * 0.08 * (k + 1), p.k * 0.04]);
    ctx.beginPath();
    ctx.arc(p.x, p.y, Math.max(1, r), a0, a0 + Math.PI * (1.3 + 0.12 * k));
    ctx.stroke();
  }
  ctx.setLineDash([]);
}

function drawCollapse(ctx: CanvasRenderingContext2D, t: number, w: number, h: number): void {
  // the implosion's flash, resolving into darkness
  if (t >= ACT.collapse && t < ACT.silence + 600) {
    const u = clamp01((t - ACT.collapse) / (ACT.silence - ACT.collapse));
    const out = 1 - span(t, ACT.silence, ACT.silence + 600);
    bloom(ctx, w / 2, h / 2, h * lerp(0.5, 0.04, u), ICE, smooth(u) * 0.6 * out);
  }
  // one heartbeat in the dark
  if (t > ACT.heart && t < ACT.name) {
    const beat = kick(t, ACT.heart, 220) + 0.6 * kick(t, ACT.heart + 180, 260);
    bloom(ctx, w / 2, h / 2, h * 0.18, CYAN, beat * 0.35);
    ctx.strokeStyle = rgba(CYAN, beat * 0.3);
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(w / 2, h / 2, h * (0.08 + (t - ACT.heart) / 4000), 0, Math.PI * 2);
    ctx.stroke();
  }
}

// ---- THE NAME: I R E N E -> It's Really Everything, No Exaggeration -> IRENE ADLER ----
// The acronym reveal, restored and raised to the rest of the shot. Each initial
// drops in from above, huge, past its place and snaps back (cyan, white-hot core,
// a shockwave); then it types out into its word. The full line holds so it can be
// read; the words fold away, the gaps close into IRENE, and ADLER types in - the
// biggest hit - then the whole name pulses once. The glyphs are a material, not a
// flat fill: a metallic gradient, an extruded edge for depth, chromatic fringes, a
// light sweep travelling across them, scanlines clipped to the letters, bloom behind.

/** When each part of the name happens, from its first letter. */
const NAME = {
  step: 300, // between initials
  type: 180, // an initial lands, then its word starts typing...
  typeMs: 280, // ... and takes this long
  fold: 9300, // the words fold back
  foldMs: 340,
  close: 9550, // the gaps close: IRENE
  closeMs: 220,
  adlerMs: 360, // ADLER types in over this, from ACT.adler
  pulse: 10000, // the whole name pulses
};

let nameLayer: HTMLCanvasElement | null = null;

function layerOf(w: number, h: number): [HTMLCanvasElement, CanvasRenderingContext2D] {
  if (!nameLayer || nameLayer.width !== w || nameLayer.height !== h) {
    nameLayer = document.createElement("canvas");
    nameLayer.width = w;
    nameLayer.height = h;
  }
  return [nameLayer, nameLayer.getContext("2d") as CanvasRenderingContext2D];
}

interface Run {
  text: string;
  x: number;
  initial: boolean;
  /** The initial's drop: y offset (px) and scale. */
  dy: number;
  scale: number;
  alpha: number;
}

function drawName(ctx: CanvasRenderingContext2D, v: View, t: number): void {
  if (t < ACT.name - 100) return;
  const { w, h } = v;
  const lift = span(t, ACT.arrival, ACT.flash);
  const gone = span(t, ACT.flash - 200, ACT.flash + 150);
  if (gone >= 1) return;
  const mono = (px: number): string => `700 ${px}px "Cascadia Mono", Consolas, monospace`;
  // size: the full line of words must fit the frame
  let size = h * 0.085;
  ctx.font = mono(size);
  const full = ctx.measureText("It's Really Everything, No Exaggeration").width;
  if (full > w * 0.9) size *= (w * 0.9) / full;
  ctx.font = mono(size);
  const cw = ctx.measureText("M").width;
  const space = cw * 0.9;

  // ---- layout: each word is its initial plus as much of its tail as is typed ----
  const runs: Run[] = [];
  const fold = span(t, NAME.fold, NAME.fold + NAME.foldMs);
  const close = span(t, NAME.close, NAME.close + NAME.closeMs);
  const pieces: { initial: string; tail: string; land: number }[] = LETTERS.map((l, i) => ({ initial: l, tail: WORDS[i].slice(1), land: ACT.name + i * NAME.step }));
  let x = 0;
  const lineStart = 0;
  for (const [i, p] of pieces.entries()) {
    if (t < p.land - 160) break;
    const drop = spring(t - p.land + 160, 6, 0.34);
    runs.push({ text: p.initial, x, initial: true, dy: (1 - clamp01(drop)) * -size * 1.8 + (drop - clamp01(drop)) * -size * 0.4, scale: lerp(2.2, 1, clamp01(drop)), alpha: clamp01(drop * 1.6) });
    x += cw;
    // the tail types out (stepped, like the old reveal) and folds away
    const typed = clamp01((t - p.land - NAME.type) / NAME.typeMs);
    const chars = Math.round(p.tail.length * typed * (1 - fold));
    if (chars > 0) {
      runs.push({ text: p.tail.slice(0, chars), x, initial: false, dy: 0, scale: 1, alpha: 1 });
      x += cw * chars;
    }
    if (i < 4) x += space * (1 - close);
  }
  // ADLER types in after a gap
  const adlerTyped = clamp01((t - ACT.adler) / NAME.adlerMs);
  if (adlerTyped > 0) {
    x += space;
    const chars = Math.ceil(5 * adlerTyped);
    runs.push({ text: "ADLER".slice(0, chars), x, initial: false, dy: 0, scale: 1, alpha: 1 });
    x += cw * chars;
  }
  const width = x - lineStart;
  // the line is centred as it grows; lifting away at the arrival it rises and shrinks
  const pulse = 1 + 0.07 * Math.sin(clamp01((t - NAME.pulse) / 600) * Math.PI) * (t > NAME.pulse ? 1 : 0);
  // once the words fold away, the camera pushes in on the name until IRENE ADLER
  // spans most of the frame (a spring: it overshoots and settles)
  const push = lerp(1, Math.min(3.2, (0.62 * w) / (11 * cw)), spring(t - NAME.close + 60, 3.2, 0.5));
  const shrink = (t > NAME.close - 60 ? push : 1) * lerp(1, 0.45, lift) * pulse;
  const cx = w / 2 + v.ox;
  const cy = h / 2 - lift * h * 0.12 + v.oy;
  const left = cx - (width / 2) * shrink;

  // ---- the glyph layer: drawn once, then lit -----------------------------------
  const lw = Math.ceil(Math.max(cw * 2, width) * 1.1 + cw * 4);
  const lh = Math.ceil(size * 4.2);
  // the layer renders at the spectacle's own scale (it is drawn under full size)
  const ls = ctx.getTransform().a || 1;
  const [layer, g] = layerOf(Math.ceil(Math.min(lw, w) * ls), Math.ceil(lh * ls));
  const LW = layer.width / ls;
  const LH = layer.height / ls;
  g.setTransform(1, 0, 0, 1, 0, 0);
  g.globalCompositeOperation = "source-over";
  g.clearRect(0, 0, layer.width, layer.height);
  g.setTransform(ls, 0, 0, ls, 0, 0);
  g.font = mono(size);
  g.textBaseline = "middle";
  g.textAlign = "left";
  const ox = (LW - width) / 2;
  const oy = LH * 0.62;
  const hits = [...LETTERS.map((_, i) => ACT.name + i * NAME.step), ACT.adler];
  const hit = Math.max(...hits.map((at) => kick(t, at, 180)));
  const split = size * (0.035 + hit * 0.07);
  // depth and fringes first, as plain text (filters on a whole layer every frame
  // cost ~40 ms): the extruded edge stepping back, then red and blue fringes
  for (const r of runs) {
    g.save();
    g.translate(ox + r.x + cw / 2, oy + r.dy);
    g.scale(r.scale, r.scale);
    g.globalAlpha = r.alpha;
    g.fillStyle = "#03202c";
    for (let k = 7; k >= 1; k -= 1) g.fillText(r.text, -cw / 2 + k * size * 0.018, k * size * 0.024);
    g.globalAlpha = r.alpha * 0.7;
    g.fillStyle = "#ff2f6a";
    g.fillText(r.text, -cw / 2 - split, 0);
    g.fillStyle = "#2f8cff";
    g.fillText(r.text, -cw / 2 + split, 0);
    g.restore();
  }
  for (const r of runs) {
    g.save();
    g.translate(ox + r.x + cw / 2, oy + r.dy);
    g.scale(r.scale, r.scale);
    g.globalAlpha = r.alpha;
    // metal: initials a deep-to-bright cyan, words ice-white
    const grad = g.createLinearGradient(0, -size * 0.5, 0, size * 0.5);
    if (r.initial) {
      grad.addColorStop(0, "#eaffff");
      grad.addColorStop(0.35, "#5ef0ff");
      grad.addColorStop(1, "#0a8fc4");
    } else {
      grad.addColorStop(0, "#ffffff");
      grad.addColorStop(0.55, "#d6f6ff");
      grad.addColorStop(1, "#7fbfd6");
    }
    g.fillStyle = grad;
    g.fillText(r.text, -cw / 2, 0);
    g.restore();
  }
  g.globalAlpha = 1;
  // a light sweep across the glyphs: once as the line completes, again on ADLER
  g.globalCompositeOperation = "source-atop";
  for (const at of [ACT.name + 4 * NAME.step + NAME.type + NAME.typeMs, ACT.adler + NAME.adlerMs]) {
    const u = (t - at) / 650;
    if (u < 0 || u > 1) continue;
    const sx = lerp(-LW * 0.2, LW * 1.2, u);
    const sweep = g.createLinearGradient(sx - size * 1.6, 0, sx + size * 1.6, LH);
    sweep.addColorStop(0, "rgba(255,255,255,0)");
    sweep.addColorStop(0.5, "rgba(255,255,255,0.95)");
    sweep.addColorStop(1, "rgba(255,255,255,0)");
    g.fillStyle = sweep;
    g.fillRect(0, 0, LW, LH);
  }
  // scanlines, clipped to the letters
  g.fillStyle = "rgba(0,20,30,0.32)";
  for (let y = 0; y < LH; y += 3) g.fillRect(0, y, LW, 1);
  g.globalCompositeOperation = "source-over";

  // ---- onto the shot: the lit glyph layer, then bloom ------------------------------
  const dx = left - ox * shrink;
  const dy = cy - oy * shrink;
  const a = 1 - gone;
  ctx.save();
  ctx.globalAlpha = a;
  ctx.drawImage(layer, dx, dy, LW * shrink, LH * shrink);
  ctx.restore();
  // bloom behind the initials (cyan) and the whole name on ADLER
  ctx.globalCompositeOperation = "lighter";
  for (const r of runs) {
    if (!r.initial) continue;
    bloom(ctx, left + (r.x + cw / 2) * shrink, cy + r.dy * shrink, size * 1.1 * shrink, CYAN, 0.3 * r.alpha * a);
  }
  // each initial's landing: a shockwave and a white-hot flash
  for (const [i, at] of hits.entries()) {
    const k = kick(t, at, i === 5 ? 380 : 200);
    if (k < 0.02) continue;
    const big = i === 5;
    const px = big ? cx : left + (pieces[i].initial ? 0 : 0) + (runs.filter((r) => r.initial)[i]?.x ?? 0) * shrink + (cw / 2) * shrink;
    ctx.strokeStyle = rgba(big ? WHITE : ICE, k * 0.8);
    ctx.lineWidth = h * 0.004;
    ctx.beginPath();
    ctx.ellipse(px, cy, size * shrink * (0.5 + (1 - k) * (big ? 4 : 2.4)), size * shrink * (0.2 + (1 - k) * (big ? 1.1 : 0.7)), 0, 0, Math.PI * 2);
    ctx.stroke();
    bloom(ctx, px, cy, size * shrink * (big ? 1.6 : 1.2), big ? ICE : CYAN, k * (big ? 0.45 : 0.55));
  }
  // ADLER's anamorphic flare: a streak across the whole frame
  const su = (t - ACT.adler - NAME.adlerMs * 0.5) / 700;
  if (su > 0 && su < 1) {
    const sx = lerp(left + width * shrink * 0.8, w * 1.15, smooth(su));
    const sa = Math.sin(su * Math.PI) * 0.8;
    const g = ctx.createLinearGradient(sx - w * 0.35, 0, sx, 0);
    g.addColorStop(0, rgba(ICE, 0));
    g.addColorStop(1, rgba(WHITE, sa));
    ctx.fillStyle = g;
    ctx.fillRect(sx - w * 0.35, cy - h * 0.003, w * 0.35, h * 0.006);
    bloom(ctx, sx, cy, h * 0.06, ICE, sa * 0.7);
  }
  ctx.globalCompositeOperation = "source-over";
}

/** The bolt FROM the panel (it sits to the left): it enters her screen's left edge
 *  as the panel's CRT opens and strikes her centre, where CORE lands. */
function drawBoltIn(ctx: CanvasRenderingContext2D, t: number, w: number, h: number): void {
  const u = (t - 900) / 300;
  if (u < 0 || u > 1.5) return;
  const head = lerp(-w * 0.05, w * 0.5, smooth(Math.min(1, u)));
  const tail = lerp(-w * 0.05, w * 0.5, smooth(Math.max(0, u - 0.4)));
  const g = ctx.createLinearGradient(head, 0, tail, 0);
  g.addColorStop(0, rgba(WHITE, 0.95));
  g.addColorStop(1, rgba(CYAN, 0));
  ctx.fillStyle = g;
  ctx.fillRect(Math.min(head, tail), h * 0.5 - h * 0.005, Math.abs(head - tail), h * 0.01);
  bloom(ctx, head, h * 0.5, h * 0.09, WHITE, 0.8 * (1 - clamp01(u - 0.7)));
  bloom(ctx, 0, h * 0.5, h * 0.4, CYAN, 0.45 * kick(t, 900, 260));
}

function drawPanelBolt(ctx: CanvasRenderingContext2D, t: number, w: number, h: number): void {
  // a bolt of light leaving for the second screen (it sits to the left)
  const u = (t - (ACT.panel - 220)) / 420;
  if (u < 0 || u > 1.4) return;
  const head = lerp(w * 0.5, -w * 0.1, smooth(Math.min(1, u)));
  const tail = lerp(w * 0.5, -w * 0.1, smooth(Math.max(0, u - 0.35)));
  const g = ctx.createLinearGradient(head, 0, tail, 0);
  g.addColorStop(0, rgba(WHITE, 0.95));
  g.addColorStop(1, rgba(CYAN, 0));
  ctx.fillStyle = g;
  ctx.fillRect(Math.min(head, tail), h * 0.5 - h * 0.006, Math.abs(tail - head), h * 0.012);
  bloom(ctx, head, h * 0.5, h * 0.1, WHITE, 0.8 * (1 - clamp01(u - 0.6)));
  // the edge it leaves through flares
  bloom(ctx, 0, h * 0.5, h * 0.5, CYAN, 0.5 * kick(t, ACT.panel, 300));
}

function drawArrival(ctx: CanvasRenderingContext2D, t: number, w: number, h: number): void {
  // a final flash that resolves into her interface
  const k = t < ACT.flash ? smooth((t - ACT.flash + 350) / 350) : Math.exp(-(t - ACT.flash) / 260);
  if (k > 0.01) {
    ctx.fillStyle = rgba(WHITE, k * 0.75);
    ctx.fillRect(0, 0, w, h);
  }
  // a shutter of light along the centre line as it opens
  const open = span(t, ACT.arrival + 500, ACT.flash);
  if (open > 0 && open < 1) {
    const y0 = h / 2 - (h / 2) * open;
    const y1 = h / 2 + (h / 2) * open;
    ctx.fillStyle = rgba(ICE, 0.8 * (1 - open));
    ctx.fillRect(0, y0 - 2, w, 4);
    ctx.fillRect(0, y1 - 2, w, 4);
  }
}

/**
 * How much of her interface the spectacle hides (1 = fully black over it): all of
 * it until the arrival, when a shutter opens from the centre line outward.
 */
export function shutter(t: number): { top: number; bottom: number; alpha: number } {
  const open = span(t, ACT.arrival + 500, ACT.flash);
  return { top: 0.5 - 0.5 * open, bottom: 0.5 + 0.5 * open, alpha: 1 - span(t, ACT.flash, SPECTACLE_MS) };
}

let overlay: { w: number; h: number; vignette: HTMLCanvasElement; lines: HTMLCanvasElement } | null = null;

/** The vignette and the scanline texture, drawn once per canvas size (in its own px,
 *  so they are stamped 1:1 - resampling a full-screen image each frame is slow). */
function overlays(w: number, h: number): NonNullable<typeof overlay> {
  if (overlay && overlay.w === w && overlay.h === h) return overlay;
  const make = (): [HTMLCanvasElement, CanvasRenderingContext2D] => {
    const c = document.createElement("canvas");
    c.width = Math.ceil(w);
    c.height = Math.ceil(h);
    return [c, c.getContext("2d") as CanvasRenderingContext2D];
  };
  const [vignette, v] = make();
  const vg = v.createRadialGradient(w / 2, h / 2, h * 0.3, w / 2, h / 2, w * 0.7);
  vg.addColorStop(0, "rgba(0,0,0,0)");
  vg.addColorStop(1, "rgba(0,0,0,0.65)");
  v.fillStyle = vg;
  v.fillRect(0, 0, w, h);
  const [lines, l] = make();
  l.fillStyle = "rgba(0,0,0,0.12)";
  for (let y = 0; y < h; y += 3) l.fillRect(0, y, w, 1);
  overlay = { w, h, vignette, lines };
  return overlay;
}

/**
 * The whole spectacle at t, into a canvas showing w x h of her interface's px;
 * `scale` is the canvas's own px per interface px (it renders under full size).
 */
export function drawSpectacle(ctx: CanvasRenderingContext2D, t: number, w: number, h: number, scale = 1): void {
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.globalCompositeOperation = "source-over";
  ctx.globalAlpha = 1;
  ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
  ctx.setTransform(scale, 0, 0, scale, 0, 0);
  if (t < 0 || t >= SPECTACLE_MS) return;
  const v = camera(t, w, h);
  const sh = shutter(t);
  // the dark: everything outside the opening shutter (her interface shows through it)
  ctx.fillStyle = `rgba(1,4,7,${sh.alpha.toFixed(3)})`;
  ctx.fillRect(0, 0, w, h * sh.top);
  ctx.fillRect(0, h * sh.bottom, w, h * (1 - sh.bottom));
  if (sh.top >= 0.499) ctx.fillRect(0, h * sh.top, w, h * (sh.bottom - sh.top));
  // vignette, always: the frame is a lens
  const cached = overlays(ctx.canvas.width, ctx.canvas.height);
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.globalAlpha = sh.alpha;
  ctx.drawImage(cached.vignette, 0, 0);
  ctx.globalAlpha = 1;
  ctx.setTransform(scale, 0, 0, scale, 0, 0);

  ctx.globalCompositeOperation = "lighter";
  drawCold(ctx, t, w, h);
  drawStreaks(ctx, v, t);
  drawGrid(ctx, v, t);
  drawGlobe(ctx, v, t);
  drawStreams(ctx, v, t);
  drawSwarm(ctx, v, t);
  drawRings(ctx, v, t);
  drawSweep(ctx, t, w, h);
  ctx.globalCompositeOperation = "source-over";
  for (let i = 0; i < SYSTEMS.length; i += 1) drawSystem(ctx, v, t, i);
  ctx.globalCompositeOperation = "lighter";
  drawCollapse(ctx, t, w, h);
  ctx.globalCompositeOperation = "source-over";
  drawName(ctx, v, t);
  ctx.globalCompositeOperation = "lighter";
  drawBoltIn(ctx, t, w, h);
  drawPanelBolt(ctx, t, w, h);
  drawArrival(ctx, t, w, h);
  ctx.globalCompositeOperation = "source-over";
  // a fine scanline texture over everything
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.globalAlpha = sh.alpha;
  ctx.drawImage(cached.lines, 0, 0);
  ctx.globalAlpha = 1;
}
