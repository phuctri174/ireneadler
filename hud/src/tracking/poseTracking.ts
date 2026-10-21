// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// Upper body, for keiko.
//
// The gesture engine reads a hand: 21 landmarks, one hand, every frame. Kamae and
// the three strikes are not hand shapes - they are where the arms are relative to
// the SHOULDERS, which a hand landmarker cannot see. Without a body frame the same
// men strike looks different depending on where he stands.
//
// So this is a second, separate landmarker, and it is deliberately kept out of
// GestureInput: nothing in gestures.ts sees it, so the zoom classifier and every
// existing gesture behave exactly as before. It runs only while a keiko capture is
// armed, and is torn down the moment that ends - the rest of the time it costs
// nothing at all.
//
// The model is vendored in hud/public/mediapipe like the hand one; it is never
// fetched from a CDN.

import { PoseLandmarker } from "@mediapipe/tasks-vision";
import type { NormalizedLandmark } from "@mediapipe/tasks-vision";

const MEDIAPIPE_ASSETS = "/mediapipe";
const MODEL_ASSET = `${MEDIAPIPE_ASSETS}/pose_landmarker_lite.task`;
const WASM_FILESET = {
  wasmLoaderPath: `${MEDIAPIPE_ASSETS}/vision_wasm_internal.js`,
  wasmBinaryPath: `${MEDIAPIPE_ASSETS}/vision_wasm_internal.wasm`,
};

/** MediaPipe pose landmarks, by the ones keiko actually uses. */
export const POSE = {
  nose: 0,
  leftShoulder: 11,
  rightShoulder: 12,
  leftElbow: 13,
  rightElbow: 14,
  leftWrist: 15,
  rightWrist: 16,
  leftHip: 23,
  rightHip: 24,
} as const;

export const POSE_LANDMARK_COUNT = 33;

export interface PoseSample {
  /** All 33 landmarks, as MediaPipe gives them. */
  landmarks: readonly NormalizedLandmark[];
  /** How sure it is about each, same order - a strike often hides a wrist. */
  visibility: readonly number[];
}

/**
 * A pose landmarker that is only alive while something needs it.
 *
 * `arm()` loads the model (once) and `disarm()` closes it. `detect()` returns the
 * upper body for this video frame, or null when no one is in view. Every call is
 * safe before the model has finished loading - it simply returns null until then,
 * so a capture that starts early just misses its first frames rather than throwing.
 */
export class PoseTracker {
  private landmarker: PoseLandmarker | null = null;
  private loading: Promise<void> | null = null;
  private lastTimestamp = 0;

  get ready(): boolean {
    return this.landmarker !== null;
  }

  arm(): Promise<void> {
    if (this.landmarker || this.loading) return this.loading ?? Promise.resolve();
    this.loading = PoseLandmarker.createFromOptions(WASM_FILESET, {
      baseOptions: { modelAssetPath: MODEL_ASSET, delegate: "GPU" },
      runningMode: "VIDEO",
      numPoses: 1,
    })
      .then((made) => {
        this.landmarker = made;
      })
      .catch((cause) => {
        console.error("[irene] pose landmarker failed to load", cause);
      })
      .finally(() => {
        this.loading = null;
      });
    return this.loading;
  }

  disarm(): void {
    this.landmarker?.close();
    this.landmarker = null;
    this.lastTimestamp = 0;
  }

  /** The upper body on this frame, or null. Timestamps must rise, as MediaPipe insists. */
  detect(video: HTMLVideoElement, timestamp: number): PoseSample | null {
    if (!this.landmarker) return null;
    const stamp = Math.max(timestamp, this.lastTimestamp + 1);
    this.lastTimestamp = stamp;
    let result;
    try {
      result = this.landmarker.detectForVideo(video, stamp);
    } catch (cause) {
      console.error("[irene] pose detect failed", cause);
      return null;
    }
    const found = result.landmarks?.[0];
    if (!found || found.length < POSE_LANDMARK_COUNT) return null;
    return {
      landmarks: found,
      visibility: found.map((p) => (typeof p.visibility === "number" ? p.visibility : 1)),
    };
  }
}

/** The flat [x, y, z, visibility, ...] a capture frame records. */
export function flatten(sample: PoseSample): number[] {
  const out: number[] = [];
  for (let i = 0; i < POSE_LANDMARK_COUNT; i += 1) {
    const p = sample.landmarks[i];
    out.push(round(p.x), round(p.y), round(p.z), round(sample.visibility[i] ?? 1));
  }
  return out;
}

function round(value: number): number {
  return Math.round(value * 1e4) / 1e4;
}
