// The film grammar of the entrances, shared by all of them: each one is shot like a
// scene from a film, the way the domain expansion is staged - a build-up, a peak, a
// settle - rather than a loop.
//
//   - a SHOT is drawn into its own frame (backdrop, her figure, effects) and laid
//     over her face with an opacity, so a shot can fade up from black and, at the
//     end, cut to her face in close-up
//   - letterbox bars slide in for the shot and out for the close-up
//   - light: vignettes, light cones and pools, fog, a flash at the peak
//   - a camera shake on an impact, decaying
//
// Everything is a pure function of t, so a frame can be drawn at any moment.

import { COLS, FADE, INK, ROWS, Frame, clamp01, ease, lerp } from "./grid";
import type { Ink, Vec } from "./grid";

export const LETTERBOX_ROWS = 5;

/** 0..1 over [a, b], eased. */
export function span(t: number, a: number, b: number): number {
  return ease((t - a) / (b - a));
}

/** 1 inside [a, b], easing in over `fadeIn` and out over `fadeOut`. */
export function window01(t: number, a: number, b: number, fadeIn: number, fadeOut: number): number {
  return Math.min(span(t, a, a + fadeIn), 1 - span(t, b - fadeOut, b));
}

export function hash(n: number): number {
  const s = Math.sin(n * 127.1 + 311.7) * 43758.5453;
  return s - Math.floor(s);
}

/** Smooth value noise, 0..1. */
export function noise(x: number, y: number): number {
  const xi = Math.floor(x);
  const yi = Math.floor(y);
  const xf = x - xi;
  const yf = y - yi;
  const h = (i: number, j: number): number => hash(i * 57.13 + j * 311.7);
  const u = xf * xf * (3 - 2 * xf);
  const v = yf * yf * (3 - 2 * yf);
  return lerp(lerp(h(xi, yi), h(xi + 1, yi), u), lerp(h(xi, yi + 1), h(xi + 1, yi + 1), u), v);
}

// ---- the shot ----------------------------------------------------------------------

const shot = new Frame();

/** A cleared frame to draw a shot into (one, reused: entrances draw one at a time). */
export function begin(): Frame {
  shot.clear();
  shot.fade.fill(FADE.fast);
  return shot;
}

/**
 * Lay the shot over what is already drawn (her face) at `alpha`: 1 hides the face
 * completely, 0 leaves it. A cell takes the shot's colour where the shot wins.
 */
export function composite(frame: Frame, src: Frame, alpha: number): void {
  const a = clamp01(alpha);
  if (a <= 0) return;
  for (let i = 0; i < frame.value.length; i += 1) {
    const under = frame.value[i] * (1 - a);
    const over = src.value[i] * a;
    frame.value[i] = under + over;
    if (over >= under) {
      frame.ink[i] = src.ink[i];
      frame.fade[i] = src.fade[i];
    }
  }
}

/** Everything darker by k (a fade from or to black). */
export function dim(frame: Frame, k: number): void {
  const m = clamp01(k);
  for (let i = 0; i < frame.value.length; i += 1) frame.value[i] *= m;
}

/** Cinema bars, top and bottom; `amount` 0..1 slides them in. */
export function letterbox(frame: Frame, amount: number, rows = LETTERBOX_ROWS): void {
  const k = Math.round(rows * clamp01(amount));
  for (let r = 0; r < k; r += 1) {
    for (let c = 0; c < COLS; c += 1) {
      frame.cover(c, r, 0, INK.accent, FADE.fast);
      frame.cover(c, ROWS - 1 - r, 0, INK.accent, FADE.fast);
    }
  }
}

/** Darker toward the edges, around (cx, cy). */
export function vignette(frame: Frame, cx: number, cy: number, reach: number, floor = 0.15): void {
  for (let r = 0; r < ROWS; r += 1) {
    for (let c = 0; c < COLS; c += 1) {
      const d = Math.hypot((c - cx) / 1.6, r - cy) / reach;
      frame.value[r * COLS + c] *= lerp(1, floor, clamp01(d * d));
    }
  }
}

/** A flash over the whole frame at the peak: everything lifted toward `ink`. */
export function flash(frame: Frame, amount: number, ink: Ink = INK.white): void {
  const a = clamp01(amount);
  if (a <= 0) return;
  for (let i = 0; i < frame.value.length; i += 1) {
    const v = frame.value[i] + (1 - frame.value[i]) * a * 0.75;
    if (a > 0.35) frame.ink[i] = ink;
    frame.value[i] = v;
    frame.fade[i] = FADE.fast;
  }
}

/** A decaying shake after each impact time: the camera's offset, in LEDs. */
export function shake(t: number, impacts: readonly number[], power = 1.6, ms = 380): Vec {
  let x = 0;
  let y = 0;
  for (const at of impacts) {
    const u = (t - at) / ms;
    if (u < 0 || u > 1) continue;
    const k = power * (1 - u) ** 2;
    x += Math.sin(t / 23 + at) * k;
    y += Math.cos(t / 17 + at * 1.3) * k * 0.7;
  }
  return { x, y };
}

// ---- light and atmosphere -------------------------------------------------------------

