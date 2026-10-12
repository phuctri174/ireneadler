// Where each entrance happens, as a place with depth and light rather than a flat
// picture: a gas-lit street, a dojo, a study under one lamp, a theatre stage, open
// ground at dusk. Each is laid out in the same space as her figure (heads, y up from
// the ground) and drawn through the same camera, so when the camera tracks or
// pushes in, the place moves with her - farther things (depth z > 1) move less.
//
// Backdrops stay dim (the figure and the light are what the eye should catch) and
// carry their own light: the lamp, the window shafts, the footlights, the sky.

import { COLS, FADE, INK, ROWS, clamp01, lerp } from "./grid";
import type { Frame, Ink, Vec } from "./grid";
import type { Camera } from "./figure";
import { cone, litShape, polygon } from "./figure";
import { fog, glow, hash, lightCone, motes, noise, pool, vignette } from "./film";

/** A point in the scene at depth z, on screen. */
export function place(cam: Camera, x: number, y: number, z = 1): Vec {
  return { x: 64 + (cam.x - 64) / z + (x * cam.s) / z, y: cam.y - (y * cam.s) / z + (cam.y - 66) * (1 - 1 / z) * 0.4 };
}

function dot(frame: Frame, x: number, y: number, v: number, ink: Ink = INK.cyan): void {
  frame.lighten(Math.round(x), Math.round(y), v, ink, FADE.scene);
}

function line(frame: Frame, a: Vec, b: Vec, v: number, ink: Ink = INK.cyan): void {
  const n = Math.max(1, Math.ceil(Math.hypot(b.x - a.x, b.y - a.y)));
  for (let k = 0; k <= n; k += 1) dot(frame, lerp(a.x, b.x, k / n), lerp(a.y, b.y, k / n), v, ink);
}

function fillPoly(frame: Frame, pts: Vec[], level: number, ink: Ink, rim = 0): void {
  const box = { x0: Math.min(...pts.map((p) => p.x)), y0: Math.min(...pts.map((p) => p.y)), x1: Math.max(...pts.map((p) => p.x)), y1: Math.max(...pts.map((p) => p.y)) };
  for (let r = Math.max(0, Math.floor(box.y0)); r <= Math.min(ROWS - 1, Math.ceil(box.y1)); r += 1) {
    for (let c = Math.max(0, Math.floor(box.x0)); c <= Math.min(COLS - 1, Math.ceil(box.x1)); c += 1) {
      const d = polygon(c + 0.5, r + 0.5, pts);
      if (d > 0.5) continue;
      const v = d > -0.7 && rim > 0 ? rim : level;
      frame.cover(c, r, v * clamp01(0.5 - d + 0.5), ink, FADE.scene);
    }
  }
}

const NO_LIGHT = { dir: { x: 0, y: -1 }, ink: INK.white, power: 0 };

// ---- victorian: a gas-lit street at night - fog, cobbles, a lamp, a carriage passing ----

export const LAMP = { x: -2.9, y: 7.6 };

