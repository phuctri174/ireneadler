// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// Study mode on the matrix (core/irene/study.py): "Irene, go study the Sicilian".
//
// She puts her head down over an open book, a pen hand scribbling along the line she
// is writing, eyes down and sweeping the page, a nod now and then. The subject runs
// along the top; a progress bar along the bottom fills at the rate core says. The
// book's written lines ARE the progress: they fill page by page as the bar does, and
// the pen sits at the end of the line being written.
//
// When he swings at her (a strike event - core decides it is a hit) the bar JUMPS
// - the jumped segment flashes white, sparks fly off its end - and she reacts by
// how many hits it has been, comic throughout:
//
//   ow          (hits 1-2)  a bonk: an impact burst on her head, stars circling it,
//                           her head knocked down into the book; the "bonked" face
//   indignant   (hits 3-4)  head snapped up off the book, an anger mark throbbing,
//                           the pen wagged at him; the "indignant" face
//   uncle       (hits 5+)   waterfall tears onto the page, a white flag waving where
//                           the pen was, her head shaking; the "surrender" face
//
// When the bar fills it flashes, sparkles burst off it, and she looks up, proud.
// Pure drawing: core's "study" messages set the state (studyState) and the scene
// reads it. The overlays (stars, the anger mark, tears, the flag) are shared with
// the three expressions' theatre (led/theatre.ts), drawn bigger on the full face.

import { glyphCells, textWidth, fits } from "../board/font";
import type { Emotion } from "../face/faceState";
import { COLS, FADE, INK, blit, capsule, clamp01, drawShape, ease, easeOutBack, lerp, sprite } from "./grid";
import type { Frame, Ink, Vec } from "./grid";
import { HANDS, drawHand } from "./hands";
import type { MouthShape } from "./face";

const TAU = Math.PI * 2;

export type StudyTier = "ow" | "indignant" | "uncle";

export interface StudyStatus {
  subject: string;
  /** The bar at `at` (0..1), rising `rate` per second. */
  progress: number;
  rate: number;
  at: number;
  hits: number;
  /** The last hit: its tier, when, and the bar just before it jumped. */
  hit?: { tier: StudyTier; at: number; from: number } | null;
  /** The bar filled (performance.now()). */
  doneAt?: number | null;
}

let status: StudyStatus | null = null;

/** What study mode is doing now (null: off). Set from core's "study" messages. */
export function studyState(next: StudyStatus | null): void {
  status = next;
}

export function currentStudy(): StudyStatus | null {
  return status;
}

/** One of core's "study" messages applied to the status. Pure. */
export function studyOn(prev: StudyStatus | null, message: { action: string; subject?: string; progress?: number; rate?: number; hits?: number; tier?: string }, now: number): StudyStatus | null {
  if (message.action === "end") return null;
  const subject = message.subject ?? prev?.subject ?? "";
  const progress = clamp01(message.progress ?? 0);
  const rate = message.rate ?? 0;
  if (message.action === "start") return { subject, progress, rate, at: now, hits: 0, hit: null, doneAt: null };
  if (!prev) return null;
  if (message.action === "hit") {
    const tier = (["ow", "indignant", "uncle"].includes(message.tier ?? "") ? message.tier : "ow") as StudyTier;
    return { ...prev, progress, rate, at: now, hits: message.hits ?? prev.hits + 1, hit: { tier, at: now, from: barAt(prev, now) } };
  }
  if (message.action === "done") return { ...prev, progress: 1, rate: 0, at: now, doneAt: now };
  return { ...prev, progress, rate, at: now };
}

/** The bar's true value at `now`. */
export function barAt(s: StudyStatus, now: number): number {
  return clamp01(s.progress + (s.rate * Math.max(0, now - s.at)) / 1000);
}

// how long each reaction plays, and the bar's jump
export const HIT_MS: Record<StudyTier, number> = { ow: 1700, indignant: 1900, uncle: 2400 };
export const JUMP_MS = 280;
const DONE_MS = 1800;

/** The bar as drawn: a jump eases up from where it was over JUMP_MS. */
export function barShown(s: StudyStatus, now: number): number {
  const real = barAt(s, now);
  if (!s.hit) return real;
  const k = (now - s.hit.at) / JUMP_MS;
  return k >= 1 ? real : lerp(s.hit.from, real, easeOutBack(clamp01(k)));
}

