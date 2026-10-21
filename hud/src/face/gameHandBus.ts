// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// The game hand's trigger API (the art and the rules are led/gameHand.ts): core's
// "game_hand" and "game_shoot" messages arrive in App.tsx, go out here, and the face
// loop (Face.tsx) folds each into the hand it draws. Like reactions.ts.

import type { GameHandEvent } from "../led/gameHand";

export interface TimedGameHandEvent {
  event: GameHandEvent;
  /** performance.now() it happened at - for a throw, the very instant his hand's
   *  reading window is anchored to (App.tsx game_shoot). */
  at: number;
}

type Listener = (event: TimedGameHandEvent) => void;
const listeners = new Set<Listener>();

export function gameHand(event: GameHandEvent, at = performance.now()): void {
  for (const listener of listeners) listener({ event, at });
}

export function onGameHand(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
