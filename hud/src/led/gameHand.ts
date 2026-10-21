// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// Her hand in a hand game (rock-paper-scissors): LED pixel glyphs beside her face,
// on the same matrix, in the same ink and glow as her eyes. Not the gesture rig
// (led/hands.ts) and no arm or body: one hand, hers, as a glyph.
//
//   neutral   a fist side-on - the counting hand, the SAME every pump of every round
//   rock / paper / scissors   her throw, from the shoot instant only
//   shrug     palm up, lifted and wobbling: "again?" after a misread
//
// Core drives it (core/irene/app.py _rps_count): "game_hand" {glyph: "neutral"} as the
// game starts (fades in), {glyph: "neutral", beat: n} as each counted word reaches the
// speaker (a pump - down on the word, back up), {glyph: "shrug"} on a redo. Her throw
// comes ONLY inside "game_shoot" {throw}: the same message that starts the reading of
// his hand, so hers shows the instant his is read - never before. Game mode off
// fades it out.
//
// This module is pure: what a message does to the hand (gameHandOn) and how the hand
// draws at a moment (drawGameHand). Nothing here can know her sealed throw before the
// shoot message - and hud/tests/gameHand.verify.mjs checks the pumps render the same
// whatever she sealed.

import { FADE, INK, blit, clamp01, ease, sprite } from "./grid";
import type { Frame, Sprite } from "./grid";

export type GameGlyph = "neutral" | "rock" | "paper" | "scissors" | "shrug";
export const THROW_GLYPHS = ["rock", "paper", "scissors"] as const;

export interface GameHand {
  /** What it shows now. */
  glyph: GameGlyph;
  /** When that glyph arrived (performance.now()). */
  at: number;
  /** When the hand faded in. */
  shownAt: number;
  /** The last pump's start, or null (no pump since the glyph arrived). */
  beatAt: number | null;
  /** When it started fading out, or null while it is up. */
  hiddenAt: number | null;
}

export type GameHandEvent =
  | { kind: "show" }
  | { kind: "beat"; n: number }
  | { kind: "throw"; glyph: GameGlyph }
  | { kind: "shrug" }
  | { kind: "hide" };

export const FADE_IN_MS = 350;
export const FADE_OUT_MS = 300;
/** A pump: down onto the word fast, a moment at the bottom, back up. */
export const PUMP_DOWN_MS = 70;
export const PUMP_HOLD_MS = 50;
export const PUMP_UP_MS = 230;
export const PUMP_DEPTH = 6;
/** The shoot: her throw lands from the bottom of a last pump. */
export const SHOOT_MS = 180;
/** The redo: her throw goes back down, then the shrug, then neutral again. */
export const SHRUG_DROP_MS = 220;
export const SHRUG_MS = 1900;

/** What one of core's messages does to the hand. Pure. */
export function gameHandOn(hand: GameHand | null, event: GameHandEvent, now: number): GameHand | null {
  const up = hand && hand.hiddenAt === null ? hand : null;
  switch (event.kind) {
    case "show":
      return up ? { ...up, glyph: "neutral", at: up.glyph === "neutral" ? up.at : now, beatAt: null } : { glyph: "neutral", at: now, shownAt: now, beatAt: null, hiddenAt: null };
    case "beat": {
      // a round's first pump brings her last throw (or the shrug) back to neutral
      const base = up ?? { glyph: "neutral" as GameGlyph, at: now, shownAt: now, beatAt: null, hiddenAt: null };
      return { ...base, glyph: "neutral", at: base.glyph === "neutral" ? base.at : now, beatAt: now };
    }
    case "throw":
      return up ? { ...up, glyph: event.glyph, at: now, beatAt: null } : null;
    case "shrug":
      return up ? { ...up, glyph: "shrug", at: now, beatAt: null } : null;
    case "hide":
      return up ? { ...up, hiddenAt: now } : hand;
  }
}

/** Gone for good (faded out): the caller can drop it. */
export function gameHandDone(hand: GameHand | null, now: number): boolean {
  return !hand || (hand.hiddenAt !== null && now - hand.hiddenAt >= FADE_OUT_MS);
}

// ---- the glyphs ----------------------------------------------------------------------
// Authored at half resolution, drawn 2x like her eyes are drawn 3x: chunky LEDs, a
// bright rim and a dimmer body. Her right hand, beside her face on the viewer's right.

