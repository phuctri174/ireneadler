// What the zoom classifier looks at, and the forest that reads it.
//
// The old gate asked one question per finger - extended or curled - and called it
// a zoom when all five agreed. That cannot tell a deliberate spread from a wave or
// a relaxed hand, because those are all open hands; measured against the captures,
// it fired on 95% of waving frames. So the pose decision is a small gradient-boosted
// forest instead (core/scripts/zoom_train.py -> zoomModel.json), over the hand's
// shape AND how it is moving: a wave swings the whole hand while the fingers hold
// still, a zoom holds the hand still while the fingers open or close.
//
// The feature vector here must match core/scripts/zoom_analyze.py's FEATURE_NAMES
// exactly, in order. hud/tests/zoom.verify.mjs checks this file against frames the
// Python side scored, so the two cannot drift apart unnoticed.

import { ZOOM_FOREST } from "./zoomModel";

/** How far back the motion features look - long enough to hold a whole wave. */
export const ZOOM_WINDOW = 15;
export const ZOOM_FEATURE_COUNT = 24;

export interface ZoomSample {
  /**
   * Where the hand is: the WRIST landmark, not the cursor. The cursor only
   * tracks while a pointing pose is live, so during a wave, a spread or a zoom
   * it sits perfectly still - on the captures, cursor travel for waving was
   * 0.000, the one pose that moves most, while the wrist reads 0.518 against
   * 0.03-0.05 for the poses that hold still.
   */
  handX: number;
  handY: number;
  spread: number;
  timestamp: number;
}

export interface ZoomShape {
  thumb: number;
  index: number;
  middle: number;
  ring: number;
  pinky: number;
  spread: number;
  ratio: number;
  tipGapPalm: number;
  knuckleGapPalm: number;
  palmSpan: number;
  /** 21 MediaPipe landmarks, or null when the hand was lost. */
  landmarks: readonly { x: number; y: number; z: number }[] | null;
}

const TIPS = [4, 8, 12, 16, 20];
const MCP = [2, 5, 9, 13, 17];

function distance(a: { x: number; y: number; z: number }, b: { x: number; y: number; z: number }): number {
  return Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);
}

function spreadOf(values: number[]): number {
  const mean = values.reduce((s, v) => s + v, 0) / values.length;
  return Math.sqrt(values.reduce((s, v) => s + (v - mean) ** 2, 0) / values.length);
}

/**
 * A rolling window of where the hand has been, so a frame can be judged in the
 * light of the ones before it rather than on its own.
 */
export class ZoomHistory {
  private readonly samples: ZoomSample[] = [];

  push(sample: ZoomSample): void {
    this.samples.push(sample);
    if (this.samples.length > ZOOM_WINDOW + 1) this.samples.shift();
  }

  clear(): void {
    this.samples.length = 0;
  }

  /** travel, swing, rise, reversals, fingerRate, drift - all per second. */
  motion(): number[] {
    const n = this.samples.length;
    if (n < 2) return [0, 0, 0, 0, 0, 0];
    const cx = this.samples.map((s) => s.handX);
    const cy = this.samples.map((s) => s.handY);
    const sp = this.samples.map((s) => s.spread);
    const seconds = Math.max((this.samples[n - 1].timestamp - this.samples[0].timestamp) / 1000, 1e-3);
    let travel = 0;
    for (let i = 1; i < n; i += 1) travel += Math.hypot(cx[i] - cx[i - 1], cy[i] - cy[i - 1]);
    const range = (v: number[]): number => Math.max(...v) - Math.min(...v);
    // how often the hand changed direction: a wave reverses, a zoom does not
    let reversals = 0;
    for (let i = 2; i < n; i += 1) {
      const before = Math.sign(cx[i - 1] - cx[i - 2]);
      const after = Math.sign(cx[i] - cx[i - 1]);
      if (before !== after) reversals += 1;
    }
    return [
      travel / seconds,
      range(cx) / seconds,
      range(cy) / seconds,
      reversals,
      range(sp) / seconds,
      (sp[n - 1] - sp[0]) / seconds,
    ];
  }
}

/** The 24 numbers the forest reads, in the order it expects them. */
export function zoomFeatures(shape: ZoomShape, history: ZoomHistory): number[] {
  const out = [
    shape.thumb,
    shape.index,
    shape.middle,
    shape.ring,
    shape.pinky,
    shape.spread,
    shape.ratio,
    shape.tipGapPalm,
    shape.knuckleGapPalm,
    shape.palmSpan,
  ];
  const lm = shape.landmarks;
  if (!lm || lm.length !== 21) {
    for (let k = 0; k < 8; k += 1) out.push(0);
  } else {
    const wrist = lm[0];
    const span = distance(lm[9], wrist) || 1;
    const reach = TIPS.map((i) => distance(lm[i], wrist) / span);
    let fan = 0;
    for (let i = 0; i < 4; i += 1) fan += distance(lm[TIPS[i]], lm[TIPS[i + 1]]);
    let curl = 0;
    for (let i = 0; i < TIPS.length; i += 1) curl += distance(lm[TIPS[i]], lm[MCP[i]]);
    out.push(...reach, fan / 4 / span, curl / TIPS.length / span, spreadOf(reach));
  }
  out.push(...history.motion());
  return out;
}

/** The forest's raw score: at or above zero is a zoom pose. */
export function zoomScore(features: number[]): number {
  let total = ZOOM_FOREST.baseline;
  for (const tree of ZOOM_FOREST.trees) {
    let node = 0;
    while (!tree.leaf[node]) {
      node = features[tree.feature[node]] <= tree.threshold[node] ? tree.left[node] : tree.right[node];
    }
    total += tree.value[node];
  }
  return total;
}

/** Is this frame a zoom pose - a hand held open or closed on purpose? */
export function isZoomPose(shape: ZoomShape, history: ZoomHistory): boolean {
  return zoomScore(zoomFeatures(shape, history)) >= 0;
}
