// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// Activity scenes on the matrix. Each is a looping timeline with two halves: a
// pure look(t) - the expression the face wears at that moment, needed before the
// face is drawn - and draw(frame, t), which paints in front of the face. The face
// keeps running underneath: scenes sit in front of part of it (a board over her
// mouth, a grille over her eyes), never replace it.

import { FADE, INK, ROWS, blit, capsule, clamp01, drawShape, ease, lerp, roundBox, sprite } from "./grid";
import type { Frame, Ink, Vec } from "./grid";
import { HANDS, drawHand } from "./hands";
import type { Expression } from "./poses";
import { PROPS } from "./props";
import { drawBackdrop } from "./backdrops";
import { STUDY_SCENE } from "./study";
import { glyphCells, textWidth } from "../board/font";

export interface SceneLook extends Expression {
  /** Eye colour override for a flash (kendo kiai). */
  eyeInk?: Ink;
}

// ---- chess -------------------------------------------------------------------------

const SQUARE = 4;
const BOARD_X = 48;
const BOARD_Y = 39;
const BOARD = SQUARE * 8;

type Piece = "pawn" | "rook" | "knight" | "bishop" | "queen" | "king";

const GLYPH: Record<Piece, ReturnType<typeof sprite>> = {
  pawn: sprite(["....", ".##.", ".##.", "...."]),
  rook: sprite(["#..#", "####", ".##.", "####"]),
  knight: sprite([".##.", "###.", ".##.", "####"]),
  bishop: sprite([".#..", ".##.", ".##.", "####"]),
  queen: sprite(["#..#", ".##.", ".##.", "####"]),
  king: sprite([".#..", "###.", ".#..", "####"]),
};

interface Man {
  piece: Piece;
  mine: boolean;
  row: number;
  col: number;
}

// row 0 is the far rank (her opponent's side)
const START: Man[] = [
  { piece: "king", mine: false, row: 0, col: 4 },
  { piece: "rook", mine: false, row: 0, col: 0 },
  { piece: "pawn", mine: false, row: 1, col: 5 },
  { piece: "pawn", mine: false, row: 1, col: 6 },
  { piece: "pawn", mine: false, row: 1, col: 7 },
  { piece: "knight", mine: false, row: 2, col: 2 },
  { piece: "pawn", mine: false, row: 2, col: 3 },
  { piece: "king", mine: true, row: 7, col: 6 },
  { piece: "rook", mine: true, row: 7, col: 5 },
  { piece: "pawn", mine: true, row: 6, col: 5 },
  { piece: "pawn", mine: true, row: 6, col: 6 },
  { piece: "pawn", mine: true, row: 6, col: 7 },
  { piece: "bishop", mine: true, row: 4, col: 2 },
  { piece: "knight", mine: true, row: 4, col: 4 },
];

// her bishop takes f7 with check, then the king takes the bishop back
const HER_MOVE = { from: { row: 4, col: 2 }, to: { row: 1, col: 5 } };
const REPLY = { from: { row: 0, col: 4 }, to: { row: 1, col: 5 } };

const T = {
  study: 1500,
  think: 3300,
  reach: 3800,
  moved: 4800,
  captured: 5100,
  withdrawn: 5600,
  pleased: 7400,
  replied: 8400,
  worried: 10400,
};

const squareXY = (row: number, col: number): Vec => ({ x: BOARD_X + col * SQUARE, y: BOARD_Y + row * SQUARE });

function drawBoard(frame: Frame): void {
  for (let row = -1; row <= BOARD; row += 1) {
    for (let col = -1; col <= BOARD; col += 1) {
      const x = BOARD_X + col;
      const y = BOARD_Y + row;
      const edge = row === -1 || col === -1 || row === BOARD || col === BOARD;
      if (edge) {
        frame.cover(x, y, 0.45, INK.accent, FADE.scene);
        continue;
      }
      const light = (Math.floor(row / SQUARE) + Math.floor(col / SQUARE)) % 2 === 0;
      frame.cover(x, y, light ? 0.1 : 0.02, INK.white, FADE.scene);
    }
  }
}

function drawMan(frame: Frame, man: Man, at: Vec, alpha = 1, lifted = false): void {
  blit(frame, GLYPH[man.piece], at.x, at.y - (lifted ? 1 : 0), {
    ink: man.mine ? INK.accent : INK.white,
    alpha,
    fade: FADE.fast,
  });
}

function burst(frame: Frame, c: Vec, t: number): void {
  // ring expanding from the square's centre, fading as it goes
  const radius = 1 + t * 7;
  const level = (1 - t) * 0.9;
  for (let a = 0; a < 24; a += 1) {
    const ang = (a / 24) * Math.PI * 2;
    frame.lighten(Math.round(c.x + Math.cos(ang) * radius), Math.round(c.y + Math.sin(ang) * radius), level, INK.white, FADE.fast);
  }
}

function sameSquare(man: Man, sq: { row: number; col: number }): boolean {
  return man.row === sq.row && man.col === sq.col;
}

function chess(frame: Frame, t: number): void {
  drawBoard(frame);
  const slide = ease((t - T.reach) / (T.moved - T.reach));
  const replySlide = ease((t - (T.replied - 1000)) / 1000);
  const moverStart = squareXY(HER_MOVE.from.row, HER_MOVE.from.col);
  const moverEnd = squareXY(HER_MOVE.to.row, HER_MOVE.to.col);
  const replyStart = squareXY(REPLY.from.row, REPLY.from.col);
  const moverAt = { x: lerp(moverStart.x, moverEnd.x, slide), y: lerp(moverStart.y, moverEnd.y, slide) };

  for (const man of START) {
    const isMover = sameSquare(man, HER_MOVE.from) && man.mine;
    const isVictim = sameSquare(man, HER_MOVE.to) && !man.mine;
    const isReplier = sameSquare(man, REPLY.from) && !man.mine;
    if (isVictim && t >= T.moved) continue;
    if (isMover) {
      if (t >= T.replied) continue; // taken back
      drawMan(frame, man, moverAt, 1, t >= T.reach && t < T.moved);
      continue;
    }
    if (isReplier) {
      const at = { x: lerp(replyStart.x, moverEnd.x, replySlide), y: lerp(replyStart.y, moverEnd.y, replySlide) };
      drawMan(frame, man, at, 1, replySlide > 0 && replySlide < 1);
      continue;
    }
    drawMan(frame, man, squareXY(man.row, man.col));
  }

  // her hand carries the bishop
  if (t >= T.reach - 500 && t < T.withdrawn) {
    const inT = ease((t - (T.reach - 500)) / 500);
    const outT = ease((t - T.captured) / (T.withdrawn - T.captured));
    const grip = { x: moverAt.x + 7, y: moverAt.y + 9 };
    const away = { x: 112, y: 84 };
    const x = lerp(lerp(away.x, grip.x, inT), away.x, outT);
    const y = lerp(lerp(away.y, grip.y, inT), away.y, outT);
    drawHand(frame, HANDS.fist, { x, y, rot: -30, scale: 0.6, fade: FADE.fast });
  }
  const end = { x: moverEnd.x + 2, y: moverEnd.y + 2 };
  if (t >= T.moved && t < T.moved + 500) burst(frame, end, (t - T.moved) / 500);
  if (t >= T.replied && t < T.replied + 500) burst(frame, end, (t - T.replied) / 500);
  if (t >= T.study && t < T.think) thinkingDots(frame, t);
}