function gaslight(frame: Frame, t: number, cam: Camera): void {
  // the far side of the street: roofs and chimneys against the night, a few lit windows
  const roofs: Vec[] = [place(cam, -16, 0, 2.6)];
  const skyline = [-16, 6, -13, 6, -13, 7.6, -11.5, 7.6, -11.5, 6.4, -8, 6.4, -8, 9.2, -7.2, 9.2, -7.2, 7.2, -3, 7.2, -3, 8.2, 1, 8.2, 1, 6.6, 4, 6.6, 4, 9.6, 4.8, 9.6, 4.8, 7.4, 9, 7.4, 9, 8.6, 12, 8.6, 12, 6.2, 16, 6.2];
  for (let k = 0; k < skyline.length; k += 2) roofs.push(place(cam, skyline[k], skyline[k + 1], 2.6));
  roofs.push(place(cam, 16, 0, 2.6));
  fillPoly(frame, roofs, 0.05, INK.cyan, 0.1);
  for (let k = 0; k < 18; k += 1) {
    const wx = -15 + k * 1.75;
    const wy = 2.4 + (k % 3) * 1.4;
    if (hash(k * 3.3) < 0.42) continue;
    const p = place(cam, wx, wy, 2.6);
    const flicker = 0.75 + 0.25 * Math.sin(t / 380 + k);
    for (const [dx, dy] of [[0, 0], [1, 0], [0, 1], [1, 1]]) dot(frame, p.x + dx, p.y + dy, 0.22 * flicker, INK.amber);
  }
  // a carriage crosses behind her, right to left, its lantern swinging
  const cx = lerp(13, -15, clamp01((t - 150) / 2700));
  if (cx > -15 && cx < 13) {
    const bob = Math.sin(t / 90) * 0.04;
    const body = [place(cam, cx - 1.2, 1.5 + bob, 1.7), place(cam, cx + 1.3, 1.5 + bob, 1.7), place(cam, cx + 1.2, 3.6 + bob, 1.7), place(cam, cx - 1.0, 3.7 + bob, 1.7)];
    fillPoly(frame, body, 0.07, INK.cyan, 0.16);
    const horse = [place(cam, cx - 3.6, 1.3, 1.7), place(cam, cx - 1.6, 1.4, 1.7), place(cam, cx - 1.7, 2.9, 1.7), place(cam, cx - 3.2, 3.4, 1.7), place(cam, cx - 3.9, 2.6, 1.7)];
    fillPoly(frame, horse, 0.06, INK.cyan, 0.13);
    for (const wx of [cx - 0.7, cx + 0.8]) {
      const w = place(cam, wx, 0.9, 1.7);
      const r = 0.85 * (cam.s / 1.7);
      for (let k = 0; k < 16; k += 1) {
        const a = (k / 16) * Math.PI * 2;
        dot(frame, w.x + Math.cos(a) * r, w.y + Math.sin(a) * r, 0.16);
      }
      for (let k = 0; k < 3; k += 1) {
        const a = -t / 120 + (k * Math.PI) / 3;
        line(frame, { x: w.x - Math.cos(a) * r, y: w.y - Math.sin(a) * r }, { x: w.x + Math.cos(a) * r, y: w.y + Math.sin(a) * r }, 0.09);
      }
    }
    glow(frame, place(cam, cx + 1.45, 3.3 + bob + Math.sin(t / 160) * 0.06, 1.7), 0.7, 0.55, INK.amber, INK.amber);
  }
  // the street: cobbles fading into the dark, wet where the lamp lights them
  for (let r = Math.round(cam.y - 1); r < ROWS; r += 1) {
    const depth = (r - cam.y + 2) / 10;
    for (let c = 0; c < COLS; c += 1) {
      const stagger = (Math.floor(r / 2) % 2) * 2;
      if ((c + stagger) % 4 !== 0 || r % 2 !== 0) continue;
      dot(frame, c, r, 0.06 + depth * 0.05);
    }
  }
  // the lamp: post, lantern, its cone of light and the pool it throws
  const base = place(cam, LAMP.x, 0);
  const head = place(cam, LAMP.x, LAMP.y);
  litShape(frame, (x, y) => cone(x, y, base, place(cam, LAMP.x, LAMP.y - 0.5), 0.13 * cam.s, 0.08 * cam.s), { x0: base.x - 3, y0: head.y, x1: base.x + 3, y1: base.y }, { ink: INK.cyan, fill: 0.14, rim: 0.3 }, NO_LIGHT, 1, false);
  const arm = place(cam, LAMP.x + 0.55, LAMP.y - 0.15);
  line(frame, place(cam, LAMP.x, LAMP.y - 0.4), arm, 0.25);
  const flicker = 0.92 + 0.08 * Math.sin(t / 70) * Math.sin(t / 190);
  lightCone(frame, head, place(cam, LAMP.x + 0.4, 0), 4.4 * cam.s, 0.13 * flicker, INK.amber);
  pool(frame, place(cam, LAMP.x + 0.4, 0.05), 3.2 * cam.s, 0.55 * cam.s, 0.2 * flicker, INK.amber);
  litShape(frame, (x, y) => polygon(x, y, [place(cam, LAMP.x - 0.38, LAMP.y + 0.45), place(cam, LAMP.x + 0.38, LAMP.y + 0.45), place(cam, LAMP.x + 0.26, LAMP.y - 0.4), place(cam, LAMP.x - 0.26, LAMP.y - 0.4)]), { x0: head.x - 6, y0: head.y - 6, x1: head.x + 6, y1: head.y + 6 }, { ink: INK.cyan, fill: 0.1, rim: 0.4 }, NO_LIGHT, 1, false);
  glow(frame, head, Math.max(1, 0.24 * cam.s), 0.95 * flicker, INK.amber, INK.white);
  // fog rolling along the street
  fog(frame, t, Math.round(cam.y - 3.2 * cam.s), Math.round(cam.y + 0.4 * cam.s), 0.16, 1);
  vignette(frame, place(cam, LAMP.x + 1.5, 4).x, 36, 70, 0.25);
}