/** A cone of light from `from`, spreading `width` LEDs wide by the time it reaches `to`. */
export function lightCone(frame: Frame, from: Vec, to: Vec, width: number, level: number, ink: Ink): void {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const len = Math.hypot(dx, dy) || 1;
  const ux = dx / len;
  const uy = dy / len;
  for (let r = 0; r < ROWS; r += 1) {
    for (let c = 0; c < COLS; c += 1) {
      const px = c + 0.5 - from.x;
      const py = r + 0.5 - from.y;
      const along = px * ux + py * uy;
      if (along < 0 || along > len) continue;
      const across = Math.abs(px * -uy + py * ux);
      const half = 0.8 + (width / 2) * (along / len);
      if (across > half + 1) continue;
      const edge = clamp01(half + 0.5 - across) * (1 - (across / (half + 1)) ** 2);
      const v = level * edge * (0.55 + 0.45 * (along / len));
      frame.lighten(c, r, v, ink, FADE.idle);
    }
  }
}

/** A soft pool of light on the ground, an ellipse (rx, ry). */
export function pool(frame: Frame, c: Vec, rx: number, ry: number, level: number, ink: Ink): void {
  for (let r = Math.max(0, Math.floor(c.y - ry - 1)); r <= Math.min(ROWS - 1, c.y + ry + 1); r += 1) {
    for (let col = Math.max(0, Math.floor(c.x - rx - 1)); col <= Math.min(COLS - 1, c.x + rx + 1); col += 1) {
      const d = Math.hypot((col + 0.5 - c.x) / rx, (r + 0.5 - c.y) / ry);
      if (d < 1) frame.lighten(col, r, level * (1 - d * d), ink, FADE.idle);
    }
  }
}

/** A glowing point: a bright core and a soft halo (a lamp, an eye, a spark). */
export function glow(frame: Frame, c: Vec, radius: number, level: number, ink: Ink, core: Ink = INK.white): void {
  const reach = radius * 2.6;
  for (let r = Math.floor(c.y - reach); r <= Math.ceil(c.y + reach); r += 1) {
    for (let col = Math.floor(c.x - reach); col <= Math.ceil(c.x + reach); col += 1) {
      const d = Math.hypot(col + 0.5 - c.x, r + 0.5 - c.y);
      if (d > reach) continue;
      const inner = d < radius;
      const v = inner ? level : level * 0.55 * (1 - (d - radius) / (reach - radius)) ** 2;
      if (inner) frame.cover(col, r, Math.max(v, 0), d < radius * 0.55 ? core : ink, FADE.fast);
      else frame.lighten(col, r, v, ink, FADE.fast);
    }
  }
}

/** Fog drifting across rows [y0, y1]: soft, moving, never solid. */
export function fog(frame: Frame, t: number, y0: number, y1: number, level: number, drift = 1): void {
  for (let r = Math.max(0, y0); r <= Math.min(ROWS - 1, y1); r += 1) {
    const depth = (r - y0) / Math.max(1, y1 - y0);
    for (let c = 0; c < COLS; c += 1) {
      const n = noise(c / 11 + (t / 1400) * drift, r / 4.5) * noise(c / 23 - (t / 2600) * drift, r / 7 + 3.1);
      const v = level * clamp01(n * 2.2 - 0.25) * (0.4 + 0.6 * Math.sin(depth * Math.PI));
      frame.lighten(c, r, v, INK.white, FADE.idle);
    }
  }
}

/** Specks drifting through a beam of light or a room (dust, embers, snow). */
export function motes(frame: Frame, t: number, count: number, seed: number, area: { x0: number; y0: number; x1: number; y1: number }, level: number, ink: Ink, rise = -0.004): void {
  for (let k = 0; k < count; k += 1) {
    const w = area.x1 - area.x0;
    const h = area.y1 - area.y0;
    const x = area.x0 + ((hash(k + seed) * w + Math.sin(t / 900 + k) * 3) % w + w) % w;
    const y = area.y0 + ((hash(k * 7 + seed) * h + t * rise * (0.5 + hash(k * 3 + seed))) % h + h) % h;
    const tw = 0.5 + 0.5 * Math.sin(t / 300 + k * 2.1);
    frame.lighten(Math.round(x), Math.round(y), level * tw, ink, FADE.fast);
  }
}

/** Sparks flung out from c, starting at `at`: fast, falling, fading. */
export function sparks(frame: Frame, t: number, at: number, c: Vec, count: number, speed: number, seed: number, ink: Ink = INK.white): void {
  const u = (t - at) / 700;
  if (u < 0 || u > 1) return;
  for (let k = 0; k < count; k += 1) {
    const ang = hash(k + seed) * Math.PI * 2;
    const v = speed * (0.4 + 0.6 * hash(k * 5 + seed));
    const x = c.x + Math.cos(ang) * v * u * 20;
    const y = c.y + Math.sin(ang) * v * u * 12 + u * u * 9;
    const level = (1 - u) ** 1.5;
    frame.lighten(Math.round(x), Math.round(y), level, ink, FADE.fast);
    // a short streak behind it
    frame.lighten(Math.round(x - Math.cos(ang) * 1.2), Math.round(y - Math.sin(ang) * 0.8), level * 0.5, ink, FADE.fast);
  }
}

/** The end of every entrance: ~`ms` before its end, the shot gives way to her face. */
export function cutToFace(t: number, at: number, ms = 260): number {
  return 1 - clamp01((t - at) / ms);
}