function chessLook(t: number): SceneLook {
  if (t < T.study) return { emotion: "curious", mouth: "hidden", gazeY: 3 };
  if (t < T.think) return { emotion: "curious", mouth: "hidden", gazeY: -2 };
  if (t < T.withdrawn) return { emotion: "neutral", mouth: "hidden", gazeY: 3 };
  if (t < T.pleased) return { emotion: "happy", mouth: "hidden", gazeY: 0 };
  if (t < T.replied) return { emotion: "curious", mouth: "hidden", gazeY: 3 };
  if (t < T.worried) return { emotion: "concerned", mouth: "hidden", gazeY: 2 };
  return { emotion: "confused", mouth: "hidden", gazeY: 1 };
}

function thinkingDots(frame: Frame, t: number): void {
  const step = Math.floor(t / 260) % 4;
  for (let dot = 0; dot < 3; dot += 1) {
    const x = 58 + dot * 5;
    const v = step === dot ? 0.95 : 0.25;
    for (let dy = 0; dy < 2; dy += 1) for (let dx = 0; dx < 2; dx += 1) frame.lighten(x + dx, 4 + dy, v, INK.amber, FADE.fast);
  }
}

// ---- kendo -------------------------------------------------------------------------
//
// Chibi Irene in full bogu, three-quarter view turned to the LEFT: a big men
// (grille, flaps, throat guard), a short body in a do, tare at the waist, a wide
// pleated hakama, white keikogi sleeves down to the kote. Kamae with the right
// foot forward and the left heel raised, both hands on the tsuka - left low by
// the waist, right ahead - and the shinai up and forward at an imagined
// opponent's head. Strike: raise overhead -> step in with the right foot while
// cutting down-forward -> hold at the hit -> back to kamae. Everything faces left.

const ARMOUR = INK.white;
// a shinai is long: it reaches well past her men at kamae (it was 52, a stick)
const SHINAI_LENGTH = 64;
// body parts, in the kamae position; the step shifts them all left
const HELMET = { x: 56, y: 17, rx: 21, ry: 17 };
const OPENING = { x: 50, y: 18, rx: 15, ry: 13 }; // the grille's face opening, turned left
const GRILLE_BARS = [8, 12, 16, 20, 24, 28];
const SHOULDER_FRONT = { x: 49, y: 38 }; // her right, nearer the opponent
const SHOULDER_BACK = { x: 66, y: 38 };
const DO = { x: 58, y: 44, hw: 11, hh: 8 };
const TARE_Y = 52;
const HAKAMA = { top: 54, bottom: ROWS - 3, x: 58, topHalf: 12, bottomHalf: 20, lean: -2 };
const STEP = 6; // how far the body moves in on the strike

interface Stance {
  hilt: Vec; // butt end of the tsuka
  /** Degrees clockwise from straight up. */
  angle: number;
  /** Body offset to the left (the step in). */
  step: number;
}

// kamae: tip up and forward at head height of an opponent on the left
const KAMAE: Stance = { hilt: { x: 62, y: 48 }, angle: -63, step: 0 };
// furikaburi: both hands up over the men, blade back over her head
const RAISED: Stance = { hilt: { x: 66, y: 9 }, angle: 35, step: 0 };
// the hit: stepped in, blade cutting down-forward onto the opponent's men
const STRUCK: Stance = { hilt: { x: 55, y: 40 }, angle: -72, step: STEP };

const K = { raise: 1600, raised: 2400, strike: 2650, struck: 2850, impact: 3400, returned: 4400 };

function mix(a: Stance, b: Stance, t: number): Stance {
  return {
    hilt: { x: lerp(a.hilt.x, b.hilt.x, t), y: lerp(a.hilt.y, b.hilt.y, t) },
    angle: lerp(a.angle, b.angle, t),
    step: lerp(a.step, b.step, t),
  };
}

function stanceAt(t: number): Stance {
  if (t < K.raise) {
    const breathe = Math.sin((t / 1000) * Math.PI * 1.4) * 0.6;
    return { ...KAMAE, hilt: { x: KAMAE.hilt.x, y: KAMAE.hilt.y + breathe } };
  }
  if (t < K.raised) return mix(KAMAE, RAISED, ease((t - K.raise) / (K.raised - K.raise)));
  if (t < K.strike) return RAISED;
  if (t < K.struck) return mix(RAISED, STRUCK, clamp01((t - K.strike) / (K.struck - K.strike)));
  if (t < K.impact) return STRUCK;
  if (t < K.returned) return mix(STRUCK, KAMAE, ease((t - K.impact) / (K.returned - K.impact)));
  return KAMAE;
}

function direction(angle: number): Vec {
  const rad = (angle * Math.PI) / 180;
  return { x: Math.sin(rad), y: -Math.cos(rad) };
}

function tipOf(s: Stance): Vec {
  const dir = direction(s.angle);
  return { x: s.hilt.x + dir.x * SHINAI_LENGTH, y: s.hilt.y + dir.y * SHINAI_LENGTH };
}

function handsOf(s: Stance): { back: Vec; front: Vec; dir: Vec } {
  const dir = direction(s.angle);
  return {
    dir,
    back: { x: s.hilt.x + dir.x * 2.5, y: s.hilt.y + dir.y * 2.5 }, // left hand, at the butt
    front: { x: s.hilt.x + dir.x * 11, y: s.hilt.y + dir.y * 11 }, // right hand, just behind the tsuba
  };
}

function box(a: Vec, b: Vec, pad: number) {
  return { x0: Math.min(a.x, b.x) - pad, y0: Math.min(a.y, b.y) - pad, x1: Math.max(a.x, b.x) + pad, y1: Math.max(a.y, b.y) + pad };
}

/** A white keikogi sleeve from shoulder to wrist - it shows between do and kote. */
function drawSleeve(frame: Frame, shoulder: Vec, wrist: Vec, fade: number): void {
  drawShape(frame, (x, y) => capsule(x, y, shoulder, wrist, 2.6), box(shoulder, wrist, 4), INK.white, 1, fade, 0.7, 0.22);
}

/** Padded glove on the grip: a mitt across the tsuka and a cuff back along the arm. */
function drawKote(frame: Frame, at: Vec, along: Vec, elbow: Vec, fade: number): void {
  const toArm = { x: elbow.x - at.x, y: elbow.y - at.y };
  const len = Math.hypot(toArm.x, toArm.y) || 1;
  const cuffEnd = { x: at.x + (toArm.x / len) * 4.5, y: at.y + (toArm.y / len) * 4.5 };
  const bounds = { x0: at.x - 8, y0: at.y - 8, x1: at.x + 8, y1: at.y + 8 };
  drawShape(frame, (x, y) => capsule(x, y, at, cuffEnd, 2.2), bounds, ARMOUR, 1, fade, 0.7, 0.16);
  const across = { x: -along.y * 1.1, y: along.x * 1.1 };
  drawShape(
    frame,
    (x, y) => capsule(x, y, { x: at.x - across.x, y: at.y - across.y }, { x: at.x + across.x, y: at.y + across.y }, 2.3),
    bounds,
    INK.accent,
    1,
    fade,
    1,
    0.3,
  );
}

/**
 * A shinai from the butt of the hilt along `dir`, every part in proportion: the
 * tsuka (leather grip, a quarter of the length, with its butt cap), the tsuba and
 * its tsubadome stopper, the bamboo shaft tapering toward the tip, the nakayui tie
 * a quarter of the way back from the tip, and the sakigawa ending in the kensen.
 */
