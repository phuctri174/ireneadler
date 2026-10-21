// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// Irene's face on the matrix: the authored 7x7 eyes and the procedural 13x5 mouth
// from faceState, smoothly upscaled 3x. Layout constants live here so hands,
// props and scenes can place themselves relative to the face.

import {
  EYE_COLS,
  EYE_ROWS,
  MOUTH_COLS,
  MOUTH_ROWS,
  EMOTION_INK,
  STATE_GAIN,
  closedEyes,
  eyeGrids,
  mouthGrid,
} from "../face/faceState";
import type { AssistantState, Emotion, GridPair } from "../face/faceState";
import { FADE, INK, blit, sprite, upscale } from "./grid";
import type { Frame, Ink } from "./grid";

export const FACE_SCALE = 3;
export const EYE_W = EYE_COLS * FACE_SCALE;
export const EYE_H = EYE_ROWS * FACE_SCALE;
export const LEFT_EYE_X = 33;
export const RIGHT_EYE_X = 74;
export const EYE_Y = 12;
export const MOUTH_W = MOUTH_COLS * FACE_SCALE;
export const MOUTH_H = MOUTH_ROWS * FACE_SCALE;
export const MOUTH_X = 44;
export const MOUTH_Y = 41;
/** Rows the eyes occupy - what a visor or a helmet grille has to cover. */
export const EYE_BAND = { y0: EYE_Y - 2, y1: EYE_Y + EYE_H + 1 };

/**
 * Where the face sits. "full" is the normal 3x face filling the matrix; "compact"
 * is a 2x face in the upper middle, leaving room below for a whole figure (the
 * kendo scene's armour).
 */
export type FaceLayout = "full" | "compact" | "profile" | "corner";

export const LAYOUTS: Record<FaceLayout, { scale: number; leftX: number; rightX: number; eyeY: number; mouthX: number; mouthY: number }> = {
  full: { scale: FACE_SCALE, leftX: LEFT_EYE_X, rightX: RIGHT_EYE_X, eyeY: EYE_Y, mouthX: MOUTH_X, mouthY: MOUTH_Y },
  compact: { scale: 2, leftX: 47, rightX: 67, eyeY: 6, mouthX: 51, mouthY: 23 },
  // three-quarter view turned to the left: features pulled toward the front
  profile: { scale: 2, leftX: 37, rightX: 54, eyeY: 9, mouthX: 41, mouthY: 26 },
  // 1x in the top-right corner while the illustration board fills the rest
  corner: { scale: 1, leftX: 104, rightX: 114, eyeY: 2, mouthX: 106, mouthY: 10 },
};

export type MouthShape = "smile" | "grin" | "o" | "flat" | "wavy" | "smirk" | "hidden";

// 13x5, same key as the eye art
const MOUTHS: Record<Exclude<MouthShape, "hidden">, readonly string[]> = {
  smile: [".............", "+...........+", ".#.........#.", "..##.....##..", "....#####...."],
  grin: ["+...........+", ".###########.", "..#-------#..", "...#-----#...", "....#####...."],
  o: ["....+###+....", "...#-----#...", "...#-----#...", "...#-----#...", "....+###+...."],
  flat: [".............", ".............", "...#######...", ".............", "............."],
  wavy: [".............", "..++.....++..", ".#..#...#..#.", "#....###....#", "............."],
  smirk: [".............", "...........+.", "..........#..", "..#######+...", "............."],
};

const MOUTH_GRIDS = Object.fromEntries(
  Object.entries(MOUTHS).map(([name, art]) => {
    const grid = new Float32Array(MOUTH_COLS * MOUTH_ROWS);
    const key: Record<string, number> = { "-": 0.22, "+": 0.55, "#": 1 };
    art.forEach((line, row) => {
      for (let col = 0; col < MOUTH_COLS; col += 1) grid[row * MOUTH_COLS + col] = key[line[col]] ?? 0;
    });
    return [name, grid];
  }),
) as Record<Exclude<MouthShape, "hidden">, Float32Array>;

