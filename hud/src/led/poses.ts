// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// Gesture poses: what a reaction looks like now. Instead of an icon replacing the
// face, Irene's LED hands make the gesture next to (or over) her face while the
// face wears a matching expression. Each pose is data plus a small draw function.

import type { Emotion } from "../face/faceState";
import { EYE_BAND, EYE_H, EYE_W, EYE_Y, LEFT_EYE_X, RIGHT_EYE_X } from "./face";
import type { FaceLayout, MouthShape } from "./face";
import { FADE, INK, blit, capsule, clamp01, drawShape, easeOutBack, roundBox, sprite } from "./grid";
import type { Frame } from "./grid";
import { HANDS, drawHand, drawThumbsUp } from "./hands";
import type { HandName, Placement } from "./hands";
import { hop, settle, sway } from "./motion";
import type { Motion } from "./motion";

export interface Expression {
  emotion: Emotion;
  mouth?: MouthShape;
  eyesClosed?: boolean;
  gazeY?: number;
  gazeX?: number;
  layout?: FaceLayout;
  shiftX?: number;
  shiftY?: number;
  moving?: boolean;
}

interface HandSpot extends Omit<Placement, "alpha"> {
  /** A rig gesture, or "thumbsUp" - drawn sideways, which the rig can't do. */
  hand: HandName | "thumbsUp";
  /** Idle motion while held: small offsets from elapsed ms. */
  wiggle?: (t: number) => { dx?: number; dy?: number; drot?: number };
}

interface Pose {
  expression: Expression;
  hands: HandSpot[];
  props?: (frame: Frame, t: number, alpha: number) => void;
  /** Her body moving with the gesture (led/motion.ts): a dip, a bounce, a tilt. */
  motion?: (t: number) => Motion;
}

// ---- props -----------------------------------------------------------------------

const HEART = sprite([
  ".##...##.",
  "####.####",
  "#########",
  "#########",
  ".#######.",
  "..#####..",
  "...###...",
  "....#....",
]);

// newsDesk: a sheaf of notes seen edge-on - a few sheets, slightly out of true,
// their printed lines faint
const PAPERS = sprite([
  "########################",
  "#++-+++-++++-++++-+++--#",
  "#----------------------#",
  "########################",
  "#+++-++++-++-+++++-++++#",
  "########################",
]);

// takeNotes: a small spiral notepad, held low - rings along the top, ruled lines,
// the top line already written on (brighter dashes)
const NOTEPAD = sprite([
  ".#.#.#.#.#.#.#.#.",
  "#################",
  "#+++++++++++++++#",
  "#+##+###+##+++++#",
  "#+++++++++++++++#",
  "#+-------------+#",
  "#+++++++++++++++#",
  "#+-------------+#",
  "#+++++++++++++++#",
  "#+-------------+#",
  "#+++++++++++++++#",
  "#################",
]);

// emptyPage: the same notepad held up to him with nothing on it - rings, the edge,
// no lines at all: she honestly has nothing on file about it
const BLANK_PAGE = sprite([
  ".#.#.#.#.#.#.#.#.#.",
  "###################",
  "#+++++++++++++++++#",
  "#+++++++++++++++++#",
  "#+++++++++++++++++#",
  "#+++++++++++++++++#",
  "#+++++++++++++++++#",
  "#+++++++++++++++++#",
  "#+++++++++++++++++#",
  "#+++++++++++++++++#",
  "#+++++++++++++++++#",
  "#+++++++++++++++++#",
  "#+++++++++++++++++#",
  "#+++++++++++++++++#",
  "#+++++++++++++++++#",
  "#+++++++++++++++++#",
  "###################",
]);

// pinNote: a written page held up, its lines filled in, and a red pushpin pressed into
// its top edge - a finished note going up on the wall
const NOTE_PAGE = sprite([
  "#############",
  "#+++++++++++#",
  "#+--------++#",
  "#+++++++++++#",
  "#+-------+++#",
  "#+++++++++++#",
  "#+---------+#",
  "#+++++++++++#",
  "#+------++++#",
  "#+++++++++++#",
  "#############",
]);
const PUSHPIN = sprite([".###.", "#####", ".###.", "..#..", "..#.."]);

// studyBoard: the game under review - a little chessboard held up, its squares in two
// tones, and a magnifying glass (a ring on a handle) sweeping over it square by square
const MINI_BOARD = sprite([
  "##################",
  "#++,,++,,++,,++,,#",
  "#++,,++,,++,,++,,#",
  "#,,++,,++,,++,,++#",
  "#,,++,,++,,++,,++#",
  "#++,,++,,++,,++,,#",
  "#++,,++,,++,,++,,#",
  "#,,++,,++,,++,,++#",
  "#,,++,,++,,++,,++#",
  "#++,,++,,++,,++,,#",
  "#++,,++,,++,,++,,#",
  "#,,++,,++,,++,,++#",
  "#,,++,,++,,++,,++#",
  "##################",
]);
const LENS = sprite([
  "..###..",
  ".#...#.",
  "#.....#",
  "#.....#",
  "#.....#",
  ".#...#.",
  "..###.#",
  "......##",
  ".......##",
]);

/** studyBoard: where the lens is over the board - a left-right sweep that steps
 *  down a row each pass (~0.7 s a pass), the way you read a position. */
function lensSweep(t: number): { dx: number; dy: number } {
  const pass = Math.floor(t / 700) % 3;
  const k = (t % 700) / 700;
  const across = pass % 2 === 0 ? k : 1 - k;
  return { dx: Math.round(10 * across), dy: 2 + pass * 3 };
}

/** dialDown: how far the knob has been turned down (0 high .. 0.8 low), a click
 *  every ~380 ms from 0.3 s, four clicks. */
function dialTurn(t: number): number {
  if (t < 300) return 0;
  const n = (t - 300) / 380;
  const whole = Math.floor(n);
  return 0.2 * Math.min(4, whole + clamp01(((n - whole) * 380) / 90));
}

/** rpsCount: the fist pumping down on each beat of "rock... paper... scissors"
 *  (~0.6 s a beat), the way you count a throw in. */
function pump(t: number): { dx: number; dy: number; drot: number } {
  const k = (t % 600) / 600;
  return { dx: 0, dy: 7 * Math.sin(Math.PI * Math.min(1, k * 1.6)), drot: -6 * Math.sin(Math.PI * Math.min(1, k * 1.6)) };
}

/** takeNotes: the pen's path - quick little strokes left to right along a line,
 *  then a hop back to the start of the next (a writing rhythm, ~1.6 s a line). */
function scribble(t: number): { dx: number; dy: number; drot: number } {
  const line = (t % 1600) / 1600;
  const across = line < 0.85 ? line / 0.85 : 1 - (line - 0.85) / 0.15;
  return { dx: 10 * across, dy: 1.2 * Math.sin(t / 55), drot: 6 * Math.sin(t / 70) };
}

/** newsDesk: how far the notes are lifted (LEDs) - two taps on the desk, then still. */
function deskTap(t: number): number {
  if (t >= 900) return 0;
  return 4 * Math.sin((Math.PI * (t % 450)) / 450);
}