// ---- the club banner: Đà Lạt Kendo Club, on the dojo wall behind her ----------------
// Traced by hand from the club's logo (an automatic downsample turned the
// kanji and the pine to mush at LED size): a double-line hexagon, point up; 武 inside
// at the top; the pine emblem below it (a fan of petals over scalloped waves); and
// the wordmark beneath in a 3x5 pixel font with its diacritics - Đ with its bar, À
// with its grave above, Ạ with its dot below. White on the club's dark green.

/** 武, hand-pixelled at 13 x 13: the short stroke, the long bar, 止 bottom-left and
 *  弋's sweeping hook to the right with its dot. */
const BU = [
  "..........##.",
  ".#####..#..##",
  "........#....",
  "#############",
  "........##...",
  "..####...#...",
  "...#.....##..",
  "...####...#..",
  ".#.#......##.",
  ".#.#.......#.",
  ".#.#.......##",
  "#######.....#",
  "...........##",
];

/** The 3x5 font for the wordmark (Đ and N are four wide). Diacritics sit in a row
 *  above (À's grave) and below (Ạ's dot) the caps. */
const GLYPH: Record<string, { rows: string[]; above?: string; above2?: string; below?: string }> = {
  "Đ": { rows: [".##.", ".#.#", "####", ".#.#", ".##."] },
  "À": { rows: [".#.", "#.#", "###", "#.#", "#.#"], above: "#.." , above2: ".#." },
  "Ạ": { rows: [".#.", "#.#", "###", "#.#", "#.#"], below: ".#." },
  L: { rows: ["#..", "#..", "#..", "#..", "###"] },
  T: { rows: ["###", ".#.", ".#.", ".#.", ".#."] },
  K: { rows: ["#.#", "#.#", "##.", "#.#", "#.#"] },
  E: { rows: ["###", "#..", "##.", "#..", "###"] },
  N: { rows: ["#..#", "##.#", "#.##", "#..#", "#..#"] },
  D: { rows: ["##.", "#.#", "#.#", "#.#", "##."] },
  O: { rows: [".#.", "#.#", "#.#", "#.#", ".#."] },
  C: { rows: [".##", "#..", "#..", "#..", ".##"] },
  U: { rows: ["#.#", "#.#", "#.#", "#.#", "###"] },
  B: { rows: ["##.", "#.#", "##.", "#.#", "##."] },
};

function textWidth(text: string): number {
  return [...text].reduce((w, ch) => w + (ch === " " ? 2 : GLYPH[ch].rows[0].length) + 1, -1);
}

/** One line of the wordmark, its caps' top-left at (x, y). */
function drawWord(frame: Frame, text: string, x: number, y: number, level: number): void {
  let cx = Math.round(x);
  const cy = Math.round(y);
  const put = (gx: number, gy: number): void => {
    if (gx >= 0 && gx < COLS && gy >= 0 && gy < ROWS) frame.cover(gx, gy, level, INK.white, FADE.scene);
  };
  for (const ch of text) {
    if (ch === " ") {
      cx += 3;
      continue;
    }
    const g = GLYPH[ch];
    g.rows.forEach((row, r) => [...row].forEach((c, k) => c === "#" && put(cx + k, cy + r)));
    // the grave: a two-pixel stroke falling to the right, a row clear of the cap
    if (g.above) [...g.above].forEach((c, k) => c === "#" && put(cx + k, cy - 3));
    if (g.above2) [...g.above2].forEach((c, k) => c === "#" && put(cx + k, cy - 2));
    if (g.below) [...g.below].forEach((c, k) => c === "#" && put(cx + k, cy + 6));
    cx += g.rows[0].length + 1;
  }
}

