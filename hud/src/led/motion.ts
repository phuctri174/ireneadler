// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// Body movement under a feeling: the whole face shifts, dips, bounces or tilts, so
// a reaction reads from across the room and not only in the shape of her eyes.
// A gesture's motion is its pose's (led/poses.ts); an expression's is here, timed
// from when the feeling arrived. Offsets are in cells, the same as FaceLook's.

import type { Emotion } from "../face/faceState";
import type { FaceLook } from "./face";

export interface Motion {
  dx?: number;
  dy?: number;
  /** Head tilt (face.ts): her left eye down, her right up. */
  tilt?: number;
  /** Fast enough that cells must follow at once rather than smear. */
  moving?: boolean;
}

const TAU = Math.PI * 2;
const smooth = (x: number): number => {
  const c = Math.min(1, Math.max(0, x));
  return c * c * (3 - 2 * c);
};

/** Eases a held offset in over `ms`, so a slump sinks rather than snaps. */
export const settle = (ms: number) => (t: number): number => smooth(t / ms);

/** Hops: 0 at the floor, up to `height` cells at the top of each bounce. */
export const hop = (hz: number, height: number) => (t: number): number => -Math.abs(Math.sin((t / 1000) * hz * Math.PI)) * height;

/** A side-to-side sway. */
export const sway = (hz: number, amp: number) => (t: number): number => Math.sin((t / 1000) * hz * TAU) * amp;

