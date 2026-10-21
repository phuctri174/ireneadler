// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
/**
 * The mouth is driven by the short-window RMS of whatever Irene is currently
 * speaking. Kokoro streams that audio from the Python side, so the real source
 * does not exist in the HUD yet — this is the seam it will plug into.
 *
 * Contract: `read(now)` returns 0..1, is called once per animation frame, and
 * must be cheap and non-blocking. Smoothing belongs to the source, not the face.
 */
export interface AudioLevelSource {
  read(now: number): number;
}

/** What a face with no audio attached should show: nothing. */
export const SILENT_LEVEL: AudioLevelSource = {
  read: () => 0,
};

// A level older than this is stale - the stream stopped or the link dropped mid-word.
const STREAM_STALE_MS = 250;

export interface StreamedLevel extends AudioLevelSource {
  /** Latest RMS level (0..1) from core's TTS, arriving at ~20 Hz. */
  push(value: number): void;
}

/**
 * Core measures RMS on each 50 ms block as it plays and sends it over the socket.
 * 20 Hz steps would make the mouth stutter at 60 fps, so this eases toward the
 * latest value with the same fast-attack / slow-release as a VU meter, and falls
 * to closed when updates stop.
 */
export function streamedLevel(): StreamedLevel {
  let target = 0;
  let stamp = 0;
  let value = 0;
  let last = 0;
  return {
    push(next: number): void {
      target = Math.max(0, Math.min(1, next));
      stamp = performance.now();
    },
    read(now: number): number {
      const delta = last === 0 ? 0 : Math.min((now - last) / 1000, 0.1);
      last = now;
      const goal = now - stamp > STREAM_STALE_MS ? 0 : target;
      const rate = goal > value ? 30 : 12;
      value += (goal - value) * Math.min(1, delta * rate);
      return value;
    },
  };
}

/**
 * Wraps a source so several consumers in the same animation frame share one read.
 * Frame callbacks all receive the same `now`, which is what keys the cache.
 */
export function cachedLevel(source: AudioLevelSource): AudioLevelSource {
  let stamp = -1;
  let value = 0;
  return {
    read(now: number): number {
      if (now !== stamp) {
        stamp = now;
        value = source.read(now);
      }
      return value;
    },
  };
}
