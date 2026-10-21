// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// Micro-expressions: the small, constant life in a face that a state alone
// doesn't give - blinks, glances, a flicker of a smile mid-sentence. None of it
// is a readout: state and the emotion core set stay authoritative, and anything a
// scene, gesture or summon draws still wins over it (led/compose.ts).
//
//   speaking   quick small glances, blinks between phrases, now and then a brief
//              blend of a neighbouring feeling (a smile flickering through)
//   listening  slow, occasional glances; normal blinks
//   thinking   looking up and around
//   typing     he's typing to her: curious, eyes down on the command bar,
//              following the text along
//
// Driven by update(now, ...) once per frame; `random` is injectable so the tests
// get a fixed sequence.

import type { AssistantState, Emotion } from "./faceState";

export interface Micro {
  gazeX: number;
  gazeY: number;
  /** A brief expression over the current emotion, or null. */
  flash: Emotion | null;
  blinking: boolean;
}

export interface MicroInput {
  state: AssistantState;
  emotion: Emotion;
  /** He is typing to her right now. */
  typing: boolean;
}

const BLINK_MS = 115;
const BLINK_GAP: Record<"speaking" | "calm", [number, number]> = { speaking: [1600, 4200], calm: [2600, 7200] };
const GLANCE_GAP: Record<"speaking" | "calm" | "thinking", [number, number]> = {
  speaking: [650, 2000],
  calm: [2200, 5200],
  thinking: [900, 1700],
};
const FLASH_GAP: [number, number] = [2600, 5400];
const FLASH_MS: [number, number] = [380, 700];

// what can flicker through each mood mid-sentence
const BLENDS: Partial<Record<Emotion, Emotion[]>> = {
  neutral: ["happy", "curious", "happy"],
  happy: ["excited", "wink", "proud"],
  curious: ["surprised", "happy"],
  concerned: ["sad", "neutral"],
  excited: ["happy", "surprised"],
  proud: ["wink", "happy"],
};

export class MicroExpressions {
  private gaze = { x: 0, y: 0 };
  private nextGlance = 0;
  private nextBlink = 0;
  private blinkUntil = 0;
  private flash: Emotion | null = null;
  private flashUntil = 0;
  private nextFlash = 0;
  private typingSince = -1;

  constructor(private readonly random: () => number = Math.random) {}

  private between([lo, hi]: [number, number]): number {
    return lo + this.random() * (hi - lo);
  }

  private pick<T>(items: readonly T[]): T {
    return items[Math.min(items.length - 1, Math.floor(this.random() * items.length))];
  }

  update(now: number, input: MicroInput): Micro {
    const { state, emotion, typing } = input;
    const speaking = state === "speaking";

    if (state === "dormant" || state === "error") {
      this.gaze = { x: 0, y: 0 };
      this.flash = null;
      this.typingSince = -1;
      return { gazeX: 0, gazeY: 0, flash: null, blinking: false };
    }

    // blinks: a little quicker while talking, as people do between phrases
    if (this.nextBlink === 0) this.nextBlink = now + this.between(BLINK_GAP.calm);
    if (now >= this.nextBlink) {
      this.blinkUntil = now + BLINK_MS;
      this.nextBlink = now + this.between(speaking ? BLINK_GAP.speaking : BLINK_GAP.calm);
    }

    if (typing) {
      // eyes down on the bar, drifting along the line as he types
      if (this.typingSince < 0) this.typingSince = now;
      const along = ((now - this.typingSince) / 1400) % 1;
      this.flash = null;
      return { gazeX: Math.round(along * 4 - 2), gazeY: 3, flash: null, blinking: now < this.blinkUntil };
    }
    this.typingSince = -1;

    // glances
    if (now >= this.nextGlance) {
      if (state === "thinking") {
        this.gaze = { x: this.pick([-2, 2, -1, 1]), y: -1 };
        this.nextGlance = now + this.between(GLANCE_GAP.thinking);
      } else if (speaking) {
        // mostly back to him, with small darts away
        const away = this.random() < 0.55;
        this.gaze = away ? { x: this.pick([-2, -1, 1, 2]), y: this.pick([-1, 0, 0, 1]) } : { x: 0, y: 0 };
        this.nextGlance = now + this.between(GLANCE_GAP.speaking);
      } else {
        const away = this.random() < 0.35;
        this.gaze = away ? { x: this.pick([-1, 1]), y: 0 } : { x: 0, y: 0 };
        this.nextGlance = now + this.between(GLANCE_GAP.calm);
      }
    }

    // brief blends while speaking
    if (!speaking) {
      this.flash = null;
      this.nextFlash = 0;
    } else {
      if (this.nextFlash === 0) this.nextFlash = now + this.between(FLASH_GAP);
      if (this.flash && now >= this.flashUntil) this.flash = null;
      const blends = BLENDS[emotion];
      if (!this.flash && now >= this.nextFlash && blends) {
        this.flash = this.pick(blends);
        this.flashUntil = now + this.between(FLASH_MS);
        this.nextFlash = now + this.between(FLASH_GAP);
      }
    }

    return { gazeX: this.gaze.x, gazeY: this.gaze.y, flash: this.flash, blinking: now < this.blinkUntil };
  }
}
