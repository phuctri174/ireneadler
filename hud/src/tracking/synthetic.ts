// Dev-only stand-in for a real hand: a pointing hand whose index tip sits on a
// chosen screen point, fed to the gesture engine in place of the camera's hand.
// It exercises the real path - classification, cursor filter, dwell timer, the
// main interface's hit test - so a dwell-select can be verified without someone
// in front of the camera. Core relays debug_point only when started with
// IRENE_DEV=1, and the HUD ignores it outside a dev build.

import type { NormalizedLandmark } from "@mediapipe/tasks-vision";
import type { HandSample } from "./gestures";

// same template as tests/gestures.verify.mjs pointingHand(): index straight,
// the other fingers curled, thumb tucked
const WRIST = { x: 0.5, y: 0.8 };
const PALM = 0.16;
const THUMB_TUCKED = { x: WRIST.x - 0.02, y: WRIST.y - 0.12 };
const CURL = [0, 1, 1, 1];
const OFFSETS = [0.05, 0.017, -0.017, -0.05];
const INDEX_TIP = 8;

function pointingTemplate(): NormalizedLandmark[] {
  const lm: NormalizedLandmark[] = new Array(21);
  const at = (x: number, y: number): NormalizedLandmark => ({ x, y, z: 0, visibility: 1 });
  lm[0] = at(WRIST.x, WRIST.y);
  for (let j = 1; j <= 4; j += 1) {
    const t = j / 4;
    lm[j] = at(WRIST.x + (THUMB_TUCKED.x - WRIST.x) * t, WRIST.y + (THUMB_TUCKED.y - WRIST.y) * t);
  }
  const mcpY = WRIST.y - PALM;
  for (let f = 0; f < 4; f += 1) {
    const base = 5 + f * 4;
    const mx = WRIST.x - OFFSETS[f];
    const c = CURL[f];
    lm[base] = at(mx, mcpY);
    lm[base + 1] = at(mx, mcpY - 0.06);
    lm[base + 2] = at(mx, mcpY - 0.1 * (1 - c));
    lm[base + 3] = at(mx, mcpY - 0.14 * (1 - c));
  }
  return lm;
}

const TEMPLATE = pointingTemplate();

let target: { x: number; y: number } | null = null;
let until = 0;

/** Point at (x, y) in 0..1 screen space for `ms` milliseconds; null stops. */
export function setSyntheticPoint(point: { x: number; y: number } | null, ms = 0): void {
  target = point;
  until = point ? performance.now() + ms : 0;
  console.log(point ? `[irene] synthetic point ${point.x.toFixed(3)},${point.y.toFixed(3)} for ${ms}ms` : "[irene] synthetic point off");
}

/** The synthetic hand for this frame, or null when none is active. */
export function syntheticSample(now: number, mirror: boolean): HandSample | null {
  if (!target || now > until) return null;
  // the cursor is the index tip, mirrored when the feed is
  const tipX = mirror ? 1 - target.x : target.x;
  const dx = tipX - TEMPLATE[INDEX_TIP].x;
  const dy = target.y - TEMPLATE[INDEX_TIP].y;
  return {
    landmarks: TEMPLATE.map((p) => ({ ...p, x: p.x + dx, y: p.y + dy })),
    handedness: "Right",
  };
}
