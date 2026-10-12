// Gesture reactions: Irene's LED hands make a gesture beside (or over) her face
// while the face wears a matching expression, then hand back to whatever
// state/emotion is current. A reaction never changes state - it is decoration on
// top of a readout, not a readout. This file is the trigger API and timing; the
// art is in led/poses.ts.

import { POSES } from "../led/poses";
import type { PoseName } from "../led/poses";

// The list is the pose table's: a new gesture is its pose (led/poses.ts) plus its
// entry in config/cues.json, nothing here.
export type Reaction = PoseName;

export const REACTIONS = Object.keys(POSES) as Reaction[];

/** "thumbsUp" -> "THUMBS UP": a readable name for any cue, for the well tag. */
export function cueLabel(name: string): string {
  return name.replace(/([a-z])([A-Z])/g, "$1 $2").toUpperCase();
}

/** Named in the well tag while a reaction plays, so it is never a guess. */
export const REACTION_LABEL = Object.fromEntries(REACTIONS.map((name) => [name, cueLabel(name)])) as Record<Reaction, string>;

/** Total time on the face, including both crossfades. */
export const REACTION_MS = 2000;
export const REACTION_FADE_IN_MS = 260;
export const REACTION_FADE_OUT_MS = 340;

/** 0..1 weight of the pose over the plain face at `elapsed` ms; smoothstep ramps. */
export function reactionEnvelope(elapsed: number): number {
  if (elapsed <= 0 || elapsed >= REACTION_MS) return 0;
  const smooth = (x: number): number => x * x * (3 - 2 * x);
  if (elapsed < REACTION_FADE_IN_MS) return smooth(elapsed / REACTION_FADE_IN_MS);
  const outStart = REACTION_MS - REACTION_FADE_OUT_MS;
  if (elapsed > outStart) return smooth((REACTION_MS - elapsed) / REACTION_FADE_OUT_MS);
  return 1;
}

export function isReaction(name: unknown): name is Reaction {
  return typeof name === "string" && (REACTIONS as string[]).includes(name);
}

// ---- trigger API ---------------------------------------------------------

export interface ReactionEvent {
  name: Reaction;
  /** performance.now() at trigger. */
  at: number;
  /** Full body: the pose's movement amplified and a hop on top (her answer to
   *  "what are you doing?" after a signature entrance - core app.py attached_shows). */
  big?: boolean;
}

type Listener = (event: ReactionEvent) => void;
const listeners = new Set<Listener>();

/**
 * Show a reaction. Safe to call from anywhere - the backend reaches it through the
 * socket. A second call while one is showing replaces it (the cells crossfade
 * between the two). Unknown names are ignored and reported, so a newer backend
 * cannot take the HUD down with a reaction this build lacks.
 */
export function showReaction(name: string, big = false): boolean {
  if (!isReaction(name)) {
    console.warn(`[irene] unknown reaction: ${name}`);
    return false;
  }
  const event: ReactionEvent = { name, at: performance.now(), big };
  console.log(`[irene] reaction -> ${name}`);
  for (const listener of listeners) listener(event);
  return true;
}

export function onReaction(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
