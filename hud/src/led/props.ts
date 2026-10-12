// Tool props: what Irene holds or looks at while a tool runs - a magnifier over
// his screen, a folder of his files, a page she reads, a clock, headphones, a
// globe for the browser. Core names the prop with the tool's status (tools/:
// Tool.cue); each is a looping scene (led/scenes.ts registers them) with the
// same two halves: look(t), the face it wears, and draw(frame, t).

import { EYE_H, EYE_Y, MOUTH_H, MOUTH_W, MOUTH_X, MOUTH_Y } from "./face";
import { FADE, INK, blit, capsule, clamp01, drawShape, roundBox, sprite } from "./grid";
import type { Frame, Ink, Vec } from "./grid";
import type { SceneLook } from "./scenes";

const TAU = Math.PI * 2;

function circle(p: Vec, c: Vec, r: number): number {
  return Math.hypot(p.x - c.x, p.y - c.y) - r;
}

function around(c: Vec, r: number) {
  return { x0: c.x - r - 2, y0: c.y - r - 2, x1: c.x + r + 2, y1: c.y + r + 2 };
}

/** Pixel-thin ring, lightened in (no fill): a lens, a clock face, a globe. */
function ring(frame: Frame, c: Vec, r: number, level: number, ink: Ink, fill: number | null = null): void {
  drawShape(frame, (x, y) => circle({ x, y }, c, r), around(c, r), ink, 1, FADE.fast, level, fill);
}

function line(frame: Frame, a: Vec, b: Vec, width: number, level: number, ink: Ink): void {
  drawShape(
    frame,
    (x, y) => capsule(x, y, a, b, width),
    { x0: Math.min(a.x, b.x) - 3, y0: Math.min(a.y, b.y) - 3, x1: Math.max(a.x, b.x) + 3, y1: Math.max(a.y, b.y) + 3 },
    ink,
    1,
    FADE.fast,
    level,
    level,
  );
}

// ---- magnifier: screen capture -------------------------------------------------

const LENS_R = 10;
const lensAt = (t: number): Vec => ({ x: 64 + Math.sin((t / 2400) * TAU) * 34, y: EYE_Y + EYE_H / 2 + Math.sin((t / 1200) * TAU) * 2 });

function magnifier(frame: Frame, t: number): void {
  const c = lensAt(t);
  // the glass: a faint fill so the eye behind reads as magnified, under a bright rim
  drawShape(frame, (x, y) => circle({ x, y }, c, LENS_R), around(c, LENS_R), INK.white, 1, FADE.fast, 1, null);
  drawShape(frame, (x, y) => circle({ x, y }, c, LENS_R - 1.3), around(c, LENS_R), INK.white, 1, FADE.fast, 0.35, null);
  const handleFrom = { x: c.x + LENS_R * 0.72, y: c.y + LENS_R * 0.72 };
  line(frame, handleFrom, { x: handleFrom.x + 11, y: handleFrom.y + 11 }, 1.6, 0.9, INK.amber);
  // glint
  frame.lighten(Math.round(c.x - 4), Math.round(c.y - 5), 1, INK.white, FADE.fast);
  frame.lighten(Math.round(c.x - 5), Math.round(c.y - 4), 0.8, INK.white, FADE.fast);
}

function magnifierLook(t: number): SceneLook {
  return { emotion: "curious", gazeX: clamp01((lensAt(t).x - 30) / 68) * 6 - 3 };
}

// ---- folder: his files -------------------------------------------------------------

const FOLDER = { x: 96, y: 46, w: 26, h: 18 };
const PAPER = sprite(["#######", "#-----#", "#-###-#", "#-----#", "#-###-#", "#-----#", "#-##--#", "#######"]);

function folder(frame: Frame, t: number): void {
  const f = FOLDER;
  // the back and its tab
  drawShape(frame, (x, y) => roundBox(x, y, { x: f.x + 5, y: f.y - 2 }, 5, 2, 1), { x0: f.x - 1, y0: f.y - 6, x1: f.x + 12, y1: f.y + 2 }, INK.amber, 1, FADE.prop, 0.9, 0.3);
  drawShape(frame, (x, y) => roundBox(x, y, { x: f.x + f.w / 2, y: f.y + f.h / 2 }, f.w / 2, f.h / 2, 1.5), { x0: f.x - 1, y0: f.y - 1, x1: f.x + f.w + 1, y1: f.y + f.h + 1 }, INK.amber, 1, FADE.prop, 0.7, 0.12);
  // two papers take turns rising out of it and sinking back
  for (let k = 0; k < 2; k += 1) {
    const phase = ((t + k * 900) % 1800) / 1800;
    const rise = Math.sin(phase * Math.PI);
    blit(frame, PAPER, f.x + 5 + k * 9, f.y - 2 - rise * 9, { ink: INK.white, fade: FADE.fast });
  }
  // the front flap, in front of the papers
  drawShape(frame, (x, y) => roundBox(x, y, { x: f.x + f.w / 2, y: f.y + f.h / 2 + 3 }, f.w / 2 + 1, f.h / 2 - 2, 1.5), { x0: f.x - 2, y0: f.y + 2, x1: f.x + f.w + 2, y1: f.y + f.h + 2 }, INK.amber, 1, FADE.prop, 1, 0.2);
}