export function drawShinaiParts(frame: Frame, hilt: Vec, dir: Vec, length: number, alpha: number, fade: number): void {
  const at = (f: number): Vec => ({ x: hilt.x + dir.x * length * f, y: hilt.y + dir.y * length * f });
  const across = (v: Vec, w: number): [Vec, Vec] => [
    { x: v.x - dir.y * w, y: v.y + dir.x * w },
    { x: v.x + dir.y * w, y: v.y - dir.x * w },
  ];
  const tip = at(1);
  const bounds = box(hilt, tip, 5);
  const part = (a: Vec, b: Vec, r: number, ink: Ink, rim: number, fill: number): void =>
    drawShape(frame, (x, y) => capsule(x, y, a, b, r), bounds, ink, alpha, fade, rim, fill);
  const tsuba = at(0.24);
  // the shaft: four bamboo staves, tapering from the tsuba to the tip
  part(at(0.27), at(0.62), 1.0, INK.white, 0.85, 0.4);
  part(at(0.62), at(0.94), 0.8, INK.white, 0.85, 0.4);
  // sakigawa: the leather cap, brighter, and the kensen - the very tip - brightest
  part(at(0.94), tip, 1.05, INK.white, 1, 0.75);
  part(tip, tip, 1.2, INK.white, 1, 1);
  // nakayui: the leather tie round the staves, a quarter of the way from the tip
  const [n1, n2] = across(at(0.75), 1.8);
  part(n1, n2, 0.65, INK.amber, 1, 0.9);
  // tsuka: the leather-sleeved grip, thicker than the blade, a cap at the butt
  part(hilt, tsuba, 1.3, INK.white, 0.8, 0.5);
  part(hilt, hilt, 1.6, INK.white, 0.9, 0.7);
  // tsubadome, then the tsuba itself across the blade
  const [d1, d2] = across(at(0.265), 1.6);
  part(d1, d2, 0.6, INK.amber, 0.6, 0.5);
  const [t1, t2] = across(tsuba, 3.2);
  part(t1, t2, 0.95, INK.amber, 1, 1);
}

function drawShinai(frame: Frame, s: Stance, alpha: number, fade: number): void {
  drawShinaiParts(frame, s.hilt, direction(s.angle), SHINAI_LENGTH, alpha, fade);
}

function drawHakamaAndFeet(frame: Frame, step: number, lunge: number, fade: number): void {
  const h = HAKAMA;
  const cx = h.x - step;
  // a trapezoid, widening to the floor and leaning a touch toward the opponent
  drawShape(
    frame,
    (x, y) => {
      const t = clamp01((y - h.top) / (h.bottom - h.top));
      const half = lerp(h.topHalf, h.bottomHalf, t);
      const mid = cx + h.lean * t;
      return Math.max(Math.abs(x - mid) - half, h.top - y, y - h.bottom);
    },
    { x0: cx - h.bottomHalf - 3, y0: h.top - 1, x1: cx + h.bottomHalf + 3, y1: h.bottom + 1 },
    ARMOUR,
    1,
    fade,
    0.6,
    0.1,
  );
  // pleats
  for (const off of [-10, -4, 3, 9]) {
    for (let y = h.top + 2; y < h.bottom; y += 1) {
      const t = (y - h.top) / (h.bottom - h.top);
      frame.cover(Math.round(cx + h.lean * t + off * lerp(1, 1.5, t)), y, 0.3, ARMOUR, fade);
    }
  }
  // right foot forward (to the left), flat; left foot back with the heel raised
  const front = { x: cx - 16 - lunge, y: ROWS - 2 };
  drawShape(frame, (x, y) => capsule(x, y, { x: front.x - 4, y: front.y }, { x: front.x + 3, y: front.y }, 1.2), box(front, front, 7), ARMOUR, 1, fade, 0.8, 0.3);
  const back = { x: cx + 17, y: ROWS - 2 };
  drawShape(frame, (x, y) => capsule(x, y, { x: back.x - 3, y: back.y }, { x: back.x + 3, y: back.y - 3 }, 1.2), box(back, back, 7), ARMOUR, 1, fade, 0.8, 0.3);
}

function drawTare(frame: Frame, step: number): void {
  const cx = HAKAMA.x - step;
  for (let x = cx - 14; x <= cx + 14; x += 1) frame.cover(x, TARE_Y, 0.6, ARMOUR, FADE.scene);
  // three flaps, the near ones longer, quilted
  for (const flap of [{ x: cx - 13, w: 8 }, { x: cx - 4, w: 8 }, { x: cx + 5, w: 7 }]) {
    for (let y = TARE_Y + 1; y < TARE_Y + 8; y += 1) {
      frame.cover(flap.x, y, 0.55, ARMOUR, FADE.scene);
      frame.cover(flap.x + flap.w, y, 0.55, ARMOUR, FADE.scene);
      for (let x = flap.x + 1; x < flap.x + flap.w; x += 1) {
        frame.cover(x, y, (y - TARE_Y) % 3 === 0 ? 0.25 : 0.1, ARMOUR, FADE.scene);
      }
    }
  }
}

function drawDo(frame: Frame, step: number): void {
  const c = { x: DO.x - step, y: DO.y };
  drawShape(frame, (x, y) => roundBox(x, y, c, DO.hw, DO.hh, 5), { x0: c.x - DO.hw - 2, y0: c.y - DO.hh - 2, x1: c.x + DO.hw + 2, y1: c.y + DO.hh + 2 }, ARMOUR, 1, FADE.scene, 0.75, 0.12);
  for (const dy of [-4, -1]) {
    for (let x = c.x - DO.hw + 4; x <= c.x + DO.hw - 4; x += 1) {
      const bow = Math.round((((x - c.x) / DO.hw) ** 2) * -1.5);
      frame.cover(x, c.y + dy + bow, 0.35, ARMOUR, FADE.scene);
    }
  }
}

function drawMen(frame: Frame, step: number): void {
  const hx = HELMET.x - step;
  const ox = OPENING.x - step;
  const ellipse = (x: number, y: number): number =>
    (Math.hypot((x - hx) / HELMET.rx, (y - HELMET.y) / HELMET.ry) - 1) * Math.min(HELMET.rx, HELMET.ry);
  drawShape(frame, ellipse, { x0: hx - HELMET.rx - 2, y0: 0, x1: hx + HELMET.rx + 2, y1: HELMET.y + HELMET.ry + 2 }, ARMOUR, 1, FADE.scene, 0.55, null);
  // mengane over the face opening, turned toward the left
  for (const y of GRILLE_BARS) {
    const half = OPENING.rx * Math.sqrt(Math.max(0, 1 - ((y - OPENING.y) / OPENING.ry) ** 2));
    for (let x = Math.round(ox - half); x <= Math.round(ox + half); x += 1) frame.cover(x, y, 0.45, ARMOUR, FADE.scene);
  }
  for (let y = OPENING.y - OPENING.ry + 2; y <= OPENING.y + OPENING.ry - 1; y += 1) frame.cover(ox - 3, y, 0.55, ARMOUR, FADE.scene);
  // men-dare: the far flap hangs behind her (right), the near one is short
  for (let k = 0; k <= 14; k += 1) {
    const y = 24 + k;
    frame.cover(Math.round(hx + 15 + k * 0.5), y, 0.5, ARMOUR, FADE.scene);
    frame.cover(Math.round(hx + 21 + k * 0.5), y + 1, 0.35, ARMOUR, FADE.scene);
    if (k % 4 === 0) for (let q = 1; q < 6; q += 1) frame.cover(Math.round(hx + 15 + k * 0.5) + q, y + 1, 0.22, ARMOUR, FADE.scene);
  }
  for (let k = 0; k <= 6; k += 1) frame.cover(Math.round(hx - 19 - k * 0.3), 27 + k, 0.4, ARMOUR, FADE.scene);
  // tsuki-dare under the chin
  const throat = { x: ox + 1, y: OPENING.y + OPENING.ry + 3 };
  drawShape(frame, (x, y) => roundBox(x, y, throat, 6, 2.5, 1.2), box(throat, throat, 8), ARMOUR, 1, FADE.scene, 0.6, 0.12);
}

