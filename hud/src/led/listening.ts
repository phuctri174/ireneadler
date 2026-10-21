// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// Voice on her face: that she is listening, that she hears him, and how long she
// will wait before deciding he has finished (core/irene/listen.py's end-of-speech
// wait, up to 3 s, shorter when his sentence clearly ended).
//
//   listening  a small mic in the top-left corner, breathing
//   hearing    the mic, with sound bars beside it moving while he talks
//   silence    the mic, and a bar along the bottom that runs down to zero -
//              the countdown; if he speaks again it is gone and the bars are back
//   thinking   the mic, dimmed, with three dots while Whisper writes it down
//   asleep     a faint mic with a "z": she is here but only a wake phrase counts
//   off        a red mic, struck through: no microphone - she can't hear at all
//
// Whatever the phase, the mic is always drawn: he can always see whether she hears.

import { FADE, INK, ROWS, blit, sprite } from "./grid";
import type { Frame } from "./grid";

/** Mirrors core's {"type": "voice", "phase"} (link/coreSocket.ts re-exports it). */
export type VoicePhase = "listening" | "hearing" | "silence" | "thinking" | "asleep" | "off";

export interface VoiceStage {
  phase: VoicePhase;
  /** performance.now() the phase (or this countdown value) arrived. */
  at: number;
  remainingMs?: number;
  totalMs?: number;
}

const MIC = sprite([
  ".###.",
  "#---#",
  "#---#",
  "#---#",
  ".###.",
  "#...#",
  ".###.",
  "..#..",
  ".###.",
]);

/** Is there anything to draw for this phase? Always, once core has said: the mic
 * state is how he knows whether she can hear him. */
export function voiceShown(voice: VoiceStage | null | undefined): voice is VoiceStage {
  return !!voice;
}

const Z = sprite([
  "###",
  "..#",
  ".#.",
  "#..",
  "###",
]);

/** How much of the end-of-speech wait is left, 0..1, at `now`. */
export function countdownLeft(voice: VoiceStage, now: number): number {
  if (voice.phase !== "silence" || !voice.totalMs) return 0;
  const left = (voice.remainingMs ?? 0) - (now - voice.at);
  return Math.max(0, Math.min(1, left / voice.totalMs));
}

export function drawListening(frame: Frame, voice: VoiceStage, now: number): void {
  const t = now - voice.at;
  if (voice.phase === "asleep") {
    // a faint mic and a slow "z": asleep to everything but her wake phrase
    blit(frame, MIC, 3, 3, { ink: INK.cyan, alpha: 0.28, fade: FADE.prop });
    const drift = Math.floor(now / 700) % 3;
    blit(frame, Z, 10, 3 - drift + 2, { ink: INK.cyan, alpha: 0.35 + 0.15 * (drift === 1 ? 1 : 0), fade: FADE.prop });
    return;
  }
  if (voice.phase === "off") {
    // no microphone: the mic in red, struck through
    blit(frame, MIC, 3, 3, { ink: INK.red, alpha: 0.7, fade: FADE.prop });
    for (let k = 0; k < 11; k += 1) frame.cover(2 + k, 2 + k, 0.95, INK.red, FADE.prop);
    return;
  }
  const breathe = 0.65 + 0.3 * Math.sin(now / 420);
  const micLevel = voice.phase === "thinking" ? 0.45 : voice.phase === "listening" ? breathe : 1;
  blit(frame, MIC, 3, 3, { ink: INK.cyan, alpha: micLevel, fade: FADE.prop });
  if (voice.phase === "hearing") {
    // five bars beside the mic, bouncing out of step
    for (let k = 0; k < 5; k += 1) {
      const h = 1 + Math.round((0.5 + 0.5 * Math.sin(now / (70 + k * 17) + k * 1.9)) * 6);
      for (let y = 0; y < h; y += 1) frame.cover(10 + k * 2, 11 - y, 0.9, INK.cyan, FADE.fast);
    }
  } else if (voice.phase === "thinking") {
    const step = Math.floor(t / 260) % 4;
    for (let k = 0; k < 3; k += 1) frame.cover(10 + k * 3, 10, step === k ? 0.95 : 0.3, INK.amber, FADE.fast);
  } else if (voice.phase === "silence") {
    // the countdown: a bar along the bottom edge, full width at the start of the
    // wait, shrinking toward the middle as it runs out
    const left = countdownLeft(voice, now);
    const half = Math.round(60 * left);
    for (let x = 64 - half; x < 64 + half; x += 1) {
      frame.cover(x, ROWS - 2, 0.85, left < 0.3 ? INK.amber : INK.cyan, FADE.fast);
      frame.cover(x, ROWS - 1, 0.35, left < 0.3 ? INK.amber : INK.cyan, FADE.fast);
    }
    // the seconds left, as dots by the mic: one per second still to wait
    const seconds = Math.ceil(((voice.remainingMs ?? 0) - (now - voice.at)) / 1000);
    for (let k = 0; k < Math.max(0, seconds); k += 1) frame.cover(10 + k * 3, 10, 0.9, INK.cyan, FADE.fast);
  }
}