function reaction(s: StudyStatus | null, now: number): { tier: StudyTier; k: number } | null {
  if (!s?.hit || now < s.hit.at) return null;
  const k = now - s.hit.at;
  return k < HIT_MS[s.hit.tier] ? { tier: s.hit.tier, k } : null;
}

// ---- overlays, shared with the full-face theatre (led/theatre.ts) -------------------

const STAR = sprite(["..#..", ".###.", "#####", ".###.", ".#.#."]);
const STAR_SMALL = sprite([".#.", "###", ".#."]);
// the anger mark: four little brackets round a gap, throbbing
const VEIN = sprite(["##.##", "#...#", ".....", "#...#", "##.##"]);

/** Stars circling her head after a bonk: `n` on an ellipse round (cx, cy). */
export function drawOrbit(frame: Frame, cx: number, cy: number, rx: number, ry: number, t: number, n = 3, big = false): void {
  for (let i = 0; i < n; i += 1) {
    const a = (t / 1000) * 1.3 * TAU + (i / n) * TAU;
    const x = cx + Math.cos(a) * rx;
    const y = cy + Math.sin(a) * ry;
    const front = Math.sin(a) > 0;
    const s = big && front ? STAR : STAR_SMALL;
    blit(frame, s, x - (s.w >> 1), y - (s.h >> 1), { ink: INK.amber, alpha: front ? 1 : 0.55, cover: false, fade: FADE.fast });
  }
}

/** The bonk itself: rays bursting from where it landed, over `len` ms. */
export function drawBurst(frame: Frame, c: Vec, t: number, len = 320, size = 1, ink: Ink = INK.white): void {
  if (t < 0 || t > len) return;
  const p = clamp01(t / len);
  for (let ray = 0; ray < 10; ray += 1) {
    const ang = (ray / 10) * TAU + 0.2;
    for (let r = (2 + p * 4) * size; r < (5 + p * 8) * size; r += 1) {
      frame.lighten(Math.round(c.x + Math.cos(ang) * r), Math.round(c.y + Math.sin(ang) * r * 0.75), 1 - p, ink, FADE.fast);
    }
  }
}

/** The anger mark, throbbing at (x, y) - its top-left. */
export function drawVein(frame: Frame, x: number, y: number, t: number, scale = 1): void {
  const pop = easeOutBack(clamp01(t / 220));
  if (pop <= 0.05) return;
  // throbbing: bright, then a beat dimmer
  const throb = Math.sin((t / 1000) * 3.2 * TAU) > -0.2 ? 1 : 0.55;
  blit(frame, VEIN, x, y, { ink: INK.red, scale, alpha: clamp01(pop) * throb, cover: false, fade: FADE.fast });
}

/** Waterfall tears: a stream from (x, y0) pouring down to y1, droplets running down it. */
export function drawTears(frame: Frame, x: number, y0: number, y1: number, t: number, width = 2): void {
  const grow = clamp01(t / 260);
  const bottom = lerp(y0, y1, grow);
  for (let y = Math.round(y0); y <= bottom; y += 1) {
    // droplets: brighter bands running down the stream
    const run = ((y - y0) / 4 - (t / 1000) * 9) % 1;
    const v = 0.45 + 0.55 * (run < 0 ? run + 1 : run);
    for (let dx = 0; dx < width; dx += 1) frame.lighten(Math.round(x + dx + Math.sin(y / 3 + t / 120) * 0.4), y, v, INK.iceCore, FADE.fast);
  }
  if (grow >= 1) {
    // a splash where it lands
    const s = Math.floor(t / 90) % 3;
    frame.lighten(Math.round(x - 1 - s), Math.round(y1), 0.7, INK.iceRing, FADE.fast);
    frame.lighten(Math.round(x + width + s), Math.round(y1), 0.7, INK.iceRing, FADE.fast);
  }
}