function kendo(frame: Frame, t: number): void {
  const stance = stanceAt(t);
  const step = stance.step;
  // the front foot leads the step, the back foot follows less
  const lunge = step * 0.7;
  drawHakamaAndFeet(frame, step, lunge, FADE.scene);
  drawTare(frame, step);
  drawDo(frame, step);
  const { back, front, dir } = handsOf(stance);
  const shoulderBack = { x: SHOULDER_BACK.x - step, y: SHOULDER_BACK.y };
  const shoulderFront = { x: SHOULDER_FRONT.x - step, y: SHOULDER_FRONT.y };
  drawSleeve(frame, shoulderBack, back, FADE.scene);
  drawMen(frame, step);

  // motion trail through the cut
  if (t >= K.strike && t < K.impact) {
    for (let k = 1; k <= 3; k += 1) {
      const trailT = clamp01((t - k * 45 - K.strike) / (K.struck - K.strike));
      drawShinai(frame, mix(RAISED, STRUCK, trailT), 0.35 / k, FADE.fast);
    }
  }
  const moving = t >= K.strike && t < K.struck ? FADE.fast : FADE.scene;
  drawShinai(frame, stance, 1, moving);
  drawSleeve(frame, shoulderFront, front, moving);
  drawKote(frame, back, dir, shoulderBack, moving);
  drawKote(frame, front, dir, shoulderFront, moving);

  if (t >= K.struck && t < K.impact) {
    const p = (t - K.struck) / (K.impact - K.struck);
    const tip = tipOf(STRUCK);
    for (let ray = 0; ray < 8; ray += 1) {
      const ang = (ray / 8) * Math.PI * 2;
      for (let r = 2 + p * 4; r < 5 + p * 6; r += 1) {
        frame.lighten(Math.round(tip.x + Math.cos(ang) * r), Math.round(tip.y + Math.sin(ang) * r), 1 - p, INK.white, FADE.fast);
      }
    }
  }
}

function kendoLook(t: number): SceneLook {
  const base = { layout: "profile" as const, shiftX: -stanceAt(t).step };
  if (t >= K.struck && t < K.impact) {
    // kiai: eyes flash white on the hit
    const p = (t - K.struck) / (K.impact - K.struck);
    return { ...base, emotion: "concerned", mouth: "o", eyeInk: p < 0.4 ? INK.white : undefined };
  }
  if (t >= K.raise && t < K.strike) return { ...base, emotion: "concerned", mouth: "flat" };
  return { ...base, emotion: "neutral", mouth: "flat" };
}

// ---- kamae, facing him -------------------------------------------------------------
//
// When he takes kamae at her, she suits up and takes it back, FACING him: the
// front view of the bogu, not the kendo scene's three-quarter one. Tare and do
// rise into place, the kote come in, the men comes down over her face, and the
// shinai lifts into chudan with its tip pointed straight at him - foreshortened
// to a short blade and a bright kensen, as a sword aimed at you looks. Then she
// holds it, breathing, for as long as the scene runs.

const SUIT = { do: 450, kote: 900, men: 1500, shinai: 2100, ready: 2600 };
const FRONT = { x: 64, men: { y: 15, rx: 22, ry: 17 }, opening: { rx: 15, ry: 12 }, do: { y: 46, hw: 14, hh: 8 }, tareY: 55 };

function drawFrontDo(frame: Frame, rise: number): void {
  const c = { x: FRONT.x, y: FRONT.do.y + rise };
  const { hw, hh } = FRONT.do;
  const bounds = { x0: c.x - hw - 2, y0: c.y - hh - 2, x1: c.x + hw + 2, y1: c.y + hh + 2 };
  // the do-dai: a red lacquered breastplate - unmistakably armour, not a shirt
  drawShape(frame, (x, y) => roundBox(x, y, c, hw, hh, 5), bounds, INK.red, 1, FADE.scene, 0.95, 0.5);
  // the mune across the top of it: white leather, stitched in amber rows
  const mune = { x: c.x, y: c.y - hh + 3 };
  drawShape(frame, (x, y) => roundBox(x, y, mune, hw - 3, 2.6, 2), bounds, ARMOUR, 1, FADE.scene, 1, 0.55);
  for (const dy of [-1, 1]) {
    for (let x = mune.x - hw + 6; x <= mune.x + hw - 6; x += 2) frame.cover(x, mune.y + dy, 0.8, INK.amber, FADE.scene);
  }
  // the curve of the do-dai's ribs below the mune
  for (const dy of [1, 4]) {
    for (let x = c.x - hw + 4; x <= c.x + hw - 4; x += 1) {
      const bow = Math.round((((x - c.x) / hw) ** 2) * -2);
      frame.cover(x, c.y + dy + bow, 0.75, INK.red, FADE.scene);
    }
  }
  // tare: a band and five quilted flaps, the nafuda (name tag) on the middle one
  const ty = FRONT.tareY + rise;
  for (let x = FRONT.x - 16; x <= FRONT.x + 16; x += 1) frame.cover(x, ty, 0.75, ARMOUR, FADE.scene);
  for (let k = 0; k < 5; k += 1) {
    const fx = FRONT.x - 16 + k * 7;
    for (let y = ty + 1; y < Math.min(ROWS, ty + 8); y += 1) {
      frame.cover(fx, y, 0.6, ARMOUR, FADE.scene);
      for (let x = fx + 1; x < fx + 6; x += 1) frame.cover(x, y, (y - ty) % 3 === 0 ? 0.3 : 0.12, ARMOUR, FADE.scene);
    }
  }
  const tag = { x: FRONT.x + 0.5, y: ty + 4 };
  drawShape(frame, (x, y) => roundBox(x, y, tag, 2.2, 2.6, 0.6), box(tag, tag, 4), ARMOUR, 1, FADE.scene, 1, 0.8);
  frame.cover(FRONT.x, ty + 4, 0.1, ARMOUR, FADE.scene);
  // hakama below, to the floor
  for (let y = ty + 8; y < ROWS - 1; y += 1) {
    const half = 16 + (y - ty - 8) * 0.8;
    frame.cover(Math.round(FRONT.x - half), y, 0.5, ARMOUR, FADE.scene);
    frame.cover(Math.round(FRONT.x + half), y, 0.5, ARMOUR, FADE.scene);
    frame.cover(FRONT.x, y, 0.3, ARMOUR, FADE.scene);
  }
}

function drawFrontMen(frame: Frame, drop: number): void {
  const { men, opening } = FRONT;
  const cy = men.y - drop;
  const ellipse = (x: number, y: number): number =>
    (Math.hypot((x - FRONT.x) / men.rx, (y - cy) / men.ry) - 1) * Math.min(men.rx, men.ry);
  drawShape(frame, ellipse, { x0: FRONT.x - men.rx - 2, y0: Math.max(0, cy - men.ry - 2), x1: FRONT.x + men.rx + 2, y1: cy + men.ry + 2 }, ARMOUR, 1, FADE.scene, 0.55, null);
  // mengane: horizontal bars across the opening and one down the middle
  for (let y = cy - opening.ry + 3; y <= cy + opening.ry - 2; y += 4) {
    const half = opening.rx * Math.sqrt(Math.max(0, 1 - ((y - cy) / opening.ry) ** 2));
    for (let x = Math.round(FRONT.x - half); x <= Math.round(FRONT.x + half); x += 1) frame.cover(x, y, 0.45, ARMOUR, FADE.scene);
  }
  for (let y = cy - opening.ry + 1; y <= cy + opening.ry - 1; y += 1) frame.cover(FRONT.x, y, 0.55, ARMOUR, FADE.scene);
  // men-dare over both shoulders, and the tsuki-dare under the chin
  for (let k = 0; k <= 12; k += 1) {
    for (const side of [-1, 1]) {
      frame.cover(Math.round(FRONT.x + side * (men.rx - 2 + k * 0.45)), cy + 8 + k, 0.5, ARMOUR, FADE.scene);
      frame.cover(Math.round(FRONT.x + side * (men.rx + 4 + k * 0.45)), cy + 9 + k, 0.35, ARMOUR, FADE.scene);
    }
  }
  const throat = { x: FRONT.x, y: cy + men.ry + 2 };
  drawShape(frame, (x, y) => roundBox(x, y, throat, 7, 2.5, 1.2), box(throat, throat, 9), ARMOUR, 1, FADE.scene, 0.6, 0.12);
}

