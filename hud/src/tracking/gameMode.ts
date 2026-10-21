// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// Game mode: while she plays a hand game with him (rock-paper-scissors, ...), his hand
// is a game piece, not a pointer. Rock is a fist, paper an open palm, scissors two
// fingers - the zoom, the summon and the scroll poses - so EVERY normal gesture is
// suspended: the engine is not run at all, and everything downstream of it (the OS
// pointer, the wheel, the panel zoom, the summon) sees a neutral state, as if no hand
// were there. The landmarks still flow, into a short buffer the game reads from.
//
// Core turns it on and off ("game_mode"); it also times out on its own here, so a
// lost "off" (core restarted, socket dropped) can never leave his hand dead.

import type { GestureEngine, GestureInput, GestureState } from "./gestures";
import { neutralGestures } from "./gestures";

/** No word from core for this long and game mode ends by itself. */
export const GAME_MODE_DEFAULT_MS = 120_000;
/** The landmark buffer: long enough for a capture window around "shoot". */
export const GAME_BUFFER_MS = 4000;

export interface GameFrame {
  /** performance.now() of the camera frame */
  t: number;
  /** 21 landmarks as x, y, z, ... (63 numbers) - the camera's hand only */
  lm: number[];
  handed: "Left" | "Right";
}

export class GameMode {
  private until = 0;
  private wasOn = false;
  game = "";
  readonly frames: GameFrame[] = [];

  /** Core's word: on for `ms` more (refreshed by every round), or off now. */
  set(on: boolean, now: number, ms = GAME_MODE_DEFAULT_MS, game = ""): void {
    this.until = on ? now + Math.max(1000, ms) : 0;
    this.game = on ? game : "";
    if (!on) this.frames.length = 0;
  }

  active(now: number): boolean {
    return now < this.until;
  }

  /** One camera frame through the gate: the engine's state normally; in game mode
   *  the engine is reset once and not run, and the state is neutral. */
  step(engine: GestureEngine, input: GestureInput, now: number): GestureState {
    const on = this.active(now);
    if (!on) {
      if (this.wasOn) {
        this.wasOn = false;
        this.frames.length = 0;
        // back from a game: a clean engine - no half-latched pose from a throw
        engine.reset();
      }
      return engine.update(input);
    }
    if (!this.wasOn) {
      this.wasOn = true;
      engine.reset();
    }
    return neutralGestures();
  }

  /** Keep the camera's hand for the game (never the dev synthetic one). */
  record(now: number, landmarks: readonly { x: number; y: number; z: number }[] | null, handed: "Left" | "Right"): void {
    if (!this.active(now)) return;
    if (landmarks && landmarks.length >= 21) {
      const lm: number[] = [];
      for (const p of landmarks) lm.push(round(p.x), round(p.y), round(p.z));
      this.frames.push({ t: now, lm, handed });
    }
    while (this.frames.length && now - this.frames[0].t > GAME_BUFFER_MS) this.frames.shift();
  }

  /** The frames from `from` to `to` (performance.now() times), relative to `t0`. */
  window(t0: number, from: number, to: number): { t: number; lm: number[]; handed: string }[] {
    return this.frames.filter((f) => f.t >= from && f.t <= to).map((f) => ({ t: Math.round(f.t - t0), lm: f.lm, handed: f.handed }));
  }
}

function round(v: number): number {
  return Math.round(v * 1e5) / 1e5;
}