/** A white flag on a pole from `base` to `top`, waving. `size` scales the cloth. */
export function drawFlag(frame: Frame, base: Vec, top: Vec, t: number, size = 1, alpha = 1): void {
  drawShape(frame, (px, py) => capsule(px, py, base, top, 0.55), { x0: Math.min(base.x, top.x) - 2, y0: top.y - 2, x1: Math.max(base.x, top.x) + 2, y1: base.y + 2 }, INK.white, alpha * 0.9, FADE.fast, 0.9, 0.9);
  const w = Math.round(12 * size);
  const h = Math.round(8 * size);
  for (let c = 0; c < w; c += 1) {
    for (let r = 0; r < h; r += 1) {
      const wave = Math.sin(c / (2.6 * size) - (t / 1000) * 2.4 * TAU) * (c / w) * 1.6 * size;
      const fx = Math.round(top.x + 1 + c);
      const fy = Math.round(top.y + r + wave);
      const edge = r === 0 || r === h - 1 || c === w - 1;
      frame.cover(fx, fy, (edge ? 1 : 0.75) * alpha, INK.white, FADE.fast);
    }
  }
}

// ---- the scene ----------------------------------------------------------------------

// the compact face (led/face.ts LAYOUTS.compact): eyes 47..61 and 67..81 from row 6
const FACE_CX = 64;
const EYE_L = 54;
const EYE_R = 74;
const HEAD_DOWN = 3;
// the open book, its spine at the face's centre
const BOOK = { x0: 38, x1: 90, y0: 38, y1: 57 };
const LINES_PER_PAGE = 5;
const LINE_Y0 = 41;
const LINE_STEP = 3;
// the bar
const BAR = { x0: 12, x1: 104, y0: 61, y1: 67 };

function nod(t: number): number {
  // a small nod every ~2.6 s - reading, agreeing with the page
  const k = (t % 2600) / 2600;
  return k > 0.82 ? Math.sin(((k - 0.82) / 0.18) * Math.PI) * 1.4 : 0;
}

/** Where the pen is: the end of the line being written (progress through the book). */
function penAt(p: number, t: number): Vec {
  const total = LINES_PER_PAGE * 2;
  const pos = Math.min(total - 0.001, p * total);
  const line = Math.floor(pos);
  const along = pos - line;
  const left = line < LINES_PER_PAGE;
  const x0 = left ? BOOK.x0 + 3 : FACE_CX + 3;
  const x1 = left ? FACE_CX - 3 : BOOK.x1 - 3;
  const y = LINE_Y0 + (line % LINES_PER_PAGE) * LINE_STEP;
  // the scribble: quick little strokes back and forth along the line
  return { x: lerp(x0, x1, along) + Math.sin(t / 60) * 1.2, y: y + Math.sin(t / 43) * 0.6 };
}

function drawBook(frame: Frame, p: number): void {
  const { x0, x1, y0, y1 } = BOOK;
  // the pages: a soft fill, a bright edge, the spine down the middle
  for (let y = y0; y <= y1; y += 1) {
    for (let x = x0; x <= x1; x += 1) {
      const edge = y === y0 || y === y1 || x === x0 || x === x1 || x === FACE_CX;
      frame.cover(x, y, edge ? 0.75 : 0.06, INK.white, FADE.scene);
    }
  }
  // the lines: written ones bright, the rest a faint dotted rule
  const total = LINES_PER_PAGE * 2;
  const pos = p * total;
  for (let line = 0; line < total; line += 1) {
    const left = line < LINES_PER_PAGE;
    const lx0 = left ? x0 + 3 : FACE_CX + 3;
    const lx1 = left ? FACE_CX - 3 : x1 - 3;
    const y = LINE_Y0 + (line % LINES_PER_PAGE) * LINE_STEP;
    const written = clamp01(pos - line);
    for (let x = lx0; x <= lx1; x += 1) {
      const done = (x - lx0) / (lx1 - lx0) <= written;
      if (done) {
        // handwriting: a jittery line with little gaps between "words"
        const word = (x * 7 + line * 13) % 9 === 0;
        if (!word) frame.cover(x, y + (((x * 31 + line * 7) % 5) === 0 ? -1 : 0), 0.85, INK.accent, FADE.scene);
      } else if (x % 3 === 0) {
        frame.cover(x, y, 0.12, INK.white, FADE.scene);
      }
    }
  }
}