function drawFrontArms(frame: Frame, reach: number, sway: number): void {
  // both hands together in front of the do, left under right on the tsuka
  const low = { x: FRONT.x + sway, y: 53 + reach };
  const high = { x: FRONT.x + sway, y: 48 + reach };
  const shoulders = [{ x: FRONT.x - 18, y: 37 }, { x: FRONT.x + 18, y: 37 }];
  for (const [shoulder, hand] of [[shoulders[0], low], [shoulders[1], high]] as const) {
    // the white keikogi sleeve to mid-forearm...
    const cuffTop = { x: lerp(shoulder.x, hand.x, 0.55), y: lerp(shoulder.y, hand.y, 0.55) };
    drawSleeve(frame, shoulder, cuffTop, FADE.scene);
    // ...then the kote: a thick padded gauntlet up the forearm (the kote-buton)
    drawShape(frame, (x, y) => capsule(x, y, cuffTop, hand, 3.1), box(cuffTop, hand, 5), INK.accent, 1, FADE.scene, 1, 0.55);
    // a pale band where the cuff's leather meets the padding
    const band = { x: lerp(cuffTop.x, hand.x, 0.35), y: lerp(cuffTop.y, hand.y, 0.35) };
    drawShape(frame, (x, y) => Math.hypot(x - band.x, y - band.y) - 2.6, box(band, band, 4), ARMOUR, 0.7, FADE.scene, 0.8, 0.4);
  }
  // the kote-gashira: two big padded mitts round the tsuka, a crease over the knuckles
  for (const hand of [low, high]) {
    drawShape(frame, (x, y) => roundBox(x, y, hand, 5, 2.6, 1.8), box(hand, hand, 8), INK.accent, 1, FADE.scene, 1, 0.7);
    for (let x = Math.round(hand.x - 3); x <= Math.round(hand.x + 3); x += 1) frame.cover(x, Math.round(hand.y - 1), 0.25, INK.accent, FADE.scene);
  }
}

function drawShinaiAtHim(frame: Frame, lift: number, sway: number, t: number): void {
  // seen from the front, pointed at him: foreshortened, the far end (the tsuka in
  // her hands) small and the near end (the kensen at his throat) big and bright.
  // The tsuba faces him - a disc, not a bar.
  const tsuba = { x: FRONT.x + sway, y: 46 };
  const tip = { x: FRONT.x + sway * 0.4, y: lerp(46, 31, lift) };
  const hilt = { x: FRONT.x + sway, y: 54 };
  const along = (f: number): Vec => ({ x: lerp(tsuba.x, tip.x, f), y: lerp(tsuba.y, tip.y, f) });
  const bounds = box(hilt, tip, 7);
  const part = (a: Vec, b: Vec, r: number, ink: Ink, rim: number, fill: number, alpha = 1): void =>
    drawShape(frame, (x, y) => capsule(x, y, a, b, r), bounds, ink, alpha, FADE.scene, rim, fill);
  // the tsuka, down between her hands
  part(hilt, tsuba, 1.2, INK.white, 0.75, 0.45);
  // the shaft, widening toward him
  part(along(0.05), along(0.55), 1.1, INK.white, 0.9, 0.4);
  part(along(0.55), along(0.88), 1.5, INK.white, 0.9, 0.4);
  if (lift > 0.3) {
    // the nakayui band, then the sakigawa and the kensen, nearest him
    part({ x: along(0.7).x - 2.4, y: along(0.7).y }, { x: along(0.7).x + 2.4, y: along(0.7).y }, 0.8, INK.amber, 1, 0.9);
    part(along(0.88), tip, 2.0, INK.white, 1, 0.7);
  }
  // the tsuba, face on: a disc with the blade through its middle
  drawShape(frame, (x, y) => Math.hypot((x - tsuba.x) / 1.0, (y - tsuba.y) / 0.55) - 4.4, box(tsuba, tsuba, 6), INK.amber, 1, FADE.scene, 1, 0.85);
  part(tsuba, tsuba, 1.1, INK.white, 1, 0.6);
  if (lift > 0.5) {
    const glint = 0.6 + 0.4 * Math.sin(t / 180);
    drawShape(frame, (x, y) => Math.hypot(x - tip.x, y - tip.y) - 2.6, box(tip, tip, 5), INK.white, glint, FADE.fast, 1, 0.6);
  }
}

function kamae(frame: Frame, t: number): void {
  const rise = t < SUIT.do ? Math.round((1 - ease(t / SUIT.do)) * 24) : 0;
  drawFrontDo(frame, rise);
  if (t >= SUIT.do) {
    const reach = t < SUIT.kote ? (1 - ease((t - SUIT.do) / (SUIT.kote - SUIT.do))) * 12 : 0;
    const sway = t >= SUIT.ready ? Math.sin((t / 1000) * Math.PI * 0.9) * 0.6 : 0;
    drawFrontArms(frame, reach, sway);
    if (t >= SUIT.men) drawShinaiAtHim(frame, clamp01((t - SUIT.men) / (SUIT.shinai - SUIT.men)), sway, t);
  }
  if (t >= SUIT.kote) {
    const drop = t < SUIT.men ? Math.round((1 - ease((t - SUIT.kote) / (SUIT.men - SUIT.kote))) * 34) : 0;
    drawFrontMen(frame, drop);
  }
}

function kamaeLook(t: number): SceneLook {
  // compact face behind the grille: excited as she suits up, then fired up - the
  // hard brow and blazing amber eyes - once the men is on, with a white flash as
  // the kensen comes up
  if (t < SUIT.men) return { layout: "compact", emotion: "excited", mouth: "grin" };
  const flash = t > SUIT.shinai && t < SUIT.shinai + 180;
  return { layout: "compact", emotion: "firedUp", mouth: "grin", eyeInk: flash ? INK.white : undefined };
}

// ---- keiko: practice with him, face to face ---------------------------------------
//
// He says "let's do keiko": she suits up exactly as for kamae, in the dojo with his
// club's banner on the wall behind her, and holds chudan facing him. When he strikes
// (the HUD's strike recogniser, core decides her answer) she does one of these,
// each timed from the moment core sent it:
//   block    her shinai snaps across to take his - a spark where they meet
//   hit      she takes it: the target (men, kote or do) flashes, she rocks back
//   strike   she strikes back at him: up, then the kensen comes at the camera
//   ippon    two or three shinpan flags go up for him, with a whoosh
//   dodge    (shiai) she slips his strike: arms and shinai swing wide the other way,
//            nothing meets, a smug look
// Shiai adds her attack and the beat of a point (core/irene/shiai.py):
//   windup   her attack coming: shinai up over her men, cocked toward where she will
//            cut, her eyes going red - and red brackets closing on that spot (men at the
//            top, kote low right, do left, tsuki the middle), blinking fast as it
//            lands. The brackets ARE the timing: block or step out before it closes.
//   impact   the cut lands - "hit" (a white burst there, the screen's edge flashes,
//            the target's name), "blocked" (his shinai across the top, a clash of
//            sparks, she is annoyed) or "dodged" (it slices through empty air)
//   ippon    (shiai) the flags, and the point called across the top: "MEN ARI"
//   reset    both back to the start lines: the kaishi-sen on the floor, and what
//            the next point is ("NIHONME", "SHOBU")
//   hajime   "HAJIME" - and play resumes