/** The banner, centred at (cx, cy) on the wall: hexagon half-width `hw` (LEDs). */
export function drawClubBanner(frame: Frame, cx: number, top: number): void {
  const hw = 17; // hexagon half-width (pointy-top: its height is hw * 4 / sqrt 3)
  const hh = (hw * 2) / Math.sqrt(3);
  const hexCy = top + 3 + hh;
  const textY = Math.round(hexCy + hh + 6);
  const fieldW = hw + 6;
  const fieldBottom = textY + 16;
  const field = INK.green;
  // dim beside her (the backdrop is held down again after): she stays the subject
  const ink = 0.78;
  // the field: the club's green, a cloth banner with a slightly darker hem
  for (let r = Math.max(0, Math.floor(top)); r <= Math.min(ROWS - 1, fieldBottom); r += 1) {
    for (let c = Math.max(0, Math.floor(cx - fieldW)); c <= Math.min(COLS - 1, Math.ceil(cx + fieldW)); c += 1) {
      const edge = c === Math.floor(cx - fieldW) || c === Math.ceil(cx + fieldW) || r === fieldBottom;
      frame.cover(c, r, edge ? 0.32 : 0.42, field, FADE.scene);
    }
  }
  // the hexagon's double line, point up: |x| <= half-width, and the slanted edges
  // |y| + |x| / sqrt 3 <= P (P: centre to the top point) - as distances
  const hex = (px: number, py: number, P: number): number => {
    const x = Math.abs(px - cx);
    const y = Math.abs(py - hexCy);
    return Math.max(x - (P * Math.sqrt(3)) / 2, (y + x / Math.sqrt(3) - P) * (Math.sqrt(3) / 2));
  };
  const R = hh;
  for (let r = Math.floor(hexCy - R - 1); r <= Math.ceil(hexCy + R + 1); r += 1) {
    for (let c = Math.floor(cx - hw - 1); c <= Math.ceil(cx + hw + 1); c += 1) {
      const d = hex(c + 0.5, r + 0.5, R);
      const outer = Math.abs(d) < 0.62;
      const inner = Math.abs(d + 2.6) < 0.62;
      if ((outer || inner) && c >= 0 && c < COLS && r >= 0 && r < ROWS) frame.cover(c, r, ink, INK.white, FADE.scene);
    }
  }
  // 武, inside at the top
  const bx = Math.round(cx - 6.5);
  const by = Math.round(hexCy - R + 6);
  BU.forEach((row, rr) => [...row].forEach((ch, k) => ch === "#" && frame.cover(bx + k, by + rr, ink, INK.white, FADE.scene)));
  // the pine: a dome of petals (a half-disc with dark slits fanning from its base),
  // two small fans at the sides, and scalloped waves below
  const py = by + 21;
  const domeR = 7;
  for (let r = py - domeR; r <= py; r += 1) {
    for (let c = Math.round(cx - domeR - 1); c <= Math.round(cx + domeR + 1); c += 1) {
      const dx = c + 0.5 - cx;
      const dy = r + 0.5 - py;
      if (Math.hypot(dx / 1.2, dy / 1.05) > domeR) continue;
      const ang = Math.atan2(-dy, dx);
      // five slits between the petals
      const slit = [0.62, 1.1, 1.57, 2.04, 2.52].some((a) => Math.abs(ang - a) < 0.17 && Math.hypot(dx, dy) > 2.2);
      if (!slit) frame.cover(c, r, ink * 0.92, INK.white, FADE.scene);
      else frame.cover(c, r, 0.42, field, FADE.scene);
    }
  }
  for (const side of [-1, 1]) {
    const fx = cx + side * 10;
    const fy = py - 3;
    for (let r = fy - 3; r <= fy; r += 1) {
      for (let c = Math.round(fx - 3); c <= Math.round(fx + 3); c += 1) {
        const dx = c + 0.5 - fx;
        const dy = r + 0.5 - fy;
        if (Math.hypot(dx, dy) <= 3 && Math.abs(Math.atan2(-dy, dx) - Math.PI / 2) > 0.2) frame.cover(c, r, ink * 0.8, INK.white, FADE.scene);
      }
    }
  }
  // the waves: two rows of small arcs under the dome
  for (const [row, n, off] of [[py + 2, 3, 0], [py + 4, 2, 2.5]] as const) {
    for (let k = 0; k < n; k += 1) {
      const wx = cx - (n - 1) * 2.5 + k * 5 + (off ? 0 : 0);
      for (let a = 0; a <= 8; a += 1) {
        const ang = Math.PI * (a / 8);
        frame.cover(Math.round(wx + Math.cos(ang) * 2), Math.round(row + Math.sin(ang) * 1.3), ink * 0.85, INK.white, FADE.scene);
      }
    }
  }
  // the wordmark: ĐÀ LẠT / KENDO CLUB
  drawWord(frame, "ĐÀ LẠT", cx - textWidth("ĐÀ LẠT") / 2, textY + 2, ink);
  // two clear rows under LẠT's dot, so it reads as Ạ's and not as a mark on KENDO
  drawWord(frame, "KENDO CLUB", cx - textWidth("KENDO CLUB") / 2, textY + 11, ink * 0.9);
}

