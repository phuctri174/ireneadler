// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// A manga speech bubble for her domain expansion's last word (a skit line's
// "domain": {"bubble": "..."}, core/irene/skit.py): a classic comic balloon with a
// tail, her words inside in heavy display type, cyan and ice-blue like the rest of
// the domain. It snaps in on the eye's reveal - small, overshooting, a shake - with
// speed lines radiating behind it, holds, then fades.
//
// It sits along the top of the matrix, over her white hair - the one strip the
// domain doesn't need - so her face, the revealed eye and the black hole stay clear.
// The tail points down between her eyes; the speed lines stay above them.

import { glyphCells, textWidth } from "../board/font";
import { COLS, FADE, INK, clamp01, ease, easeOutBack, lerp } from "./grid";
import type { Frame, Ink } from "./grid";

const SIZE = 2; // the board font, every cell doubled: heavy display letters
const LETTER_H = 5 * SIZE;
const PAD_X = 4;
const PAD_Y = 2;
const CENTER = { x: COLS / 2, y: 7 };
// nothing of it below this row: her eyes start just under it (domain-lowered)
const FLOOR_Y = 19;
const SNAP_MS = 260;
const SHAKE_MS = 220;
const FLASH_MS = 140;
const FADE_MS = 420;

interface Shape {
  hw: number;
  hh: number;
  radius: number;
  tail: [number, number][];
  text: Set<string>;
}

const shapes = new Map<string, Shape>();

function shapeFor(words: string): Shape {
  const text = words.toUpperCase();
  const known = shapes.get(text);
  if (known) return known;
  const w = textWidth(text, SIZE);
  const hw = Math.min(COLS / 2 - 3, w / 2 + PAD_X);
  const hh = LETTER_H / 2 + PAD_Y;
  const cells = new Set<string>();
  let x = -Math.floor(w / 2);
  for (const ch of text) {
    for (const c of glyphCells(ch, x, -LETTER_H / 2, SIZE)) cells.add(`${c.x},${c.y}`);
    x += textWidth(ch, SIZE) + SIZE;
  }
  // the tail: off the bottom edge, pointing down between her eyes (never at the
  // revealed one, on the left)
  const tail: [number, number][] = [
    [2, hh - 1],
    [9, hh - 1],
    [1, hh + 6],
  ];
  const shape = { hw, hh, radius: 6, tail, text: cells };
  shapes.set(text, shape);
  return shape;
}

function inBox(x: number, y: number, s: Shape): boolean {
  const qx = Math.abs(x) - (s.hw - s.radius);
  const qy = Math.abs(y) - (s.hh - s.radius);
  return Math.hypot(Math.max(qx, 0), Math.max(qy, 0)) + Math.min(Math.max(qx, qy), 0) <= s.radius;
}

function inTail(x: number, y: number, t: [number, number][]): boolean {
  const [a, b, c] = t;
  const side = (p: [number, number], q: [number, number]) => (q[0] - p[0]) * (y - p[1]) - (q[1] - p[1]) * (x - p[0]);
  const d1 = side(a, b);
  const d2 = side(b, c);
  const d3 = side(c, a);
  return !((d1 < 0 || d2 < 0 || d3 < 0) && (d1 > 0 || d2 > 0 || d3 > 0));
}

function hash(n: number): number {
  const s = Math.sin(n * 91.7 + 17.3) * 43758.5453;
  return s - Math.floor(s);
}

/**
 * The bubble, `t` ms after the reveal, held `hold` ms. Drawn last, over her face's
 * lower half (the summon's scene owns the matrix while it plays).
 */