//   countdown before the bout (10 s) and after each point's reset (3 s): the seconds
//            left, big, and what the point is - then hajime
export type KeikoAction = "block" | "hit" | "strike" | "ippon" | "dodge" | "windup" | "impact" | "reset" | "hajime" | "countdown";
export type KeikoTarget = "men" | "kote" | "dou" | "tsuki";

export interface KeikoMoment {
  action: KeikoAction;
  /** When it began, on the stage clock (performance.now()). */
  at: number;
  target?: KeikoTarget;
  /** ippon: how many flags go up (2 or 3). */
  flags?: number;
  /** ippon: the point called across the top ("MEN ARI"). */
  call?: string;
  /** ippon: whose point - his calls in amber, hers in pink. */
  who?: "you" | "her";
  /** impact: how her attack ended. */
  result?: "hit" | "blocked" | "dodged";
  /** windup: how long until it lands; reset: how long it holds. */
  ms?: number;
  /** reset: what the next point is ("NIHONME", "SHOBU"). */
  label?: string;
}

let keikoMoment: KeikoMoment | null = null;

/** What she is doing in keiko now (null: just kamae). Set from core's "keiko" messages. */
export function keikoReact(moment: KeikoMoment | null): void {
  keikoMoment = moment;
}

const KEIKO_MS: Record<KeikoAction, number> = {
  block: 900, hit: 1000, strike: 1150, ippon: 3000, dodge: 900, windup: 1400, impact: 1300, reset: 2600, hajime: 1100, countdown: 10000,
};
// the camera off to her side, so the club banner hangs on the wall beside her, not hidden behind her
const KEIKO_CAM = { x: 136, y: 66, s: 5 };
const TARGET: Record<KeikoTarget, Vec> = {
  men: { x: FRONT.x, y: FRONT.men.y - 6 }, kote: { x: FRONT.x - 6, y: 50 }, dou: { x: FRONT.x, y: FRONT.do.y + 2 },
  tsuki: { x: FRONT.x, y: FRONT.men.y + FRONT.men.ry + 2 },
};
// where HER cut lands on him (the camera), as the screen shows it: each its own corner
// of the picture, so the ring says where at a glance
const AIM: Record<KeikoTarget, Vec> = { men: { x: 64, y: 9 }, kote: { x: 100, y: 58 }, dou: { x: 40, y: 58 }, tsuki: { x: 64, y: 40 } };
// her shinai cocked toward the side she cuts - never straight up, where it would
// read as the grille's middle bar
const LEAN: Record<KeikoTarget, number> = { men: 0.7, kote: 1.1, dou: -1.1, tsuki: -0.5 };

function current(now: number): { m: KeikoMoment; k: number } | null {
  const m = keikoMoment;
  if (!m || now < m.at) return null;
  const k = now - m.at;
  // a countdown holds its last second until hajime replaces it (she may still be talking)
  const lasts = (m.ms ?? KEIKO_MS[m.action]) + (m.action === "countdown" ? 15000 : 0);
  return k < lasts ? { m, k } : null;
}

/** Text centred on x, top at y, each lit cell `ink` - on a dark plate, so it reads
 *  over her armour. */
function words(frame: Frame, text: string, x: number, y: number, size: number, ink: Ink, alpha = 1): void {
  let at = Math.round(x - textWidth(text, size) / 2);
  if (alpha > 0.05) {
    for (let py = y - 1; py <= y + 5 * size; py += 1) for (let px = at - 2; px <= at + textWidth(text, size) + 1; px += 1) frame.cover(px, py, 0, ink, FADE.fast);
  }
  for (const ch of text) {
    for (const c of glyphCells(ch, at, y, size)) frame.cover(c.x, c.y, alpha, ink, FADE.fast);
    at += textWidth(ch, size) + size;
  }
}

/** Her arms up from the shoulders to her hands on the tsuka, drawn over her men. */
function raisedArms(frame: Frame, hands: Vec): void {
  const shoulders = [{ x: FRONT.x - 18, y: 37 }, { x: FRONT.x + 18, y: 37 }];
  for (const shoulder of shoulders) {
    const cuff = { x: lerp(shoulder.x, hands.x, 0.5), y: lerp(shoulder.y, hands.y, 0.5) };
    drawSleeve(frame, shoulder, cuff, FADE.fast);
    drawShape(frame, (x, y) => capsule(x, y, cuff, hands, 3.1), box(cuff, hands, 5), INK.accent, 1, FADE.fast, 1, 0.55);
  }
  drawShape(frame, (x, y) => roundBox(x, y, hands, 6, 3, 2), box(hands, hands, 9), INK.accent, 1, FADE.fast, 1, 0.75);
}

/** The shinai from her hands up and out of the picture, leaning `lean` to a side. */
function raisedShinai(frame: Frame, hands: Vec, lean: number, alpha: number): void {
  const len = 44;
  const ang = Math.atan2(lean, 1);
  const tip = { x: hands.x + Math.sin(ang) * len, y: hands.y - Math.cos(ang) * len };
  drawShape(frame, (x, y) => capsule(x, y, hands, tip, 2.0), box(hands, tip, 4), INK.white, alpha, FADE.fast, 1, 0.75);
  // the nakayui, so it reads as a shinai and not a stick
  const band = { x: lerp(hands.x, tip.x, 0.55), y: lerp(hands.y, tip.y, 0.55) };
  drawShape(frame, (x, y) => Math.hypot(x - band.x, y - band.y) - 2.2, box(band, band, 4), INK.amber, alpha, FADE.fast, 1, 0.9);
}