// ---- kendo: a dojo - a board floor, shoji, a scroll, light shafts through high windows --

function dojo(frame: Frame, t: number, cam: Camera): void {
  // the back wall: pillars and shoji panels, softly lit from outside
  for (let k = -5; k <= 5; k += 1) {
    const x = k * 3.4;
    const top = place(cam, x, 11, 1.8);
    const bottom = place(cam, x, 0, 1.8);
    line(frame, top, bottom, 0.18);
    line(frame, { x: top.x + 1, y: top.y }, { x: bottom.x + 1, y: bottom.y }, 0.1);
  }
  line(frame, place(cam, -18, 8.3, 1.8), place(cam, 18, 8.3, 1.8), 0.2);
  // the scroll on the wall: a hanging strip with three brush strokes
  const s0 = place(cam, 4.6, 7.4, 1.8);
  const s1 = place(cam, 6.0, 2.2, 1.8);
  fillPoly(frame, [s0, { x: s1.x, y: s0.y }, s1, { x: s0.x, y: s1.y }], 0.09, INK.white, 0.2);
  const mid = (s0.x + s1.x) / 2;
  for (const [y0, y1, w] of [[0.2, 0.32, 0.5], [0.42, 0.62, 0.35], [0.7, 0.86, 0.45]]) {
    line(frame, { x: mid - 1, y: lerp(s0.y, s1.y, y0) }, { x: mid + w, y: lerp(s0.y, s1.y, y1) }, 0.3, INK.red);
  }
  // the club's banner, centred on the wall behind her (a little parallax as the
  // camera pushes in)
  drawClubBanner(frame, place(cam, 0.6, 0, 1.8).x, 3 + (cam.y - 66) * 0.4);
  // the floor: boards running away, a sheen where the light falls
  for (let r = Math.round(cam.y); r < ROWS; r += 1) {
    const depth = clamp01((r - cam.y) / 8);
    for (let c = 0; c < COLS; c += 1) {
      const board = Math.abs(((c - 64 + (c - 64) * depth * 0.6) % 7) + 7) % 7 < 1;
      if (board) dot(frame, c, r, 0.08 + depth * 0.06);
    }
  }
  line(frame, { x: 0, y: cam.y }, { x: COLS - 1, y: cam.y }, 0.22);
  // shafts of light through the high windows, dust turning in them
  for (const [wx, k] of [[-6, 0], [1, 1], [8, 2]] as const) {
    const from = place(cam, wx, 11.5, 1.8);
    const to = place(cam, wx + 3.2, 0, 1);
    lightCone(frame, from, to, 2.4 * cam.s, 0.08 + 0.02 * Math.sin(t / 900 + k), INK.white);
    motes(frame, t, 6, 40 + k * 9, { x0: Math.min(from.x, to.x), y0: from.y, x1: Math.max(from.x, to.x) + 6, y1: to.y }, 0.28, INK.white, -0.003);
  }
  vignette(frame, 64, 34, 72, 0.3);
}

// ---- chess: a study at night - one lamp over the table, books in the dark -------------

export const TABLE = { x0: 0.5, x1: 5.2, top: 2.55 };