function drawBar(frame: Frame, s: StudyStatus, now: number): void {
  const shown = barShown(s, now);
  const { x0, x1, y0, y1 } = BAR;
  for (let x = x0; x <= x1; x += 1) {
    frame.cover(x, y0, 0.5, INK.white, FADE.fast);
    frame.cover(x, y1, 0.5, INK.white, FADE.fast);
  }
  for (let y = y0; y <= y1; y += 1) {
    frame.cover(x0, y, 0.5, INK.white, FADE.fast);
    frame.cover(x1, y, 0.5, INK.white, FADE.fast);
  }
  const fx0 = x0 + 2;
  const fx1 = x1 - 2;
  const end = lerp(fx0, fx1, shown);
  // the jumped segment flashes white for a moment after a hit
  const flash = s.hit ? clamp01(1 - (now - s.hit.at) / 650) : 0;
  const from = s.hit ? lerp(fx0, fx1, s.hit.from) : end;
  const done = s.doneAt != null ? now - s.doneAt : -1;
  for (let x = fx0; x <= end; x += 1) {
    const jumped = flash > 0 && x >= from;
    const shimmer = done >= 0 && done < DONE_MS ? 0.75 + 0.25 * Math.sin(x / 3 - done / 60) : 1;
    for (let y = y0 + 2; y <= y1 - 2; y += 1) frame.cover(x, y, (jumped ? 1 : 0.85) * shimmer, jumped && flash > 0.3 ? INK.white : INK.accent, FADE.fast);
  }
  // the leading edge pulses while it fills
  if (shown < 1) {
    const pulse = 0.6 + 0.4 * Math.sin((now / 1000) * 3 * TAU);
    for (let y = y0 + 1; y <= y1 - 1; y += 1) frame.lighten(Math.round(end) + 1, y, pulse, INK.white, FADE.fast);
  }
  // sparks off the end of a jump
  if (s.hit && now - s.hit.at < 520) {
    const k = (now - s.hit.at) / 520;
    for (let i = 0; i < 5; i += 1) {
      const a = -Math.PI / 2 + (i - 2) * 0.45;
      const r = 2 + k * 9;
      frame.lighten(Math.round(end + Math.cos(a) * r), Math.round(y0 + Math.sin(a) * r), 1 - k, INK.amber, FADE.fast);
    }
  }
  // the percentage, beside the bar
  const pct = `${Math.round(shown * 100)}%`;
  drawText(frame, pct, x1 + 3, y0 + 1, 0.9, INK.white);
  if (done >= 0 && done < DONE_MS) {
    for (let i = 0; i < 6; i += 1) drawBurst(frame, { x: lerp(fx0, fx1, (i + 0.5) / 6), y: (y0 + y1) / 2 }, done - i * 70, 380, 0.8, INK.amber);
  }
}

function drawText(frame: Frame, text: string, x: number, y: number, v: number, ink: Ink): void {
  let cx = x;
  for (const ch of text) {
    for (const c of glyphCells(ch, cx, y)) frame.cover(c.x, c.y, v, ink, FADE.fast);
    cx += textWidth(ch) + 1;
  }
}