/** Her attack: the windup, then the cut landing - hit, blocked or dodged. */
function herAttack(frame: Frame, on: { m: KeikoMoment; k: number }): void {
  const { m, k } = on;
  const target = m.target ?? "men";
  const aim = AIM[target];
  const lean = LEAN[target];
  drawFrontDo(frame, 0);
  drawFrontMen(frame, 0);
  if (m.action === "windup") {
    const ms = m.ms ?? KEIKO_MS.windup;
    const p = clamp01(k / ms);
    // up over her men in the first third, unmistakably: then it holds, cocked
    const raise = ease(clamp01(k / (ms * 0.3)));
    const hands = { x: FRONT.x + lean * 10 * raise, y: lerp(50, 10, raise) };
    raisedArms(frame, hands);
    raisedShinai(frame, hands, lean * raise, 1);
    // brackets closing on where it will land (they read at the picture's edge too,
    // where a ring would be cut off), blinking faster at the end
    const blink = p > 0.7 ? (Math.floor(k / 80) % 2 === 0 ? 1 : 0.3) : 0.6 + 0.4 * Math.sin(k / 110);
    const half = Math.round(lerp(24, 4, ease(p)));
    for (const sx of [-1, 1]) {
      for (const sy of [-1, 1]) {
        const cx = aim.x + sx * half;
        const cy = aim.y + sy * half;
        // two cells thick, on a dark halo: it reads over the red do and the banner
        for (let d = -1; d < 7; d += 1) {
          for (let w = -1; w <= 2; w += 1) {
            frame.cover(cx - sx * d, cy - sy * w, 0, INK.red, FADE.fast);
            frame.cover(cx - sx * w, cy - sy * d, 0, INK.red, FADE.fast);
          }
        }
        for (let d = 0; d < 6; d += 1) {
          for (const w of [0, 1]) {
            frame.cover(cx - sx * d, cy - sy * w, blink, INK.red, FADE.fast);
            frame.cover(cx - sx * w, cy - sy * d, blink, INK.red, FADE.fast);
          }
        }
      }
    }
    drawShape(frame, (x, y) => Math.hypot(x - aim.x, y - aim.y) - (3 + 2 * p), box(aim, aim, 7), INK.red, 0, FADE.fast, 1, 1);
    drawShape(frame, (x, y) => Math.hypot(x - aim.x, y - aim.y) - (1.5 + 2 * p), box(aim, aim, 6), INK.red, blink, FADE.fast, 1, 1);
    // the line of the cut, dotted in from her hands as it comes
    for (let f = 0.1; f < p; f += 0.08) {
      const d = { x: lerp(hands.x, aim.x, f), y: lerp(hands.y, aim.y, f) };
      frame.cover(Math.round(d.x), Math.round(d.y), 0.5, INK.red, FADE.fast);
    }
    if (p > 0.55) words(frame, "!", aim.x + (aim.x > 64 ? -10 : 10), Math.max(1, aim.y - 4), 2, INK.red, blink);
    return;
  }
  // impact: the cut comes down from overhead in 140 ms
  const result = m.result ?? "hit";
  const swing = ease(clamp01(k / 140));
  const hands = { x: FRONT.x + lean * 10 * (1 - swing), y: lerp(10, 30, swing) };
  raisedArms(frame, hands);
  const miss = result === "dodged" ? { x: aim.x + (aim.x >= 64 ? 22 : -22), y: Math.min(71, aim.y + 18) } : aim;
  const end = { x: lerp(hands.x, miss.x, swing), y: lerp(hands.y, miss.y, swing) };
  drawShape(frame, (x, y) => capsule(x, y, hands, end, 1.6), box(hands, end, 4), INK.white, k < 700 ? 1 : 1 - (k - 700) / 600, FADE.fast, 1, 0.6);
  const fade = k < 500 ? 1 : Math.max(0, 1 - (k - 500) / 700);
  if (result === "hit") {
    if (k > 100) impact(frame, aim, k - 100, 420, INK.white, 14);
    if (k < 220) {
      // the screen's own edge flashes: it hit HIM
      for (let x = 0; x < 128; x += 1) for (const y of [0, 1, ROWS - 2, ROWS - 1]) frame.lighten(x, y, 1 - k / 220, INK.white, FADE.fast);
      for (let y = 0; y < ROWS; y += 1) for (const x of [0, 1, 126, 127]) frame.lighten(x, y, 1 - k / 220, INK.white, FADE.fast);
    }
    words(frame, `${target === "dou" ? "DO" : target.toUpperCase()}!`, 64, 2, 2, INK.white, fade);
  } else if (result === "blocked") {
    // his shinai, across the top of his view, and the clash
    for (let x = 34; x <= 94; x += 1) frame.cover(x, 13 + Math.round((x - 64) / 30), 0.9 * fade, INK.amber, FADE.fast);
    if (k > 60) impact(frame, { x: 64, y: 13 }, k - 60, 360, INK.amber, 12);
    words(frame, "BLOCKED", 64, 2, 1, INK.amber, fade);
  } else {
    // nothing there: streaks where it went through
    for (let s = 1; s <= 3; s += 1) {
      const a = { x: lerp(hands.x, miss.x, 0.3) + s * 3, y: lerp(hands.y, miss.y, 0.3) - s };
      const b = { x: miss.x + s * 3, y: miss.y - s };
      drawShape(frame, (x, y) => capsule(x, y, a, b, 0.4), box(a, b, 2), INK.white, 0.4 * fade, FADE.fast, 1, 0.5);
    }
    words(frame, "MISS", 64, 2, 1, INK.white, fade);
  }
}

/** The beat between points: the start lines on the floor and what comes next. */
function startLines(frame: Frame, alpha: number): void {
  for (const [x0, x1, y] of [[50, 78, ROWS - 2], [44, 84, ROWS - 1]]) {
    for (let x = x0; x <= x1; x += 1) frame.cover(x, y, alpha, INK.white, FADE.fast);
  }
}

function impact(frame: Frame, c: Vec, k: number, len: number, ink: Ink, rays = 8): void {
  const p = clamp01(k / len);
  for (let ray = 0; ray < rays; ray += 1) {
    const ang = (ray / rays) * Math.PI * 2 + 0.3;
    for (let r = 2 + p * 5; r < 5 + p * 9; r += 1) frame.lighten(Math.round(c.x + Math.cos(ang) * r), Math.round(c.y + Math.sin(ang) * r * 0.8), 1 - p, ink, FADE.fast);
  }
}

/** A shinpan's flag, raised from (x, y): a pole and a red flag, waving. */
function flag(frame: Frame, x: number, y: number, up: number, t: number, lean: number): void {
  const top = { x: x + lean * up * 6, y: y - 22 * up };
  drawShape(frame, (px, py) => capsule(px, py, { x, y }, top, 0.6), box({ x, y }, top, 3), INK.white, 1, FADE.fast, 0.9, 0.8);
  if (up < 0.4) return;
  const wave = Math.sin(t / 110) * 1.2;
  for (let c = 0; c < 10; c += 1) {
    for (let r = 0; r < 7; r += 1) {
      const fx = Math.round(top.x + Math.sign(lean || 1) * (c + 1));
      const fy = Math.round(top.y + r + Math.sin(c / 2.5 + t / 140) * wave);
      frame.cover(fx, fy, r === 0 || r === 6 || c === 9 ? 1 : 0.85, INK.red, FADE.fast);
    }
  }
}