function folderLook(t: number): SceneLook {
  return { emotion: "curious", gazeX: 3, gazeY: 3 + Math.round(Math.sin((t / 900) * TAU)) };
}

// ---- reading: a document she reads through -----------------------------------------

const PAGE = { x: MOUTH_X - 4, y: MOUTH_Y - 3, w: MOUTH_W + 8, h: MOUTH_H + 14 };
const LINE_MS = 700;

function reading(frame: Frame, t: number): void {
  const p = PAGE;
  drawShape(frame, (x, y) => roundBox(x, y, { x: p.x + p.w / 2, y: p.y + p.h / 2 }, p.w / 2, p.h / 2, 1.5), { x0: p.x - 1, y0: p.y - 1, x1: p.x + p.w + 1, y1: p.y + p.h + 1 }, INK.white, 1, FADE.prop, 0.8, 0.06);
  // lines of text scrolling up, the one she's on brighter
  const scroll = (t / LINE_MS) % 1;
  const current = Math.floor(t / LINE_MS);
  for (let k = 0; k < 6; k += 1) {
    const y = Math.round(p.y + 4 + k * 4 - scroll * 4);
    if (y < p.y + 2 || y > p.y + p.h - 3) continue;
    const n = (current + k) % 12;
    const length = 18 + ((n * 7919) % 17);
    const bright = k === 1;
    for (let x = p.x + 4; x < p.x + 4 + length && x < p.x + p.w - 3; x += 1) {
      // word gaps
      if ((x * 13 + n * 5) % 9 === 0) continue;
      frame.cover(x, y, bright ? 0.85 : 0.35, INK.white, FADE.fast);
    }
  }
}

function readingLook(t: number): SceneLook {
  // eyes sweep along the line, then snap back for the next
  const along = (t % LINE_MS) / LINE_MS;
  return { emotion: "neutral", mouth: "hidden", gazeY: 3, gazeX: Math.round(along * 6 - 3) };
}

// ---- clock: the time, a timer -----------------------------------------------------

const CLOCK = { x: 110, y: 44, r: 12 };

function clockProp(frame: Frame, t: number): void {
  const c = { x: CLOCK.x, y: CLOCK.y };
  ring(frame, c, CLOCK.r, 1, INK.white, 0.08);
  for (let h = 0; h < 12; h += 1) {
    const a = (h / 12) * TAU;
    const r = h % 3 === 0 ? CLOCK.r - 3 : CLOCK.r - 2;
    frame.lighten(Math.round(c.x + Math.sin(a) * r), Math.round(c.y - Math.cos(a) * r), h % 3 === 0 ? 1 : 0.5, INK.white, FADE.fast);
  }
  const minute = (t / 2000) * TAU;
  const hour = (t / 24000) * TAU;
  line(frame, c, { x: c.x + Math.sin(minute) * 9, y: c.y - Math.cos(minute) * 9 }, 0.7, 1, INK.amber);
  line(frame, c, { x: c.x + Math.sin(hour) * 5.5, y: c.y - Math.cos(hour) * 5.5 }, 0.9, 0.9, INK.white);
}

function clockLook(t: number): SceneLook {
  // glances at the clock and back
  const glance = Math.sin((t / 2000) * TAU) > -0.3;
  return { emotion: "curious", gazeX: glance ? 3 : 0, gazeY: glance ? 1 : 0 };
}

// ---- headphones: music, volume, videos ---------------------------------------------

const NOTE = sprite(["..##", "..#.", "..#.", "###.", "###."]);

