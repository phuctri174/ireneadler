// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// Whether his hands are in the picture before a body capture starts recording.
//
// The hits capture's first desk session had his wrists below the bottom edge in a
// third of its strike frames: the pose model still gives a position there, but a
// guessed one, and it was trained on as if seen. So a capture with "framing" in its
// profile waits in kamae, recording nothing, until the lower of his two wrists sits
// at most wristMaxY of the frame height (0 top, 1 the bottom edge, over 1 below it).

const L_WRIST = 15;
const R_WRIST = 16;
/** In frame this long, continuously, before the run goes on - a wrist flickering
 *  across the line is not framed. */
export const FRAMED_MS = 1000;

/** The lower of his wrists, as a fraction of frame height; null without a body. */
export function lowestWrist(landmarks: readonly { y: number }[] | null | undefined): number | null {
  if (!landmarks || landmarks.length <= R_WRIST) return null;
  return Math.max(landmarks[L_WRIST].y, landmarks[R_WRIST].y);
}

/** Follows the check frame by frame: framed once the wrist has been low enough for FRAMED_MS. */
export class FramingCheck {
  /** when the wrist last came inside the line; null while it is outside */
  private since: number | null = null;
  /** The latest lowest wrist, for the readout. */
  lowest: number | null = null;

  constructor(readonly wristMaxY: number) {}

  update(landmarks: readonly { y: number }[] | null | undefined, now: number): boolean {
    this.lowest = lowestWrist(landmarks);
    if (this.lowest === null || this.lowest > this.wristMaxY) {
      this.since = null;
      return false;
    }
    this.since ??= now;
    return now - this.since >= FRAMED_MS;
  }

  /** Inside the line right now (not yet held for FRAMED_MS). */
  get inside(): boolean {
    return this.lowest !== null && this.lowest <= this.wristMaxY;
  }
}