const HEART_OUTLINE = sprite([
  ".##...##.",
  "#++#.#++#",
  "#+++#+++#",
  "#+++++++#",
  ".#+++++#.",
  "..#+++#..",
  "...#+#...",
  "....#....",
]);

const SMALL_HEART = sprite([".#.#.", "#####", ".###.", "..#.."]);
// humAlong: a quaver - a filled head, its stem and flag
const NOTE = sprite(["..##", "..#.#", "..#..", "###..", "###.."]);
// tapTemple: a memory surfacing - a little four-point spark
const SPARK = sprite(["..#..", ".###.", "##.##", ".###.", "..#.."]);

// cheek blush: a soft oval of pink under each eye
const BLUSH = sprite([".-+++-.", "-+++++-", ".-+++-."]);

// microphone at 9x13, the slash drawn separately so it can be its own colour
const MIC = sprite([
  "...###...",
  "..#---#..",
  "..#---#..",
  "..#---#..",
  "..#---#..",
  "#.#---#.#",
  "#..###..#",
  ".#.....#.",
  "..#####..",
  "....#....",
  "....#....",
  "..#####..",
]);

function heartsRising(frame: Frame, t: number, alpha: number, x: number, y: number): void {
  for (let k = 0; k < 3; k += 1) {
    const phase = ((t + k * 420) % 1260) / 1260;
    const a = alpha * (1 - phase) * clamp01(phase * 5);
    blit(frame, SMALL_HEART, x + Math.sin(phase * 6 + k) * 3, y - phase * 18, {
      ink: INK.pink,
      alpha: a,
      cover: false,
    });
  }
}

/** humAlong: notes drifting up and away beside her face, one every ~0.55 s, each
 *  swaying as it rises and fading out at the top. */
function notesRising(frame: Frame, t: number, alpha: number, x: number, y: number): void {
  for (let k = 0; k < 3; k += 1) {
    const phase = ((t + k * 550) % 1650) / 1650;
    const a = alpha * (1 - phase) * clamp01(phase * 5);
    blit(frame, NOTE, x + Math.sin(phase * 5 + k * 2) * 4 + k * 3, y - phase * 26, { ink: k === 1 ? INK.amber : INK.cyan, alpha: a, scale: 2, cover: false });
  }
}

function sunglasses(frame: Frame, t: number, alpha: number): void {
  const lensY = EYE_Y + EYE_H / 2 - 1;
  const lenses = [
    { x: LEFT_EYE_X + EYE_W / 2, y: lensY },
    { x: RIGHT_EYE_X + EYE_W / 2, y: lensY },
  ];
  const bounds = { x0: LEFT_EYE_X - 4, y0: EYE_BAND.y0, x1: RIGHT_EYE_X + EYE_W + 4, y1: EYE_BAND.y1 };
  for (const lens of lenses) {
    // dark lens hides the eye; the rim is the frame
    drawShape(frame, (x, y) => roundBox(x, y, lens, 13, 10, 5), bounds, INK.white, alpha, FADE.prop, 0.75, 0.02);
  }
  drawShape(
    frame,
    (x, y) => capsule(x, y, { x: lenses[0].x + 12, y: lensY - 5 }, { x: lenses[1].x - 12, y: lensY - 5 }, 0.8),
    bounds,
    INK.white,
    alpha,
    FADE.prop,
    0.75,
    0.75,
  );
  // a glint sweeps across both lenses now and then
  const sweep = (t % 1500) / 1500;
  if (sweep < 0.45) {
    const gx = LEFT_EYE_X - 6 + (sweep / 0.45) * (RIGHT_EYE_X + EYE_W - LEFT_EYE_X + 12);
    for (let k = 0; k < 7; k += 1) {
      const cx = Math.round(gx + k * 0.6);
      const cy = lensY - 4 + k;
      for (const lens of lenses) {
        if (roundBox(cx + 0.5, cy + 0.5, lens, 12, 9, 5) < 0) frame.cover(cx, cy, 0.9 * alpha, INK.white, FADE.fast);
      }
    }
  }
}

// ---- poses -----------------------------------------------------------------------

const RIGHT = 106;
const LEFT = 22;
const shake = (hz: number, amp: number) => (t: number) => ({ drot: Math.sin((t / 1000) * hz * Math.PI * 2) * amp });
const bob = (hz: number, amp: number) => (t: number) => ({ dy: Math.sin((t / 1000) * hz * Math.PI * 2) * amp });