function study(frame: Frame, t: number, cam: Camera): void {
  // shelves of books, barely there
  for (let shelf = 0; shelf < 4; shelf += 1) {
    const y = 1.2 + shelf * 2.3;
    line(frame, place(cam, -12, y, 1.9), place(cam, 12, y, 1.9), 0.12);
    for (let k = 0; k < 40; k += 1) {
      if (hash(k + shelf * 41) < 0.2) continue;
      const x = -11.8 + k * 0.6;
      const h = 1.2 + hash(k * 7 + shelf) * 0.8;
      const lean = hash(k * 13 + shelf) < 0.1 ? 0.3 : 0;
      line(frame, place(cam, x, y + 0.1, 1.9), place(cam, x + lean, y + h, 1.9), 0.05 + hash(k * 3 + shelf) * 0.05, hash(k * 5 + shelf) < 0.25 ? INK.amber : INK.cyan);
    }
  }
  // the lamp hangs over the table on its cord, swaying a touch
  const swing = Math.sin(t / 1100) * 0.18;
  const mount = place(cam, (TABLE.x0 + TABLE.x1) / 2, 11);
  const shadeAt = place(cam, (TABLE.x0 + TABLE.x1) / 2 + swing, 6.2);
  line(frame, mount, shadeAt, 0.2);
  lightCone(frame, shadeAt, place(cam, (TABLE.x0 + TABLE.x1) / 2 + swing * 2.2, TABLE.top), 5.4 * cam.s, 0.11, INK.amber);
  pool(frame, place(cam, (TABLE.x0 + TABLE.x1) / 2 + swing * 2.2, TABLE.top + 0.05), 2.9 * cam.s, 0.35 * cam.s, 0.28, INK.amber);
  litShape(frame, (x, y) => polygon(x, y, [place(cam, (TABLE.x0 + TABLE.x1) / 2 + swing - 0.2, 6.6), place(cam, (TABLE.x0 + TABLE.x1) / 2 + swing + 0.2, 6.6), place(cam, (TABLE.x0 + TABLE.x1) / 2 + swing + 0.75, 5.9), place(cam, (TABLE.x0 + TABLE.x1) / 2 + swing - 0.75, 5.9)]), { x0: shadeAt.x - 10, y0: shadeAt.y - 6, x1: shadeAt.x + 10, y1: shadeAt.y + 4 }, { ink: INK.amber, fill: 0.2, rim: 0.6 }, NO_LIGHT, 1, false);
  glow(frame, place(cam, (TABLE.x0 + TABLE.x1) / 2 + swing, 5.85), Math.max(1, 0.15 * cam.s), 0.9, INK.amber, INK.white);
  motes(frame, t, 10, 77, { x0: shadeAt.x - 18, y0: shadeAt.y, x1: shadeAt.x + 18, y1: place(cam, 0, TABLE.top).y }, 0.22, INK.amber, -0.002);
  // the floor
  line(frame, { x: 0, y: cam.y }, { x: COLS - 1, y: cam.y }, 0.14);
  vignette(frame, shadeAt.x - 8, place(cam, 0, TABLE.top).y - 6, 64, 0.18);
}

// ---- cards: a theatre stage - curtains, a valance, footlights, a polished floor ---------

function stage(frame: Frame, t: number, cam: Camera): void {
  // the curtains, gathered at the sides: folds of light and shadow in red
  for (const side of [-1, 1]) {
    for (let r = 0; r < ROWS; r += 1) {
      for (let c = 0; c < COLS; c += 1) {
        const x = side < 0 ? c : COLS - 1 - c;
        const edge = 26 + Math.sin(r / 9) * 2 - (r / ROWS) * 8;
        if (x > edge) continue;
        const fold = 0.5 + 0.5 * Math.sin((x + Math.sin(r / 11 + t / 1600) * 1.5) / 2.1);
        const v = 0.05 + fold * 0.16 * (0.55 + 0.45 * (x / edge));
        frame.lighten(c, r, v, INK.red, FADE.scene);
      }
    }
  }
  // the valance across the top, scalloped
  for (let c = 0; c < COLS; c += 1) {
    const depth = 6 + Math.abs(Math.sin(c / 6)) * 2.5;
    for (let r = 0; r < depth; r += 1) frame.lighten(c, r, 0.12 + (r > depth - 1.5 ? 0.12 : 0), INK.red, FADE.scene);
    if (c % 6 === 3) frame.lighten(c, Math.round(depth), 0.35, INK.amber, FADE.scene);
  }
  // the floor: boards and the glint of footlights along its edge
  for (let r = Math.round(cam.y); r < ROWS; r += 1) {
    for (let c = 0; c < COLS; c += 6) dot(frame, c + ((r * 2) % 6), r, 0.07);
  }
  line(frame, { x: 0, y: cam.y }, { x: COLS - 1, y: cam.y }, 0.16, INK.amber);
  for (let k = 0; k < 9; k += 1) dot(frame, 8 + k * 14, ROWS - 2, 0.3 + 0.1 * Math.sin(t / 200 + k), INK.amber);
  vignette(frame, 64, 40, 70, 0.4);
}

