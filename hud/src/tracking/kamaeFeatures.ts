// Kamae, from the upper body: is he holding chudan at her?
//
// The features are the arms measured from the midpoint of the shoulders, in
// shoulder-widths, so the same kamae reads the same wherever he stands - and how
// far the wrists and elbows are in FRONT of the shoulders (MediaPipe's z), because
// a shinai pointed at her puts both hands out toward the camera. This file is the
// TS twin of features() and Watcher in core/scripts/kamae_train.py and must stay in
// step - hud/tests/kamae.verify.mjs replays the trainer's golden frames through it.
//
// The watcher decides when a kamae is HELD, not glimpsed - live, almost any arm
// movement used to fire it. It fires only when, for a whole hold window:
//   - most samples score above the ENTER threshold,
//   - both hands are together on the tsuka (the wrists close),
//   - and they are STILL (a reach, a wave, a stretch moves; kamae does not);
// then it stays in kamae until the score has been below the lower EXIT threshold
// for the release time (hysteresis), and cannot fire again for a while after.
// Every threshold is the trainer's, fitted on his captures (model.gate).

import { KAMAE_MODEL } from "./kamaeModel";
import type { KamaeModel } from "./kamaeModel";

const L_SHOULDER = 11;
const R_SHOULDER = 12;
const L_ELBOW = 13;
const R_ELBOW = 14;
const L_WRIST = 15;
const R_WRIST = 16;

/** Feature order, as the trainer writes it. */
export const WRIST_GAP = 8;
export const WRIST_MID_X = 9;
export const WRIST_MID_Y = 10;
export const WRIST_DEPTH = 13;

/** The feature vector for one frame's flat [x, y, z, visibility] x 33, or null without shoulders. */
export function kamaeFeatures(body: readonly number[]): number[] | null {
  if (body.length !== 132) return null;
  const at = (i: number) => ({ x: body[i * 4], y: body[i * 4 + 1], z: body[i * 4 + 2], v: body[i * 4 + 3] });
  const ls = at(L_SHOULDER);
  const rs = at(R_SHOULDER);
  const width = Math.hypot(ls.x - rs.x, ls.y - rs.y);
  if (width < 1e-3 || Math.min(ls.v, rs.v) < 0.5) return null;
  const mx = (ls.x + rs.x) / 2;
  const my = (ls.y + rs.y) / 2;
  const mz = (ls.z + rs.z) / 2;
  const rel = (i: number): [number, number] => {
    const p = at(i);
    return [(p.x - mx) / width, (p.y - my) / width];
  };
  const depth = (i: number): number => (at(i).z - mz) / width;
  const lw = rel(L_WRIST);
  const rw = rel(R_WRIST);
  const le = rel(L_ELBOW);
  const re = rel(R_ELBOW);
  return [
    lw[0], lw[1], rw[0], rw[1],
    le[0], le[1], re[0], re[1],
    Math.hypot(lw[0] - rw[0], lw[1] - rw[1]), (lw[0] + rw[0]) / 2, (lw[1] + rw[1]) / 2,
    Math.min(at(L_WRIST).v, at(R_WRIST).v), Math.min(at(L_ELBOW).v, at(R_ELBOW).v),
    (depth(L_WRIST) + depth(R_WRIST)) / 2, (depth(L_ELBOW) + depth(R_ELBOW)) / 2,
  ];
}

/** Probability that this frame is kamae. */
export function kamaeScore(features: readonly number[], model: KamaeModel = KAMAE_MODEL): number {
  let z = model.bias;
  for (let i = 0; i < features.length; i += 1) z += (model.weights[i] * (features[i] - model.mean[i])) / model.scale[i];
  return 1 / (1 + Math.exp(-z));
}

export interface KamaeEvent {
  /** "start": he has taken kamae; "end": he has clearly left it. */
  kind: "start" | "end";
}

interface Sample {
  at: number;
  /** Scored above the enter threshold with the hands together. */
  yes: boolean;
  /** Where the hands are (shoulder-widths), for "held steady". */
  x: number;
  y: number;
}

/** Held-kamae detection over time. Feed it each new pose sample (or null). */
export class KamaeWatcher {
  private readonly window: Sample[] = [];
  private holding = false;
  private lastIn = -Infinity;
  private endedAt = -Infinity;

  constructor(private readonly model: KamaeModel = KAMAE_MODEL) {}

  get active(): boolean {
    return this.holding;
  }

  /** The last sample's score, for the debug view. */
  lastScore = 0;

  update(body: readonly number[] | null, now: number): KamaeEvent | null {
    const g = this.model.gate;
    const f = body ? kamaeFeatures(body) : null;
    const p = f ? kamaeScore(f, this.model) : 0;
    this.lastScore = p;
    // both hands on the tsuka, out in front toward her: pointed at her
    const together = f !== null && f[WRIST_GAP] <= g.gapMax && f[WRIST_DEPTH] <= g.depthMax;
    if (this.holding) {
      // hysteresis: in kamae until clearly out of it for the release time
      if (p >= g.exit && together) this.lastIn = now;
      if (now - this.lastIn > g.releaseMs) {
        this.holding = false;
        this.endedAt = now;
        this.window.length = 0;
        return { kind: "end" };
      }
      return null;
    }
    this.window.push({ at: now, yes: p >= g.enter && together, x: f ? f[WRIST_MID_X] : NaN, y: f ? f[WRIST_MID_Y] : NaN });
    while (this.window.length && now - this.window[0].at > g.holdMs) this.window.shift();
    if (now - this.endedAt < g.refireMs) return null;
    // the window must really span the hold time, not just a burst of samples
    if (this.window.length < g.minSamples || now - this.window[0].at < g.holdMs * 0.9) return null;
    const yes = this.window.filter((s) => s.yes);
    if (yes.length / this.window.length < g.share) return null;
    if (spread(yes.map((s) => s.x)) > g.steadyMax || spread(yes.map((s) => s.y)) > g.steadyMax) return null;
    this.holding = true;
    this.lastIn = now;
    return { kind: "start" };
  }
}

/** Standard deviation. */
function spread(values: number[]): number {
  if (values.length < 2) return 0;
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  return Math.sqrt(values.reduce((a, b) => a + (b - mean) ** 2, 0) / values.length);
}