// A new gesture is one entry here plus one in config/cues.json; face/reactions.ts
// takes its list from this table.
export const POSES = {
  heartHands: {
    expression: { emotion: "happy", mouth: "smile" },
    hands: [
      // fingertips meet over the heart, thumbs meet under it
      { hand: "flat", x: 44, y: 64, rot: 52, scale: 1.1, mirror: true },
      { hand: "flat", x: 84, y: 64, rot: -52, scale: 1.1 },
    ],
    props: (frame, t, alpha) => {
      const beat = Math.floor(t / 360) % 2 === 0;
      blit(frame, beat ? HEART : HEART_OUTLINE, 55, 54, { ink: INK.pink, alpha, scale: 2 });
    },
    motion: (t) => ({ dx: sway(0.8, 1.5)(t) }),
  },
  peace: {
    expression: { emotion: "happy", mouth: "grin" },
    hands: [{ hand: "peace", x: RIGHT, y: 32, rot: 10, scale: 1.25, wiggle: shake(2.2, 5) }],
  },
  salute: {
    expression: { emotion: "neutral", mouth: "flat" },
    hands: [{ hand: "flat", x: RIGHT - 2, y: 11, rot: -74, scale: 1.2 }],
  },
  thumbsUp: {
    expression: { emotion: "happy", mouth: "grin" },
    hands: [{ hand: "thumbsUp", x: RIGHT, y: 40, scale: 1.3, wiggle: bob(1.6, 1.2) }],
    motion: (t) => ({ dy: t < 600 ? Math.sin((t / 600) * Math.PI) * 1.5 : 0 }),
  },
  giggle: {
    expression: { emotion: "happy", mouth: "hidden" },
    hands: [{ hand: "flat", x: 66, y: 55, rot: -6, scale: 1.2, wiggle: bob(5.5, 0.9) }],
    motion: (t) => ({ dy: hop(5.5, 1.5)(t), moving: true }),
  },
  fingersCrossed: {
    expression: { emotion: "curious", mouth: "smile" },
    hands: [{ hand: "crossed", x: RIGHT, y: 34, rot: 6, scale: 1.3, wiggle: shake(1.2, 3) }],
    motion: (t) => ({ dy: 1, dx: sway(1.2, 0.8)(t) }),
  },
  facepalm: {
    expression: { emotion: "concerned", mouth: "wavy" },
    hands: [{ hand: "flat", x: 44, y: 16, rot: 16, scale: 1.35 }],
    motion: (t) => ({ dy: 2 * settle(400)(t), dx: -1 }),
  },
  cool: {
    expression: { emotion: "happy", mouth: "smirk" },
    hands: [],
    props: sunglasses,
    motion: (t) => ({ dy: -1 * settle(300)(t), tilt: -1 * settle(300)(t) }),
  },
  fingerHeart: {
    expression: { emotion: "happy", mouth: "smile" },
    hands: [{ hand: "fingerHeart", x: RIGHT - 2, y: 42, rot: -8, scale: 1.25 }],
    props: (frame, t, alpha) => heartsRising(frame, t, alpha, 96, 22),
  },
  // both arms up over her head, eyes shut: a good long stretch (idle life)
  stretch: {
    expression: { emotion: "happy", mouth: "o", eyesClosed: true, shiftY: -1 },
    hands: [
      { hand: "open", x: 20, y: 12, rot: -24, scale: 1.15, mirror: true, wiggle: bob(0.9, 1.4) },
      { hand: "open", x: 108, y: 12, rot: 24, scale: 1.15, wiggle: bob(0.9, 1.4) },
    ],
  },
  yawn: {
    expression: { emotion: "neutral", mouth: "o", eyesClosed: true },
    hands: [{ hand: "flat", x: 84, y: 54, rot: -12, scale: 1.1, wiggle: bob(0.8, 0.8) }],
    motion: (t) => ({ dy: -2 * Math.sin(Math.min(1, t / 1500) * Math.PI) }),
  },
  thinking: {
    expression: { emotion: "curious", mouth: "flat", gazeY: -3 },
    hands: [{ hand: "point", x: 90, y: 64, rot: -38, scale: 1.1 }],
    motion: (t) => ({ tilt: settle(500)(t), dx: 1 }),
  },
  wave: {
    expression: { emotion: "happy", mouth: "smile" },
    hands: [{ hand: "open", x: RIGHT, y: 30, scale: 1.25, wiggle: shake(2.4, 18) }],
    motion: (t) => ({ dx: sway(1.2, 1.5)(t) }),
  },
  embarrassed: {
    expression: { emotion: "happy", mouth: "wavy" },
    // scratching the back of her head
    hands: [{ hand: "flat", x: RIGHT - 6, y: 8, rot: -52, scale: 1.15, wiggle: bob(4.5, 1.2) }],
    props: (frame, _t, alpha) => {
      for (const x of [LEFT_EYE_X + 1, RIGHT_EYE_X + 7]) {
        blit(frame, BLUSH, x, EYE_Y + EYE_H + 1, { ink: INK.pink, alpha, scale: 2, cover: false });
      }
    },
    motion: (t) => ({ dy: 1.5 * settle(300)(t), tilt: -1 }),
  },
  noMic: {
    expression: { emotion: "confused", mouth: "wavy" },
    hands: [{ hand: "cupped", x: RIGHT + 2, y: 26, rot: -18, scale: 1.2, mirror: true }],
    props: (frame, _t, alpha) => {
      blit(frame, MIC, LEFT - 9, 18, { alpha, scale: 2 });
      drawShape(
        frame,
        (x, y) => capsule(x, y, { x: LEFT + 11, y: 17 }, { x: LEFT - 11, y: 43 }, 1.1),
        { x0: LEFT - 14, y0: 14, x1: LEFT + 14, y1: 46 },
        INK.red,
        alpha,
        FADE.prop,
        1,
        1,
      );
    },
  },
  shrug: {
    expression: { emotion: "curious", mouth: "wavy" },
    // both hands out to the sides, palms up, lifting with the shoulders
    hands: [
      { hand: "open", x: 17, y: 50, rot: -72, scale: 1.1, mirror: true, wiggle: bob(1.1, 1.6) },
      { hand: "open", x: 111, y: 50, rot: 72, scale: 1.1, wiggle: bob(1.1, 1.6) },
    ],
    motion: (t) => ({ dy: 2 * Math.abs(Math.sin((t / 1000) * 1.1 * Math.PI)), tilt: 1 }),
  },
  bow: {
    // head dipped, eyes down, hands together low in front: the dojo bow, and the
    // one she takes after a card trick
    expression: { emotion: "happy", mouth: "smile", eyesClosed: true, shiftY: 7 },
    hands: [
      { hand: "flat", x: 52, y: 66, rot: 84, scale: 0.95, mirror: true },
      { hand: "flat", x: 76, y: 66, rot: -84, scale: 0.95 },
    ],
    props: (frame, t, alpha) => {
      // her shoulders rolling forward as she goes down, and coming back up
      const dip = Math.sin(clamp01(t / 1500) * Math.PI) * 3;
      for (const side of [-1, 1]) {
        const a = { x: 64 + side * 4, y: 56 + dip };
        const b = { x: 64 + side * 20, y: 60 + dip + side * 0 };
        drawShape(frame, (x, y) => capsule(x, y, a, b, 2), { x0: 40, y0: 50, x1: 88, y1: 68 }, INK.accent, alpha, FADE.prop, 0.8, 0.25);
      }
    },
  },
  // pure glee: bouncing on her toes, both fists pumping with each hop
  excitedBounce: {
    expression: { emotion: "excited", mouth: "grin" },
    hands: [
      { hand: "fist", x: LEFT + 2, y: 44, rot: -10, scale: 1.15, mirror: true, wiggle: (t) => ({ dy: hop(2.6, 7)(t) }) },
      { hand: "fist", x: RIGHT - 2, y: 44, rot: 10, scale: 1.15, wiggle: (t) => ({ dy: hop(2.6, 7)(t + 90) }) },
    ],
    motion: (t) => ({ dy: hop(2.6, 5)(t), moving: true }),
  },
  // "I'm listening": a hand cupped behind her right ear, eyes turned toward it,
  // head leaning in - can you hear me? say that again? go on...
  listenClose: {
    expression: { emotion: "curious", mouth: "flat", gazeX: 3, gazeY: -1 },
    hands: [{ hand: "cupped", x: RIGHT + 15, y: 28, rot: -12, scale: 1.1, mirror: true, wiggle: bob(0.8, 0.8) }],
    motion: (t) => ({ tilt: -2.5 * settle(400)(t), dx: 4 * settle(400)(t) }),
  },
  // "aha - found it!": one finger shot up beside her face, eyes wide and bright, a
  // little hop - the moment research turns up the answer
  eureka: {
    expression: { emotion: "excited", mouth: "o", gazeY: -2 },
    hands: [{ hand: "point", x: RIGHT + 4, y: 16, rot: 8, scale: 1.15, wiggle: bob(2.2, 0.8) }],
    motion: (t) => ({ dy: -2 * Math.sin(Math.min(1, t / 450) * Math.PI) }),
  },
  // "look at this": an open palm swept out toward the board, eyes following it -
  // as an illustrated answer goes up
  presentBoard: {
    expression: { emotion: "happy", mouth: "smile", gazeX: -3, gazeY: 1 },
    hands: [{ hand: "open", x: LEFT + 2, y: 50, rot: -30, scale: 1.1, wiggle: bob(0.7, 0.8) }],
    motion: (t) => ({ tilt: 1.5 * settle(450)(t), dx: -4 * settle(450)(t) }),
  },
  // "let me draw it for you": a fingertip tracing little loops in the air toward
  // the board, eyes following her own hand - she is composing the picture
  airDraw: {
    expression: { emotion: "curious", mouth: "smile", gazeX: -2, gazeY: 2 },
    hands: [{ hand: "point", x: LEFT + 6, y: 46, rot: -20, scale: 1.1, wiggle: (t) => ({ dx: 3 * Math.cos(t / 190), dy: 2 * Math.sin(t / 190), drot: 4 * Math.sin(t / 380) }) }],
    motion: (t) => ({ tilt: 1.2 * settle(400)(t), dx: -2 * settle(400)(t) }),
  },
  // "let me write that down": a little notepad held low, a pen hand scribbling
  // across it line by line, eyes down on the page, a small focused smile - she is
  // taking notes for him (a lecture, something to remember)
  takeNotes: {
    expression: { emotion: "focused", mouth: "flat", gazeX: 1, gazeY: 3 },
    hands: [
      { hand: "flat", x: 80, y: 66, rot: 100, scale: 0.9 },
      { hand: "point", x: 48, y: 50, rot: 145, scale: 0.95, wiggle: scribble },
    ],
    props: (frame, _t, alpha) => {
      blit(frame, NOTEPAD, 52, 57, { alpha, ink: INK.white, cover: true });
    },
    motion: (t) => ({ dy: 1.5 * settle(400)(t), tilt: 1 * settle(400)(t) }),
  },
  // "so-so": a flat hand held level beside her face, palm down, rocking slowly side
  // to side - weighing it, matter-of-fact, no attitude; eyes level, mouth flat
  soSo: {
    expression: { emotion: "neutral", mouth: "flat", gazeX: 1 },
    hands: [{ hand: "flat", x: RIGHT + 4, y: 46, rot: -90, scale: 1.15, wiggle: shake(1.1, 11) }],
    motion: (t) => ({ tilt: Math.sin((t / 1000) * 1.1 * Math.PI * 2) * 0.8 }),
  },
  // "deal?": her hand held out to him to shake on it - thumb up, fingers forward - and
  // pumped twice, firm, then held out waiting; a level look, a small sure smile
  shakeOnIt: {
    expression: { emotion: "focused", mouth: "smile", gazeX: 1 },
    hands: [{ hand: "flat", x: RIGHT + 2, y: 47, rot: -78, scale: 1.3, wiggle: (t) => ({ dy: t > 250 && t < 1050 ? Math.sin(((t - 250) / 400) * Math.PI * 2) * 2.5 : 0, drot: t < 250 ? -14 * (1 - t / 250) : 0 }) }],
    motion: (t) => ({ dx: -1.5 * settle(300)(t), dy: t > 250 && t < 1050 ? Math.sin(((t - 250) / 400) * Math.PI * 2) * 0.6 : 0 }),
  },
  // rock-paper-scissors: the count - her fist held out beside her face, pumping on
  // each beat; eyes on his hand, a competitive little smile
  rpsCount: {
    expression: { emotion: "focused", mouth: "smile", gazeX: 2, gazeY: 1 },
    hands: [{ hand: "fist", x: RIGHT + 4, y: 44, rot: -90, scale: 1.7, wiggle: pump }],
    motion: (t) => ({ dy: 0.6 * Math.sin(Math.PI * ((t % 600) / 600)) }),
  },
  // her throw, revealed: rock - the fist thrust forward and held, a confident grin
  throwRock: {
    expression: { emotion: "smug", mouth: "smile", gazeX: 1 },
    hands: [{ hand: "fist", x: RIGHT + 4, y: 46, rot: -90, scale: 1.7, wiggle: (t) => ({ dy: t < 220 ? -6 * (1 - t / 220) : 0 }) }],
    motion: (t) => ({ dx: -1.5 * settle(220)(t) }),
  },
  // paper - the flat open hand thrown out, fingers together, palm to him
  throwPaper: {
    expression: { emotion: "happy", mouth: "smile", gazeX: 1 },
    hands: [{ hand: "open", x: RIGHT + 6, y: 42, rot: -90, scale: 1.25, wiggle: (t) => ({ dy: t < 220 ? -6 * (1 - t / 220) : 0 }) }],
    motion: (t) => ({ dx: -1.5 * settle(220)(t) }),
  },
  // scissors - two fingers out in a V, a little snip
  throwScissors: {
    expression: { emotion: "excited", mouth: "smile", gazeX: 1 },
    hands: [{ hand: "peace", x: RIGHT + 6, y: 42, rot: -90, scale: 1.25, wiggle: (t) => ({ dy: t < 220 ? -6 * (1 - t / 220) : 0, drot: t > 400 && t < 700 ? 6 * Math.sin(((t - 400) / 300) * Math.PI * 2) : 0 }) }],
    motion: (t) => ({ dx: -1.5 * settle(220)(t) }),
  },
  // "let's see what really happened": the game held up small beside her face and
  // read through a magnifying glass, eyes down on it - focused, a reviewer's frown
  studyBoard: {
    expression: { emotion: "focused", mouth: "flat", gazeX: 1, gazeY: 2 },
    hands: [{ hand: "flat", x: RIGHT + 9, y: 51, rot: -90, scale: 0.9 }],
    props: (frame, t, alpha) => {
      const lift = 4 * settle(380)(t);
      blit(frame, MINI_BOARD, RIGHT, 38 - lift, { alpha, ink: INK.white, cover: true });
      const at = lensSweep(t);
      blit(frame, LENS, RIGHT + at.dx, 36 - lift + at.dy, { alpha: alpha * clamp01((t - 250) / 250), ink: INK.amber, cover: false });
    },
    motion: (t) => ({ tilt: 0.6 * settle(400)(t), dy: 1 * settle(400)(t) }),
  },
  // "written up for you": a finished page lifted beside her face, then the pin goes in -
  // a little press, a red pushpin landing on its top edge; a pleased, closed-eye smile
  pinNote: {
    expression: { emotion: "happy", mouth: "smile", gazeX: -1, gazeY: -1 },
    hands: [{ hand: "point", x: RIGHT + 17, y: 22, rot: 200, scale: 0.9 }],
    props: (frame, t, alpha) => {
      const lift = 5 * settle(360)(t);
      blit(frame, NOTE_PAGE, RIGHT + 1, 32 - lift, { alpha, ink: INK.white, cover: true });
      // the pin drops in at ~500 ms and settles with a small bounce
      const drop = clamp01((t - 450) / 220);
      if (drop > 0) {
        const bounce = drop < 1 ? (1 - drop) * 6 : 0;
        blit(frame, PUSHPIN, RIGHT + 4, 29 - lift - bounce, { alpha: alpha * drop, ink: INK.red, cover: false });
      }
    },
    motion: (t) => ({ tilt: 0.8 * settle(400)(t), dy: t > 450 && t < 700 ? 0.8 : 0 }),
  },
  // "nothing on file": she lifts a blank page beside her face and turns it to him with
  // a little tilt - see, nothing written there - eyes on him, mouth level: honest,
  // not sorry (the memory guard's "I don't remember", irene/provenance.py)
  emptyPage: {
    expression: { emotion: "neutral", mouth: "flat", gazeX: -1, gazeY: 0 },
    hands: [{ hand: "flat", x: RIGHT + 12, y: 50, rot: -100, scale: 1.0 }],
    props: (frame, t, alpha) => {
      const lift = 6 * settle(380)(t);
      // one slow tilt to show both ways that it's empty, then still
      const sway = t < 1400 ? Math.round(1.5 * Math.sin((t / 1400) * Math.PI * 2)) : 0;
      blit(frame, BLANK_PAGE, RIGHT + 1 + sway, 30 - lift, { alpha, ink: INK.white, cover: true });
    },
    motion: (t) => ({ tilt: -0.8 * settle(420)(t) }),
  },
  // "oh - you told me!": a fingertip tapping her temple twice, eyes up and to the side
  // as a memory surfaces - a small amber spark lifting off where she taps
  tapTemple: {
    expression: { emotion: "curious", mouth: "smile", gazeX: -2, gazeY: -3 },
    hands: [],
    props: (frame, t, alpha) => {
      // two taps, then held: each a quick press in toward the temple
      const press = t < 900 ? 1.8 * Math.max(0, Math.sin(((t % 450) / 450) * Math.PI)) : 0;
      // below and outside her right eye, the finger up and in to the temple; a tap
      // moves along the finger
      drawHand(frame, HANDS.point, { x: RIGHT + 9 - press, y: 22 - press * 0.8, rot: -34, scale: 1.1, alpha });
      const rise = clamp01((t - 300) / 900);
      if (rise > 0) {
        const a = alpha * clamp01(rise * 4) * (1 - 0.6 * rise);
        blit(frame, SPARK, RIGHT - 6, 4 - rise * 8, { ink: INK.amber, alpha: a, cover: false });
      }
    },
    motion: (t) => ({ tilt: 1.2 * settle(380)(t), dy: -0.6 * settle(380)(t) }),
  },
  // "one, two, three": a hand raised beside her face counting off on its fingers - one
  // finger, two, three, each a little tap up - eyes on the hand, as she lists things
  countOff: {
    expression: { emotion: "focused", mouth: "smile", gazeX: 2, gazeY: -1 },
    hands: [],
    props: (frame, t, alpha) => {
      const step = Math.min(2, Math.floor(t / 520));
      const name = (["point", "peace", "three"] as const)[step];
      const tap = 1.6 * Math.max(0, Math.sin(Math.min(1, (t % 520) / 180) * Math.PI));
      drawHand(frame, HANDS[name], { x: RIGHT + 8, y: 38 - tap, rot: 8, scale: 1.1, alpha });
    },
    motion: (t) => ({ tilt: -1.2 * settle(350)(t), dx: 2 * settle(350)(t) }),
  },
  // "showtime!": both open hands beside her cheeks, shimmering fast - the big
  // entrance, the curtain going up
  jazzHands: {
    expression: { emotion: "excited", mouth: "smile" },
    hands: [
      { hand: "open", x: 30, y: 44, rot: -20, scale: 1.1, mirror: true, wiggle: (t) => ({ dx: 0, dy: 0, drot: 9 * Math.sin(t / 45) }) },
      { hand: "open", x: 98, y: 44, rot: 20, scale: 1.1, wiggle: (t) => ({ dx: 0, dy: 0, drot: -9 * Math.sin(t / 45) }) },
    ],
    motion: (t) => ({ dy: -1.5 * settle(250)(t) }),
  },
  // "systems online": a fingertip tapped to her temple twice, a bright little
  // smile - booted, sharp, ready
  templeTap: {
    expression: { emotion: "happy", mouth: "smile", gazeX: 2, gazeY: -1 },
    hands: [{ hand: "point", x: RIGHT - 10, y: 20, rot: -150, scale: 1.05, wiggle: (t) => ({ dx: -2.5 * Math.max(0, Math.sin(t / 120)), dy: 0 }) }],
    motion: (t) => ({ tilt: -2 * settle(350)(t) }),
  },
  // "phew": the back of a flat hand wiped across her brow, eyes closing in relief -
  // that was close, it worked after all
  phew: {
    expression: { emotion: "happy", mouth: "smile", gazeY: -2 },
    hands: [{ hand: "flat", x: 54, y: 18, rot: -100, scale: 1.05, wiggle: (t) => ({ dx: 18 * Math.min(1, (t % 1400) / 700), dy: 0 }) }],
    motion: (t) => ({ dy: 1.5 * settle(400)(t) }),
  },
  // "uh-uh": a raised finger wagging side to side, a knowing smile - teasing him
  // off a bad idea, "not so fast"
  fingerWag: {
    expression: { emotion: "wink", mouth: "smile", gazeX: 1 },
    hands: [{ hand: "point", x: RIGHT - 4, y: 30, rot: 0, scale: 1.1, wiggle: (t) => ({ dx: 0, dy: 0, drot: 16 * Math.sin(t / 110) }) }],
    motion: (t) => ({ tilt: -1.5 * settle(300)(t) }),
  },
  // "not now - we're in the middle of something": one palm raised flat toward him like
  // a stop sign, a small firm push forward, eyes closed, chin up - hold that thought
  notNow: {
    expression: { emotion: "smug", mouth: "flat", gazeX: -1 },
    hands: [{ hand: "flat", x: RIGHT + 10, y: 44, rot: 6, scale: 1.2, wiggle: (t) => ({ dx: 0, dy: t < 260 ? -2 * Math.sin((t / 260) * Math.PI) : 0, drot: 0 }) }],
    motion: (t) => ({ dx: 1 * settle(260)(t), tilt: 1.5 * settle(300)(t) }),
  },
  // "lights out": palms pressed together under a tilted cheek, eyes soft - a
  // pillow of hands, as the screens go dark and she settles in to listen
  pillowHands: {
    expression: { emotion: "happy", mouth: "smile", gazeY: 1 },
    hands: [
      { hand: "flat", x: 84, y: 40, rot: -60, scale: 1.05, wiggle: bob(0.4, 0.5) },
      { hand: "flat", x: 88, y: 44, rot: -60, scale: 1.05, mirror: true, wiggle: bob(0.4, 0.5) },
    ],
    motion: (t) => ({ tilt: 4 * settle(600)(t), dx: 3 * settle(600)(t) }),
  },
  // "next!": a flat hand sweeping across in front of her, eyes riding along -
  // moving on, flicking to the next thing on the panel
  swipe: {
    expression: { emotion: "happy", mouth: "smile", gazeX: -2 },
    hands: [{ hand: "flat", x: 92, y: 46, rot: -80, scale: 1.1, wiggle: (t) => ({ dx: -22 * ((t / 900) % 1), dy: 0 }) }],
    motion: (t) => ({ dx: -2 * settle(400)(t) }),
  },
  // "let me look": a flat hand shading her brow, eyes narrowed toward the
  // distance - scanning far off for something, peering at the panel
  lookout: {
    expression: { emotion: "curious", mouth: "flat", gazeX: -3, gazeY: -1 },
    hands: [{ hand: "flat", x: 70, y: 18, rot: -8, scale: 1.1, wiggle: bob(0.5, 0.6) }],
    motion: (t) => ({ dx: -2 * settle(500)(t), tilt: -1 * settle(500)(t) }),
  },
  // "and... action!": a film clapperboard held up beside her face, its striped stick
  // raised, then snapped shut with a flash - starting a take, he's filming, on cue
  clapper: {
    expression: { emotion: "excited", mouth: "grin", gazeX: 2 },
    hands: [{ hand: "fist", x: 104, y: 60, rot: -6, scale: 1.05 }],
    props: (frame, t, alpha) => {
      const body = { x: 104, y: 46 };
      drawShape(frame, (x, y) => roundBox(x, y, body, 13, 9, 1), { x0: 89, y0: 35, x1: 119, y1: 57 }, INK.white, alpha, FADE.fast, 0.9, 0.15);
      // the stick, hinged at its left end: open, then shut at 520 ms
      const shut = clamp01((t - 380) / 140);
      const angle = (-28 * (1 - shut) * Math.PI) / 180;
      const hinge = { x: 91, y: 35 };
      for (let i = 0; i < 28; i += 1) {
        for (let j = 0; j < 4; j += 1) {
          const along = i;
          const across = -j;
          const x = Math.round(hinge.x + along * Math.cos(angle) - across * Math.sin(angle));
          const y = Math.round(hinge.y + along * Math.sin(angle) + across * Math.cos(angle));
          const stripe = Math.floor((i + j) / 4) % 2 === 0;
          frame.cover(x, y, (stripe ? 1 : 0.25) * alpha, INK.white, FADE.fast);
        }
      }
      // the clap: a flash at the hinge's far end
      const k = t - 520;
      if (k > 0 && k < 220) {
        for (let r = 0; r < 6; r += 1) {
          for (const [dx, dy] of [[1, -1], [1, 0], [1, 1], [0, -1]]) frame.lighten(118 + dx * (3 + r), 33 + dy * (2 + r), (1 - k / 220) * alpha, INK.amber, FADE.fast);
        }
      }
    },
    motion: (t) => ({ dy: t > 520 && t < 640 ? 1 : 0 }),
  },
  // "this is bad": a fist at her mouth, nibbling a nail, eyes darting side to side -
  // nerves, a position falling apart, waiting for the blow she can see coming
  nailBite: {
    expression: { emotion: "concerned", mouth: "hidden", gazeY: -1 },
    hands: [{ hand: "fist", x: 70, y: 52, rot: -20, scale: 1.0, wiggle: (t) => ({ dx: 0, dy: Math.sin(t / 70) > 0.6 ? -1 : 0, drot: 3 * Math.sin(t / 70) }) }],
    motion: (t) => ({ dx: 1.2 * Math.sin(t / 420), dy: 0.5 * settle(300)(t) }),
  },
  // a song he loves, the tune in her head: eyes closed, a small hum of a mouth,
  // swaying slowly side to side while notes drift up beside her face
  humAlong: {
    expression: { emotion: "happy", mouth: "o", eyesClosed: true },
    hands: [],
    props: (frame, t, alpha) => notesRising(frame, t, alpha, RIGHT - 6, 40),
    motion: (t) => ({ dx: sway(0.5, 2)(t), tilt: sway(0.5, 0.8)(t) }),
  },
  // "I'll go easy on you": a knob beside her face, its ring of ticks lit, turned down
  // click by click by her fingertips until the pointer sits low - a smug little smirk
  dialDown: {
    expression: { emotion: "smug", mouth: "smirk", gazeX: 1 },
    hands: [{ hand: "fist", x: RIGHT + 6, y: 22, rot: -30, scale: 0.85, wiggle: (t) => ({ drot: -70 * dialTurn(t) }) }],
    props: (frame, t, alpha) => {
      const c = { x: RIGHT + 4, y: 32 };
      const turn = dialTurn(t);
      for (let k = 0; k <= 6; k += 1) {
        // ticks from low (lower left) round the top to high (lower right); lit up to the pointer
        const a = Math.PI * (0.75 + (1.5 * k) / 6);
        const lit = k / 6 <= 1 - turn + 0.01;
        frame.cover(Math.round(c.x + 10 * Math.cos(a)), Math.round(c.y + 10 * Math.sin(a)), (lit ? 1 : 0.3) * alpha, INK.amber, FADE.fast);
      }
      drawShape(frame, (x, y) => Math.hypot(x - c.x, y - c.y) - 6.5, { x0: c.x - 8, y0: c.y - 8, x1: c.x + 8, y1: c.y + 8 }, INK.white, alpha, FADE.prop);
      const a = Math.PI * (0.75 + 1.5 * (1 - turn));
      const tip = { x: c.x + 5 * Math.cos(a), y: c.y + 5 * Math.sin(a) };
      drawShape(frame, (x, y) => capsule(x, y, c, tip, 0.6), { x0: c.x - 7, y0: c.y - 7, x1: c.x + 7, y1: c.y + 7 }, INK.white, alpha, FADE.fast, 1, 0.9);
    },
    motion: (t) => ({ tilt: 0.5 * settle(300)(t), dy: t % 380 < 40 && t > 300 && t < 1600 ? 1 : 0 }),
  },
  // "on my mark": a stopwatch held up beside her face, its hand sweeping round and the
  // crown pressed with a click at the start - a countdown, timing something, "ready...?"
  stopwatch: {
    expression: { emotion: "focused", mouth: "flat", gazeX: 2 },
    hands: [{ hand: "fist", x: 106, y: 58, rot: -8, scale: 1.0 }],
    props: (frame, t, alpha) => {
      const c = { x: 106, y: 44 };
      drawShape(frame, (x, y) => Math.abs(Math.hypot(x - c.x, y - c.y) - 9) - 0.8, { x0: 94, y0: 32, x1: 118, y1: 56 }, INK.white, alpha, FADE.fast, 1, 0.9);
      // the crown and its button, pressed down at the start
      const press = t < 180 ? 1 : 0;
      drawShape(frame, (x, y) => roundBox(x, y, { x: c.x, y: c.y - 11 + press }, 2, 1.2, 0.5), { x0: 102, y0: 30, x1: 110, y1: 36 }, INK.amber, alpha, FADE.fast, 1, 0.9);
      // the ticks at 12, 3, 6, 9
      for (const [dx, dy] of [[0, -7], [7, 0], [0, 7], [-7, 0]]) frame.cover(c.x + dx, c.y + dy, alpha, INK.white, FADE.fast);
      // the sweep hand: once round every two seconds
      const a = ((t % 2000) / 2000) * Math.PI * 2;
      for (let r = 0; r <= 6; r += 1) frame.cover(Math.round(c.x + Math.sin(a) * r), Math.round(c.y - Math.cos(a) * r), alpha, INK.red, FADE.fast);
    },
    motion: (t) => ({ dy: t < 180 ? 1 : 0, tilt: -1 * settle(300)(t) }),
  },
  // "hajime!": one flat hand raised edge-on beside her face, held a beat, then
  // chopped down between them like a shinpan starting the bout - eyes on him, a grin
  hajimeCall: {
    expression: { emotion: "firedUp", mouth: "grin", gazeX: -1 },
    hands: [{ hand: "flat", x: RIGHT + 2, y: 26, rot: -14, scale: 1.15, wiggle: (t) => ({ dx: -6 * clamp01((t - 320) / 140), dy: 22 * clamp01((t - 320) / 140), drot: -50 * clamp01((t - 320) / 140) }) }],
    motion: (t) => ({ dy: t > 320 && t < 520 ? 1 : 0, tilt: -1 * settle(300)(t) }),
  },
  // "men ari - ippon!": a shinpan's red flag snapped up overhead in her right hand,
  // waving, eyes bright - calling the point (shiai's score, or anything he nailed)
  refFlag: {
    expression: { emotion: "excited", mouth: "o", gazeY: -1 },
    hands: [{ hand: "fist", x: 114, y: 34, rot: -10, scale: 1.1, wiggle: bob(1.2, 0.6) }],
    props: (frame, t, alpha) => {
      const up = easeOutBack(clamp01(t / 260));
      const base = { x: 116, y: 34 };
      const top = { x: 119, y: 34 - 30 * up };
      drawShape(frame, (x, y) => capsule(x, y, base, top, 0.6), { x0: 112, y0: 1, x1: 124, y1: 38 }, INK.white, alpha, FADE.fast, 0.9, 0.8);
      if (up < 0.5) return;
      const wave = Math.sin(t / 110) * 1.2;
      for (let c = 0; c < 12; c += 1) {
        for (let r = 0; r < 8; r += 1) {
          const fx = Math.round(top.x - 1 - c);
          const fy = Math.round(top.y + r + Math.sin(c / 2.5 + t / 140) * wave);
          frame.cover(fx, fy, (r === 0 || r === 7 || c === 11 ? 1 : 0.85) * alpha, INK.red, FADE.fast);
        }
      }
    },
    motion: (t) => ({ dy: -1.5 * settle(260)(t) }),
  },
  // "about this big": both hands up flat either side of her face, palms facing,
  // closing in and opening out as she sizes it up - a gap, a distance, how far off
  measure: {
    expression: { emotion: "focused", mouth: "flat", gazeX: 1 },
    hands: [
      { hand: "flat", x: 20, y: 38, rot: 8, scale: 1.1, mirror: true, wiggle: (t) => ({ dx: 6 * Math.sin((t / 1000) * 0.9 * Math.PI * 2) }) },
      { hand: "flat", x: 108, y: 38, rot: -8, scale: 1.1, wiggle: (t) => ({ dx: -6 * Math.sin((t / 1000) * 0.9 * Math.PI * 2) }) },
    ],
    motion: (t) => ({ tilt: 1 * settle(400)(t) }),
  },
  // "where did your hands go?": she sinks to the bottom edge, both hands flat on the
  // rim, and peers over it, eyes down, glancing one way then the other - looking for
  // something that dropped out of the picture (his wrists below the camera's frame)
  peerDown: {
    expression: { emotion: "curious", mouth: "o", gazeY: 3 },
    hands: [
      { hand: "flat", x: 22, y: 60, rot: 24, scale: 1.1, mirror: true, wiggle: bob(0.4, 0.5) },
      { hand: "flat", x: 106, y: 60, rot: -24, scale: 1.1, wiggle: bob(0.4, 0.5) },
    ],
    motion: (t) => ({ dy: 16 * settle(450)(t), dx: 2 * Math.sin((t / 1000) * 0.8 * Math.PI * 2) * settle(700)(t) }),
  },
  // "don't you dare": both hands flat over the top of her head, eyes squeezed shut,
  // ducking with a tremble - bracing for the hit he's winding up (a shinai raised at
  // her while she studies, a threat to bonk her)
  flinch: {
    expression: { emotion: "concerned", mouth: "wavy", eyesClosed: true, shiftY: 2 },
    hands: [
      { hand: "flat", x: 46, y: 16, rot: 70, scale: 1.1, wiggle: shake(9, 2.5) },
      { hand: "flat", x: 82, y: 16, rot: -70, scale: 1.1, mirror: true, wiggle: shake(9, 2.5) },
    ],
    motion: (t) => ({ dy: 3 * settle(160)(t), dx: Math.sin((t / 1000) * 9 * Math.PI * 2) * 0.6 }),
  },
  // "you got me!": both open hands raised high beside her head, palms out, a little
  // wobble - caught out, giving in, a playful surrender
  handsUp: {
    expression: { emotion: "sheepish", mouth: "smile", gazeY: -1 },
    hands: [
      { hand: "open", x: 22, y: 26, rot: -8, scale: 1.1, mirror: true, wiggle: bob(1.6, 1.2) },
      { hand: "open", x: 106, y: 26, rot: 8, scale: 1.1, wiggle: bob(1.6, 1.2) },
    ],
    motion: (t) => ({ dy: -1.5 * settle(250)(t) }),
  },
  // "click": a fingertip pressing forward into the air and back, eyes on it -
  // pressing a button that isn't there, the way his hand clicks
  airTap: {
    expression: { emotion: "curious", mouth: "smile", gazeX: 2, gazeY: 1 },
    hands: [{ hand: "point", x: RIGHT - 6, y: 44, rot: 18, scale: 1.1, wiggle: (t) => ({ dy: 2.5 * Math.max(0, Math.sin(t / 170)), drot: 0 }) }],
    motion: (t) => ({ dx: 2 * settle(300)(t) }),
  },
  // "ta-da!": both hands flung open and up beside her face, a little pop of the
  // head - here it is, it's on your panel
  taDa: {
    expression: { emotion: "excited", mouth: "smile", gazeY: -1 },
    hands: [
      { hand: "open", x: 20, y: 36, rot: -38, scale: 1.15, mirror: true, wiggle: (t) => ({ dy: -2 * Math.max(0, Math.sin(t / 140)), drot: -6 * Math.max(0, Math.sin(t / 140)) }) },
      { hand: "open", x: 108, y: 36, rot: 38, scale: 1.15, wiggle: (t) => ({ dy: -2 * Math.max(0, Math.sin(t / 140)), drot: 6 * Math.max(0, Math.sin(t / 140)) }) },
    ],
    motion: (t) => ({ dy: -2 * settle(260)(t) }),
  },
  // "over there": a finger jabbing out past the edge of her screen toward his
  // second monitor, eyes going with it - the dashboard, the story she opened
  pointAside: {
    expression: { emotion: "happy", mouth: "smile", gazeX: -4, gazeY: 0 },
    hands: [{ hand: "point", x: LEFT - 4, y: 40, rot: -62, scale: 1.15, wiggle: (t) => ({ dx: -2.5 * Math.max(0, Math.sin(t / 160)), dy: 0 }) }],
    motion: (t) => ({ tilt: 1.8 * settle(380)(t), dx: -5 * settle(380)(t) }),
  },
  // "Irene Adler.": a hand laid on her chest, chin up, one slow pleased nod - saying
  // her own name like it explains everything (it's really everything, no exaggeration)
  selfIntro: {
    expression: { emotion: "proud", mouth: "smile", gazeY: -1, gazeX: 1 },
    hands: [{ hand: "flat", x: 70, y: 56, rot: -24, scale: 1.1, wiggle: bob(0.4, 0.5) }],
    motion: (t) => ({ dy: -1.5 * settle(320)(t) + 1.2 * Math.max(0, Math.sin(t / 260)) * Math.exp(-t / 900), tilt: -1.2 * settle(400)(t) }),
  },
  // "let me blow that up for you": two fingertips together in front of her, then
  // drawn apart - the zoom-in, done in the air - and back for another go
  zoomIn: {
    expression: { emotion: "curious", mouth: "o", gazeY: 1 },
    hands: [
      { hand: "point", x: 52, y: 48, rot: -70, scale: 1.05, mirror: true, wiggle: (t) => ({ dx: -9 * (0.5 - 0.5 * Math.cos(t / 280)), dy: 0 }) },
      { hand: "point", x: 76, y: 48, rot: 70, scale: 1.05, wiggle: (t) => ({ dx: 9 * (0.5 - 0.5 * Math.cos(t / 280)), dy: 0 }) },
    ],
    motion: (t) => ({ dy: -1 * settle(300)(t) }),
  },
  // "all clean!": two flat hands brushed past each other in front of her, twice,
  // a pleased little nod - a clean slate (her research cleared, a job finished)
  dustOff: {
    expression: { emotion: "happy", mouth: "smile", gazeY: 1 },
    hands: [
      { hand: "flat", x: 54, y: 52, rot: -12, scale: 1.05, mirror: true, wiggle: (t) => ({ dx: 6 * Math.sin(t / 110), dy: 0 }) },
      { hand: "flat", x: 74, y: 54, rot: 12, scale: 1.05, wiggle: (t) => ({ dx: -6 * Math.sin(t / 110), dy: 0 }) },
    ],
    motion: (t) => ({ dy: 1.2 * Math.max(0, Math.sin(t / 240)) * Math.exp(-t / 1200) }),
  },
  // "here's the news": a newsreader squaring her notes - a sheaf of papers held
  // upright between two flat hands, tapped twice on the desk, then a brisk look up
  // at him; the morning briefing about to begin
  newsDesk: {
    expression: { emotion: "focused", mouth: "smile", gazeY: -1 },
    hands: [
      { hand: "flat", x: 46, y: 57, rot: -84, scale: 1.05, mirror: true, wiggle: (t) => ({ dy: -deskTap(t) }) },
      { hand: "flat", x: 82, y: 57, rot: 84, scale: 1.05, wiggle: (t) => ({ dy: -deskTap(t) }) },
    ],
    props: (frame, t, alpha) => {
      blit(frame, PAPERS, 52, 54 - deskTap(t), { alpha, ink: INK.white, cover: true });
    },
    motion: (t) => ({ dy: 0.8 * deskTap(t) / 4 - 1 * settle(900)(t), tilt: -0.8 * settle(900)(t) }),
  },
  // "lights out": a fingertip flicking an imaginary switch down beside her face,
  // eyes going sleepy - his screens going dark on her word
  lightsOut: {
    expression: { emotion: "happy", mouth: "smile", gazeY: 2 },
    hands: [{ hand: "point", x: RIGHT - 8, y: 30, rot: 160, scale: 1.05, wiggle: (t) => ({ dy: 7 * settle(260)(t), drot: 0 }) }],
    motion: (t) => ({ dy: 1.5 * settle(600)(t), tilt: -1 * settle(700)(t) }),
  },
  // "the full picture": a director's frame - two fingertips at opposite corners, and
  // the frame between them opening out from her face to the edges of her screen
  frameUp: {
    expression: { emotion: "excited", mouth: "smile", gazeY: -1 },
    hands: [
      { hand: "point", x: LEFT - 2, y: 14, rot: -45, scale: 1.0, mirror: true, wiggle: (t) => ({ dx: -6 * settle(420)(t), dy: -4 * settle(420)(t) }) },
      { hand: "point", x: RIGHT + 2, y: 58, rot: 135, scale: 1.0, wiggle: (t) => ({ dx: 6 * settle(420)(t), dy: 4 * settle(420)(t) }) },
    ],
    props: (frame, t, alpha) => {
      const open = settle(420)(t);
      const hw = 22 + 28 * open;
      const hh = 12 + 14 * open;
      drawShape(
        frame,
        (x, y) => roundBox(x, y, { x: 64, y: 36 }, hw, hh, 1),
        { x0: 64 - hw - 2, y0: 36 - hh - 2, x1: 64 + hw + 2, y1: 36 + hh + 2 },
        INK.cyan,
        alpha,
        FADE.prop,
        0.8,
        null,
      );
    },
    motion: (t) => ({ dy: -1.5 * settle(420)(t) }),
  },
  // "hmm?": head on one side, eyes up and away, a finger resting on her cheek
  // the slow, disbelieving head-shake of a friend hearing the story: "mm-mm, no.
  // Unbelievable." Eyes shut, mouth pressed flat, two long shakes, then still
  headShake: {
    expression: { emotion: "neutral", mouth: "flat", eyesClosed: true },
    hands: [],
    motion: (t) => ({ dx: t < 2400 ? Math.sin((t / 1000) * 0.85 * Math.PI * 2) * 5 * (1 - t / 2400) : 0, dy: 1 * settle(400)(t), tilt: t < 2400 ? Math.sin((t / 1000) * 0.85 * Math.PI * 2) * 0.8 : 0 }),
  },
  headTilt: {
    expression: { emotion: "curious", mouth: "flat", gazeY: -2, gazeX: 2 },
    hands: [{ hand: "point", x: 96, y: 50, rot: -24, scale: 1.05, wiggle: bob(0.6, 0.6) }],
    motion: (t) => ({ tilt: 2.5 * settle(450)(t), dx: 3 * settle(450)(t) }),
  },
} satisfies Record<string, Pose>;

/** How her body moves with a gesture at `elapsed` ms (none for most). */
export function poseMotion(name: PoseName, elapsed: number): Motion {
  const pose: Pose = POSES[name];
  return pose.motion?.(Math.max(0, elapsed)) ?? {};
}

export type PoseName = keyof typeof POSES;

/** Hands slide up into place as the pose fades in. */
const ENTER_MS = 360;

export function drawPose(frame: Frame, name: PoseName, elapsed: number, alpha: number): void {
  const pose: Pose = POSES[name];
  const enter = easeOutBack(elapsed / ENTER_MS);
  for (const spot of pose.hands) {
    const w = spot.wiggle?.(elapsed) ?? {};
    const place = {
      ...spot,
      x: spot.x + (w.dx ?? 0),
      y: spot.y + (w.dy ?? 0) + (1 - enter) * 26,
      rot: (spot.rot ?? 0) + (w.drot ?? 0),
      alpha,
    };
    if (spot.hand === "thumbsUp") drawThumbsUp(frame, place);
    else drawHand(frame, HANDS[spot.hand], place);
  }
  pose.props?.(frame, elapsed, alpha);
}