// ---- energy wave: open ground at dusk - a low sky, far mountains, wind ----------------

export const HORIZON = 4.2;

function ground(frame: Frame, t: number, cam: Camera): void {
  const horizon = place(cam, 0, HORIZON, 3).y;
  // the last light of the sky, low along the horizon
  for (let r = 0; r < Math.min(ROWS, horizon); r += 1) {
    const k = clamp01(1 - (horizon - r) / 26);
    for (let c = 0; c < COLS; c += 1) frame.lighten(c, r, 0.03 + k * k * 0.16, k > 0.6 ? INK.amber : INK.cyan, FADE.scene);
  }
  // two ranges of mountains, the far one paler
  for (const [z, h, seed, level] of [[4.5, 3.4, 3, 0.07], [2.6, 2.0, 9, 0.1]] as const) {
    const pts: Vec[] = [{ x: -1, y: ROWS }];
    for (let k = 0; k <= 32; k += 1) {
      const x = -20 + k * 1.25;
      const y = HORIZON + h * (0.35 + 0.65 * noise(k / 3 + seed, seed));
      pts.push(place(cam, x, y, z));
    }
    pts.push({ x: COLS, y: ROWS });
    fillPoly(frame, pts, level * 0.6, INK.cyan, level * 1.6);
  }
  // the ground: dark, a few stones, grass bent by the wind
  for (let r = Math.max(0, Math.round(horizon)); r < ROWS; r += 1) {
    for (let c = 0; c < COLS; c += 1) frame.cover(c, r, Math.min(frame.value[r * COLS + c], 0.04), INK.cyan, FADE.scene);
  }
  line(frame, { x: 0, y: horizon }, { x: COLS - 1, y: horizon }, 0.12, INK.amber);
  for (let k = 0; k < 26; k += 1) {
    const x = -14 + hash(k) * 28;
    const z = 1 + hash(k * 3) * 1.6;
    const g = place(cam, x, 0, z);
    if (g.y < horizon) continue;
    const bend = Math.sin(t / 260 + k) * 1.2 + 1.6;
    line(frame, g, { x: g.x + bend, y: g.y - 2.4 / z }, 0.14, INK.cyan);
  }
  line(frame, { x: 0, y: cam.y }, { x: COLS - 1, y: cam.y }, 0.1);
  // the wind, streaking past low
  for (let k = 0; k < 7; k += 1) {
    const y = horizon + 3 + hash(k * 5) * (ROWS - horizon - 4);
    const x = ((hash(k) * 160 - t * (0.05 + hash(k * 2) * 0.04)) % 160 + 160) % 160 - 16;
    line(frame, { x, y }, { x: x + 6 + hash(k * 9) * 6, y }, 0.12, INK.white);
  }
  vignette(frame, 64, horizon, 80, 0.35);
}

export const BACKDROPS = { gaslight, dojo, study, stage, ground };

export type BackdropName = keyof typeof BACKDROPS;

/**
 * The place, drawn first into an empty shot and then held down to 60%: dim and
 * quiet, so she is always the brightest, clearest thing in the frame.
 */
export function drawBackdrop(frame: Frame, name: BackdropName, t: number, cam: Camera): void {
  BACKDROPS[name](frame, t, cam);
  for (let i = 0; i < frame.value.length; i += 1) frame.value[i] *= BACKDROP_LEVEL;
}

const BACKDROP_LEVEL = 0.6;