// What each feeling does with her body. Neutral stands still.
export const EMOTION_MOTION: Partial<Record<Emotion, (t: number) => Motion>> = {
  // a bounce on her toes, big at first, then a happy jiggle
  excited: (t) => ({ dy: hop(2.4, t < 1400 ? 4 : 1.5)(t), moving: true }),
  starryEyed: (t) => ({ dy: hop(1.8, t < 1200 ? 2.5 : 1)(t), moving: true }),
  // the droop: shoulders drop and the head goes down
  sad: (t) => ({ dy: 4 * settle(700)(t), tilt: settle(900)(t) }),
  // turned away, chin down, making a point of it
  sulking: (t) => ({ dx: -5 * settle(450)(t), dy: 2 * settle(450)(t), tilt: -1 * settle(600)(t) }),
  // a jump back, then settling where she landed
  surprised: (t) => ({ dy: -3 + 2 * settle(900)(t), moving: t < 250 }),
  // ducking her head
  sheepish: (t) => ({ dy: 2 * settle(500)(t), tilt: settle(500)(t) }),
  // the lean in: closer, head on one side
  curious: (t) => ({ dx: 2 * settle(500)(t), dy: 1 * settle(500)(t), tilt: settle(500)(t) }),
  confused: (t) => ({ tilt: -2 * settle(400)(t), dx: sway(0.5, 1)(t) }),
  concerned: (t) => ({ dy: 2 * settle(600)(t) }),
  // chin up
  proud: (t) => ({ dy: -2 * settle(400)(t) }),
  happy: (t) => ({ dx: sway(0.9, 1.2)(t) }),
  love: (t) => ({ dx: sway(0.7, 2)(t), tilt: settle(500)(t) }),
  wink: (t) => ({ tilt: settle(250)(t) }),
  satisfied: (t) => ({ dy: t < 900 ? Math.sin((t / 900) * Math.PI) * 1.5 : 0 }),
  // sobbing: head down, shaking all over, shoulders heaving with each sob
  sobbing: (t) => ({
    dy: 2 * settle(400)(t) + Math.max(0, Math.sin((t / 1000) * 1.15 * Math.PI * 2)) * 3,
    dx: Math.sin((t / 1000) * 11 * Math.PI * 2) * 0.9,
    moving: true,
  }),
  // innocent: a slow, gentle bob - butter wouldn't melt
  innocent: (t) => ({ dy: Math.sin((t / 1000) * 0.5 * Math.PI * 2) * 1.2, tilt: 0.6 * settle(800)(t) }),
  // peeking: shrinking down behind her hands
  peeking: (t) => ({ dy: 4 * settle(450)(t), dx: -2 * settle(450)(t) }),
  // smug: head tilted back and cocked - then not one more movement
  smug: (t) => ({ dy: -3 * settle(350)(t), tilt: 1.5 * settle(350)(t) }),
  // fuming: head down like a bull, trembling with it
  fuming: (t) => ({ dy: 2 * settle(300)(t), dx: Math.sin((t / 1000) * 9 * Math.PI * 2) * 0.6, moving: true }),
  // shocked: snapped back, and frozen there
  shocked: (t) => ({ dy: -4 * settle(160)(t), moving: t < 200 }),
  // caughtOffGuard: a small jolt back - then not one more movement while it holds
  caughtOffGuard: (t) => ({ dy: -3 * settle(140)(t), tilt: -0.6 * settle(140)(t), moving: t < 180 }),
  // arrogant: chin up and head cocked, then a slow, satisfied little nod
  arrogant: (t) => ({ dy: -3 * settle(320)(t) + (t > 400 ? 0.8 * Math.sin(((t - 400) / 1000) * 0.9 * TAU) : 0), tilt: 1.2 * settle(320)(t) }),
  // triumphant: a hop up on the win, then a gleeful little wiggle side to side
  triumphant: (t) => ({ dy: t < 700 ? hop(1.45, 4)(t) : 0, dx: t > 500 ? sway(1.8, 1.4)(t) : 0, moving: t < 800 }),
  // outplayed: rocked back by it, then a slump with a small disbelieving head shake
  outplayed: (t) => ({ dy: t < 220 ? -2 * Math.sin((t / 220) * Math.PI) : 2.5 * settle(600)(t - 220), dx: t > 400 && t < 1600 ? Math.sin(((t - 400) / 1000) * 3 * TAU) * 1.2 : 0, moving: t < 300 }),
  // standoff: leaning in, eye to eye, and a slow sway - sizing each other up
  standoff: (t) => ({ dx: 2 * settle(500)(t) + sway(0.4, 0.8)(t), dy: 1 * settle(500)(t) }),
  // oops: the double take - the head cocks past where it lands and bobs back, then
  // a slow puzzled wobble
  oops: (t) => ({
    tilt: -3.2 * settle(220)(t) + 1.1 * settle(420)(Math.max(0, t - 220)) + (t > 700 ? Math.sin(((t - 700) / 1000) * 0.7 * TAU) * 0.5 : 0),
    dy: t < 260 ? -1.5 * Math.sin((t / 260) * Math.PI) : 0,
    dx: 1.5 * settle(400)(t),
    moving: t < 300,
  }),
  // the study-mode hits (core/irene/study.py)
  // bonked: knocked down by it, a dazed wobble, slowly back up
  bonked: (t) => ({ dy: t < 120 ? (t / 120) * 4 : 4 * (1 - settle(900)(t - 120)), dx: t < 1200 ? Math.sin(t / 70) * (1 - t / 1200) * 1.5 : 0, tilt: Math.sin(t / 260) * 0.8 * Math.max(0, 1 - t / 1600), moving: t < 300 }),
  // indignant: snapped upright, chin up, a huffy little shake
  indignant: (t) => ({ dy: -2.5 * settle(160)(t), dx: t > 200 && t < 900 ? Math.sin(t / 40) * 0.8 : 0, moving: t < 200 }),
  // surrender: slumped, shaking her head, sobbing - for show
  surrender: (t) => ({ dy: 2 * settle(400)(t) + Math.abs(Math.sin(t / 170)) * 1.5, dx: Math.sin(t / 110) * 1.8, moving: true }),
};

export function emotionMotion(emotion: Emotion, elapsed: number): Motion {
  return EMOTION_MOTION[emotion]?.(Math.max(0, elapsed)) ?? {};
}

/** Adds a motion to a look, `weight` of the way (a fading pose moves less). */
export function applyMotion(look: FaceLook, motion: Motion, weight = 1): void {
  if (motion.dx) look.shiftX = (look.shiftX ?? 0) + motion.dx * weight;
  if (motion.dy) look.shiftY = (look.shiftY ?? 0) + motion.dy * weight;
  if (motion.tilt) look.tilt = (look.tilt ?? 0) + motion.tilt * weight;
  if (motion.moving) look.moving = true;
}