function headphones(frame: Frame, t: number): void {
  const bob = Math.round(Math.sin((t / 500) * TAU) * 0.8);
  // the band over the top of her head
  for (let a = 0; a <= 180; a += 1.5) {
    const r = (a * Math.PI) / 180;
    const x = 64 - Math.cos(r) * 43;
    const y = 30 - Math.sin(r) * 27 + bob;
    frame.lighten(Math.round(x), Math.round(y), 0.9, INK.white, FADE.fast);
    frame.lighten(Math.round(x), Math.round(y) + 1, 0.4, INK.white, FADE.fast);
  }
  for (const x of [19, 109]) {
    drawShape(frame, (px, py) => roundBox(px, py, { x, y: 32 + bob }, 5, 8, 3), { x0: x - 7, y0: 22 + bob, x1: x + 7, y1: 42 + bob }, INK.accent, 1, FADE.fast, 1, 0.35);
  }
  // notes drift up and away
  for (let k = 0; k < 3; k += 1) {
    const phase = ((t + k * 667) % 2000) / 2000;
    const alpha = Math.sin(phase * Math.PI);
    blit(frame, NOTE, 112 + k * 4 + Math.sin(phase * 6 + k) * 2, 20 - phase * 18, { ink: INK.pink, alpha, cover: false, fade: FADE.fast });
  }
}

function headphonesLook(t: number): SceneLook {
  return { emotion: "happy", gazeY: Math.round(Math.sin((t / 500) * TAU) * 0.8) };
}

// ---- globe: her browser -----------------------------------------------------------

const GLOBE = { x: 110, y: 44, r: 12 };

function globe(frame: Frame, t: number): void {
  const c = { x: GLOBE.x, y: GLOBE.y };
  ring(frame, c, GLOBE.r, 1, INK.accent, 0.1);
  // meridians sweep round as it spins; the equator and two parallels stay
  const spin = (t / 3000) * TAU;
  for (let m = 0; m < 3; m += 1) {
    const w = Math.cos(spin + (m * Math.PI) / 3) * GLOBE.r;
    for (let y = -GLOBE.r + 1; y < GLOBE.r; y += 0.5) {
      const x = w * Math.sqrt(1 - (y / GLOBE.r) ** 2);
      frame.lighten(Math.round(c.x + x), Math.round(c.y + y), 0.45, INK.accent, FADE.fast);
    }
  }
  for (const lat of [-6, 0, 6]) {
    const half = Math.sqrt(GLOBE.r ** 2 - lat ** 2);
    for (let x = -half; x <= half; x += 1) frame.lighten(Math.round(c.x + x), c.y + lat, lat === 0 ? 0.7 : 0.35, INK.accent, FADE.fast);
  }
}

function globeLook(t: number): SceneLook {
  return { emotion: "curious", gazeX: 3, gazeY: Math.sin((t / 1500) * TAU) > 0 ? 1 : 0 };
}

// ---- chip: reading his PC's load ---------------------------------------------------

const CHIP = { x: 110, y: 44, half: 8 };

function chip(frame: Frame, t: number): void {
  const c = { x: CHIP.x, y: CHIP.y };
  drawShape(frame, (x, y) => roundBox(x, y, c, CHIP.half, CHIP.half, 1.5), around(c, CHIP.half + 1), INK.white, 1, FADE.prop, 0.9, 0.1);
  // pins on all four sides
  for (let k = -6; k <= 6; k += 3) {
    for (let p = 1; p <= 3; p += 1) {
      frame.lighten(c.x + k, c.y - CHIP.half - p, 0.6, INK.white, FADE.prop);
      frame.lighten(c.x + k, c.y + CHIP.half + p, 0.6, INK.white, FADE.prop);
      frame.lighten(c.x - CHIP.half - p, c.y + k, 0.6, INK.white, FADE.prop);
      frame.lighten(c.x + CHIP.half + p, c.y + k, 0.6, INK.white, FADE.prop);
    }
  }
  // activity lights inside, flickering like load
  const tick = Math.floor(t / 150) % 8;
  for (let row = 0; row < 3; row += 1) {
    for (let col = 0; col < 3; col += 1) {
      const on = Math.sin(row * 7.1 + col * 3.3 + tick * 1.7) > 0;
      frame.lighten(c.x - 4 + col * 4, c.y - 4 + row * 4, on ? 1 : 0.2, row === 0 ? INK.amber : INK.accent, FADE.fast);
    }
  }
}

function chipLook(t: number): SceneLook {
  return { emotion: "curious", gazeX: 3, gazeY: Math.sin((t / 1200) * TAU) > 0 ? 1 : 0 };
}

export const PROPS = {
  chip: { loopMs: 1200, look: chipLook, draw: chip },
  magnifier: { loopMs: 2400, look: magnifierLook, draw: magnifier },
  folder: { loopMs: 1800, look: folderLook, draw: folder },
  reading: { loopMs: LINE_MS * 12, look: readingLook, draw: reading },
  clock: { loopMs: 24000, look: clockLook, draw: clockProp },
  headphones: { loopMs: 2000, look: headphonesLook, draw: headphones },
  globe: { loopMs: 3000, look: globeLook, draw: globe },
};