export function drawBubble(frame: Frame, words: string, t: number, hold: number): void {
  if (!words || t < 0 || t > hold + FADE_MS) return;
  const s = shapeFor(words);
  const alpha = 1 - ease((t - hold) / FADE_MS);
  // snap: from small, overshooting, settling - with a short sideways shake
  const scale = lerp(0.45, 1, easeOutBack(clamp01(t / SNAP_MS)));
  const shake = t < SHAKE_MS ? Math.sin(t * 0.13) * 1.6 * (1 - t / SHAKE_MS) : 0;
  const flash = t < FLASH_MS ? 1 - t / FLASH_MS : 0;
  const cx = CENTER.x + shake;
  const cy = CENTER.y;
  const local = (x: number, y: number): [number, number] => [(x + 0.5 - cx) / scale, (y + 0.5 - cy) / scale];
  const inside = (x: number, y: number): boolean => {
    const [u, v] = local(x, y);
    return inBox(u, v, s) || inTail(u, v, s.tail);
  };

  // speed lines, radiating from behind it: hard at the snap, then a faint flicker
  const power = (t < 380 ? 1 : 0.32 + 0.12 * Math.sin(t / 90)) * alpha;
  const grow = ease(clamp01(t / 300));
  for (let k = 0; k < 32; k += 1) {
    const a = (k / 32) * Math.PI * 2 + hash(k) * 0.12;
    const dx = Math.cos(a);
    const dy = Math.sin(a);
    // from the balloon's edge (an ellipse round it) outward
    const edge = 1 / Math.hypot(dx / (s.hw * scale + 2), dy / (s.hh * scale + 2));
    const length = (5 + 14 * hash(k + 40)) * grow;
    const ink: Ink = k % 2 ? INK.cyan : INK.iceRing;
    for (let d = 0; d < length; d += 0.6) {
      const x = Math.round(cx + dx * (edge + d));
      const y = Math.round(cy + dy * (edge + d));
      if (x < 0 || x >= COLS || y < 0 || y >= FLOOR_Y || inside(x, y)) continue;
      frame.lighten(x, y, power * (0.85 - 0.6 * (d / Math.max(1, length))), ink, FADE.fast);
    }
  }

  // the balloon: its glow, its border, its dark fill, the words
  const x0 = Math.max(0, Math.floor(cx - (s.hw + 2) * 1.12));
  const x1 = Math.min(COLS - 1, Math.ceil(cx + (s.hw + 2) * 1.12));
  const y0 = Math.max(0, Math.floor(cy + (-s.hh - 2) * 1.12));
  const y1 = Math.min(FLOOR_Y + 1, Math.ceil(cy + (s.hh + 8) * 1.12));
  const set = (x: number, y: number, level: number, ink: Ink): void => {
    const i = y * COLS + x;
    frame.value[i] = frame.value[i] * (1 - alpha) + level * alpha;
    if (alpha > 0.3) frame.ink[i] = ink;
    frame.fade[i] = FADE.fast;
  };
  for (let y = y0; y <= y1; y += 1) {
    for (let x = x0; x <= x1; x += 1) {
      const isIn = inside(x, y);
      const edgeOut = !inside(x - 1, y) || !inside(x + 1, y) || !inside(x, y - 1) || !inside(x, y + 1);
      if (!isIn) {
        // a soft cyan glow round the outline, like the LEDs bleeding
        if (inside(x - 1, y) || inside(x + 1, y) || inside(x, y - 1) || inside(x, y + 1)) {
          frame.lighten(x, y, (0.3 + 0.4 * flash) * alpha, INK.cyan, FADE.fast);
        }
        continue;
      }
      if (edgeOut) {
        set(x, y, 1, flash > 0.3 ? INK.white : INK.iceCore);
        continue;
      }
      const [u, v] = local(x, y);
      const tu = Math.floor(u);
      const tv = Math.floor(v);
      if (s.text.has(`${tu},${tv}`)) {
        set(x, y, 1, INK.iceCore);
      } else if (s.text.has(`${tu - 1},${tv - 1}`)) {
        // a hard drop shadow under each letter: weight, as display type has
        set(x, y, 0.28, INK.cyan);
      } else {
        // the balloon's dark inside (the face under it gone), flashing white on impact
        set(x, y, 0.04 + 0.4 * flash, INK.white);
      }
    }
  }
}