export interface FaceLook {
  state: AssistantState;
  emotion: Emotion;
  blinking: boolean;
  /** 0..1 speech level; drives the procedural mouth while speaking. */
  level: number;
  now: number;
  /** Eyes' vertical offset in cells: positive looks down (at a chessboard). */
  gazeY?: number;
  /** Eyes' horizontal offset in cells: positive looks to the viewer's right. */
  gazeX?: number;
  /** Replaces the state's mouth, for an expression that goes with a gesture. */
  mouth?: MouthShape;
  /** Shut eyes whatever the emotion (yawn). */
  eyesClosed?: boolean;
  ink?: Ink;
  /** Eye colour alone, for a flash (visor lifting, a kiai). */
  eyeInk?: Ink;
  layout?: FaceLayout;
  /** Horizontal offset in cells - the whole face moves with a stepping body. */
  shiftX?: number;
  /** Vertical offset in cells, eyes and mouth together (a swing, a hop). */
  shiftY?: number;
  /** The face is moving fast: cells follow at once instead of easing (no smear). */
  moving?: boolean;
  /** Head tilt in cells: her left eye drops and her right rises by this much. */
  tilt?: number;
}

const mouthScratch = new Float32Array(MOUTH_COLS * MOUTH_ROWS);

export function drawFace(frame: Frame, look: FaceLook): void {
  const gain = STATE_GAIN[look.state];
  const ink = look.ink ?? INK.accent;
  const own = look.state === "error" ? undefined : EMOTION_INK[look.emotion];
  const eyeInk = look.eyeInk ?? (own === "pink" ? INK.pink : own === "gold" ? INK.amber : ink);
  const eyes: GridPair = look.eyesClosed ? closedEyes() : eyeGrids(look.state, look.emotion, look.blinking);
  const eyeFade = look.moving ? FADE.fast : look.blinking ? FADE.blink : FADE.eyes;
  const at = LAYOUTS[look.layout ?? "full"];
  const sx = Math.round(look.shiftX ?? 0);
  const sy = Math.round(look.shiftY ?? 0);
  // gaze is authored for the full 3x face; a smaller face glances less far
  const gy = Math.round(((look.gazeY ?? 0) * at.scale) / FACE_SCALE);
  const gx = Math.round(((look.gazeX ?? 0) * at.scale) / FACE_SCALE);
  // write the whole eye boxes (zeros included) so switching shapes fades both ways
  const tilt = Math.round(((look.tilt ?? 0) * at.scale) / FACE_SCALE);
  upscale(frame, eyes.left, EYE_COLS, EYE_ROWS, at.scale, at.leftX + sx + gx, at.eyeY + gy + sy + tilt, gain, eyeInk, eyeFade);
  upscale(frame, eyes.right, EYE_COLS, EYE_ROWS, at.scale, at.rightX + sx + gx, at.eyeY + gy + sy - tilt, gain, eyeInk, eyeFade);

  if (look.mouth === "hidden") return;
  let mouth: Float32Array;
  if (look.mouth) {
    mouth = MOUTH_GRIDS[look.mouth];
  } else {
    mouthGrid(mouthScratch, look.state, look.state === "speaking" ? look.level : 0, look.now);
    mouth = mouthScratch;
  }
  // a tilted head carries the mouth a little toward the dropped side
  upscale(frame, mouth, MOUTH_COLS, MOUTH_ROWS, at.scale, at.mouthX + sx - tilt, at.mouthY + sy, gain, ink, look.moving ? FADE.fast : FADE.mouth);
}

// ---- humming ------------------------------------------------------------------

const NOTE = sprite([
  "..##",
  "..#.",
  "..#.",
  "###.",
  "##..",
]);

/** Little notes drifting up from beside her mouth while she hums (idle life). */
export function drawNotes(frame: Frame, elapsed: number): void {
  for (let k = 0; k < 2; k += 1) {
    const t = ((elapsed + k * 1300) % 2600) / 2600;
    const alpha = Math.sin(t * Math.PI);
    const x = MOUTH_X + MOUTH_W + 4 + Math.round(Math.sin(t * Math.PI * 2 + k) * 2) + k * 6;
    const y = MOUTH_Y + 6 - Math.round(t * 18);
    blit(frame, NOTE, x, y, { ink: INK.amber, alpha, fade: FADE.prop });
  }
}

// ---- status glyph --------------------------------------------------------------

const MUTED = sprite([
  "...#.........",
  "..##...#...#.",
  "####....#.#..",
  "####.....#...",
  "####....#.#..",
  "..##...#...#.",
  "...#.........",
]);

/** Speaker with a cross in the matrix corner while TTS output is off. */
export function drawMuted(frame: Frame): void {
  blit(frame, MUTED, 111, 3, { ink: INK.amber, fade: FADE.prop });
}