function keiko(frame: Frame, t: number, now = 0): void {
  if (t < SUIT.ready) {
    kamae(frame, t);
    return;
  }
  const on = current(now);
  if (on && (on.m.action === "windup" || on.m.action === "impact")) {
    herAttack(frame, on);
    return;
  }
  const sway = Math.sin((t / 1000) * Math.PI * 0.9) * 0.6;
  let side = 0; // her shinai and hands swinging across (block)
  let lift = 1; // the shinai's tip: 1 = chudan at his throat
  let rock = 0; // she rocks back (hit)
  if (on?.m.action === "block") {
    const k = on.k;
    side = k < 140 ? k / 140 : k < 520 ? 1 : 1 - (k - 520) / 380;
  } else if (on?.m.action === "hit") {
    rock = on.k < 120 ? on.k / 120 : Math.max(0, 1 - (on.k - 120) / 600);
  } else if (on?.m.action === "dodge") {
    // the other way from a block, and further: out of the line, not into it
    const k = on.k;
    side = -1.4 * (k < 160 ? k / 160 : k < 480 ? 1 : 1 - (k - 480) / 420);
  }
  drawFrontDo(frame, Math.round(rock * 2));
  if (on?.m.action === "strike") {
    // up over her head, then the kensen comes down AT him: it grows toward the lens
    const k = on.k;
    const up = k < 260 ? ease(k / 260) : k < 420 ? 1 - ease((k - 260) / 160) : 0;
    drawFrontArms(frame, -10 * up, sway);
    if (k < 420) {
      drawShinaiAtHim(frame, lerp(1, 2.2, up), sway, t);
    } else {
      const grow = clamp01((k - 420) / 160);
      const fade = k > 750 ? 1 - (k - 750) / 400 : 1;
      const c = { x: FRONT.x, y: 34 };
      const r = 3 + grow * 12;
      drawShape(frame, (x, y) => Math.abs(Math.hypot(x - c.x, y - c.y) - r) - 1.2, box(c, c, r + 3), INK.white, fade, FADE.fast, 1, 0.9);
      drawShape(frame, (x, y) => Math.hypot(x - c.x, y - c.y) - r * 0.45, box(c, c, r), INK.white, fade * 0.8, FADE.fast, 1, 0.6);
      if (k < 520) impact(frame, c, k - 420, 100, INK.white, 12);
    }
  } else {
    drawFrontArms(frame, 0, sway + side * -9);
    drawShinaiAtHim(frame, lift, sway + side * -11, t);
    if (on?.m.action === "block" && on.k > 100 && on.k < 380) impact(frame, { x: FRONT.x - 10, y: 30 }, on.k - 100, 280, INK.amber);
  }
  drawFrontMen(frame, -Math.round(rock * 2));
  if (on?.m.action === "hit") {
    const c = TARGET[on.m.target ?? "men"];
    impact(frame, c, on.k, 420, INK.white, 10);
    if (on.k < 260) drawShape(frame, (x, y) => Math.hypot(x - c.x, (y - c.y) * 1.3) - 7, box(c, c, 9), INK.white, 1 - on.k / 260, FADE.fast, 1, 0.5);
  }
  if (on?.m.action === "ippon") {
    const flags = on.m.flags ?? 3;
    const spots = [{ x: 8, y: 70, lean: 1 }, { x: 119, y: 70, lean: -1 }, { x: 100, y: 30, lean: 1 }].slice(0, flags);
    spots.forEach((s, i) => flag(frame, s.x, s.y, ease(clamp01((on.k - i * 140) / 220)), now, s.lean));
    // the shinpan's call, across the top
    if (on.m.call) words(frame, on.m.call, 64, 1, 2, on.m.who === "her" ? INK.pink : INK.amber, on.k < 150 ? on.k / 150 : 1);
  }
  if (on?.m.action === "reset") {
    startLines(frame, 0.9);
    if (on.m.label) words(frame, on.m.label, 64, 1, 2, INK.amber, 0.7 + 0.3 * Math.sin(on.k / 160));
  }
  if (on?.m.action === "countdown") {
    // the seconds left, big over her men, ticking: each one lands bright and dims
    const ms = on.m.ms ?? KEIKO_MS.countdown;
    const left = Math.max(1, Math.ceil((ms - on.k) / 1000));
    const tick = ((ms - on.k) % 1000) / 1000;
    startLines(frame, 0.9);
    words(frame, String(left), 64, 8, 4, left <= 3 ? INK.amber : INK.white, 0.85 + 0.15 * tick);
    words(frame, on.m.label ?? "KAMAE", 64, 1, 1, INK.white, 0.8);
  }
  if (on?.m.action === "hajime") {
    startLines(frame, Math.max(0, 1 - on.k / 600));
    words(frame, "HAJIME", 64, 1, 2, INK.white, on.k < 700 ? 1 : 1 - (on.k - 700) / 400);
  }
}

function keikoLook(t: number, now = 0): SceneLook {
  if (t < SUIT.ready) return kamaeLook(t);
  const on = current(now);
  if (on?.m.action === "hit" && on.k < 700) return { layout: "compact", emotion: "dizzy", mouth: "wavy" };
  if (on?.m.action === "strike") {
    const flash = on.k > 400 && on.k < 520;
    return { layout: "compact", emotion: "firedUp", mouth: "grin", eyeInk: flash ? INK.white : undefined };
  }
  if (on?.m.action === "block") return { layout: "compact", emotion: "focused", mouth: "flat" };
  if (on?.m.action === "dodge") return { layout: "compact", emotion: "smug", mouth: "smirk" };
  if (on?.m.action === "ippon") {
    return on.m.who === "her" ? { layout: "compact", emotion: "triumphant", mouth: "grin" } : { layout: "compact", emotion: "surprised", mouth: "o" };
  }
  if (on?.m.action === "windup") {
    // the eyes go red and blink with the ring as it closes
    const p = on.k / (on.m.ms ?? KEIKO_MS.windup);
    const red = p > 0.3 && (p < 0.7 || Math.floor(on.k / 80) % 2 === 0);
    return { layout: "compact", emotion: "firedUp", mouth: p > 0.7 ? "o" : "grin", eyeInk: red ? INK.red : undefined };
  }
  if (on?.m.action === "impact") {
    if (on.m.result === "blocked") return { layout: "compact", emotion: "indignant", mouth: "flat" };
    if (on.m.result === "dodged") return { layout: "compact", emotion: "surprised", mouth: "o" };
    return { layout: "compact", emotion: "triumphant", mouth: "grin", eyeInk: on.k < 160 ? INK.white : undefined };
  }
  if (on?.m.action === "reset" || on?.m.action === "countdown") return { layout: "compact", emotion: "focused", mouth: "flat" };
  if (on?.m.action === "hajime") return { layout: "compact", emotion: "firedUp", mouth: "grin", eyeInk: on.k < 160 ? INK.white : undefined };
  return { layout: "compact", emotion: "firedUp", mouth: "grin" };
}

function keikoBackdrop(frame: Frame, t: number): void {
  drawBackdrop(frame, "dojo", t, KEIKO_CAM);
}

interface Scene {
  /** One pass of the loop, ms (the intro included). */
  loopMs: number;
  /** A first part that plays once (suiting up); later passes loop what follows it. */
  introMs?: number;
  look: (t: number, now?: number) => SceneLook;
  draw: (frame: Frame, t: number, now?: number) => void;
  /** A place behind her, drawn before her face (and held down, like every backdrop). */
  backdrop?: (frame: Frame, t: number) => void;
  /** May play on its own while she is dormant. */
  idle?: boolean;
}

// Every scene the matrix can play, by name: the two she performs (offered to the
// model through config/cues.json) and the tool props. A new scene is its entry
// here plus one in the registry.
export const SCENES = {
  chess: { loopMs: 12000, look: chessLook, draw: chess, idle: true },
  kendo: { loopMs: 6000, look: kendoLook, draw: kendo, idle: true },
  kamae: { loopMs: 6600, introMs: SUIT.ready, look: kamaeLook, draw: kamae, idle: true },
  keiko: { loopMs: 6600, introMs: SUIT.ready, look: keikoLook, draw: keiko, backdrop: keikoBackdrop },
  // study mode (led/study.ts): head down over a book, the bar filling - and his hits
  study: STUDY_SCENE,
  ...PROPS,
} satisfies Record<string, Scene>;

export type SceneName = keyof typeof SCENES;

/** Where in its timeline a scene is: the intro once, then the rest on a loop. */
function sceneTime(scene: Scene, elapsed: number): number {
  const intro = scene.introMs ?? 0;
  if (elapsed < intro) return elapsed;
  return intro + ((elapsed - intro) % (scene.loopMs - intro));
}

export function sceneLook(name: SceneName, elapsed: number, now = 0): SceneLook {
  const scene: Scene = SCENES[name];
  return scene.look(sceneTime(scene, elapsed), now);
}

export function drawScene(frame: Frame, name: SceneName, elapsed: number, now = 0): void {
  const scene: Scene = SCENES[name];
  scene.draw(frame, sceneTime(scene, elapsed), now);
}

/** The scene's place behind her, if it has one: drawn before her face. */
export function drawSceneBackdrop(frame: Frame, name: SceneName, elapsed: number): void {
  const scene: Scene = SCENES[name];
  scene.backdrop?.(frame, sceneTime(scene, elapsed));
}