/** The subject along the top, upper case, as much as fits. */
function drawSubject(frame: Frame, subject: string): void {
  const clean = subject.toUpperCase().replace(/[^A-Z0-9 '\-.,!?&:]/g, "");
  const max = fits(COLS - 4);
  const text = clean.length > max ? `${clean.slice(0, max - 1).trimEnd()}.` : clean;
  drawText(frame, text, Math.round((COLS - textWidth(text)) / 2), 0, 0.7, INK.white);
}

export interface StudyLook {
  layout: "compact";
  emotion: Emotion;
  mouth?: MouthShape;
  gazeX: number;
  gazeY: number;
  shiftX: number;
  shiftY: number;
  moving?: boolean;
}

/** The face: head down over the book, eyes reading - or the hit's reaction. */
export function studyLook(t: number, now: number): StudyLook {
  const s = status;
  const r = reaction(s, now);
  const reading = Math.sin((t / 1000) * 0.9 * TAU) * 1.5;
  if (s?.doneAt != null) {
    // done: head up off the book, proud, telling him what she learned
    return { layout: "compact", emotion: "proud", gazeX: 0, gazeY: -1, shiftX: 0, shiftY: lerp(HEAD_DOWN, 0, ease(clamp01((now - s.doneAt) / 250))), moving: now - s.doneAt < 250 };
  }
  if (r?.tier === "ow") {
    // knocked down into the book, then wobbling back up, dazed
    const knock = r.k < 120 ? (r.k / 120) * 4 : 4 * (1 - ease((r.k - 120) / 700));
    return { layout: "compact", emotion: "bonked", mouth: r.k < 500 ? "o" : undefined, gazeX: 0, gazeY: 0, shiftX: Math.sin(r.k / 70) * (r.k < 900 ? 1 : 0), shiftY: HEAD_DOWN + knock, moving: r.k < 300 };
  }
  if (r?.tier === "indignant") {
    // snapped up off the book to glare at him, a little huffy shake
    return { layout: "compact", emotion: "indignant", gazeX: 0, gazeY: -1, shiftX: r.k > 200 && r.k < 900 ? Math.sin(r.k / 40) * 0.8 : 0, shiftY: lerp(HEAD_DOWN, -1, ease(clamp01(r.k / 150))), moving: r.k < 200 };
  }
  if (r?.tier === "uncle") {
    // head shaking, slumped, sobbing - theatrically
    return { layout: "compact", emotion: "surrender", gazeX: 0, gazeY: 0, shiftX: Math.sin(r.k / 110) * 2, shiftY: HEAD_DOWN + 1 + Math.abs(Math.sin(r.k / 160)) * 1.2, moving: true };
  }
  return { layout: "compact", emotion: "focused", gazeX: reading, gazeY: 3, shiftX: 0, shiftY: HEAD_DOWN + nod(t) };
}

export function drawStudy(frame: Frame, t: number, now: number): void {
  const s = status;
  if (!s) return;
  const look = studyLook(t, now);
  const shown = barShown(s, now);
  drawSubject(frame, s.subject);
  drawBook(frame, shown);
  const r = reaction(s, now);
  const sx = Math.round(look.shiftX);
  const sy = Math.round(look.shiftY);
  const pen = penAt(shown, t);
  if (r?.tier === "uncle") {
    // the pen dropped; a white flag up instead, waving at him
    drawTears(frame, EYE_L - 1 + sx, 20 + sy, BOOK.y0 - 1, r.k);
    drawTears(frame, EYE_R - 1 + sx, 20 + sy, BOOK.y0 - 1, r.k);
    const up = ease(clamp01(r.k / 300));
    drawFlag(frame, { x: 96, y: 58 }, { x: 99, y: lerp(52, 30, up) }, now, 1, up);
    drawHand(frame, HANDS.fist, { x: 96, y: 56, rot: 10, scale: 0.6 });
  } else if (r?.tier === "indignant") {
    // the pen wagged at him
    const wag = Math.sin(r.k / 70) * 12;
    drawHand(frame, HANDS.point, { x: 98, y: 44, rot: -20 + wag, scale: 0.65 });
    drawVein(frame, EYE_R + 12 + sx, 8 + sy, r.k);
  } else if (s.doneAt != null) {
    // done: the pen put down at the end of the last line
    drawHand(frame, HANDS.point, { x: BOOK.x1 + 6, y: BOOK.y1 - 4, rot: 200, scale: 0.6 });
  } else {
    // writing: the pen hand at the end of the line, a pen stroke off its fingertip
    drawHand(frame, HANDS.point, { x: pen.x + 8, y: pen.y - 5, rot: 215, scale: 0.6 });
    drawShape(frame, (px, py) => capsule(px, py, { x: pen.x + 3, y: pen.y - 3 }, pen, 0.5), { x0: pen.x - 2, y0: pen.y - 6, x1: pen.x + 6, y1: pen.y + 2 }, INK.white, 1, FADE.fast, 0.9, 1);
  }
  if (r?.tier === "ow") {
    drawBurst(frame, { x: FACE_CX + 8 + sx, y: 3 + sy }, r.k, 340);
    if (r.k > 150) drawOrbit(frame, FACE_CX + sx, 3 + sy, 21, 3, r.k);
  }
  drawBar(frame, s, now);
}

export const STUDY_SCENE = { loopMs: 26000, look: (t: number, now = 0) => studyLook(t, now), draw: (frame: Frame, t: number, now = 0) => drawStudy(frame, t, now) };