const GLYPHS: Record<GameGlyph, Sprite> = {
  // the counting fist, side-on: the thumb wrapped over the top, curled fingers stepping
  // down toward her face, the wrist below on the far side
  neutral: sprite([
    "...######...",
    "..#++++++#..",
    ".#+######+#.",
    "#+#++++++#+#",
    "#+########+#",
    "#+#+++++#++#",
    "#+#######++#",
    "#+#++++#+++#",
    ".#######+++#",
    "...#+++++++#",
    "...#++++++#.",
    "...#++++++#.",
    "...########.",
  ]),
  // rock: the fist turned to him - four knuckles in a row, the thumb across
  rock: sprite([
    ".###.###.##.",
    "#+++#+++#++#",
    "#+++#+++#++#",
    "#+++#+++#++#",
    "############",
    "#++++++++++#",
    "#+######+++#",
    "#++++++#+++#",
    ".#+++++++++#",
    "..#+++++++#.",
    "..#+++++++#.",
    "..#########.",
  ]),
  // paper: the open hand, fingers up and together, thumb out
  paper: sprite([
    "....###.....",
    "..###+###...",
    "..#+#+#+###.",
    "..#+#+#+#+#.",
    "..#+#+#+#+#.",
    "..#+#+#+#+#.",
    "..#+#+#+#+#.",
    "###+++++++#.",
    "#+#+++++++#.",
    "#++#++++++#.",
    ".#++++++++#.",
    "..#++++++#..",
    "..#++++++#..",
    "..########..",
  ]),
  // scissors: index and middle up in a V, ring and pinky folded under the thumb
  scissors: sprite([
    ".###...###..",
    ".#+#...#+#..",
    ".#+#...#+#..",
    "..#+#.#+#...",
    "..#+#.#+#...",
    "...#+#+#....",
    "..##+#+###..",
    ".#+++#+++##.",
    ".#+#######+#",
    ".#+++++++++#",
    "..#+++++++#.",
    "..#+++++++#.",
    "..#########.",
  ]),
  // shrug: palm up and open, fingers flat toward her face, the thumb up - "who knows?"
  shrug: sprite([
    ".........##.",
    "........#+#.",
    "........#+#.",
    "........#+#.",
    "#########+#.",
    "#+++++++++##",
    "############",
    "#++++++++++#",
    ".##++++++##.",
    "...######...",
  ]),
};

/** Where the hand sits: right of her face, low enough to read as hers. */
export const HAND_X = 101;
export const HAND_Y = 27;
const SCALE = 2;

export function glyphSprite(glyph: GameGlyph): Sprite {
  return GLYPHS[glyph];
}

/** How far down the hand is `t` ms into a pump (cells). */
export function pumpDepth(t: number): number {
  if (t < 0) return 0;
  if (t < PUMP_DOWN_MS) return PUMP_DEPTH * ease(t / PUMP_DOWN_MS);
  if (t < PUMP_DOWN_MS + PUMP_HOLD_MS) return PUMP_DEPTH;
  const u = (t - PUMP_DOWN_MS - PUMP_HOLD_MS) / PUMP_UP_MS;
  return u < 1 ? PUMP_DEPTH * (1 - ease(u)) : 0;
}

/** The glyph shown and its offset at `now` - what drawGameHand puts on the matrix. */
export function gameHandPose(hand: GameHand, now: number): { glyph: GameGlyph; dx: number; dy: number; alpha: number } {
  const fadeIn = clamp01((now - hand.shownAt) / FADE_IN_MS);
  const fadeOut = hand.hiddenAt === null ? 1 : 1 - clamp01((now - hand.hiddenAt) / FADE_OUT_MS);
  const alpha = ease(fadeIn) * fadeOut;
  const t = now - hand.at;
  if (hand.glyph === "neutral") {
    // between pumps: still, with the slightest breath
    const dy = hand.beatAt !== null ? pumpDepth(now - hand.beatAt) : 0;
    return { glyph: "neutral", dx: 0, dy, alpha };
  }
  if (hand.glyph === "shrug") {
    // the throw drops back down (the round doesn't count) as neutral, then the
    // shrug lifts and wobbles, then down to neutral, ready
    if (t < SHRUG_DROP_MS) return { glyph: "neutral", dx: 0, dy: 4 * ease(t / SHRUG_DROP_MS), alpha };
    if (t < SHRUG_MS) {
      const s = t - SHRUG_DROP_MS;
      const lift = -3 * ease(s / 240);
      const wobble = Math.round(Math.sin((s / 1000) * 2.6 * Math.PI * 2) * 1.2);
      return { glyph: "shrug", dx: wobble, dy: lift + 6, alpha };
    }
    return { glyph: "neutral", dx: 0, dy: 4 * (1 - ease((t - SHRUG_MS) / 250)), alpha };
  }
  // a throw: it lands from the bottom of the last pump and holds
  return { glyph: hand.glyph, dx: 0, dy: t < SHOOT_MS ? PUMP_DEPTH * (1 - ease(t / SHOOT_MS)) : 0, alpha };
}

export function drawGameHand(frame: Frame, hand: GameHand | null, now: number): void {
  if (!hand || gameHandDone(hand, now)) return;
  const pose = gameHandPose(hand, now);
  if (pose.alpha <= 0) return;
  const s = GLYPHS[pose.glyph];
  // centred on the same column whatever the glyph's width; bottoms line up
  const x = HAND_X + Math.round(((12 - s.w) * SCALE) / 2) + pose.dx;
  const y = HAND_Y + (14 - s.h) * SCALE + Math.round(pose.dy);
  blit(frame, s, x, y, { ink: INK.accent, alpha: pose.alpha, scale: SCALE, cover: true, fade: FADE.fast });
}
